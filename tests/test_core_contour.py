from __future__ import annotations

from math import atan2, cos, degrees, pi, radians, sin, tan

import pytest

from lpa.core import (
    ChamberLength,
    LengthMode,
    NozzleContourType,
    NozzleGeometry,
    ThrustChamberInput,
    generate_contour,
)


def test_conical_contour_has_exact_count_and_area_ratios():
    chamber = ThrustChamberInput(
        nozzle=NozzleGeometry(
            contour_type=NozzleContourType.CONICAL,
            conical_half_angle_deg=15.0,
        )
    )
    contour = generate_contour(chamber, throat_diameter_mm=20.0, expansion_ratio=12.0, resolution=300)
    assert contour.section_count == 300
    assert contour.throat_index == contour.radius_m.index(min(contour.radius_m))
    throat_area = pi * 0.01**2
    assert contour.area_m2[contour.throat_index] == pytest.approx(throat_area)
    assert contour.area_m2[0] / throat_area == pytest.approx(4.0)
    assert contour.area_m2[-1] / throat_area == pytest.approx(12.0)
    assert all(right > left for left, right in zip(contour.x_m, contour.x_m[1:]))


def test_lstar_includes_cylinder_and_converging_section_volume():
    chamber = ThrustChamberInput(
        contraction_area_ratio=4.0,
        length=ChamberLength(
            mode=LengthMode.CHARACTERISTIC_LENGTH,
            characteristic_length_mm=1200.0,
        ),
    )
    contour = generate_contour(chamber, 30.0, 8.0, "low")
    throat_area = pi * 0.015**2
    assert contour.metadata["cylindrical_length_mm"] < 300.0
    assert contour.metadata["convergent_volume_m3"] > 0.0
    assert contour.metadata["chamber_volume_m3"] == pytest.approx(
        contour.metadata["cylindrical_volume_m3"]
        + contour.metadata["convergent_volume_m3"]
    )
    assert contour.metadata["chamber_volume_m3"] / throat_area * 1000.0 == pytest.approx(
        1200.0
    )
    assert contour.metadata["characteristic_length_mm"] == pytest.approx(1200.0)
    assert contour.metadata["characteristic_volume_convention"] == (
        "cylinder_plus_converging_section"
    )


def test_lstar_rejects_volume_smaller_than_the_converging_section():
    chamber = ThrustChamberInput(
        contraction_area_ratio=4.0,
        length=ChamberLength(
            mode=LengthMode.CHARACTERISTIC_LENGTH,
            characteristic_length_mm=1.0,
        ),
    )
    with pytest.raises(ValueError, match="must exceed .* converging geometry"):
        generate_contour(chamber, 30.0, 8.0, "low")


def test_direct_chamber_lengths_are_honored():
    chamber = ThrustChamberInput(
        length=ChamberLength(
            mode="direct",
            chamber_length_mm=410.0,
            cylindrical_length_mm=250.0,
        )
    )
    contour = generate_contour(chamber, 20.0, 5.0, 120)
    assert contour.throat_x_m == pytest.approx(0.410)
    assert contour.x_m[contour.chamber_end_index] == pytest.approx(0.250)
    assert contour.metadata["characteristic_length_mm"] > 4.0 * 250.0


@pytest.mark.parametrize("expansion_ratio", [5.0, 10.0, 14.0, 40.0, 50.0])
def test_rao_bell_reaches_exit_and_returns_construction_values(expansion_ratio):
    chamber = ThrustChamberInput(
        nozzle=NozzleGeometry(
            contour_type=NozzleContourType.RAO_BELL,
            bell_length_percent=80.0,
            throat_radius_ratio=0.382,
        )
    )
    contour = generate_contour(chamber, 24.0, expansion_ratio, "medium")
    assert contour.section_count == 300
    assert contour.radius_m[-1] / contour.radius_m[contour.throat_index] == pytest.approx(
        expansion_ratio**0.5
    )
    assert 4 <= contour.metadata["nozzle_exit_angle_deg"] < contour.metadata[
        "nozzle_initial_angle_deg"
    ]
    assert contour.metadata["rao_angle_method"] == (
        "nasa_sp125_chart_interpolation"
    )
    nozzle_radii = contour.radius_m[contour.throat_index :]
    assert all(right >= left for left, right in zip(nozzle_radii, nozzle_radii[1:]))


