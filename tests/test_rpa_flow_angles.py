from __future__ import annotations

import json
from pathlib import Path

import pytest

from lpa.core import AnalysisInput, NozzleExitCondition, NozzleGeometry, ThrustChamberInput, analyze_engine, generate_contour
from lpa.core.rao import rpa_flow_angles, select_rao_angles


REFERENCE = json.loads((Path(__file__).parent / "fixtures" / "rpa_rao_4_0_13.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", REFERENCE["cases"], ids=lambda case: case["id"])
def test_flow_relations_match_actual_rpa_script_outputs(case):
    measured = case["measurements"]
    result = rpa_flow_angles(measured["exit_mach"], measured["throat_isentropic_exponent"],
                             measured["exit_isentropic_exponent"])
    assert result == pytest.approx((measured["initial_angle_deg"], measured["exit_angle_deg"]), abs=5e-12)


def test_rpa_exit_preference_can_exceed_ninety_percent_of_initial():
    measured = next(case["measurements"] for case in REFERENCE["cases"]
                    if case["measurements"]["expansion_ratio"] == 5.0)
    initial, exit_angle = rpa_flow_angles(measured["exit_mach"], measured["throat_isentropic_exponent"],
                                         measured["exit_isentropic_exponent"])
    assert 0.9 * initial < exit_angle < initial


@pytest.mark.parametrize("mach,throat_k,exit_k", [
    (1.0, 1.2, 1.2), (float("nan"), 1.2, 1.2), (float("inf"), 1.2, 1.2),
    (3.0, 1.0, 1.2), (3.0, 1.2, 1.0), (3.0, float("nan"), 1.2),
])
def test_rpa_flow_relations_reject_invalid_supersonic_state(mach, throat_k, exit_k):
    with pytest.raises(ValueError, match="RPA flow-angle"):
        rpa_flow_angles(mach, throat_k, exit_k)


@pytest.mark.parametrize("ratio", [1.0001, 1.5, 2.0, 3.0, 4.0, 50.001, 100.0, 250.0, 1000.0, 10000.0])
def test_automatic_flow_extension_preserves_length_exit_area_and_mesh(ratio):
    chamber = ThrustChamberInput(nozzle=NozzleGeometry(contour_type="rao_bell"))
    contour = generate_contour(chamber, 20.0, ratio, 120)
    metadata = contour.metadata
    assert metadata["rao_angle_method"] == "rpa_observed_flow_auto"
    assert metadata["rao_length_fraction"] == 0.8
    assert metadata["Rn/Rt"] == 0.382
    assert contour.section_count == 120
    assert contour.area_m2[-1] / contour.area_m2[contour.throat_index] == pytest.approx(ratio)
    assert contour.exit_x_m - contour.throat_x_m == pytest.approx(metadata["nozzle_length_mm"] / 1000.0)
    assert all(b > a for a, b in zip(contour.x_m, contour.x_m[1:]))
    assert all(b > a for a, b in zip(contour.radius_m[contour.throat_index:], contour.radius_m[contour.throat_index + 1:]))


def test_adjusted_flow_preferences_are_reported_in_engine_warnings():
    inputs = AnalysisInput(thrust_chamber=ThrustChamberInput(
        nozzle=NozzleGeometry(contour_type="rao_bell"),
        exit_condition=NozzleExitCondition(mode="expansion_ratio", expansion_area_ratio=2.0),
    ))
    result = analyze_engine(inputs, prefer_rocketcea=False)
    metadata = result.contour.metadata
    assert metadata["rao_geometry_adjusted"] == 1.0
    assert metadata["rao_flow_source"] == "ideal_gas_constant_gamma"
    assert any("RPA flow preferences" in warning for warning in result.warnings)


def test_impossible_fixed_blend_and_length_have_a_geometric_error():
    with pytest.raises(ValueError, match="Rao.*(geometry|length|arc)"):
        select_rao_angles(1.1, 0.8)
