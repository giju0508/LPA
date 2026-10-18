"""Mixture settings persistence and auditable station diagnostics."""

import csv
import json
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import pytest

from lpa.analysis import _jsonable, _thermal_solver_settings
from lpa.project import load_project, make_project, project_with_defaults, save_project, validate_project
from lpa.ui.input_views import ThermalAnalysisPage, default_segment
from lpa.ui.result_views import ResultPage, ThermalResultsPage, _coolant_wet_wall_flags
from lpa.ui.theme import apply_theme
from tests.test_two_phase_ui import phase_fixture


@pytest.mark.parametrize("selection,pure,mixture", [
    ("Auto (Beta)", "auto", "shah_gungor_winterton"),
    ("Pure fluids only", "auto", "disabled"),
    ("Disabled", "disabled", "disabled"),
])
def test_ui_selection_reaches_distinct_solver_settings(selection, pure, mixture):
    settings = _thermal_solver_settings({"two_phase_model": selection,
        "mixture_mass_transfer_coefficient_m_s": "0.0004"})
    assert settings["two_phase_model"] == pure
    assert settings["mixture_boiling_model"] == mixture
    assert settings["mixture_mass_transfer_coefficient_m_s"] == .0004
    # Solver constructor validates the actual field names/types accepted here.
    from lpa.thermal.solver import ThermalSolverSettings
    instance = ThermalSolverSettings(**settings)
    assert instance.mixture_boiling_model == mixture


def test_missing_legacy_setting_uses_new_default_without_a_stale_mode_or_beta():
    first = _thermal_solver_settings({"two_phase_model": "Pure fluids only",
        "mixture_mass_transfer_coefficient_m_s": .0007})
    second = _thermal_solver_settings({})
    assert first["mixture_boiling_model"] == "disabled"
    assert second["mixture_boiling_model"] == "shah_gungor_winterton"
    assert second["mixture_mass_transfer_coefficient_m_s"] == .0003
    assert _thermal_solver_settings({"mixture_boiling_model":"disabled"})["mixture_boiling_model"] == "disabled"


@pytest.mark.parametrize("value", [0, -1, "nan", "inf", "invalid"])
def test_invalid_empirical_parameter_is_not_silently_replaced(value):
    with pytest.raises(ValueError):
        _thermal_solver_settings({"mixture_mass_transfer_coefficient_m_s":value})


def test_project_validation_accepts_the_new_mode_and_rejects_bad_model_beta():
    project = make_project({}, {}, {"thermal_enabled":True,
        "thermal_max_iterations":"200", "two_phase_model":"Pure fluids only",
        "mixture_boiling_model":"disabled", "mixture_mass_transfer_coefficient_m_s":"0.0003",
        "segments":[default_segment("Regen", 1)]})
    related = {"two_phase_model", "mixture_boiling_model", "mixture_mass_transfer_coefficient_m_s"}
    assert not any(issue.field in related for issue in validate_project(project))
    project["thermal"].update(mixture_boiling_model="invented", mixture_mass_transfer_coefficient_m_s="nan")
    bad = {issue.field for issue in validate_project(project)}
    assert {"mixture_boiling_model", "mixture_mass_transfer_coefficient_m_s"} <= bad


def test_thermal_input_round_trip_and_legacy_defaults_fit_minimum_window(tmp_path):
    window = tk.Tk()
    window.geometry("1080x700")
    apply_theme(window)
    try:
        page = ThermalAnalysisPage(window)
        page.pack(fill="both", expand=True)
        page.variables["thermal_enabled"].set(True)
        page._refresh_enabled()
        window.update()
        defaults = make_project({}, {}, page.values())
        for selection in ("Auto (Beta)", "Pure fluids only", "Disabled"):
            page.variables["two_phase_model"].set(selection)
            page.variables["mixture_mass_transfer_coefficient_m_s"].set("0.00045")
            target = tmp_path/(selection.replace(" ", "_")+".cfg")
            save_project(target, make_project({}, {}, page.values()))
            restored = load_project(target)
            page.load_values(restored["thermal"])
            assert page.values()["two_phase_model"] == selection
            assert page.values()["mixture_mass_transfer_coefficient_m_s"] == "0.00045"
            assert _thermal_solver_settings(page.values())["mixture_boiling_model"] == (
                "shah_gungor_winterton" if selection == "Auto (Beta)" else "disabled")
        legacy = make_project({}, {}, {"thermal_enabled":True, "segments":[]})
        page.load_values(project_with_defaults(legacy, defaults)["thermal"])
        assert page.values()["two_phase_model"] == "Auto (Beta)"
        assert page.values()["mixture_mass_transfer_coefficient_m_s"] == "0.0003"
        page.load_values({"thermal_enabled":True, "two_phase_model":"Auto (Beta)",
                          "mixture_boiling_model":"disabled", "segments":[]})
        assert page.values()["two_phase_model"] == "Pure fluids only"
        window.update()
        hint = page.boiling_hint
        assert hint.winfo_reqheight() < 85
        assert hint.winfo_rootx()+hint.winfo_width() <= page.canvas.winfo_rootx()+page.canvas.winfo_width()
        assert "not predicted" in hint.cget("text")
    finally:
        window.destroy()