def _bell_chamber(**kwargs) -> ThrustChamberInput:
    return ThrustChamberInput(nozzle=NozzleGeometry(contour_type="rao_bell", **kwargs))


def _endpoint_angles(contour) -> tuple[float, float]:
    metadata = contour.metadata
    start_x = metadata["rao_start_x_mm"]
    start_r = metadata["rao_start_radius_mm"]
    control_x = metadata["rao_control_x_mm"]
    control_r = metadata["rao_control_radius_mm"]
    exit_x = metadata["nozzle_length_mm"]
    exit_r = metadata["exit_radius_mm"]
    return (
        degrees(atan2(control_r - start_r, control_x - start_x)),
        degrees(atan2(exit_r - control_r, exit_x - control_x)),
    )


def test_rao_reproduces_nasa_sp125_p98_angles_and_throat_blend():
    contour = generate_contour(_bell_chamber(), 20.0, 14.0, 300)
    metadata = contour.metadata
    # Published worked example: epsilon=14, Lf=.8, theta_n=27.4, theta_e=9.8.
    assert metadata["nozzle_initial_angle_deg"] == pytest.approx(27.4)
    assert metadata["nozzle_exit_angle_deg"] == pytest.approx(9.8)
    assert _endpoint_angles(contour) == pytest.approx((27.4, 9.8), abs=1e-10)
    radius = metadata["Rn_mm"]
    expected_start_x = radius * sin(radians(27.4))
    expected_start_r = 10.0 + radius * (1.0 - cos(radians(27.4)))
    assert metadata["rao_start_x_mm"] == pytest.approx(expected_start_x)
    assert metadata["rao_start_radius_mm"] == pytest.approx(expected_start_r)
    # SP-125 Eq. (4-7) defines a rounded-throat 15-degree reference cone.
    reference_length = (
        10.0 * (14.0**0.5 - 1.0)
        + radius * (1.0 / cos(radians(15.0)) - 1.0)
    ) / tan(radians(15.0))
    assert metadata["conical_15_length_mm"] == pytest.approx(reference_length)
    assert metadata["nozzle_length_mm"] == pytest.approx(0.8 * reference_length)
    assert contour.exit_x_m - contour.throat_x_m == pytest.approx(
        metadata["nozzle_length_mm"] / 1000.0
    )


@pytest.mark.parametrize("bell_percent", [60.0, 65.0, 70.0, 80.0, 90.0, 100.0])
@pytest.mark.parametrize("expansion_ratio", [5.0, 7.5, 14.0, 22.3, 50.0])
def test_rao_chart_bells_preserve_endpoint_tangents_and_monotone_curve(
    bell_percent, expansion_ratio
):
    contour = generate_contour(_bell_chamber(bell_length_percent=bell_percent), 20.0, expansion_ratio, 300)
    metadata = contour.metadata
    assert _endpoint_angles(contour) == pytest.approx(
        (metadata["nozzle_initial_angle_deg"], metadata["nozzle_exit_angle_deg"]),
        abs=1e-10,
    )
    # For a quadratic Bezier, derivatives interpolate its control-polygon
    # edges.  Positive edge components guarantee no hidden fold between samples.
    assert 0 < metadata["rao_start_x_mm"] < metadata["rao_control_x_mm"] < metadata["nozzle_length_mm"]
    assert metadata["throat_radius_mm"] < metadata["rao_start_radius_mm"] < metadata["rao_control_radius_mm"] < metadata["exit_radius_mm"]
    assert contour.section_count == 300
    assert contour.area_m2[-1] / contour.area_m2[contour.throat_index] == pytest.approx(expansion_ratio)
    assert all(right > left for left, right in zip(contour.x_m, contour.x_m[1:]))
    nozzle_radii = contour.radius_m[contour.throat_index:]
    assert all(right > left for left, right in zip(nozzle_radii, nozzle_radii[1:]))


