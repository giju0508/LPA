"""Axisymmetric thrust-chamber contour generation.

The bell implementation uses NASA SP-125's Rao parabolic approximation:
a circular throat blend and a quadratic parabola with the specified endpoint
tangents.  Automatic wall angles come from the published chart within its
domain and verified RPA flow relations outside it; explicit angle pairs are
also supported.  The reference
15-degree cone includes the same rounded throat as the bell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import asin, atan, cos, degrees, isfinite, pi, radians, sin, sqrt, tan

from ._numerics import linspace
from .models import LengthMode, NozzleContourType, Resolution, ThrustChamberInput
from .rao import rao_angles, select_rao_angles


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
    """Return automatic wall angles in degrees, including outside the chart."""

    return rao_angles(expansion_ratio, length_fraction)


def _quadratic_bezier(
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
    count: int,
) -> tuple[tuple[float, float], ...]:
    if count < 2:
        raise ValueError("a quadratic parabola requires at least two points")
    points: list[tuple[float, float]] = []
    for t_value in linspace(0.0, 1.0, count):
        inverse = 1.0 - t_value
        x_value = inverse * inverse * start[0] + 2 * inverse * t_value * control[0] + t_value**2 * end[0]
        y_value = inverse * inverse * start[1] + 2 * inverse * t_value * control[1] + t_value**2 * end[1]
        points.append((x_value, y_value))
    points[0], points[-1] = start, end
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


def _convergent_volume_m3(
    *,
    chamber_radius: float,
    throat_radius: float,
    chamber_blend_radius: float,
    throat_blend_radius: float,
    straight_axial_length: float,
    contraction_angle: float,
) -> float:
    """Return the exact volume of the arc-line-arc converging section."""

    sine = sin(contraction_angle)
    cosine = cos(contraction_angle)
    cosine_squared_integral = (
        contraction_angle / 2.0
        + sin(2.0 * contraction_angle) / 4.0
    )
    cosine_cubed_integral = sine - sine**3 / 3.0

    def arc_volume(
        *, radius_offset: float, arc_radius: float, cosine_sign: float
    ) -> float:
        # r(theta) = radius_offset +/- arc_radius*cos(theta),
        # dx = arc_radius*cos(theta)dtheta for theta in [0, beta].
        return pi * arc_radius * (
            radius_offset**2 * sine
            + 2.0
            * cosine_sign
            * radius_offset
            * arc_radius
            * cosine_squared_integral
            + arc_radius**2 * cosine_cubed_integral
        )

    chamber_arc_volume = arc_volume(
        radius_offset=chamber_radius - chamber_blend_radius,
        arc_radius=chamber_blend_radius,
        cosine_sign=1.0,
    )
    throat_arc_volume = arc_volume(
        radius_offset=throat_radius + throat_blend_radius,
        arc_radius=throat_blend_radius,
        cosine_sign=-1.0,
    )
    straight_start_radius = chamber_radius - chamber_blend_radius * (1.0 - cosine)
    straight_end_radius = throat_radius + throat_blend_radius * (1.0 - cosine)
    straight_volume = (
        pi
        * straight_axial_length
        / 3.0
        * (
            straight_start_radius**2
            + straight_start_radius * straight_end_radius
            + straight_end_radius**2
        )
    )
    return chamber_arc_volume + straight_volume + throat_arc_volume


def generate_contour(
    chamber: ThrustChamberInput,
    throat_diameter_mm: float,
    expansion_ratio: float,
    resolution: Resolution | str | int = Resolution.MEDIUM,
    *,
    exit_mach: float | None = None,
    throat_isentropic_exponent: float | None = None,
    exit_isentropic_exponent: float | None = None,
    nozzle_flow_source: str | None = None,
) -> ContourResult:
    """Generate a cylindrical chamber, convergent and nozzle contour.

    Coordinates run downstream from the injector face.  All returned dimensions
    are SI; millimetre convenience properties are included on ``ContourResult``.
    """

    if not isfinite(throat_diameter_mm) or throat_diameter_mm <= 0:
        raise ValueError("throat diameter must be finite and positive")
    if not isfinite(expansion_ratio) or expansion_ratio <= 1:
        raise ValueError("expansion ratio must be finite and greater than 1")
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
    natural_convergent_volume = _convergent_volume_m3(
        chamber_radius=chamber_radius,
        throat_radius=throat_radius,
        chamber_blend_radius=chamber_blend_radius,
        throat_blend_radius=upstream_radius,
        straight_axial_length=straight_axial_length,
        contraction_angle=beta,
    )
    throat_area = pi * throat_radius**2
    chamber_area = pi * chamber_radius**2
    if chamber.length.mode is LengthMode.DIRECT:
        cylindrical_length = chamber.length.cylindrical_length_mm / 1000.0  # type: ignore[operator]
        total_chamber_length = chamber.length.chamber_length_mm / 1000.0  # type: ignore[operator]
        convergent_length = total_chamber_length - cylindrical_length
    else:
        # L* = (Vcyl + Vconv) / At.  The converging-section volume follows the
        # actual arc-line-arc contour, so only the remaining target volume is
        # assigned to the cylindrical chamber.
        target_chamber_volume = (
            chamber.length.characteristic_length_mm / 1000.0 * throat_area
        )  # type: ignore[operator]
        cylindrical_volume = target_chamber_volume - natural_convergent_volume
        if cylindrical_volume <= 0.0:
            minimum_lstar_mm = natural_convergent_volume / throat_area * 1000.0
            raise ValueError(
                "characteristic length L* must exceed "
                f"{minimum_lstar_mm:.3f} mm for the selected converging geometry"
            )
        cylindrical_length = cylindrical_volume / chamber_area
        convergent_length = natural_convergent_length
        total_chamber_length = cylindrical_length + convergent_length

    axial_scale = convergent_length / natural_convergent_length
    cylindrical_volume = chamber_area * cylindrical_length
    convergent_volume = natural_convergent_volume * axial_scale
    chamber_volume = cylindrical_volume + convergent_volume
    resolved_characteristic_length_mm = chamber_volume / throat_area * 1000.0

    throat_blend_radius = chamber.nozzle.throat_radius_ratio * throat_radius
    conical_15_length = (
        (exit_radius - throat_radius) / tan(radians(15.0))
        + throat_blend_radius * tan(radians(7.5))
    )
    if chamber.nozzle.contour_type is NozzleContourType.CONICAL:
        half_angle = radians(chamber.nozzle.conical_half_angle_deg)
        if exit_radius <= throat_radius + throat_blend_radius * (1.0 - cos(half_angle)):
            raise ValueError("conical nozzle exit is inside the throat blend; increase Ae/At, reduce Rn/Rt, or reduce the half angle")
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
        "actual_contraction_angle_deg": degrees(atan(tan(beta) / axial_scale)),
        "convergent_arc_form": "circular" if abs(axial_scale - 1.0) < 1e-12 else "elliptical",
        "nozzle_length_mm": nozzle_length * 1000.0,
        "conical_15_length_mm": conical_15_length * 1000.0,
        "cylindrical_volume_m3": cylindrical_volume,
        "convergent_volume_m3": convergent_volume,
        "chamber_volume_m3": chamber_volume,
        "characteristic_length_mm": resolved_characteristic_length_mm,
        "characteristic_volume_convention": "cylinder_plus_converging_section",
        "R2/R2max": chamber.chamber_radius_ratio,
        "R1/Rt": chamber.throat_upstream_radius_ratio,
        "Rn/Rt": chamber.nozzle.throat_radius_ratio,
        "R1_mm": upstream_radius * axial_scale**2 * 1000.0,
        "R2_mm": chamber_blend_radius * axial_scale**2 * 1000.0,
        "requested_R1_mm": upstream_radius * 1000.0,
        "requested_R2_mm": chamber_blend_radius * 1000.0,
        "throat_upstream_curvature_radius_mm": upstream_radius * axial_scale**2 * 1000.0,
        "chamber_blend_curvature_radius_mm": chamber_blend_radius * axial_scale**2 * 1000.0,
        "R2max_mm": maximum_chamber_blend_radius * 1000.0,
        "Rn_mm": throat_blend_radius * 1000.0,
    }
    if abs(axial_scale - 1.0) > 1e-12:
        metadata["convergent_geometry_warning"] = (
            "Direct chamber lengths scale the convergent axially: its arcs are elliptical, "
            f"actual straight angle is {metadata['actual_contraction_angle_deg']:.6g} deg, "
            f"and endpoint curvature radii R1/R2 are {metadata['R1_mm']:.6g}/{metadata['R2_mm']:.6g} mm. "
            "R1/R2 are endpoint curvatures, not constant radii of circular arcs."
        )
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
        angle_selection = None
        if (chamber.nozzle.rao_initial_angle_deg is None) != (chamber.nozzle.rao_exit_angle_deg is None):
            raise ValueError("specify both Rao angles Tn and Te, or leave both automatic")
        if chamber.nozzle.rao_initial_angle_deg is None:
            angle_selection = select_rao_angles(
                expansion_ratio, length_fraction,
                throat_radius_ratio=chamber.nozzle.throat_radius_ratio,
                exit_mach=exit_mach,
                throat_isentropic_exponent=throat_isentropic_exponent,
                exit_isentropic_exponent=exit_isentropic_exponent,
                flow_source=nozzle_flow_source,
            )
            initial_angle_deg = angle_selection.initial_angle_deg
            exit_angle_deg = angle_selection.exit_angle_deg
            angle_method = angle_selection.method
            angle_source = angle_selection.source
        else:
            initial_angle_deg = chamber.nozzle.rao_initial_angle_deg
            exit_angle_deg = chamber.nozzle.rao_exit_angle_deg
            angle_method = "user_specified"
            angle_source = "Explicit Tn and Te inputs"
        if (
            exit_angle_deg is None
            or not isfinite(initial_angle_deg)
            or not isfinite(exit_angle_deg)
            or not 0.0 <= exit_angle_deg < initial_angle_deg < 90.0
        ):
            raise ValueError("Rao wall angles must satisfy 0 <= Te < Tn < 90 degrees")
        initial_angle = radians(initial_angle_deg)
        exit_angle = radians(exit_angle_deg)
        blend_radius = throat_blend_radius
        blend_x = blend_radius * sin(initial_angle)
        blend_y = throat_radius + blend_radius * (1.0 - cos(initial_angle))
        exit_point = (nozzle_length, exit_radius)
        initial_slope = tan(initial_angle)
        exit_slope = tan(exit_angle)
        geometry_description = (
            f"Ae/At={expansion_ratio:g}, Le/Lc15={length_fraction * 100:g}%, "
            f"Rn/Rt={chamber.nozzle.throat_radius_ratio:g}, "
            f"Tn={initial_angle_deg:g} deg, Te={exit_angle_deg:g} deg"
        )
        if blend_x >= nozzle_length or blend_y >= exit_radius:
            raise ValueError(
                "Rao throat arc must end upstream of and below the nozzle exit "
                f"({geometry_description}); adjust Rn/Rt, length or wall angles"
            )
        chord_slope = (exit_radius - blend_y) / (nozzle_length - blend_x)
        if not exit_slope < chord_slope < initial_slope:
            raise ValueError(
                "Rao wall angles cannot form a downstream bell parabola: "
                "the N-to-exit slope must lie strictly between tan(Te) and tan(Tn) "
                f"({geometry_description}); adjust Rn/Rt, length or wall angles"
            )
        # Keep the exact intersection of the two endpoint tangents.  Moving Q
        # would change the actual exit angle while still reporting the old Te.
        control_x = blend_x + (
            exit_radius - blend_y - exit_slope * (nozzle_length - blend_x)
        ) / (initial_slope - exit_slope)
        control_y = exit_radius - exit_slope * (nozzle_length - control_x)
        if not blend_x < control_x < nozzle_length or not blend_y < control_y <= exit_radius:
            raise ValueError(f"Rao tangent intersection is outside the bell ({geometry_description})")
        # Adjacent sections share N.  Fix the total interval count and reserve
        # four intervals for each curve, even for a very short throat blend.
        arc_intervals = min(
            nozzle_intervals - 4,
            max(4, round(nozzle_intervals * blend_x / nozzle_length)),
        )
        arc_count = arc_intervals + 1
        bezier_count = nozzle_intervals - arc_intervals + 1
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
                "rao_angle_method": angle_method,
                "rao_angle_source": angle_source,
                "rao_length_fraction": length_fraction,
                "rao_expansion_ratio": expansion_ratio,
                "rao_start_x_mm": blend_x * 1000.0,
                "rao_start_radius_mm": blend_y * 1000.0,
                "rao_control_x_mm": control_x * 1000.0,
                "rao_control_radius_mm": control_y * 1000.0,
            }
        )
        if angle_selection is not None:
            metadata.update({
                "rao_initial_preference_deg": angle_selection.initial_preference_deg,
                "rao_exit_preference_deg": angle_selection.exit_preference_deg,
                "rao_geometry_adjusted": float(angle_selection.geometry_adjusted),
                "rao_flow_source": angle_selection.flow_source,
            })
            if angle_selection.exit_mach is not None:
                metadata.update({
                    "rao_flow_exit_mach": angle_selection.exit_mach,
                    "rao_flow_throat_isentropic_exponent": angle_selection.throat_isentropic_exponent,
                    "rao_flow_exit_isentropic_exponent": angle_selection.exit_isentropic_exponent,
                })
            if angle_selection.geometry_adjusted:
                metadata["rao_angle_warning"] = (
                    "Automatic Rao angles were adjusted to satisfy the selected nozzle "
                    "length and throat blend: RPA flow preferences "
                    f"Tn={angle_selection.initial_preference_deg:.6g} deg, "
                    f"Te={angle_selection.exit_preference_deg:.6g} deg; applied "
                    f"Tn={initial_angle_deg:.6g} deg, Te={exit_angle_deg:.6g} deg. "
                    "The requested Le/Lc15 and Rn/Rt are preserved."
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
