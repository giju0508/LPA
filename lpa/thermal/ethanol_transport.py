"""Phase-qualified ethanol/water transport with experimental excess terms.

Liquid viscosity uses a Redlich-Kister excess log-viscosity fit to Gonzalez
(2007) and Ono (2016), with an entire pressure level withheld. Liquid k uses
Li's aqueous-compatible volume-fraction mixing rule and an excess log-k fit
to Cui (2019). Hoga (2018) and Zhou (2013) are independent holdout studies.
These are predictive correlations, not a new EOS or a validated T/P rectangle.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import exp, isfinite, log, sqrt
from typing import Any


M_ETHANOL = .04606844  # kg/mol
M_WATER = .018015268  # kg/mol
R = 8.31446261815324  # J/(mol K)
LIQUID_SOURCE = "Experimental ethanol-water excess transport correlations with pure HEOS liquid references and Li mixing"
VAPOR_SOURCE = "Wilke viscosity / Wassiljewa-Mason-Saxena conductivity; dilute HEOS vapor references"
REFERENCES = (
    "https://doi.org/10.1016/j.jct.2007.05.004",  # viscosity calibration
    "https://doi.org/10.1016/j.fluid.2015.07.012",  # high-pressure viscosity calibration
    "https://doi.org/10.1021/acs.jced.8b01147",  # conductivity calibration
    "https://doi.org/10.1002/aic.690220520",  # Li aqueous-compatible liquid k rule
    "https://doi.org/10.1016/j.jct.2018.02.022",  # independent viscosity holdout
    "https://doi.org/10.1021/je301171y",  # independent conductivity holdout
)
VAPOR_REFERENCES = (
    "https://doi.org/10.1063/1.1747673",
    "https://idaes-pse.readthedocs.io/en/stable/explanations/components/property_package/general/transport_properties/thermal_conductivity_wms.html",
)

# Fit from the SI source fixture tests/data/ethanol_water_transport_reference.json.
# u=300/T-1, z=2*x_E-1, q=(P/MPa-0.1)/40. Coefficient order is
# j=0..3,m=0..2, followed by pressure terms j=0..2,m=0..1.
# All 30 MPa points and all Hoga/Zhou points are excluded from calibration.
_MU_COEFFICIENTS = (
    2.5521625427318106, 7.381255316391699, 3.8820730843465414,
    -2.3885410429255782, -9.335149448199186, -11.35526198590314,
    3.1505576964162714, 17.72264695242283, 27.203299295133487,
    -2.195054125281231, -6.734776917950873, -6.46554841341915,
    .19927058981792906, .44946861195684695, .024757656657972225,
    .4525939649932906, .19624855432660412, .16469781815635626,
)
# Excess log-k: j=0..3,m=0..1. The baseline itself accounts for pure-fluid
# T/P transport and molar volume changes; no mixture pressure data were fitted.
_K_COEFFICIENTS = (
    .21298306590306998, -.3568602380534128, -.1530780489283577, .4175922851379672,
    .20715840407742087, .03953778801213393, -.22072060713771582, 2.519705690651605,
)

# Reproducible against the retained source fixture. These errors are observed
# holdout comparisons, not universal uncertainties or experiment replacements.
INDEPENDENT_HOLDOUT = {
    "viscosity_Hoga2018": {"points": 100, "aad_percent": 2.55315298695,
                           "maximum_absolute_percent": 6.59678728890},
    "conductivity_Zhou2013": {"points": 63, "aad_percent": .585613416584,
                              "maximum_absolute_percent": 2.17989510079},
}


@dataclass(frozen=True, slots=True)
class EthanolWaterTransport:
    viscosity_pa_s: float
    conductivity_w_mk: float
    phase: str
    source: str
    issues: tuple[str, ...]
    evidence: dict[str, Any]
    references: tuple[str, ...] = REFERENCES
    property_applicability: str = "correlated"
    validation_status: str = "screening"


def _positive(value: float, name: str) -> float:
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError(f"ethanol/water {name} must be finite and positive")
    return number


@lru_cache(maxsize=4096)
def _pure_liquid_reference(temperature: float, pressure: float, fluid: str
                           ) -> tuple[float, float, float, bool]:
    """Return pure-liquid mu, k, molar volume, and saturation-reference flag.

    A liquid mixture can coexist with vapor above a *pure* component's boiling
    temperature. Using an automatically selected pure gas there is incorrect.
    The defined pure reference is compressed liquid when available, otherwise
    saturated liquid at that T. This is explicitly an engineering reference;
    its use never asserts that the mixture was measured at the supplied T/P.
    """
    import CoolProp.CoolProp as CP

    state = CP.AbstractState("HEOS", fluid)
    if temperature >= state.T_critical():
        raise ValueError(f"ethanol/water pure liquid reference for {fluid} is undefined at/above its critical temperature")
    state.update(CP.QT_INPUTS, 0.0, temperature)
    saturation_pressure = float(state.p())
    saturation_reference = pressure <= saturation_pressure
    if not saturation_reference:
        state.specify_phase(CP.iphase_liquid)
        state.update(CP.PT_INPUTS, pressure, temperature)
    return (_positive(state.viscosity(), "pure liquid viscosity"),
            _positive(state.conductivity(), "pure liquid conductivity"),
            _positive(state.molar_mass() / state.rhomass(), "pure liquid molar volume"), saturation_reference)


@lru_cache(maxsize=2048)
def _pure_dilute_vapor_reference(temperature: float, fluid: str) -> tuple[float, float, float]:
    import CoolProp.CoolProp as CP

    state = CP.AbstractState("HEOS", fluid)
    state.specify_phase(CP.iphase_gas)
    state.update(CP.DmolarT_INPUTS, 1.e-8, temperature)
    return (_positive(state.viscosity(), "pure vapor viscosity"),
            _positive(state.conductivity(), "pure vapor conductivity"), state.molar_mass())


def _li_mixing(x: float, ethanol: tuple[float, ...], water: tuple[float, ...]) -> float:
    phi = x * ethanol[2] / (x * ethanol[2] + (1.0 - x) * water[2])
    cross_k = 2.0 * ethanol[1] * water[1] / (ethanol[1] + water[1])
    return phi ** 2 * ethanol[1] + (1.0 - phi) ** 2 * water[1] + 2.0 * phi * (1.0 - phi) * cross_k


def _liquid(temperature: float, pressure: float, x: float) -> EthanolWaterTransport:
    if not 273.15 <= temperature <= 500.0 or pressure > 40.e6:
        raise ValueError("ethanol/water liquid correlation outside 273.15-500 K / <=40 MPa calculation guard")
    ethanol = _pure_liquid_reference(temperature, pressure, "Ethanol")
    water = _pure_liquid_reference(temperature, pressure, "Water")
    u, z, q = 300.0 / temperature - 1.0, 2.0 * x - 1.0, (pressure / 1.e6 - .1) / 40.0
    basis_mu = [x * (1.0 - x) * z ** j * u ** m for j in range(4) for m in range(3)]
    basis_mu += [x * (1.0 - x) * q * z ** j * u ** m for j in range(3) for m in range(2)]
    viscosity = exp(x * log(ethanol[0]) + (1.0 - x) * log(water[0])
                    + sum(a * b for a, b in zip(_MU_COEFFICIENTS, basis_mu)))
    basis_k = [x * (1.0 - x) * z ** j * u ** m for j in range(4) for m in range(2)]
    conductivity = _li_mixing(x, ethanol, water) * exp(sum(a * b for a, b in zip(_K_COEFFICIENTS, basis_k)))
    # These describe source-point hulls and prediction, not a verified rectangle.
    ambient_mu_hull = 293.15 <= temperature <= 303.15 and abs(pressure - 101000.) < 1.
    high_mu_hull = 350.7 <= temperature <= 476.2 and 10.e6 <= pressure <= 40.e6 and x >= .1
    k_hull = 282.71 <= temperature <= 343.02 and abs(pressure - 100000.) < 1.
    issues = ["Ethanol-water experimental excess transport correlation; phase EOS and channel heat-transfer validation remain separate"]
    if not (ambient_mu_hull or high_mu_hull):
        issues.append("Viscosity is an engineering prediction outside the sparse calibrated T/P/composition source hulls; independent high-pressure accuracy at this state is unestablished")
    if not k_hull:
        issues.append("Thermal conductivity is an engineering prediction outside the ambient-pressure 282.71-343.02 K calibration data; mixture pressure/high-temperature correction is unvalidated")
    saturation_reference = bool(x > 0 and ethanol[3] or x < 1 and water[3])
    if saturation_reference:
        issues.append("Pure saturated-liquid reference used where mixture pressure is below a pure component saturation pressure; this reference substitution is predictive, not measured mixture transport")
    evidence = {
        "viscosity_model": "pure-liquid log mixture plus calibrated Redlich-Kister excess log viscosity",
        "conductivity_model": "Li aqueous-compatible volume-fraction/harmonic-pair baseline plus calibrated excess log conductivity",
        "viscosity_source_grids": (
            {"doi": "10.1016/j.jct.2007.05.004", "temperature_k": (293.15, 298.15, 303.15),
             "pressure_pa": (101000.,), "ethanol_mole_fraction": "full composition source points"},
            {"doi": "10.1016/j.fluid.2015.07.012", "temperature_k": (350.7, 373.2, 476.2),
             "pressure_pa": (10.e6, 20.e6, 40.e6), "ethanol_mole_fraction": (.1, .2, .3, .4, .6, .8, 1.),
             "withheld_pressure_pa": 30.e6}),
        "conductivity_source_grid": {"doi": "10.1021/acs.jced.8b01147", "points": 68,
                                      "temperature_k_extent": (282.71, 343.02), "pressure_pa": (100000.,)},
        "source_grid_extent_is_validated_rectangle": False,
        "viscosity_scope": "sparse calibration-hull interpolation" if ambient_mu_hull or high_mu_hull else "engineering prediction",
        "conductivity_scope": "ambient calibration-hull interpolation" if k_hull else "engineering prediction",
        "pure_saturated_liquid_reference_used": saturation_reference,
        "independent_holdout": {key: dict(value) for key, value in INDEPENDENT_HOLDOUT.items()},
        "calculation_guard_is_experimental_validity": False,
    }
    return EthanolWaterTransport(_positive(viscosity, "predicted viscosity"),
                                 _positive(conductivity, "predicted conductivity"), "liquid",
                                 LIQUID_SOURCE, tuple(issues), evidence)


def _vapor(temperature: float, pressure: float, x: float, phase: str,
           density: float | None) -> EthanolWaterTransport:
    if not 273.15 <= temperature <= 600.0 or pressure > 40.e6:
        raise ValueError("ethanol/water dilute-vapor transport outside 273.15-600 K / <=40 MPa calculation guard")
    inputs = (_pure_dilute_vapor_reference(temperature, "Ethanol"),
              _pure_dilute_vapor_reference(temperature, "Water"))
    fractions = (x, 1.0 - x)
    viscosity = conductivity = 0.0
    for yi, (mui, ki, mi) in zip(fractions, inputs):
        denominator = sum(yj * (1.0 + sqrt(mui / muj) * (mj / mi) ** .25) ** 2
                          / sqrt(8.0 * (1.0 + mi / mj))
                          for yj, (muj, _kj, mj) in zip(fractions, inputs))
        viscosity += yi * mui / denominator
        conductivity += yi * ki / denominator
    issues = ["Ethanol-water vapor uses dilute-gas Wilke/Wassiljewa-Mason-Saxena engineering estimates at phase composition; dense-gas/critical transport corrections are unavailable"]
    z_factor = pressure * (x * M_ETHANOL + (1.0 - x) * M_WATER) / (density * R * temperature) if density else None
    if pressure > 1.e6 or z_factor is not None and abs(z_factor - 1.0) > .1:
        issues.append("High-pressure/nonideal vapor is outside dilute-gas validation; finite coefficients are predictive diagnostics")
    if phase.startswith("supercritical"):
        issues.append("Supercritical vapor-side transport is an engineering continuation, without a mixture critical enhancement model")
    evidence = {"viscosity_model": "Wilke dilute-gas mixing",
                "conductivity_model": "Wassiljewa-Mason-Saxena dilute-gas mixing",
                "viscosity_scope": "engineering prediction", "conductivity_scope": "engineering prediction",
                "phase_compressibility_factor": z_factor, "dense_gas_correction": False,
                "critical_enhancement": False, "calculation_guard_is_experimental_validity": False}
    return EthanolWaterTransport(_positive(viscosity, "predicted vapor viscosity"),
                                 _positive(conductivity, "predicted vapor conductivity"), phase,
                                 VAPOR_SOURCE, tuple(issues), evidence, VAPOR_REFERENCES)


def ethanol_water_transport(*, temperature_k: float, pressure_pa: float, ethanol_mole_fraction: float,
                            phase: str = "liquid", phase_density_kg_m3: float | None = None
                            ) -> EthanolWaterTransport:
    """Return predictive transport for one EOS-qualified ethanol/water phase.

    ``ethanol_mole_fraction`` is the liquid/vapor phase fraction, rather than
    feed mass fraction. EOS phase stability remains the caller's responsibility.
    Unknown, two-phase bulk, or unqualified supercritical inputs are rejected.
    """
    temperature, pressure = _positive(temperature_k, "temperature"), _positive(pressure_pa, "pressure")
    x = float(ethanol_mole_fraction)
    if not isfinite(x) or not 0.0 <= x <= 1.0:
        raise ValueError("ethanol/water phase mole fraction must be finite and within 0-1")
    density = _positive(phase_density_kg_m3, "phase density") if phase_density_kg_m3 is not None else None
    name = str(phase).casefold().replace("-", "_")
    try:
        if name in {"liquid", "supercritical_liquid"}:
            result = _liquid(temperature, pressure, x)
            if name == "supercritical_liquid":
                return EthanolWaterTransport(result.viscosity_pa_s, result.conductivity_w_mk, name,
                    result.source, (*result.issues, "Supercritical-liquid continuation is predictive; mixture critical transport anomalies are not represented"),
                    result.evidence, result.references)
            return result
        if name in {"gas", "vapor", "supercritical_gas"}:
            return _vapor(temperature, pressure, x, name, density)
        raise ValueError(f"ethanol/water transport requires an identified liquid or vapor phase, got {phase!r}")
    except (OverflowError, ZeroDivisionError) as error:
        raise ValueError("ethanol/water state outside finite transport correlation domain") from error


__all__ = ["EthanolWaterTransport", "INDEPENDENT_HOLDOUT", "ethanol_water_transport"]
