"""Constrain automatic Rao angle candidates to the requested bell geometry.

This module only tests and enforces the geometry of a circular throat arc
followed by a quadratic parabola with decreasing, nonnegative wall slope.
It does not select flow-optimal angles or reproduce RPA's angle algorithm.
The expansion ratio, nozzle length fraction, and throat radius remain fixed.
If those dimensions cannot form this contour, a ValueError describes them.
"""

from __future__ import annotations

from math import (
    asin,
    atan,
    atan2,
    degrees,
    hypot,
    isfinite,
    nextafter,
    pi,
    radians,
    sin,
    sqrt,
    tan,
)


def constrain_rao_angles(
    expansion_ratio: float,
    length_fraction: float,
    throat_radius_ratio: float,
    initial_angle_deg: float,
    exit_angle_deg: float,
) -> tuple[float, float]:
    """Preserve feasible candidates, otherwise project them inside the bounds.

    ``length_fraction`` uses the rounded-throat 15-degree cone reference.
    Candidate angles must be finite and nonnegative; zero or >=90-degree
    initial candidates can be projected. An already valid pair is returned
    unchanged. Projection changes angles only, never the supplied dimensions.
    """

    if not isfinite(expansion_ratio) or expansion_ratio <= 1.0:
        raise ValueError("Rao geometry requires a finite expansion ratio greater than 1")
    for value, name in (
        (length_fraction, "nozzle length fraction"),
        (throat_radius_ratio, "throat radius ratio Rn/Rt"),
    ):
        if not isfinite(value) or value <= 0.0:
            raise ValueError(f"Rao geometry requires a finite positive {name}")
    if any(not isfinite(value) or value < 0.0 for value in (initial_angle_deg, exit_angle_deg)):
        raise ValueError("Rao candidate angles must be finite and nonnegative")

    description = (
        f"Ae/At={expansion_ratio:g}, Le/Lc15={length_fraction * 100:g}%, "
        f"Rn/Rt={throat_radius_ratio:g}"
    )

    def impossible() -> ValueError:
        return ValueError(
            "Rao geometry cannot fit the specified nozzle length and throat radius "
            f"({description}); increase nozzle length or adjust Rn/Rt"
        )

    # Rationalization avoids the subtraction in sqrt(epsilon) - 1. Scale all
    # dimensions together again to keep the subsequent products bounded.
    radial_gain = (expansion_ratio - 1.0) / (sqrt(expansion_ratio) + 1.0)
    scale = max(radial_gain, throat_radius_ratio)
    radial_gain /= scale
    radius = throat_radius_ratio / scale
    length = length_fraction * (
        radial_gain / tan(radians(15.0)) + radius * tan(radians(7.5))
    )
    if radial_gain <= 0.0 or radius <= 0.0 or not isfinite(length):
        raise impossible()

    # Below the arc center, E must lie strictly outside the throat circle.
    # Above it, E must also lie downstream of the arc's maximum x coordinate.
    circle_term = 2.0 * radius - radial_gain
    if radial_gain < radius:
        minimum_length = sqrt(radial_gain) * sqrt(circle_term)
        if length <= minimum_length:
            raise impossible()
        upper = 2.0 * asin(sqrt(radial_gain / (2.0 * radius)))
    else:
        if length <= radius:
            raise impossible()
        upper = pi / 2.0

    # The lower tangent limit solves
    # 2*L*u - delta - (2*Rn-delta)*u**2 = 0, u = tan(Tn/2).
    # Use its rationalized root, avoiding a difference of similar angles.
    if circle_term > 0.0:
        circle_length = sqrt(radial_gain) * sqrt(circle_term)
        root = sqrt(length - circle_length) * sqrt(length + circle_length)
    else:
        root = hypot(length, sqrt(radial_gain) * sqrt(-circle_term))
    lower = 2.0 * atan((radial_gain / length) / (1.0 + root / length))
    if not lower < upper:
        raise impossible()

    def chord_angle(angle_deg: float) -> float | None:
        if not 0.0 < angle_deg < 90.0:
            return None
        angle = radians(angle_deg)
        axial_gap = length - radius * sin(angle)
        # 2*sin(theta/2)**2 is stable even for very small wall angles.
        radial_gap = radial_gain - 2.0 * radius * sin(angle / 2.0) ** 2
        if axial_gap <= 0.0 or radial_gap <= 0.0:
            return None
        return degrees(atan2(radial_gap, axial_gap))

    chord = chord_angle(initial_angle_deg)
    initial_is_valid = chord is not None and chord < initial_angle_deg
    if initial_is_valid and exit_angle_deg < chord:
        return initial_angle_deg, exit_angle_deg

    if not initial_is_valid:
        lower_deg, upper_deg = degrees(lower), degrees(upper)
        margin = min(2.0, 0.02 * (upper_deg - lower_deg))
        inner_lower = max(lower_deg + margin, nextafter(lower_deg, upper_deg))
        inner_upper = min(upper_deg - margin, nextafter(upper_deg, lower_deg))
        if not inner_lower <= inner_upper:
            raise impossible()
        initial_angle_deg = min(inner_upper, max(inner_lower, initial_angle_deg))
        chord = chord_angle(initial_angle_deg)
        if chord is None or not chord < initial_angle_deg:
            raise impossible()

    if exit_angle_deg >= chord or exit_angle_deg >= initial_angle_deg:
        exit_angle_deg = max(0.0, min(chord, initial_angle_deg) * 0.98)
    if not 0.0 <= exit_angle_deg < chord < initial_angle_deg < 90.0:
        raise impossible()
    return initial_angle_deg, exit_angle_deg