def mixture_fixture():
    data = phase_fixture()
    thermal = data["thermal"]
    thermal.update(
        coolant_temperature_glide_k=[None, 15., 20., 30., None, 40., None],
        coolant_boiling_mass_transfer_factor=[None, .8, .7, .6, None, .5, None],
        coolant_boiling_convective_factor=[None, .9, .8, .7, None, .6, None],
        coolant_wet_wall_assumed=[None, True, True, True, False, True, None],
        coolant_outlet_phase={"a":"gas", "b":"two_phase"},
        coolant_inlet_temperature_k={"a":150., "b":300.},
        coolant_outlet_temperature_k={"a":330., "b":400.},
    )
    thermal["metadata"]["mixture_boiling_model"]={
        "method":"shah_gungor_winterton", "mass_transfer_coefficient_m_s":.0003,
        "wet_wall_assumption":True, "critical_heat_flux_predicted":False,
        "dryout_predicted":False, "post_dryout_model":False,
    }
    thermal["metadata"]["regen_segment_completion"]["a"]["outlet_property_applicability"]="correlated"
    thermal["metadata"]["regen_segment_completion"]["b"]["outlet_property_applicability"]="unsupported"
    return data


def test_csv_keeps_mixture_factors_assumptions_and_property_applicability(tmp_path):
    page = SimpleNamespace(data=mixture_fixture(), report_warnings=["wet-wall engineering estimate"])
    target = tmp_path/"mixture.csv"
    ThermalResultsPage.export_all_stations(page, target)
    with target.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[1]["coolant_temperature_glide_k"] == "15.0"
    assert rows[1]["coolant_boiling_mass_transfer_factor"] == "0.8"
    assert rows[1]["coolant_boiling_convective_factor"] == "0.9"
    assert rows[1]["coolant_wet_wall_assumed"] == "True"
    assert rows[4]["coolant_wet_wall_assumed"] == "False"
    assert rows[0]["coolant_wet_wall_assumed"] == ""
    assert rows[5]["twg_k"] == "" and rows[5]["coolant_temperature_glide_k"] == "40.0"
    assert rows[5]["station_applicability"] == "unsupported"
    assert rows[1]["segment_outlet_phase"] == "gas"
    assert rows[1]["segment_outlet_property_applicability"] == "correlated"
    assert rows[3]["segment_outlet_property_applicability"] == "unsupported"
    sources = json.loads(rows[1]["model_and_property_sources"])
    assert sources["mixture_boiling_model"]["mass_transfer_coefficient_m_s"] == .0003
    assert sources["mixture_boiling_model"]["dryout_predicted"] is False
    diagnostic = ResultPage._diagnostic_text(page)
    assert "Wet-wall assumption: 4 stations" in diagnostic
    assert "not channel validation" in diagnostic
    assert "Local liquid-composition glide (K): 15 to 40" in diagnostic
    assert "empirical beta: 0.000300 m/s" in diagnostic


def test_bool_and_none_survive_json_snapshot_without_becoming_zero():
    data = _jsonable(mixture_fixture())
    recovered = json.loads(json.dumps(data, allow_nan=False))
    assert _coolant_wet_wall_flags(recovered["thermal"]) == (None, True, True, True, False, True, None)
    assert _coolant_wet_wall_flags({"coolant_wet_wall_assumed":[None, 0, "True", True, False]}) == (None, None, None, True, False)
    assert _coolant_wet_wall_flags({}) == ()


def test_station_diagnostics_and_outlet_notes_remain_accessible_at_1080x700():
    window = tk.Tk()
    window.geometry("1080x700")
    apply_theme(window)
    try:
        page = ThermalResultsPage(window)
        page.pack(fill="both", expand=True)
        page.set_result(mixture_fixture())
        window.update()
        tree = page.axial_tree
        row = dict(zip(tree.cget("columns"), tree.item(tree.get_children()[1], "values")))
        assert row["glide"] == "15.000"
        assert row["F_TS"] == "0.8000"
        assert row["F_BG"] == "0.9000"
        assert row["wet_wall"] == "True"
        assert row["applicability"] == "screening"
        assert tree.xview()[1] < 1
        tree.xview_moveto(1)
        assert tree.xview()[1] == 1
        texts=[]
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Label):
                    texts.append(str(child.cget("text")))
                walk(child)
        walk(page)
        assert any("Numerical completion does not validate" in text for text in texts)
        assert any("Outside supported model domain" in text for text in texts)
        assert any("phase gas; property applicability correlated" in text for text in texts)
        assert any("phase two_phase; property applicability unsupported" in text for text in texts)
    finally:
        window.destroy()
