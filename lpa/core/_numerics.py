"""Small dependency-free numerical helpers used by the core package."""

from __future__ import annotations

from math import sqrt


def linspace(start: float, stop: float, count: int) -> tuple[float, ...]:
    if count < 2:
        return (float(start),)
    step = (stop - start) / (count - 1)
    return tuple(start + index * step for index in range(count))


def area_mach_ratio(mach: float, gamma: float) -> float:
    if mach <= 0:
        raise ValueError("Mach number must be positive")
    exponent = (gamma + 1.0) / (2.0 * (gamma - 1.0))
    factor = (2.0 / (gamma + 1.0)) * (
        1.0 + 0.5 * (gamma - 1.0) * mach * mach
    )
    return factor**exponent / mach


def solve_mach(area_ratio: float, gamma: float, *, supersonic: bool) -> float:
    """Invert the isentropic area-Mach relation by robust bisection."""

    if area_ratio < 1.0:
        raise ValueError("area ratio must be >= 1")
    if abs(area_ratio - 1.0) < 1e-10:
        return 1.0
    if supersonic:
        low, high = 1.0 + 1e-8, 2.0
        while area_mach_ratio(high, gamma) < area_ratio and high < 50.0:
            high *= 1.5
        for _ in range(90):
            mid = 0.5 * (low + high)
            if area_mach_ratio(mid, gamma) < area_ratio:
                low = mid
            else:
                high = mid
    else:
        low, high = 1e-8, 1.0 - 1e-8
        for _ in range(90):
            mid = 0.5 * (low + high)
            if area_mach_ratio(mid, gamma) > area_ratio:
                low = mid
            else:
                high = mid
    return 0.5 * (low + high)


def mach_from_pressure_ratio(chamber_to_static: float, gamma: float) -> float:
    if chamber_to_static <= 1:
        return 1.0
    term = chamber_to_static ** ((gamma - 1.0) / gamma) - 1.0
    return sqrt(2.0 * term / (gamma - 1.0))


def expansion_ratio_for_pressure(
    chamber_pressure_pa: float,
    exit_pressure_pa: float,
    gamma: float,
) -> float:
    if exit_pressure_pa <= 0:
        return 250.0
    pressure_ratio = chamber_pressure_pa / exit_pressure_pa
    if pressure_ratio <= ((gamma + 1) / 2) ** (gamma / (gamma - 1)):
        return 1.0001
    mach = mach_from_pressure_ratio(pressure_ratio, gamma)
    return max(1.0001, area_mach_ratio(mach, gamma))
