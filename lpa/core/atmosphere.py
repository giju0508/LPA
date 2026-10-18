"""U.S. Standard Atmosphere 1976 lower-atmosphere model.

The layer equations use geopotential altitude internally and expose geometric
altitude to the UI.  The implemented range is -5 km through the 84.852 km
geopotential boundary (about 86 km geometric altitude).
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from math import exp, isfinite, log


G0_M_S2 = 9.80665
DRY_AIR_GAS_CONSTANT_J_KGK = 287.05287
EARTH_RADIUS_M = 6_356_766.0
SEA_LEVEL_PRESSURE_PA = 101_325.0
SEA_LEVEL_TEMPERATURE_K = 288.15
MIN_GEOMETRIC_ALTITUDE_M = -5_000.0

_BASE_GEOPOTENTIAL_ALTITUDES_M = (
    0.0,
    11_000.0,
    20_000.0,
    32_000.0,
    47_000.0,
    51_000.0,
    71_000.0,
    84_852.0,
)
_LAPSE_RATES_K_M = (-0.0065, 0.0, 0.0010, 0.0028, 0.0, -0.0028, -0.0020)


def _geopotential_from_geometric(altitude_m: float) -> float:
    return EARTH_RADIUS_M * altitude_m / (EARTH_RADIUS_M + altitude_m)


def _geometric_from_geopotential(altitude_m: float) -> float:
    return EARTH_RADIUS_M * altitude_m / (EARTH_RADIUS_M - altitude_m)


MAX_GEOMETRIC_ALTITUDE_M = _geometric_from_geopotential(
    _BASE_GEOPOTENTIAL_ALTITUDES_M[-1]
)


def _base_states() -> tuple[tuple[float, ...], tuple[float, ...]]:
    temperatures = [SEA_LEVEL_TEMPERATURE_K]
    pressures = [SEA_LEVEL_PRESSURE_PA]
    for index, lapse_rate in enumerate(_LAPSE_RATES_K_M):
        h0 = _BASE_GEOPOTENTIAL_ALTITUDES_M[index]
        h1 = _BASE_GEOPOTENTIAL_ALTITUDES_M[index + 1]
        temperature0 = temperatures[-1]
        pressure0 = pressures[-1]
        if lapse_rate == 0.0:
            temperature1 = temperature0
            pressure1 = pressure0 * exp(
                -G0_M_S2 * (h1 - h0)
                / (DRY_AIR_GAS_CONSTANT_J_KGK * temperature0)
            )
        else:
            temperature1 = temperature0 + lapse_rate * (h1 - h0)
            pressure1 = pressure0 * (temperature1 / temperature0) ** (
                -G0_M_S2 / (DRY_AIR_GAS_CONSTANT_J_KGK * lapse_rate)
            )
        temperatures.append(temperature1)
        pressures.append(pressure1)
    return tuple(temperatures), tuple(pressures)


_BASE_TEMPERATURES_K, _BASE_PRESSURES_PA = _base_states()


@dataclass(frozen=True, slots=True)
class StandardAtmosphereState:
    geometric_altitude_m: float
    geopotential_altitude_m: float
    temperature_k: float
    pressure_pa: float
    density_kg_m3: float


def standard_atmosphere(geometric_altitude_m: float) -> StandardAtmosphereState:
    """Return temperature, pressure, and density at geometric altitude."""

    altitude = float(geometric_altitude_m)
    if not isfinite(altitude):
        raise ValueError("altitude must be finite")
    if not MIN_GEOMETRIC_ALTITUDE_M <= altitude <= MAX_GEOMETRIC_ALTITUDE_M:
        raise ValueError(
            f"altitude must be between {MIN_GEOMETRIC_ALTITUDE_M:g} and "
            f"{MAX_GEOMETRIC_ALTITUDE_M:.3f} m"
        )
    geopotential = _geopotential_from_geometric(altitude)
    layer = max(
        0,
        min(
            len(_LAPSE_RATES_K_M) - 1,
            bisect_right(_BASE_GEOPOTENTIAL_ALTITUDES_M, geopotential) - 1,
        ),
    )
    h0 = _BASE_GEOPOTENTIAL_ALTITUDES_M[layer]
    temperature0 = _BASE_TEMPERATURES_K[layer]
    pressure0 = _BASE_PRESSURES_PA[layer]
    lapse_rate = _LAPSE_RATES_K_M[layer]
    if lapse_rate == 0.0:
        temperature = temperature0
        pressure = pressure0 * exp(
            -G0_M_S2 * (geopotential - h0)
            / (DRY_AIR_GAS_CONSTANT_J_KGK * temperature0)
        )
    else:
        temperature = temperature0 + lapse_rate * (geopotential - h0)
        pressure = pressure0 * (temperature / temperature0) ** (
            -G0_M_S2 / (DRY_AIR_GAS_CONSTANT_J_KGK * lapse_rate)
        )
    density = pressure / (DRY_AIR_GAS_CONSTANT_J_KGK * temperature)
    return StandardAtmosphereState(
        geometric_altitude_m=altitude,
        geopotential_altitude_m=geopotential,
        temperature_k=temperature,
        pressure_pa=pressure,
        density_kg_m3=density,
    )


MIN_MODEL_PRESSURE_PA = standard_atmosphere(MAX_GEOMETRIC_ALTITUDE_M).pressure_pa
MAX_MODEL_PRESSURE_PA = standard_atmosphere(MIN_GEOMETRIC_ALTITUDE_M).pressure_pa


def altitude_for_pressure(pressure_pa: float) -> StandardAtmosphereState | None:
    """Invert the standard atmosphere; return ``None`` outside model bounds."""

    pressure = float(pressure_pa)
    if not isfinite(pressure) or not MIN_MODEL_PRESSURE_PA <= pressure <= MAX_MODEL_PRESSURE_PA:
        return None

    if pressure > SEA_LEVEL_PRESSURE_PA:
        layer = 0
    else:
        layer = len(_LAPSE_RATES_K_M) - 1
        for index in range(len(_LAPSE_RATES_K_M)):
            upper = _BASE_PRESSURES_PA[index]
            lower = _BASE_PRESSURES_PA[index + 1]
            if upper >= pressure >= lower:
                layer = index
                break

    h0 = _BASE_GEOPOTENTIAL_ALTITUDES_M[layer]
    temperature0 = _BASE_TEMPERATURES_K[layer]
    pressure0 = _BASE_PRESSURES_PA[layer]
    lapse_rate = _LAPSE_RATES_K_M[layer]
    if lapse_rate == 0.0:
        geopotential = h0 - (
            DRY_AIR_GAS_CONSTANT_J_KGK * temperature0 / G0_M_S2
        ) * log(pressure / pressure0)
    else:
        temperature = temperature0 * (pressure / pressure0) ** (
            -DRY_AIR_GAS_CONSTANT_J_KGK * lapse_rate / G0_M_S2
        )
        geopotential = h0 + (temperature - temperature0) / lapse_rate
    geometric = _geometric_from_geopotential(geopotential)
    return standard_atmosphere(geometric)


def bounded_altitude_for_pressure(pressure_pa: float) -> StandardAtmosphereState:
    """Return an inverse state, clipping only to the documented model bounds."""

    pressure = min(MAX_MODEL_PRESSURE_PA, max(MIN_MODEL_PRESSURE_PA, float(pressure_pa)))
    state = altitude_for_pressure(pressure)
    if state is None:  # Defensive: pressure has just been clipped to valid bounds.
        raise RuntimeError("standard-atmosphere pressure inversion failed")
    return state