@pytest.mark.parametrize("resolution", [30, 120, 300, 700])
def test_rao_preserves_point_count_and_includes_arc_parabola_junction(resolution):
    contour = generate_contour(_bell_chamber(), 20.0, 14.0, resolution)
    metadata = contour.metadata
    start_x = contour.throat_x_m + metadata["rao_start_x_mm"] / 1000.0
    junction = next(index for index, x in enumerate(contour.x_m) if abs(x - start_x) < 1e-12)
    assert contour.radius_mm[junction] == pytest.approx(metadata["rao_start_radius_mm"])
    assert junction - contour.throat_index >= 4
    assert len(contour.x_m) - 1 - junction >= 4
    assert contour.section_count == resolution


def test_rao_manual_angles_preserve_valid_tangent_intersection_near_exit():
    # This valid intersection was formerly clamped to .92*L, changing Te.
    contour = generate_contour(
        _bell_chamber(bell_length_percent=50.0, throat_radius_ratio=1.0,
                      rao_initial_angle_deg=29.7, rao_exit_angle_deg=11.4),
        20.0, 100.0, 300,
    )
    metadata = contour.metadata
    assert metadata["rao_control_x_mm"] / metadata["nozzle_length_mm"] > 0.92
    assert _endpoint_angles(contour) == pytest.approx((29.7, 11.4), abs=1e-10)
    assert metadata["rao_angle_method"] == "user_specified"
    assert contour.area_m2[-1] / contour.area_m2[contour.throat_index] == pytest.approx(100.0)


@pytest.mark.parametrize("expansion_ratio,bell_percent,initial,exit_angle", [
    (1.5, 50.0, 34.2, 15.4),
    (1.1, 90.0, 30.6, 10.2),
    (1.0001, 80.0, 31.5, 11.5),
])
def test_rao_rejects_incompatible_geometry_instead_of_changing_tangents(
    expansion_ratio, bell_percent, initial, exit_angle
):
    with pytest.raises(ValueError, match="Rao (wall angles|throat arc)"):
        generate_contour(
            _bell_chamber(bell_length_percent=bell_percent,
                          rao_initial_angle_deg=initial, rao_exit_angle_deg=exit_angle),
            20.0, expansion_ratio, 300,
        )


@pytest.mark.parametrize("expansion_ratio,bell_percent", [(2.0, 80.0), (100.0, 80.0), (14.0, 50.0), (14.0, 120.0)])
def test_rao_automatically_constructs_bells_outside_published_chart(expansion_ratio, bell_percent):
    contour = generate_contour(_bell_chamber(bell_length_percent=bell_percent), 20.0, expansion_ratio)
    metadata = contour.metadata
    assert metadata["rao_angle_method"] == "rpa_observed_flow_auto"
    assert _endpoint_angles(contour) == pytest.approx(
        (metadata["nozzle_initial_angle_deg"], metadata["nozzle_exit_angle_deg"]), abs=1e-10,
    )
    assert metadata["rao_length_fraction"] == pytest.approx(bell_percent / 100.0)
    assert contour.area_m2[-1] / contour.area_m2[contour.throat_index] == pytest.approx(expansion_ratio)
    assert contour.section_count == 300


def test_rao_explicit_zero_exit_angle_is_exact_and_monotone():
    contour = generate_contour(_bell_chamber(rao_initial_angle_deg=30.0, rao_exit_angle_deg=0.0), 20.0, 14.0)
    assert _endpoint_angles(contour) == pytest.approx((30.0, 0.0), abs=1e-10)
    assert contour.metadata["rao_control_radius_mm"] == contour.metadata["exit_radius_mm"]
    assert all(b > a for a, b in zip(contour.radius_m[contour.throat_index:], contour.radius_m[contour.throat_index + 1:]))


@pytest.mark.parametrize("angle_field,value", [("rao_initial_angle_deg", 30.0), ("rao_exit_angle_deg", 10.0)])
def test_rao_rejects_partial_angle_pair_after_model_mutation(angle_field, value):
    chamber = _bell_chamber()
    setattr(chamber.nozzle, angle_field, value)
    with pytest.raises(ValueError, match="both Rao angles"):
        generate_contour(chamber, 20.0, 14.0)


def test_contour_rejects_impossible_dimensions():
    with pytest.raises(ValueError):
        generate_contour(ThrustChamberInput(), 0.0, 5.0)
    with pytest.raises(ValueError):
        generate_contour(ThrustChamberInput(), 20.0, 1.0)
