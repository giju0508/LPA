from __future__ import annotations

import tkinter as tk

import pytest

from lpa.analysis import _core_project
from lpa.core import (
    NozzleGeometry,
    analysis_input_from_dict,
    analysis_input_to_dict,
)
from lpa.project import load_project, make_project, save_project, validate_project
from lpa.ui.input_views import ThrustChamberPage
from lpa.ui.theme import apply_theme


def _project(**chamber_updates):
    chamber = {
        "contraction_mode": "Area ratio (Ac/At)",
        "contraction_area_ratio": "4",
        "exit_condition_mode": "Expansion area ratio",
        "exit_condition_value": "14",
        "flow_model": "Shifting equilibrium",
        "reaction_efficiency_pct": "98",
        "nozzle_efficiency_mode": "Estimate",
        "sizing_mode": "Chamber throat diameter",
        "throat_diameter_mm": "20",
        "chamber_length_mode": "Characteristic length L*",
        "characteristic_length_mm": "1200",
        "contraction_angle_deg": "30",
        "r2_ratio": "0.5",
        "r1_rt": "1.5",
        "rn_rt": "0.382",
        "nozzle_type": "Parabolic contour (Rao)",
        "nozzle_half_angle_deg": "15",
        "rao_length_pct": "80",
    }
    chamber.update(chamber_updates)
    return make_project(
        {
            "engine_name": "Rao input verification",
            "chamber_pressure_bar": "20",
            "mixture_ratio": "1.3",
            "oxidizer": "LOX",
            "fuel": "RP-1",
        },
        chamber,
        {"thermal_enabled": False, "segments": []},
    )


@pytest.mark.parametrize("optional", [{}, {"rao_start_angle_deg": "", "rao_exit_angle_deg": " "}])
def test_legacy_and_blank_angles_remain_automatic(optional):
    project = _project(**optional)
    assert validate_project(project) == []
    nozzle = analysis_input_from_dict(_core_project(project)).thrust_chamber.nozzle
    assert nozzle.rao_initial_angle_deg is None
    assert nozzle.rao_exit_angle_deg is None


def test_manual_angles_survive_project_and_core_round_trip(tmp_path):
    project = _project(
        exit_condition_value="100",
        rao_length_pct="50",
        rao_start_angle_deg="45",
        rao_exit_angle_deg="10",
    )
    assert validate_project(project) == []
    path = save_project(tmp_path / "manual-rao.cfg", project)
    loaded = load_project(path)
    assert loaded == project
    inputs = analysis_input_from_dict(_core_project(loaded))
    restored = analysis_input_from_dict(analysis_input_to_dict(inputs))
    nozzle = restored.thrust_chamber.nozzle
    assert nozzle.bell_length_percent == 50
    assert nozzle.rao_initial_angle_deg == 45
    assert nozzle.rao_exit_angle_deg == 10


@pytest.mark.parametrize(
    "initial,exit",
    [
        (30, None),
        (None, 10),
        (30, 30),
        (90, 10),
        (30, -1),
        (float("nan"), 10),
        (30, float("inf")),
    ],
)
def test_core_model_rejects_partial_or_invalid_manual_pair(initial, exit):
    with pytest.raises(ValueError, match="Rao angles"):
        NozzleGeometry(
            contour_type="rao_bell",
            rao_initial_angle_deg=initial,
            rao_exit_angle_deg=exit,
        )


@pytest.mark.parametrize(
    "initial,exit",
    [("30", ""), ("", "10"), ("abc", "10"), ("nan", "10"), ("30", "inf"), ("10", "30")],
)
def test_project_reports_invalid_manual_pair(initial, exit):
    issues = validate_project(_project(rao_start_angle_deg=initial, rao_exit_angle_deg=exit))
    assert issues
    assert all(issue.page == "thrust_chamber" for issue in issues)
    assert any("Rao angle" in issue.message for issue in issues)


