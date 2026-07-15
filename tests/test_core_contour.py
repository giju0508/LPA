from __future__ import annotations

from math import pi

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


def test_lstar_uses_cylindrical_area_excluding_contraction():
    chamber = ThrustChamberInput(
        contraction_area_ratio=4.0,
        length=ChamberLength(
            mode=LengthMode.CHARACTERISTIC_LENGTH,
            characteristic_length_mm=1200.0,
        ),
    )
    contour = generate_contour(chamber, 30.0, 8.0, "low")
    assert contour.metadata["cylindrical_length_mm"] == pytest.approx(300.0)
    assert contour.metadata["characteristic_volume_convention"] == (
        "cylindrical_area_excluding_contraction"
    )


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


@pytest.mark.parametrize("expansion_ratio", [2.0, 10.0, 40.0, 100.0])
def test_rao_like_bell_reaches_exit_and_returns_construction_values(expansion_ratio):
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
        "lpa_empirical_approximation_not_rpa"
    )
    nozzle_radii = contour.radius_m[contour.throat_index :]
    assert all(right >= left for left, right in zip(nozzle_radii, nozzle_radii[1:]))


def test_contour_rejects_impossible_dimensions():
    with pytest.raises(ValueError):
        generate_contour(ThrustChamberInput(), 0.0, 5.0)
    with pytest.raises(ValueError):
        generate_contour(ThrustChamberInput(), 20.0, 1.0)
