"""Axisymmetric thrust-chamber contour generation.

The bell implementation is a Rao-like quadratic-parabola construction.  It
uses the conventional 15-degree conical length reference and tangent
intersection construction.  Tn and Te are currently selected by an LPA
empirical estimate, not by Rocket Propulsion Analysis (RPA)'s undocumented
automatic-angle logic; the returned metadata records that provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import asin, cos, pi, radians, sin, sqrt, tan

from ._numerics import linspace
from .models import LengthMode, NozzleContourType, Resolution, ThrustChamberInput


def math_asin_clamped(value: float) -> float:
    """asin with round-off protection at circular-arc endpoints."""

    return asin(max(-1.0, min(1.0, value)))


@dataclass(frozen=True, slots=True)
class ContourResult:
    x_m: tuple[float, ...]
    radius_m: tuple[float, ...]
    area_m2: tuple[float, ...]
    throat_index: int
    chamber_end_index: int
    throat_x_m: float
    exit_x_m: float
    metadata: dict[str, float | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        count = len(self.x_m)
        if count < 3 or len(self.radius_m) != count or len(self.area_m2) != count:
            raise ValueError("contour arrays must have matching lengths >= 3")
        if any(right <= left for left, right in zip(self.x_m, self.x_m[1:])):
            raise ValueError("contour x coordinates must be strictly increasing")
        if any(radius <= 0 for radius in self.radius_m):
            raise ValueError("contour radii must be positive")

    @property
    def x_mm(self) -> tuple[float, ...]:
        return tuple(value * 1000.0 for value in self.x_m)

    @property
    def radius_mm(self) -> tuple[float, ...]:
        return tuple(value * 1000.0 for value in self.radius_m)

    @property
    def section_count(self) -> int:
        return len(self.x_m)

    @property
    def length_m(self) -> float:
        return self.exit_x_m - self.x_m[0]


def _point_count(value: Resolution | str | int) -> int:
    if isinstance(value, int):
        if value < 30:
            raise ValueError("contour point count must be at least 30")
        return value
    if not isinstance(value, Resolution):
        text = str(value).strip().casefold()
        try:
            value = Resolution(text)
        except ValueError as error:
            raise ValueError("resolution must be low, medium, high, or an integer") from error
    return value.section_count


def _rao_angles(expansion_ratio: float, length_fraction: float) -> tuple[float, float]:
    """Return LPA's empirical Tn/Te estimate (not an RPA-equivalent solver)."""

    ratio_term = min(1.0, max(0.0, (sqrt(expansion_ratio) - sqrt(4.0)) / 8.0))
    length_term = min(1.2, max(0.5, length_fraction))
    initial = 31.5 - 4.5 * ratio_term - 9.0 * (length_term - 0.8)
    exit_angle = 11.5 - 4.0 * ratio_term - 13.0 * (length_term - 0.8)
    return max(20.0, min(36.0, initial)), max(4.0, min(16.0, exit_angle))


def _quadratic_bezier(
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
    count: int,
) -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    for t_value in linspace(0.0, 1.0, count):
        inverse = 1.0 - t_value
        x_value = inverse * inverse * start[0] + 2 * inverse * t_value * control[0] + t_value**2 * end[0]
        y_value = inverse * inverse * start[1] + 2 * inverse * t_value * control[1] + t_value**2 * end[1]
        points.append((x_value, y_value))
    return tuple(points)


def _section_intervals(
    total_points: int,
    lengths: tuple[float, float, float],
) -> tuple[int, int, int]:
    """Allocate exact plot intervals while retaining detail at both transitions."""

    total_intervals = total_points - 1
    minimums = (3, 6, 8)
    total_length = sum(lengths)
    intervals = [
        max(minimum, round(total_intervals * length / total_length))
        for minimum, length in zip(minimums, lengths)
    ]
    while sum(intervals) > total_intervals:
        candidates = [
            (intervals[index] - minimums[index], index) for index in range(3)
        ]
        slack, selected = max(candidates)
        if slack <= 0:
            raise ValueError("contour point count is too small for three sections")
        intervals[selected] -= 1
    while sum(intervals) < total_intervals:
        selected = max(
            range(3),
            key=lambda index: total_intervals * lengths[index] / total_length - intervals[index],
        )
        intervals[selected] += 1
    return intervals[0], intervals[1], intervals[2]


