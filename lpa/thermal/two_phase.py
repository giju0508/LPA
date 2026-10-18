"""Pre-dryout boiling correlations with explicit Beta applicability limits.

Chen/Bennett (1980), doi:10.1002/aic.690260317; Li/Wu (2010),
doi:10.1016/j.ijheatmasstransfer.2010.01.012; Lockhart/Martinelli (1949)
with Chisholm (1967), doi:10.1016/0017-9310(67)90047-6.
The ht/fluids packages supply independently maintained implementations.
Equivalent circular mass flow adapts their API while preserving actual G.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, pi

from fluids.two_phase import Lockhart_Martinelli
from ht.boiling_flow import Chen_Bennett, Li_Wu


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
