"""Small dependency-free numerical helpers used by the core package."""

from __future__ import annotations

from math import exp, isfinite, log, sqrt


def _validate_gamma(gamma: float) -> None:
    if not isfinite(gamma) or gamma <= 1.0:
        raise ValueError("isentropic exponent must be finite and greater than 1")


def _log_area_mach_ratio(mach: float, gamma: float) -> float:
    exponent = (gamma + 1.0) / (2.0 * (gamma - 1.0))
    return exponent * log((2.0 / (gamma + 1.0)) * (1.0 + 0.5 * (gamma - 1.0) * mach * mach)) - log(mach)


def linspace(start: float, stop: float, count: int) -> tuple[float, ...]:
    if count < 2:
        return (float(start),)
    step = (stop - start) / (count - 1)
    return tuple(start + index * step for index in range(count))


def area_mach_ratio(mach: float, gamma: float) -> float:
    _validate_gamma(gamma)
    if not isfinite(mach) or mach <= 0:
        raise ValueError("Mach number must be finite and positive")
    return exp(_log_area_mach_ratio(mach, gamma))


def solve_mach(area_ratio: float, gamma: float, *, supersonic: bool) -> float:
    """Invert the isentropic area-Mach relation by robust bisection."""

    _validate_gamma(gamma)
    if not isfinite(area_ratio) or area_ratio < 1.0:
        raise ValueError("area ratio must be finite and >= 1")
    if abs(area_ratio - 1.0) < 1e-10:
        return 1.0
    if supersonic:
        low, high = 1.0 + 1e-8, 2.0
        target = log(area_ratio)
        while _log_area_mach_ratio(high, gamma) < target:
            high *= 1.5
            if not isfinite(high) or high > 1.0e150:
                raise ValueError("area-Mach inversion could not bracket the requested area ratio")
        for _ in range(90):
            mid = 0.5 * (low + high)
            if _log_area_mach_ratio(mid, gamma) < target:
                low = mid
            else:
                high = mid
    else:
        low, high = min(1e-8, 0.1 / area_ratio), 1.0 - 1e-8
        target = log(area_ratio)
        for _ in range(1100):
            mid = 0.5 * (low + high)
            if mid == low or mid == high:
                break
            if _log_area_mach_ratio(mid, gamma) > target:
                low = mid
            else:
                high = mid
    return 0.5 * (low + high)


def mach_from_pressure_ratio(chamber_to_static: float, gamma: float) -> float:
    _validate_gamma(gamma)
    if not isfinite(chamber_to_static) or chamber_to_static <= 1:
        raise ValueError("total-to-static pressure ratio must be finite and greater than 1")
    term = chamber_to_static ** ((gamma - 1.0) / gamma) - 1.0
    return sqrt(2.0 * term / (gamma - 1.0))


def expansion_ratio_for_pressure(
    chamber_pressure_pa: float,
    exit_pressure_pa: float,
    gamma: float,
) -> float:
    _validate_gamma(gamma)
    if not isfinite(chamber_pressure_pa) or chamber_pressure_pa <= 0:
        raise ValueError("chamber pressure must be finite and positive")
    if not isfinite(exit_pressure_pa) or exit_pressure_pa < 0:
        raise ValueError("exit pressure must be finite and non-negative")
    if exit_pressure_pa <= 0:
        return 250.0
    pressure_ratio = chamber_pressure_pa / exit_pressure_pa
    if pressure_ratio <= ((gamma + 1) / 2) ** (gamma / (gamma - 1)):
        raise ValueError("exit pressure does not admit a supersonic nozzle expansion")
    mach = mach_from_pressure_ratio(pressure_ratio, gamma)
    return max(1.0001, area_mach_ratio(mach, gamma))