def generate_contour(
    chamber: ThrustChamberInput,
    throat_diameter_mm: float,
    expansion_ratio: float,
    resolution: Resolution | str | int = Resolution.MEDIUM,
) -> ContourResult:
    """Generate a cylindrical chamber, convergent and nozzle contour.

    Coordinates run downstream from the injector face.  All returned dimensions
    are SI; millimetre convenience properties are included on ``ContourResult``.
    """

    if throat_diameter_mm <= 0:
        raise ValueError("throat diameter must be positive")
    if expansion_ratio <= 1:
        raise ValueError("expansion ratio must be greater than 1")
    count = _point_count(resolution)
    throat_radius = throat_diameter_mm / 2000.0
    contraction_area_ratio = chamber.resolved_contraction_area_ratio(throat_diameter_mm)
    chamber_radius = throat_radius * sqrt(contraction_area_ratio)
    exit_radius = throat_radius * sqrt(expansion_ratio)

    beta = radians(chamber.contraction_angle_deg)
    upstream_radius = chamber.throat_upstream_radius_ratio * throat_radius
    maximum_chamber_blend_radius = (
        (chamber_radius - throat_radius) / (1.0 - cos(beta)) - upstream_radius
    )
    if maximum_chamber_blend_radius <= 0.0:
        raise ValueError(
            "R1/Rt is too large for the selected contraction ratio and angle"
        )
    chamber_blend_radius = (
        chamber.chamber_radius_ratio * maximum_chamber_blend_radius
    )
    straight_radial_drop = (
        chamber_radius
        - throat_radius
        - (upstream_radius + chamber_blend_radius) * (1.0 - cos(beta))
    )
    # At R2/R2max=1 the straight tangent vanishes and both blend arcs meet.
    straight_axial_length = max(0.0, straight_radial_drop / tan(beta))
    natural_convergent_length = (
        (upstream_radius + chamber_blend_radius) * sin(beta)
        + straight_axial_length
    )
    if chamber.length.mode is LengthMode.DIRECT:
        cylindrical_length = chamber.length.cylindrical_length_mm / 1000.0  # type: ignore[operator]
        total_chamber_length = chamber.length.chamber_length_mm / 1000.0  # type: ignore[operator]
        convergent_length = total_chamber_length - cylindrical_length
    else:
        # LPA follows the requested convention: L* volume uses the cylindrical
        # area and excludes the contraction volume.
        cylindrical_length = (
            chamber.length.characteristic_length_mm
            / 1000.0
            / contraction_area_ratio
        )  # type: ignore[operator]
        convergent_length = natural_convergent_length
        total_chamber_length = cylindrical_length + convergent_length

    throat_blend_radius = chamber.nozzle.throat_radius_ratio * throat_radius
    conical_15_length = (
        (exit_radius - throat_radius) / tan(radians(15.0))
        + throat_blend_radius * tan(radians(7.5))
    )
    if chamber.nozzle.contour_type is NozzleContourType.CONICAL:
        half_angle = radians(chamber.nozzle.conical_half_angle_deg)
        nozzle_length = (
            (exit_radius - throat_radius) / tan(half_angle)
            + throat_blend_radius * tan(half_angle / 2.0)
        )
    else:
        nozzle_length = conical_15_length * chamber.nozzle.bell_length_percent / 100.0

    total_length = total_chamber_length + nozzle_length
    cylinder_intervals, convergent_intervals, nozzle_intervals = _section_intervals(
        count, (cylindrical_length, convergent_length, nozzle_length)
    )
    cylinder_count = cylinder_intervals + 1
    convergent_count = convergent_intervals + 1
    nozzle_count = nozzle_intervals + 1

    cylinder_x = linspace(0.0, cylindrical_length, cylinder_count)
    cylinder_r = (chamber_radius,) * cylinder_count

    convergent_x = linspace(cylindrical_length, total_chamber_length, convergent_count)
    convergent_r: list[float] = []
    axial_scale = convergent_length / natural_convergent_length
    first_arc_end = chamber_blend_radius * sin(beta)
    straight_end = first_arc_end + straight_axial_length
    for x_value in convergent_x:
        natural_x = (x_value - cylindrical_length) / axial_scale
        if natural_x <= first_arc_end and chamber_blend_radius > 0.0:
            angle = min(beta, max(0.0, math_asin_clamped(natural_x / chamber_blend_radius)))
            radius = chamber_radius - chamber_blend_radius * (1.0 - cos(angle))
        elif natural_x <= straight_end:
            radius_at_arc = chamber_radius - chamber_blend_radius * (1.0 - cos(beta))
            radius = radius_at_arc - (natural_x - first_arc_end) * tan(beta)
        else:
            remaining = max(0.0, natural_convergent_length - natural_x)
            angle = min(beta, max(0.0, math_asin_clamped(remaining / upstream_radius)))
            radius = throat_radius + upstream_radius * (1.0 - cos(angle))
        convergent_r.append(radius)

    nozzle_local: tuple[tuple[float, float], ...]
    metadata: dict[str, float | str] = {
        "contour_type": chamber.nozzle.contour_type.value,
        "throat_radius_mm": throat_radius * 1000.0,
        "chamber_radius_mm": chamber_radius * 1000.0,
        "chamber_diameter_mm": chamber_radius * 2000.0,
        "contraction_area_ratio": contraction_area_ratio,
        "exit_radius_mm": exit_radius * 1000.0,
        "cylindrical_length_mm": cylindrical_length * 1000.0,
        "convergent_length_mm": convergent_length * 1000.0,
        "natural_convergent_length_mm": natural_convergent_length * 1000.0,
        "convergent_axial_scale": axial_scale,
        "nozzle_length_mm": nozzle_length * 1000.0,
        "characteristic_volume_convention": "cylindrical_area_excluding_contraction",
        "R2/R2max": chamber.chamber_radius_ratio,
        "R1/Rt": chamber.throat_upstream_radius_ratio,
        "Rn/Rt": chamber.nozzle.throat_radius_ratio,
        "R1_mm": upstream_radius * 1000.0,
        "R2_mm": chamber_blend_radius * 1000.0,
        "R2max_mm": maximum_chamber_blend_radius * 1000.0,
        "Rn_mm": throat_blend_radius * 1000.0,
    }
    if chamber.nozzle.contour_type is NozzleContourType.CONICAL:
        x_values = linspace(0.0, nozzle_length, nozzle_count)
        half_angle = radians(chamber.nozzle.conical_half_angle_deg)
        blend_x = throat_blend_radius * sin(half_angle)
        blend_y = throat_radius + throat_blend_radius * (1.0 - cos(half_angle))
        points: list[tuple[float, float]] = []
        for x_value in x_values:
            if x_value <= blend_x:
                angle = math_asin_clamped(x_value / throat_blend_radius)
                radius = throat_radius + throat_blend_radius * (1.0 - cos(angle))
            else:
                radius = blend_y + (x_value - blend_x) * tan(half_angle)
            points.append((x_value, radius))
        nozzle_local = tuple(points)
        metadata["nozzle_initial_angle_deg"] = chamber.nozzle.conical_half_angle_deg
        metadata["nozzle_exit_angle_deg"] = chamber.nozzle.conical_half_angle_deg
    else:
        length_fraction = chamber.nozzle.bell_length_percent / 100.0
        initial_angle_deg, exit_angle_deg = _rao_angles(expansion_ratio, length_fraction)
        initial_angle = radians(initial_angle_deg)
        exit_angle = radians(exit_angle_deg)
        blend_radius = throat_blend_radius
        blend_x = blend_radius * sin(initial_angle)
        blend_y = throat_radius + blend_radius * (1.0 - cos(initial_angle))
        exit_point = (nozzle_length, exit_radius)
        initial_slope = tan(initial_angle)
        exit_slope = tan(exit_angle)
        control_x = (
            exit_radius
            - blend_y
            + initial_slope * blend_x
            - exit_slope * nozzle_length
        ) / (initial_slope - exit_slope)
        control_x = min(nozzle_length * 0.92, max(blend_x * 1.05, control_x))
        control_y = blend_y + initial_slope * (control_x - blend_x)
        arc_count = max(5, round(nozzle_count * blend_x / nozzle_length))
        bezier_count = nozzle_count - arc_count + 1
        arc_angles = linspace(0.0, initial_angle, arc_count)
        arc = tuple(
            (
                blend_radius * sin(angle),
                throat_radius + blend_radius * (1.0 - cos(angle)),
            )
            for angle in arc_angles
        )
        bell = _quadratic_bezier(
            (blend_x, blend_y), (control_x, control_y), exit_point, bezier_count
        )
        nozzle_local = arc + bell[1:]
        metadata.update(
            {
                "nozzle_initial_angle_deg": initial_angle_deg,
                "nozzle_exit_angle_deg": exit_angle_deg,
                "rao_angle_method": "lpa_empirical_approximation_not_rpa",
                "rao_length_fraction": length_fraction,
                "rao_control_x_mm": control_x * 1000.0,
                "rao_control_radius_mm": control_y * 1000.0,
            }
        )

    # Boundary samples are shared by adjacent sections; remove the duplicates.
    x_values = cylinder_x + convergent_x[1:] + tuple(
        total_chamber_length + point[0] for point in nozzle_local[1:]
    )
    radii = cylinder_r + tuple(convergent_r[1:]) + tuple(
        point[1] for point in nozzle_local[1:]
    )
    areas = tuple(pi * radius * radius for radius in radii)
    throat_index = len(cylinder_x) + len(convergent_x) - 2
    chamber_end_index = len(cylinder_x) - 1
    metadata["actual_section_count"] = float(len(x_values))
    return ContourResult(
        x_m=x_values,
        radius_m=radii,
        area_m2=areas,
        throat_index=throat_index,
        chamber_end_index=chamber_end_index,
        throat_x_m=total_chamber_length,
        exit_x_m=x_values[-1],
        metadata=metadata,
    )
