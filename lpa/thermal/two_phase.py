"""Pre-dryout boiling correlations with explicit Beta applicability limits.

Chen/Bennett (1980), doi:10.1002/aic.690260317; Li/Wu (2010),
doi:10.1016/j.ijheatmasstransfer.2010.01.012; Lockhart/Martinelli (1949)
with Chisholm (1967), doi:10.1016/0017-9310(67)90047-6.
The ht/fluids packages supply independently maintained implementations.
Equivalent circular mass flow adapts their API while preserving actual G.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import expm1, isfinite, nan, pi

from fluids.two_phase import Lockhart_Martinelli
from ht.boiling_flow import Chen_Bennett, Li_Wu
from ht.boiling_nucleic import Cooper


class TwoPhaseApplicabilityError(ValueError):
    """The pre-dryout model cannot represent this coolant state."""


@dataclass(frozen=True, slots=True)
class BoilingResult:
    coefficient_w_m2k: float
    pressure_gradient_pa_m: float
    homogeneous_density_kg_m3: float
    velocity_m_s: float
    model: str
    warnings: tuple[str, ...]
    applicability: str = "screening"
    regime: str = "pure_fluid_pre_dryout"
    nucleate_coefficient_w_m2k: float = nan
    convective_coefficient_w_m2k: float = nan
    ideal_nucleate_coefficient_w_m2k: float = nan
    ideal_convective_coefficient_w_m2k: float = nan
    vapor_reference_coefficient_w_m2k: float = nan
    mass_transfer_correction_factor: float = nan
    convective_correction_factor: float = nan
    liquid_composition_glide_k: float = nan
    sensible_vapor_heat_fraction: float = nan
    boiling_number: float = nan
    wet_wall_assumed: bool = True
    critical_heat_flux_w_m2: float = nan
    dryout_vapor_quality: float = nan


def mixture_saturated_boiling(
    *, state: object, mass_flow_kg_s: float, total_flow_area_m2: float,
    hydraulic_diameter_m: float, wall_temperature_k: float,
    wall_heat_flux_w_m2: float, model: str = "shah_gungor_winterton",
    mass_transfer_coefficient_m_s: float = 3e-4,
) -> BoilingResult:
    """Wet-wall mixture engineering calculation, not a CHF/dryout model.

    Shah (2015), doi:10.1016/j.applthermaleng.2015.06.047: apply
    Thome-Shakir to GW87's nucleate part, and Bell-Ghaly to its convective
    part. No surface tension or invented diffusion coefficient is required.
    beta=0.0003 m/s is a published empirical mass-transfer parameter.

    State temperatures must be bubble/dew at the SAME CURRENT LIQUID
    composition; a fixed overall-composition glide is insufficient. The
    derivative dT/dh is along the local equilibrium path at fixed P and
    overall composition. Its units are K*kg/J, not an EOS single-phase Cp.

    Every result is screening or unsupported, even when numerical values are
    returned outside the published parameter envelope. The wet-wall formula
    applies only for 0 <= mass quality < 1. At the equilibrium dew endpoint
    the caller must use its single-phase gas branch; no arbitrary quality
    floor or artificial interpolation to gas h is introduced here.
    """
    if model == "disabled":
        raise TwoPhaseApplicabilityError("mixture two-phase channel model disabled")
    if model != "shah_gungor_winterton":
        raise ValueError("unknown mixture flow-boiling model")
    names = tuple(getattr(state, "mixture_component_names", ()))
    if len(names) < 2:
        raise TwoPhaseApplicabilityError("mixture component identities unavailable")
    pressure = getattr(state, "pressure_pa", nan)
    temperature = getattr(state, "temperature_k", nan)
    critical_pressure = getattr(state, "critical_pressure_pa", nan)
    numeric = (mass_flow_kg_s, total_flow_area_m2, hydraulic_diameter_m,
               wall_temperature_k, wall_heat_flux_w_m2, pressure, temperature,
               critical_pressure, mass_transfer_coefficient_m_s)
    if not all(isfinite(value) and value > 0 for value in numeric):
        raise TwoPhaseApplicabilityError("mixture boiling requires finite positive flow, properties, wall heat flux and beta")
    if wall_temperature_k <= temperature:
        raise TwoPhaseApplicabilityError("cold-wall/condensation heat transfer is outside the mixture boiling model")
    reduced_pressure = pressure / critical_pressure
    if reduced_pressure >= 1:
        raise TwoPhaseApplicabilityError("mixture boiling requires subcritical pressure; Cooper pool term is undefined at/above critical pressure")
    quality = getattr(state, "vapor_quality_mass_fraction", nan)
    if not isfinite(quality) or not 0 <= quality < 1:
        raise TwoPhaseApplicabilityError("mixture wet-wall model requires 0 <= mass quality < 1; use gas convection at the dew endpoint")
    liquid = getattr(state, "saturated_liquid", None)
    vapor = getattr(state, "saturated_vapor", None)
    if liquid is None or vapor is None:
        raise TwoPhaseApplicabilityError("mixture saturated phase properties unavailable")
    for phase in (liquid, vapor):
        needed = (phase.density_kg_m3, phase.specific_heat_j_kgk,
                  phase.conductivity_w_mk, phase.viscosity_pa_s,
                  getattr(phase, "molar_mass_kg_mol", nan))
        if not all(isfinite(value) and value > 0 for value in needed):
            raise TwoPhaseApplicabilityError("mixture phase density, Cp, conductivity, viscosity and molecular weight must be finite and positive")
        if getattr(phase, "transport_applicability", "eos") in {"unsupported", "screening"}:
            raise TwoPhaseApplicabilityError("mixture phase transport is unsupported or a screening fallback; explicit engineering provider required")
        # Unknown bulk two-phase Cp/sound speed do not invalidate phase-resolved
        # transport. Explicit fallback of a REQUIRED phase property does.
        for issue in getattr(phase, "issues", ()):
            lower = str(issue).casefold()
            if ("unavailable" in lower or "fallback" in lower) and any(
                token in lower for token in ("viscosity", "conductivity", "density", "specific heat", "heat capacity", " cp")
            ):
                raise TwoPhaseApplicabilityError("required mixture phase property is a fallback; explicit engineering provider required")
    if liquid.density_kg_m3 <= vapor.density_kg_m3:
        raise TwoPhaseApplicabilityError("mixture liquid density must exceed vapor density")
    latent = vapor.enthalpy_j_kg - liquid.enthalpy_j_kg
    if not isfinite(latent) or latent <= 0:
        raise TwoPhaseApplicabilityError("positive mixture phase enthalpy difference unavailable")
    bubble = getattr(state, "mixture_liquid_bubble_temperature_k", nan)
    dew = getattr(state, "mixture_liquid_dew_temperature_k", nan)
    slope = getattr(state, "equilibrium_temperature_enthalpy_derivative_k_kg_j", nan)
    if not all(isfinite(value) and value > 0 for value in (bubble, dew)):
        raise TwoPhaseApplicabilityError("bubble/dew temperatures at current liquid composition unavailable")
    if abs(bubble - temperature) > max(0.01, temperature * 1e-5):
        raise TwoPhaseApplicabilityError("liquid-composition bubble point is inconsistent with local equilibrium temperature")
    if dew < bubble or not isfinite(slope) or slope < 0:
        raise TwoPhaseApplicabilityError("nonnegative local mixture glide and equilibrium dT/dh are required")
    glide = dew - bubble
    g = mass_flow_kg_s / total_flow_area_m2
    d = hydraulic_diameter_m
    pr_l = liquid.specific_heat_j_kgk * liquid.viscosity_pa_s / liquid.conductivity_w_mk
    pr_v = vapor.specific_heat_j_kgk * vapor.viscosity_pa_s / vapor.conductivity_w_mk
    re_lo = g*d/liquid.viscosity_pa_s
    re_l = re_lo*(1-quality)
    re_v = g*quality*d/vapor.viscosity_pa_s
    h_lo = 0.023*re_lo**0.8*pr_l**0.4*liquid.conductivity_w_mk/d
    remaining = 1-quality
    boiling_number = wall_heat_flux_w_m2/(g*latent)
    # Algebraically identical to h_l * (1 + 1.12*(x/(1-x))**.75
    # *(rho_l/rho_v)**.41). This avoids divergent intermediate factors near
    # x=1 without altering x or adding a numerical heat-transfer floor.
    ideal_cb = h_lo*(remaining**0.8 + 1.12*quality**0.75*remaining**0.05*
                     (liquid.density_kg_m3/vapor.density_kg_m3)**0.41)
    ideal_nb = 3000*boiling_number**0.86*h_lo*remaining**0.8
    # Mass quality and phase molecular weights determine total mixture MW.
    # Cooper's dimensional equation requires g/mol, while states use kg/mol.
    molar_mass = 1/((1-quality)/liquid.molar_mass_kg_mol + quality/vapor.molar_mass_kg_mol)
    ideal_pool = Cooper(P=pressure, Pc=critical_pressure,
                        MW=1000*molar_mass, q=wall_heat_flux_w_m2)
    suppression = -expm1(-wall_heat_flux_w_m2/(
        liquid.density_kg_m3*latent*mass_transfer_coefficient_m_s))
    f_ts = 1/(1+ideal_pool/wall_heat_flux_w_m2*glide*suppression)
    sensible_fraction = quality*vapor.specific_heat_j_kgk*slope
    h_gs = 0.0 if quality == 0 else 0.023*re_v**0.8*pr_v**0.4*vapor.conductivity_w_mk/d
    corrected_cb = ideal_cb if sensible_fraction == 0 else 1/(
        1/ideal_cb+sensible_fraction/h_gs)
    corrected_nb = f_ts*ideal_nb
    coefficient = corrected_cb+corrected_nb
    equivalent_mass_flow = g*pi*d**2/4
    if quality == 0:
        # fluids.Lockhart_Martinelli evaluates 64/Re_g before its x=0 early
        # return; evaluate its exact liquid limit directly to avoid 0/0.
        friction = 64/re_lo if re_lo < 2000 else 0.184*re_lo**-0.2
        gradient = friction/d*g**2/(2*liquid.density_kg_m3)
    else:
        gradient = Lockhart_Martinelli(
            m=equivalent_mass_flow, x=quality, D=d,
            rhol=liquid.density_kg_m3, rhog=vapor.density_kg_m3,
            mul=liquid.viscosity_pa_s, mug=vapor.viscosity_pa_s, L=1,
        )
    rho = 1/(quality/vapor.density_kg_m3+(1-quality)/liquid.density_kg_m3)
    if not all(isfinite(value) and value > 0 for value in (coefficient, gradient, rho)):
        raise TwoPhaseApplicabilityError("mixture correlation returned a nonphysical result")
    warnings = [
        "engineering mixture flow boiling assumes a continuously wetted wall for every 0 <= x < 1; actual dryout/CHF and post-dryout heat transfer are NOT predicted",
        "Shah/GW87 + Thome-Shakir/Bell-Ghaly mixture correction; beta is an empirical mass-transfer parameter, not a measured diffusion coefficient",
        "rectangular one-sided/conjugate channel, variable heat flux, orientation, fuel composition and phase transport require independent validation",
        "local-composition equilibrium glide and fixed-pressure dT/dh are used; phase enthalpy difference approximates mixture vaporization enthalpy",
        "Lockhart-Martinelli smooth-channel friction and homogeneous density are engineering assumptions; acceleration is handled by the channel solver",
        "no globally verified quality interval is established for LNG/aqueous ethanol; x=0.7 is not a predicted dryout boundary",
        "GW87 wet-wall h has a zero mathematical limit as x approaches one; switching to gas convection at the dew endpoint can produce a model discontinuity",
    ]
    applicability = "screening"
    outside = []
    if not 0.00019 <= d <= 0.014:
        outside.append("Dh outside mixture database 0.19..14 mm")
    if not 50 <= g <= 930:
        outside.append("G outside mixture database 50..930 kg/(m2 s)")
    if not 0.05 <= reduced_pressure <= 0.63:
        outside.append("reduced pressure outside mixture database 0.05..0.63")
    if glide > 156:
        outside.append("liquid-composition glide exceeds reported database maximum 156 K")
    if not 0.7 <= pr_l <= 160 or not 0.7 <= pr_v <= 160:
        outside.append("phase Pr outside Dittus-Boelter reference interval 0.7..160")
    if re_l < 10000 or (sensible_fraction > 0 and re_v < 10000):
        outside.append("phase Re below Dittus-Boelter turbulent reference 10000; endpoint/film adaptation unvalidated")
    folded_names = {str(name).casefold() for name in names}
    if "water" in folded_names or "ethanol" in folded_names:
        outside.append("aqueous/alcohol composition is outside the demonstrated Shah flow-boiling mixture database; Marangoni effects are unmodelled")
    if outside:
        applicability = "unsupported"
        warnings.extend("engineering extrapolation: "+issue for issue in outside)
    if "methane" in folded_names:
        warnings.append("published LNG data were an exception to the mixture correction; this LNG composition is not independently validated")
    if sensible_fraction > 1:
        applicability = "unsupported"
        warnings.append("Bell-Ghaly sensible vapor fraction exceeds one; equilibrium-path approximation is outside its physical interpretation")
    return BoilingResult(
        coefficient, gradient, rho, g/rho,
        "Shah (2015) GW87 + Thome-Shakir/Bell-Ghaly mixture wet-wall engineering",
        tuple(warnings), applicability=applicability, regime="mixture_wet_wall_assumption",
        nucleate_coefficient_w_m2k=corrected_nb,
        convective_coefficient_w_m2k=corrected_cb,
        ideal_nucleate_coefficient_w_m2k=ideal_nb,
        ideal_convective_coefficient_w_m2k=ideal_cb,
        vapor_reference_coefficient_w_m2k=h_gs,
        mass_transfer_correction_factor=f_ts,
        convective_correction_factor=corrected_cb/ideal_cb,
        liquid_composition_glide_k=glide,
        sensible_vapor_heat_fraction=sensible_fraction,
        boiling_number=boiling_number,
    )


def saturated_boiling(*, state: object, mass_flow_kg_s: float,
                     total_flow_area_m2: float, hydraulic_diameter_m: float,
                     wall_temperature_k: float, wall_heat_flux_w_m2: float,
                     wall_saturation_pressure_pa: float,
                     model: str = "auto", max_quality: float = 0.7) -> BoilingResult:
    """Pure-fluid saturated boiling; quality limit is NOT a dryout prediction.

    Rectangular-channel hydraulic-D adaptation remains screening. Mixtures
    require mass-transfer/glide corrections and are explicitly gated.
    """
    liquid = getattr(state, "saturated_liquid", None)
    vapor = getattr(state, "saturated_vapor", None)
    quality = getattr(state, "vapor_quality_mass_fraction", float("nan"))
    if model == "disabled":
        raise TwoPhaseApplicabilityError("two-phase channel model disabled")
    if not all(isfinite(v) and v>0 for v in (mass_flow_kg_s,total_flow_area_m2,
            hydraulic_diameter_m,wall_temperature_k,wall_heat_flux_w_m2,
            state.pressure_pa,state.temperature_k,state.critical_pressure_pa)):
        raise TwoPhaseApplicabilityError("boiling requires finite positive pressure, flow, temperature and heat flux")
    if wall_temperature_k <= state.temperature_k:
        raise TwoPhaseApplicabilityError("cold-wall/condensation heat transfer is outside the boiling model")
    if "&" in str(getattr(state, "source", "")):
        raise TwoPhaseApplicabilityError("mixture boiling/glide/mass-transfer correlation unavailable")
    if liquid is None or vapor is None or not isfinite(quality):
        raise TwoPhaseApplicabilityError("saturated phase properties or vapor mass quality unavailable")
    if quality < 0 or quality > max_quality:
        raise TwoPhaseApplicabilityError(f"vapor quality exceeds Beta pre-dryout calculation limit x={max_quality:g}; dryout/CHF unpredicted")
    d = hydraulic_diameter_m
    if not 0.00019 <= d <= 0.032:
        raise TwoPhaseApplicabilityError("hydraulic diameter outside Beta boiling envelope [0.19,32] mm")
    if state.pressure_pa >= 0.8 * state.critical_pressure_pa:
        raise TwoPhaseApplicabilityError("near-critical boiling above 0.8 critical pressure requires a validated model")
    for phase in (liquid, vapor):
        if not all(isfinite(v) and v>0 for v in (phase.density_kg_m3,
                phase.specific_heat_j_kgk,phase.conductivity_w_mk,phase.viscosity_pa_s)):
            raise TwoPhaseApplicabilityError("saturated phase thermophysical properties must be finite and positive")
        if any("screening" in issue or "unavailable" in issue for issue in phase.issues):
            raise TwoPhaseApplicabilityError("saturated phase transport unavailable; refusing screening transport in boiling model")
    x = max(1e-8, quality)
    g = mass_flow_kg_s / total_flow_area_m2
    equivalent_mass_flow = g * pi * d**2 / 4
    latent = vapor.enthalpy_j_kg - liquid.enthalpy_j_kg
    sigma = state.surface_tension_n_m
    if not isfinite(sigma) or sigma <= 0 or not isfinite(latent) or latent <= 0:
        raise TwoPhaseApplicabilityError("surface tension or latent heat unavailable")
    selected = ("li_wu" if d <= 0.0031 else "chen_bennett") if model == "auto" else model
    common = dict(m=equivalent_mass_flow, x=x, D=d,
                  rhol=liquid.density_kg_m3, rhog=vapor.density_kg_m3,
                  mul=liquid.viscosity_pa_s, kl=liquid.conductivity_w_mk,
                  Hvap=latent, sigma=sigma)
    if selected == "li_wu":
        if d > 0.0031:
            raise TwoPhaseApplicabilityError("Li-Wu mini-channel correlation requires Dh <= 3.1 mm")
        coefficient = Li_Wu(**common, q=max(1.0, wall_heat_flux_w_m2))
        label = "Li-Wu (2010) mini-channel saturated boiling"
    elif selected == "chen_bennett":
        if d < 0.003:
            raise TwoPhaseApplicabilityError("Chen-Bennett conventional-tube Beta envelope requires Dh >= 3 mm")
        rel = g * (1 - x) * d / liquid.viscosity_pa_s
        if rel < 2300:
            raise TwoPhaseApplicabilityError("Chen-Bennett turbulent liquid convection requires Re_l >= 2300")
        excess = max(1e-5, wall_temperature_k - state.temperature_k)
        if not isfinite(wall_saturation_pressure_pa):
            raise TwoPhaseApplicabilityError("wall saturation pressure unavailable; nucleate boiling term undefined")
        coefficient = Chen_Bennett(**common, mug=vapor.viscosity_pa_s,
            Cpl=liquid.specific_heat_j_kgk,
            dPsat=max(1e-3, wall_saturation_pressure_pa-state.pressure_pa), Te=excess)
        label = "Chen-Bennett (1980) saturated boiling"
    else:
        raise ValueError("unknown two-phase heat-transfer model")
    gradient = Lockhart_Martinelli(m=equivalent_mass_flow, x=x, D=d,
        rhol=liquid.density_kg_m3, rhog=vapor.density_kg_m3,
        mul=liquid.viscosity_pa_s, mug=vapor.viscosity_pa_s, L=1.0)
    rho = 1.0 / (x/vapor.density_kg_m3+(1-x)/liquid.density_kg_m3)
    if not all(isfinite(v) and v > 0 for v in (coefficient, gradient, rho)):
        raise TwoPhaseApplicabilityError("boiling correlation returned a nonphysical result")
    return BoilingResult(coefficient, gradient, rho, g/rho, label, (
        "Beta pre-dryout boiling correlation; CHF/dryout not predicted",
        "rectangular-channel hydraulic-diameter adaptation and slip/flow pattern require experimental validation",
        "Lockhart-Martinelli friction assumes smooth channels; gravity/local losses not included",
        "cryogenic-fluid applicability requires fluid-specific validation",
    ))
