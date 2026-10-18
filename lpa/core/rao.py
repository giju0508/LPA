"""Rao parabolic-nozzle wall angles from a chart and verified RPA flow relations.

Source: Huzel and Huang, *Design of Liquid Propellant Rocket Engines*,
NASA SP-125, Fig. 4-14 (printed p. 91; PDF page 100), and the worked
example on printed p. 98 (PDF page 107):
https://ntrs.nasa.gov/api/citations/19710019929/downloads/19710019929.pdf

The scanned chart has curves for 60, 70, 80, 90, and 100 percent of the
equivalent 15-degree conical-nozzle length, over area ratios 5 through 50.
The samples below were read from that chart and mostly rounded to half
a degree.  Allow roughly half a degree for chart-reading/interpolation
uncertainty; this is an engineering estimate, not a guaranteed error bound
or a claim of 0.1-degree accuracy.  The 80-percent, area-ratio-14 sample
uses the explicitly published 27.4/9.8-degree example instead.

Both axes are interpolated linearly, matching the chart's linear axes.
The additional area-ratio samples near the lower end capture the sharper
curvature there.  Rounded samples can produce small plateaus; the table
preserves the chart's nondecreasing initial angle and nonincreasing exit
angle with increasing expansion ratio.  Both angles decrease with nozzle
length.  The chart is only interpolated within its published domain.

Outside that domain, flow-based initial and exit angle relations were
verified against 20 actual outputs from the official scripting utility
bundled with RPA 4.0.13.  See tests/fixtures/rpa_rao_4_0_13.json for the
inputs, measured isentropic exponents, outputs and executable provenance.
They are observed relations, not formulas published in the RPA manual.
LPA uses its own thermochemical backend to supply the flow state, so equal
relations do not imply equal RPA/LPA thermochemistry or thrust optimality.
Geometry constraints are applied to the angles before constructing Q,
preserving the requested length and blend radius and both actual tangents.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from math import asin, atan, degrees, isfinite, sqrt

from ._numerics import solve_mach
from .rao_geometry import constrain_rao_angles


RAO_MIN_EXPANSION_RATIO = 5.0
RAO_MAX_EXPANSION_RATIO = 50.0
RAO_MIN_LENGTH_FRACTION = 0.6
RAO_MAX_LENGTH_FRACTION = 1.0
RAO_ANGLE_METHOD = "nasa_sp125_chart_interpolation"
RAO_ANGLE_SOURCE = "NASA SP-125, Fig. 4-14 and p. 98"
RPA_FLOW_ANGLE_METHOD = "rpa_observed_flow_auto"
RPA_FLOW_ANGLE_SOURCE = "Flow relations verified against the official Script utility in the RPA 4.0.13 bundle"

# Column order is expansion area ratio Ae/At.  Angles are wall angles in
# degrees relative to the nozzle axis, not gas-flow deflection angles.
_EXPANSION_RATIOS = (5.0, 7.5, 10.0, 14.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0)
_LENGTH_FRACTIONS = (0.6, 0.7, 0.8, 0.9, 1.0)

# Rows follow _LENGTH_FRACTIONS.  Retain the source-chart samples instead
# of fitting an unsourced algebraic correlation to the angle trends.
_INITIAL_ANGLES_DEG = (
    (28.5, 30.5, 32.5, 34.0, 34.0, 35.5, 36.5, 37.5, 38.0, 38.0, 38.5, 39.0),
    (25.5, 27.0, 28.5, 30.0, 30.5, 31.5, 32.5, 33.5, 34.0, 34.5, 35.0, 35.0),
    (23.5, 25.0, 26.0, 27.4, 28.0, 29.0, 30.0, 31.0, 31.5, 31.5, 32.0, 32.5),
    (21.5, 23.0, 24.5, 26.0, 26.0, 27.5, 28.0, 29.0, 29.5, 30.0, 30.5, 30.5),
    (20.0, 21.5, 23.0, 24.5, 24.5, 26.0, 26.5, 27.5, 28.0, 28.5, 29.0, 29.5),
)
_EXIT_ANGLES_DEG = (
    (20.0, 18.0, 17.0, 15.5, 15.5, 14.5, 14.0, 14.0, 13.5, 13.0, 13.0, 13.0),
    (16.5, 15.0, 13.5, 12.5, 12.0, 11.5, 11.0, 10.5, 10.5, 10.0, 10.0, 10.0),
    (13.5, 12.0, 10.5, 9.8, 9.5, 9.0, 8.5, 8.5, 8.5, 8.0, 8.0, 8.0),
    (10.5, 9.5, 8.5, 7.5, 7.5, 6.5, 6.5, 6.5, 6.5, 6.5, 6.5, 6.5),
    (8.5, 7.5, 6.5, 6.0, 5.5, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0),
)


def _interval(axis: tuple[float, ...], value: float) -> tuple[int, float]:
    """Find an in-range interpolation interval, including its upper end."""

    index = min(bisect_right(axis, value) - 1, len(axis) - 2)
    fraction = (value - axis[index]) / (axis[index + 1] - axis[index])
    return index, fraction


def _chart_angles(expansion_ratio: float, length_fraction: float) -> tuple[float, float]:
    """Interpolate the source-chart samples; called only within their domain."""

    ratio_index, ratio_fraction = _interval(_EXPANSION_RATIOS, expansion_ratio)
    length_index, length_weight = _interval(_LENGTH_FRACTIONS, length_fraction)

    def interpolate(table: tuple[tuple[float, ...], ...]) -> float:
        shorter = table[length_index]
        longer = table[length_index + 1]
        shorter_angle = shorter[ratio_index] + ratio_fraction * (
            shorter[ratio_index + 1] - shorter[ratio_index]
        )
        longer_angle = longer[ratio_index] + ratio_fraction * (
            longer[ratio_index + 1] - longer[ratio_index]
        )
        return shorter_angle + length_weight * (longer_angle - shorter_angle)

    return interpolate(_INITIAL_ANGLES_DEG), interpolate(_EXIT_ANGLES_DEG)


def rpa_flow_angles(
    exit_mach: float,
    throat_isentropic_exponent: float,
    exit_isentropic_exponent: float,
) -> tuple[float, float]:
    """Return the observed RPA flow-angle preferences in degrees.

    K is the sonic/isentropic exponent, not necessarily Cp/Cv for reacting
    equilibrium gas.  RPA observations use Tn=nu(Me,Kt)/3 and a bounded exit
    preference .5*asin(2*sqrt(Me**2-1)/(Ke*Me**2)).  The 8-degree floor is
    applied first; only when that preference exceeds Tn is Te=.9*Tn used.
    The returned preferences have not yet been checked against bell length.
    """

    if not isfinite(exit_mach) or exit_mach <= 1.0:
        raise ValueError("RPA flow-angle calculation requires a finite supersonic exit Mach number")
    if any(not isfinite(value) or value <= 1.0 for value in
           (throat_isentropic_exponent, exit_isentropic_exponent)):
        raise ValueError("RPA flow-angle calculation requires finite isentropic exponents greater than 1")
    expansion_factor_squared = (
        (throat_isentropic_exponent - 1.0)
        / (throat_isentropic_exponent + 1.0)
    )
    expansion_factor = sqrt(expansion_factor_squared)
    sonic_excess = sqrt(exit_mach - 1.0) * sqrt(exit_mach + 1.0)
    if sonic_excess < 0.01:
        # Direct subtraction of the two atan terms loses precision at M=1.
        square = sonic_excess**2
        nu = sonic_excess**3 * (
            (1.0 - expansion_factor_squared) / 3.0
            - (1.0 - expansion_factor_squared**2) * square / 5.0
            + (1.0 - expansion_factor_squared**3) * square**2 / 7.0
            - (1.0 - expansion_factor_squared**4) * square**3 / 9.0
        )
    else:
        nu = atan(expansion_factor * sonic_excess) / expansion_factor - atan(sonic_excess)
    initial = degrees(nu / 3.0)
    inverse_mach = 1.0 / exit_mach
    argument = (
        2.0 * inverse_mach * sqrt(max(0.0, 1.0 - inverse_mach**2))
        / exit_isentropic_exponent
    )
    exit_preference = max(8.0, degrees(0.5 * asin(min(1.0, argument))))
    return initial, 0.9 * initial if exit_preference > initial else exit_preference


@dataclass(frozen=True, slots=True)
class RaoAngleSelection:
    initial_angle_deg: float
    exit_angle_deg: float
    method: str
    source: str
    initial_preference_deg: float
    exit_preference_deg: float
    flow_source: str = "not_used_chart_interpolation"
    exit_mach: float | None = None
    throat_isentropic_exponent: float | None = None
    exit_isentropic_exponent: float | None = None

    @property
    def geometry_adjusted(self) -> bool:
        return (
            abs(self.initial_angle_deg - self.initial_preference_deg) > 1e-10
            or abs(self.exit_angle_deg - self.exit_preference_deg) > 1e-10
        )


def select_rao_angles(
    expansion_ratio: float,
    length_fraction: float,
    *,
    throat_radius_ratio: float = 0.382,
    exit_mach: float | None = None,
    throat_isentropic_exponent: float | None = None,
    exit_isentropic_exponent: float | None = None,
    flow_source: str | None = None,
) -> RaoAngleSelection:
    """Select automatic angles for finite Ae/At>1 and 50-120% bell length.

    Preserve the NASA chart inside its domain.  Otherwise use the verified
    RPA flow relations, with geometric feasibility enforced before Q is built.
    Geometry-only callers without a flow state use an ideal gas with K=1.2;
    engine analysis supplies its actual backend Mach and station exponents.
    """

    if not isfinite(expansion_ratio) or expansion_ratio <= 1.0:
        raise ValueError("Rao automatic angles require finite expansion ratio Ae/At greater than 1")
    if not isfinite(length_fraction) or not 0.5 <= length_fraction <= 1.2:
        raise ValueError("Rao automatic angles require a finite bell length of 50-120%")
    if not isfinite(throat_radius_ratio) or throat_radius_ratio <= 0.0:
        raise ValueError("Rao automatic angles require a finite positive Rn/Rt")
    if (
        RAO_MIN_EXPANSION_RATIO <= expansion_ratio <= RAO_MAX_EXPANSION_RATIO
        and RAO_MIN_LENGTH_FRACTION <= length_fraction <= RAO_MAX_LENGTH_FRACTION
    ):
        initial, exit_angle = _chart_angles(expansion_ratio, length_fraction)
        return RaoAngleSelection(initial, exit_angle, RAO_ANGLE_METHOD, RAO_ANGLE_SOURCE,
                                 initial, exit_angle)
    supplied = any(value is not None for value in
                   (exit_mach, throat_isentropic_exponent, exit_isentropic_exponent))
    throat_k = 1.2 if throat_isentropic_exponent is None else throat_isentropic_exponent
    exit_k = throat_k if exit_isentropic_exponent is None else exit_isentropic_exponent
    if not isfinite(exit_k) or exit_k <= 1.0:
        raise ValueError("Rao exit isentropic exponent must be finite and greater than 1")
    mach = solve_mach(expansion_ratio, exit_k, supersonic=True) if exit_mach is None else exit_mach
    initial_preference, exit_preference = rpa_flow_angles(mach, throat_k, exit_k)
    initial, exit_angle = constrain_rao_angles(
        expansion_ratio, length_fraction, throat_radius_ratio,
        initial_preference, exit_preference,
    )
    return RaoAngleSelection(
        initial, exit_angle, RPA_FLOW_ANGLE_METHOD, RPA_FLOW_ANGLE_SOURCE,
        initial_preference, exit_preference,
        flow_source or ("provided_or_estimated_flow_state" if supplied else "ideal_gas_default_K_1.2"),
        mach, throat_k, exit_k,
    )


def rao_angles(expansion_ratio: float, length_fraction: float, **flow_options) -> tuple[float, float]:
    """Return automatic (Tn, Te), including outside the published chart."""

    selection = select_rao_angles(expansion_ratio, length_fraction, **flow_options)
    return selection.initial_angle_deg, selection.exit_angle_deg
