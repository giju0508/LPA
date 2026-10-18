from __future__ import annotations

import math

import pytest

from lpa.analysis import _geometry, _normalised_segment
from lpa.core import (
    AnalysisInput,
    ChamberLength,
    LengthMode,
    SegmentRange,
    ThrustChamberInput,
    analyze_engine,
)
from lpa.thermal import ThermalSolverSettings
from lpa.ui.input_views import default_segment, validate_segment_layout


def test_engine_propellant_coolant_source_sets_identity_and_mass_fraction() -> None:
    engine = {
        "oxidizer": "LOX",
        "fuel": "Ethanol 100%",
        "mixture_ratio": "3.0",
    }
    oxidizer_segment = default_segment("Regen", 1)
    oxidizer_segment["coolant_source_mode"] = "Engine oxidizer"
    fuel_segment = default_segment("Regen", 2)
    fuel_segment["coolant_source_mode"] = "Engine fuel"

    oxidizer = _normalised_segment(oxidizer_segment, engine)["coolant"]
    fuel = _normalised_segment(fuel_segment, engine)["coolant"]

    assert oxidizer["coolant"] == "LOX"
    assert oxidizer["relative_mass_flow_percent"] == pytest.approx(75.0)
    assert fuel["coolant"] == "Ethanol (100%)"
    assert fuel["relative_mass_flow_percent"] == pytest.approx(25.0)


def test_contraction_boundary_resolves_and_adjacent_regens_do_not_overlap() -> None:
    assert SegmentRange("top", "boundary").resolved(350.0, 240.0) == (0.0, 240.0)
    assert SegmentRange("boundary", "bottom").resolved(350.0, 240.0) == (240.0, 350.0)

    upstream = default_segment("Regen", 1)
    upstream.update(x2="CONV_BOUNDARY", end_mode="Conv Boundary")
    downstream = default_segment("Regen", 2)
    downstream.update(x1="CONV_BOUNDARY", start_mode="Conv Boundary")
    assert validate_segment_layout([upstream, downstream]) == []


def test_regen_overlap_is_a_blocking_layout_issue() -> None:
    first = default_segment("Regen", 1)
    second = default_segment("Regen", 2)
    issues = validate_segment_layout([first, second])
    assert len(issues) == 1
    assert "overlaps Regen" in issues[0]["message"]


def test_residence_time_is_reported_in_milliseconds() -> None:
    result = analyze_engine(AnalysisInput(), prefer_rocketcea=False)
    geometry = _geometry(result)
    assert math.isfinite(geometry["gas_residence_time_ms"])
    assert geometry["gas_residence_time_ms"] > 0.0


def test_geometry_reports_resolved_dimensions_and_direct_mode_lstar() -> None:
    inputs = AnalysisInput(
        thrust_chamber=ThrustChamberInput(
            contraction_area_ratio=4.0,
            length=ChamberLength(
                mode=LengthMode.DIRECT,
                chamber_length_mm=250.0,
                cylindrical_length_mm=150.0,
                characteristic_length_mm=None,
            ),
            contraction_angle_deg=30.0,
        )
    )
    geometry = _geometry(analyze_engine(inputs, prefer_rocketcea=False))

    throat_area = math.pi * (geometry["throat_radius_mm"] / 1000.0) ** 2
    expected_lstar_mm = (
        geometry["cylindrical_volume_m3"] + geometry["convergent_volume_m3"]
    ) / throat_area * 1000.0
    assert geometry["characteristic_length_mm"] == pytest.approx(expected_lstar_mm)
    assert geometry["characteristic_length_mm"] > 600.0
    actual_angle = math.degrees(math.atan(math.tan(math.radians(30.0)) / geometry["convergent_axial_scale"]))
    assert geometry["contraction_angle_deg"] == pytest.approx(actual_angle)
    for key in (
        "chamber_radius_mm",
        "throat_radius_mm",
        "exit_radius_mm",
        "cylindrical_length_mm",
        "chamber_length_mm",
        "nozzle_length_mm",
        "R1_mm",
        "R2_mm",
        "Rn_mm",
        "rao_start_angle_deg",
        "rao_exit_angle_deg",
        "contraction_area_ratio",
        "expansion_ratio",
    ):
        assert math.isfinite(geometry[key])


def test_thermal_iteration_default_is_200() -> None:
    assert ThermalSolverSettings().max_iterations == 200
