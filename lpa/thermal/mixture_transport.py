"""Nonpolar mixture transport from Ely and Hanley, NBS TN 1039 (1981).

The one-fluid shape/mixing rules and original methane transport equations are
used with an externally supplied *single-phase* molar density (normally HEOS).
This substitutes the caller's density for the report's methane-based pVT model;
it is a predictive correlation, not a mixture-specific experimental validation.
No polar/aqueous mixture model or critical enhancement is supplied here.

Primary source (equations 9-29, Tables 2-4, Appendix B):
https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote1039.pdf
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import exp, expm1, isfinite, log, sqrt
from typing import Sequence


GAS_CONSTANT_J_MOLK = 8.31446261815324
SOURCE = "Ely-Hanley NBS TN 1039 (1981) TRAPP; supplied phase density"
REFERENCE = "https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote1039.pdf"

# These are chemical families included by the report, not a fixed LNG recipe.
# A caller can provide TransportComponent for additional nonpolar species.
_NONPOLAR_FLUIDS = frozenset({
    "Methane", "Ethane", "Propane", "n-Butane", "IsoButane", "Isobutane",
    "n-Pentane", "IsoPentane", "Isopentane", "n-Hexane", "n-Heptane",
    "n-Octane", "n-Nonane", "n-Decane", "n-Undecane", "n-Dodecane",
    "Nitrogen", "Oxygen", "CarbonDioxide", "CarbonMonoxide", "Ethylene",
    "Propylene", "Benzene", "Toluene", "Cyclopentane", "CycloHexane",
    "Cyclohexane", "MethylCyclohexane", "trans-Decalin",
})


@dataclass(frozen=True, slots=True)
class TransportComponent:
    """Pure-component input at the requested T; SI units, molar ideal-gas Cp.

    Supplying this record is an explicit assertion that the component is within
    the nonpolar applicability of the TRAPP model. It does not add a polar rule.
    """

    name: str
    critical_temperature_k: float
    critical_pressure_pa: float
    critical_molar_density_mol_m3: float
    molar_mass_kg_mol: float
    acentric_factor: float
    ideal_gas_cp_j_molk: float

    @property
    def critical_compressibility(self) -> float:
        return self.critical_pressure_pa / (
            self.critical_molar_density_mol_m3 * GAS_CONSTANT_J_MOLK * self.critical_temperature_k)


@dataclass(frozen=True, slots=True)
class MixtureTransport:
    viscosity_pa_s: float
    conductivity_w_mk: float
    reference_temperature_k: float
    reference_molar_density_mol_m3: float
    property_applicability: str = "correlated"
    validation_status: str = "screening"
    source: str = SOURCE
    references: tuple[str, ...] = (REFERENCE,)
    issues: tuple[str, ...] = (
        "TRAPP nonpolar one-fluid transport is predictive; composition-specific experimental validation required",
        "Supplied phase density replaces the original TRAPP pVT calculation; reported historical errors are not a validation of this adaptation",
        "Critical thermal-conductivity enhancement and mixture diffusion/critical anomalies are not represented",
    )


def _positive(value: float, name: str, *, zero: bool = False) -> float:
    number = float(value)
    if not isfinite(number) or (number < 0 if zero else number <= 0):
        raise ValueError(f"TRAPP {name} must be finite and {'nonnegative' if zero else 'positive'}")
    return number


@lru_cache(maxsize=1024)
def _coolprop_component(name: str, temperature_k: float) -> TransportComponent:
    if name not in _NONPOLAR_FLUIDS:
        raise ValueError(f"TRAPP component {name!r} is not in the declared nonpolar component set")
    import CoolProp.CoolProp as CP

    pure = CP.AbstractState("HEOS", name)
    tc, pc, rhoc = pure.T_critical(), pure.p_critical(), pure.rhomolar_critical()
    molar_mass, omega = pure.molar_mass(), pure.acentric_factor()
    # Only ideal-gas Cp is used: a very dilute gas input prevents evaluating a
    # heavy pure species at the mixture's dense-liquid molar density.
    pure.specify_phase(CP.iphase_gas)
    pure.update(CP.DmolarT_INPUTS, 1.0e-8, temperature_k)
    return TransportComponent(name, tc, pc, rhoc, molar_mass, omega, pure.cp0molar())


def _validate_component(component: TransportComponent) -> None:
    for name in ("critical_temperature_k", "critical_pressure_pa", "critical_molar_density_mol_m3",
                 "molar_mass_kg_mol", "ideal_gas_cp_j_molk"):
        _positive(getattr(component, name), f"{component.name} {name}")
    if not isfinite(component.acentric_factor):
        raise ValueError("TRAPP acentric factor must be finite")
    if component.ideal_gas_cp_j_molk < 2.5 * GAS_CONSTANT_J_MOLK:
        raise ValueError("TRAPP internal-energy Cp contribution is negative")


def _mixing(factors_f: Sequence[float], factors_h: Sequence[float], fractions: Sequence[float],
            components: Sequence[TransportComponent]) -> tuple[float, float, float, float]:
    """Equations 21-27, including separate transport effective molar masses."""
    hm = fmhm = mass_eta = mass_lambda = 0.0
    for i, xi in enumerate(fractions):
        for j, xj in enumerate(fractions):
            hij = ((factors_h[i] ** (1.0/3.0) + factors_h[j] ** (1.0/3.0)) / 2.0) ** 3
            fij = sqrt(factors_f[i] * factors_f[j])
            mij = 2.0 * components[i].molar_mass_kg_mol * components[j].molar_mass_kg_mol / (
                components[i].molar_mass_kg_mol + components[j].molar_mass_kg_mol)
            weight = xi * xj
            hm += weight * hij
            fmhm += weight * fij * hij
            mass_eta += weight * hij ** (4.0/3.0) * sqrt(fij * mij)
            mass_lambda += weight * hij ** (4.0/3.0) * sqrt(fij / mij)
    fm = fmhm / hm
    factor = fm * hm ** (8.0/3.0)
    return fm, hm, mass_eta * mass_eta / factor, factor / (mass_lambda * mass_lambda)


def _shape_mapping(temperature: float, density: float, components: Sequence[TransportComponent],
                   fractions: Sequence[float], reference: TransportComponent
                   ) -> tuple[float, float, float, float, tuple[float, ...], tuple[float, ...]]:
    f = [item.critical_temperature_k / reference.critical_temperature_k for item in components]
    h = [reference.critical_molar_density_mol_m3 / item.critical_molar_density_mol_m3 for item in components]
    for _ in range(100):
        fm, hm, mass_eta, mass_lambda = _mixing(f, h, fractions, components)
        next_f, next_h = [], []
        for fi, hi, item in zip(f, h, components):
            # TN1039 section 4 removes the lower T*=0.5 restriction. The
            # original upper-T and reduced-volume bounds remain model equations.
            tr = min(2.0, fi * temperature / (fm * item.critical_temperature_k))
            vr = min(2.0, max(0.5, hi * item.critical_molar_density_mol_m3 / (hm * density)))
            delta_omega = item.acentric_factor - reference.acentric_factor
            theta = 1.0 + delta_omega * (
                0.090569 - 0.862762 * log(tr) + (0.316636 - 0.465684 / tr) * (vr - 0.5))
            phi = (1.0 + delta_omega * (
                0.394901 * (vr - 1.023545) - 0.932813 * (vr - 0.754639) * log(tr))) * (
                    reference.critical_compressibility / item.critical_compressibility)
            next_f.append(_positive(item.critical_temperature_k / reference.critical_temperature_k * theta, "shape f"))
            next_h.append(_positive(reference.critical_molar_density_mol_m3 / item.critical_molar_density_mol_m3 * phi, "shape h"))
        error = max(abs(new / old - 1.0) for new, old in zip(next_f + next_h, f + h))
        f, h = next_f, next_h
        if error < 1.0e-10:
            fm, hm, mass_eta, mass_lambda = _mixing(f, h, fractions, components)
            return fm, hm, mass_eta, mass_lambda, tuple(f), tuple(h)
    raise ValueError("TRAPP one-fluid shape factors did not converge")


# Table 3 viscosity: each coefficient result is in 1e-7 Pa s. Table 4
# translational conductivity coefficients yield mW/(m K). Density is g/cm3.
_ETA_DILUTE = (2.907741307e6, -3.312874033e6, 1.608101838e6, -4.331904871e5,
               7.062481330e4, -7.116620750e3, 4.325174400e2, -1.445911210e1, .2037119479)
_ETA_B = (1.6969859271, -.13337234608, 1.4, 168.0)
_ETA_A = (-10.239160427, 174.22822961, 17.460545674, -2847.6328289,
          .13368502192, 142.07239767, 5002.0669720)
_LAMBDA_B = (-.252762920, .334328590, 1.12, 168.0)
_LAMBDA_A = (-7.1977082270, 85.678222640, 12.471834689, -984.62522975,
             .35946850007, 69.798412538, -872.88332851)


def _methane_reference_parts(temperature: float, molar_density: float, molar_mass: float
                             ) -> tuple[float, float, float, float, float, float]:
    """Original reference gas/linear/residual contributions, all returned in SI."""
    # 40 K is the report's explicit extension. 1000 K is this implementation's
    # calculation guard, not a claim of validated temperature coverage.
    if not 40.0 <= temperature <= 1000.0:
        raise ValueError("TRAPP methane reference outside implemented 40-1000 K calculation interval")
    density = _positive(molar_density, "reference molar density", zero=True) * molar_mass / 1000.0
    eta0 = _positive(sum(c * temperature ** ((n - 3.0) / 3.0) for n, c in enumerate(_ETA_DILUTE)),
                     "reference dilute viscosity")

    def terms(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float]:
        linear = (b[0] + b[1] * (b[2] - log(temperature / b[3])) ** 2) * density
        exponent = ((a[2] + a[3] / temperature ** 1.5) * density ** .1
                    + (density / .1628 - 1.0) * sqrt(density) * (
                        a[4] + a[5] / temperature + a[6] / temperature ** 2))
        residual = exp(a[0] + a[1] / temperature) * expm1(exponent)
        return linear, residual

    eta1, etar = terms(_ETA_A, _ETA_B)
    lambda1, lambdar = terms(_LAMBDA_A, _LAMBDA_B)
    eta0 *= 1.0e-7
    # Table 4 Eucken dilute translational term, modern SI R and molar mass.
    lambda0 = 15.0 * GAS_CONSTANT_J_MOLK * eta0 / (4.0 * molar_mass)
    return eta0, eta1 * 1.0e-7, etar * 1.0e-7, lambda0, lambda1 * .001, lambdar * .001


def _lng_ecs_transport(*, temperature_k: float, molar_density_mol_m3: float,
                       components: Sequence[str | TransportComponent], mole_fractions: Sequence[float]
                       ) -> MixtureTransport:
    """TRAPP transport of one nonpolar equilibrium phase, including LNG.

    Fractions are the *phase* mole fractions, never mass fractions or the feed
    composition of a two-phase mixture. The caller owns EOS phase stability,
    density validity, and the subsequent boiling/heat-transfer applicability.
    """
    temperature = _positive(temperature_k, "temperature")
    density = _positive(molar_density_mol_m3, "phase molar density")
    if not components or len(components) != len(mole_fractions):
        raise ValueError("TRAPP component and phase-composition lengths must match")
    fractions = tuple(_positive(x, "mole fraction", zero=True) for x in mole_fractions)
    if abs(sum(fractions) - 1.0) > 1.0e-8:
        raise ValueError("TRAPP phase mole fractions must sum to one")
    selected = [(item, fraction) for item, fraction in zip(components, fractions) if fraction > 0]
    inputs = tuple(_coolprop_component(item, temperature) if isinstance(item, str) else item
                   for item, _fraction in selected)
    fractions = tuple(fraction for _item, fraction in selected)
    for item in inputs:
        _validate_component(item)
    reference = _coolprop_component("Methane", temperature)
    fm, hm, mass_eta, mass_lambda, pure_f, pure_h = _shape_mapping(temperature, density, inputs, fractions, reference)
    t0, rho0 = temperature / fm, density * hm
    # Numerical partial derivative at fixed phase molar density implements the
    # nonconformality correction in Eq29 without the original pVT solver.
    step = max(1.0e-4, temperature * 1.0e-5)
    high_f = _shape_mapping(temperature + step, density, inputs, fractions, reference)[0]
    low_f = _shape_mapping(temperature - step, density, inputs, fractions, reference)[0]
    dfdt = (high_f - low_f) / (2.0 * step)
    zc = sum(x * item.critical_compressibility for x, item in zip(fractions, inputs))
    max_rhoc = max(item.critical_molar_density_mol_m3 for item in inputs)
    rbar = 1.0 / sum(x * (max_rhoc / item.critical_molar_density_mol_m3) ** (1.0/3.0)
                     for x, item in zip(fractions, inputs))
    mixture_correction = (.161290 - 4.516129 * rbar) / (1.0 - 5.354839 * rbar)
    eta_correction = sqrt((1.0 - t0 * 1.5 * min(0.0, dfdt)) * zc / reference.critical_compressibility) * mixture_correction
    lambda_correction = ((1.0 - t0 * min(0.0, dfdt)) * reference.critical_compressibility / zc) ** 1.5
    e0, e1, er, k0, k1, kr = _methane_reference_parts(t0, rho0, reference.molar_mass_kg_mol)
    eta_factor = sqrt(fm * mass_eta / reference.molar_mass_kg_mol) / hm ** (2.0/3.0)
    lambda_factor = sqrt(fm * reference.molar_mass_kg_mol / mass_lambda) / hm ** (2.0/3.0)
    viscosity = (e0 + e1 + er * eta_correction) * eta_factor
    translational_k = (k0 + k1 + kr) * lambda_factor * lambda_correction
    internal = []
    for item, fi, hi in zip(inputs, pure_f, pure_h):
        pure_eta0 = _methane_reference_parts(temperature / fi, 0.0, reference.molar_mass_kg_mol)[0]
        pure_eta0 *= sqrt(fi * item.molar_mass_kg_mol / reference.molar_mass_kg_mol) / hi ** (2.0/3.0)
        internal.append(1.32 * (item.ideal_gas_cp_j_molk - 2.5 * GAS_CONSTANT_J_MOLK)
                        * pure_eta0 / item.molar_mass_kg_mol)
    internal_k = sum(xi * xj * (2.0 * ki * kj / (ki + kj) if ki + kj > 0 else 0.0)
                     for xi, ki in zip(fractions, internal) for xj, kj in zip(fractions, internal))
    conductivity = translational_k + internal_k
    return MixtureTransport(_positive(viscosity, "predicted viscosity"),
                            _positive(conductivity, "predicted conductivity"), t0, rho0)


def lng_ecs_transport(*, temperature_k: float, molar_density_mol_m3: float,
                      components: Sequence[str | TransportComponent], mole_fractions: Sequence[float]
                      ) -> MixtureTransport:
    """Return nonpolar phase transport, raising ValueError for unavailable states.

    See the module description for source and applicability. Numerical overflow
    is an unavailable correlation state, never a clipped transport coefficient.
    """
    try:
        return _lng_ecs_transport(temperature_k=temperature_k,
                                  molar_density_mol_m3=molar_density_mol_m3,
                                  components=components, mole_fractions=mole_fractions)
    except (OverflowError, ZeroDivisionError) as error:
        raise ValueError("TRAPP phase state outside the finite correlation domain") from error


__all__ = ["MixtureTransport", "TransportComponent", "lng_ecs_transport"]