@pytest.mark.parametrize(
    "updates",
    [
        {"exit_condition_value": "4"},
        {"exit_condition_value": "100"},
        {"exit_condition_value": "2", "rao_length_pct": "50"},
        {"exit_condition_value": "250", "rao_length_pct": "120"},
        {"exit_condition_value": "1000"},
        {"rao_length_pct": "50"},
        {"rao_length_pct": "120"},
        {"exit_condition_mode": "Ambient pressure", "exit_condition_value": "1", "rao_length_pct": "55"},
    ],
)
def test_automatic_angles_outside_chart_survive_input_round_trip(updates, tmp_path):
    project = _project(rao_start_angle_deg="", rao_exit_angle_deg="", **updates)
    assert validate_project(project) == []
    loaded = load_project(save_project(tmp_path / "automatic-rao.cfg", project))
    assert loaded == project
    inputs = analysis_input_from_dict(_core_project(loaded))
    restored = analysis_input_from_dict(analysis_input_to_dict(inputs))
    nozzle = restored.thrust_chamber.nozzle
    assert nozzle.rao_initial_angle_deg is None
    assert nozzle.rao_exit_angle_deg is None
    assert nozzle.bell_length_percent == float(project["thrust_chamber"]["rao_length_pct"])
    if project["thrust_chamber"]["exit_condition_mode"] == "Expansion area ratio":
        assert restored.thrust_chamber.exit_condition.expansion_area_ratio == float(
            project["thrust_chamber"]["exit_condition_value"]
        )


@pytest.mark.parametrize("value", ["-1", "0", "1", "nan", "inf", "-inf"])
@pytest.mark.parametrize("manual", [False, True])
def test_rao_invalid_expansion_is_still_rejected(value, manual):
    angles = {"rao_start_angle_deg": "30", "rao_exit_angle_deg": "10"} if manual else {}
    issues = validate_project(_project(exit_condition_value=value, **angles))
    assert any(issue.field == "exit_condition_value" for issue in issues)


@pytest.mark.parametrize("value", ["0", "49.9", "120.1", "nan", "inf", "-inf"])
def test_rao_invalid_length_is_still_rejected(value):
    issues = validate_project(_project(rao_length_pct=value))
    assert any(issue.field == "rao_length_pct" for issue in issues)


def test_manual_exit_angle_can_be_zero_and_conical_ignores_disabled_pair():
    manual = _project(rao_start_angle_deg="30", rao_exit_angle_deg="0")
    assert validate_project(manual) == []
    assert analysis_input_from_dict(_core_project(manual)).thrust_chamber.nozzle.rao_exit_angle_deg == 0
    conical = _project(nozzle_type="Conical nozzle", rao_start_angle_deg="30")
    assert validate_project(conical) == []
    assert analysis_input_from_dict(_core_project(conical)).thrust_chamber.nozzle.rao_initial_angle_deg is None


def test_angle_controls_preserve_values_and_reset_when_loading_legacy_project():
    window = tk.Tk()
    window.withdraw()
    apply_theme(window)
    try:
        page = ThrustChamberPage(window)
        page.load_values(_project(rao_start_angle_deg="32", rao_exit_angle_deg="9")["thrust_chamber"])
        assert page.values()["rao_start_angle_deg"] == "32"
        assert page.values()["rao_exit_angle_deg"] == "9"
        assert not page.rao_start_angle.instate(["disabled"])
        page.variables["nozzle_type"].set("Conical nozzle")
        assert page.rao_start_angle.instate(["disabled"])
        assert page.rao_exit_angle.instate(["disabled"])
        assert page.values()["rao_start_angle_deg"] == "32"
        page.load_values(_project()["thrust_chamber"])
        assert page.values()["rao_start_angle_deg"] == ""
        assert page.values()["rao_exit_angle_deg"] == ""
        page.load_values({"rao_start_angle_deg": None, "rao_exit_angle_deg": None})
        assert page.values()["rao_start_angle_deg"] == ""
        assert page.values()["rao_exit_angle_deg"] == ""
    finally:
        window.destroy()
