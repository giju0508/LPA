"""User-path regression coverage for release review fixes."""

from __future__ import annotations

import copy
import csv
import json
import tkinter as tk
from concurrent.futures import Future
from tkinter import ttk

import pytest

import lpa.app as app_module
import lpa.project as project_module
import lpa.ui.input_views as input_module
from lpa.app import LPAApplication
from lpa.core import EquilibriumMode, MixtureRatioOptimum
from lpa.project import load_project, save_project, validate_project
from lpa.ui.input_views import SegmentDialog, default_segment


@pytest.fixture(scope="module")
def application():
    app = LPAApplication()
    app.geometry("1080x700+0+0")
    app.deiconify()
    app.update()
    yield app
    app._shutdown_immediately()


@pytest.fixture
def app(application):
    application._future = None
    application._project_path = None
    application.load_project_data(copy.deepcopy(application._default_project))
    application.update()
    yield application
    application._future = None
    application.clear_results()
    application._set_dirty(False)


def cooling_project(app):
    project = app.collect_project()
    project["thermal"].update(thermal_enabled=True, segments=[default_segment("Regen", 1)])
    return project


@pytest.mark.parametrize("action", ["add", "edit", "duplicate", "remove"])
def test_segment_changes_trigger_unsaved_project_handling(app, monkeypatch, action):
    app.load_project_data(cooling_project(app))
    page = app.pages["thermal_input"]
    page.tree.selection_set("0")
    before = copy.deepcopy(page.segments)
    result = default_segment("Radiation", 2) if action == "add" else {**before[0], "name": "Edited"}
    monkeypatch.setattr(input_module, "SegmentDialog", lambda *args: type("Dialog", (), {"result": result})())
    monkeypatch.setattr(page, "wait_window", lambda dialog: None)
    monkeypatch.setattr(input_module.messagebox, "askyesno", lambda *args, **kwargs: True)
    if action == "add":
        page._add_segment("Radiation")
    else:
        getattr(page, f"_{action}_selected")()
    assert page.segments != before
    assert app._dirty is True
    calls = []
    monkeypatch.setattr(app_module.messagebox, "askyesnocancel", lambda *args, **kwargs: calls.append(args) or None)
    assert app._confirm_discard() is False
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["new", "edit", "clear"])
def test_old_analysis_completion_cannot_populate_new_input_state(app, change):
    future = Future()
    app._future = future
    app._analysis_revision = app._project_revision
    if change == "new":
        app.new_project()
    elif change == "edit":
        app.pages["engine"].variables["chamber_pressure_bar"].set("42")
    else:
        app.clear_results()
    future.set_result({"method": "old analysis"})
    app._poll_analysis()
    assert app._future is None
    assert all(getattr(page, "data", None) is None for page in app.pages.values())
    assert "discarded" in app.status_text.get()
    assert "disabled" not in app.run_button.state()


def test_editing_inputs_clears_previously_displayed_results(app):
    app.pages["size_result"].data = {"old": True}
    app.pages["engine"].variables["mixture_ratio"].set("2")
    assert app.pages["size_result"].data is None
    assert "Inputs changed" in app.status_text.get()


@pytest.mark.parametrize("key,value", [("chamber_pressure_bar", "nan"), ("mixture_ratio", "inf"),
                                      ("oxidizer_temperature_k", "nan"), ("fuel_pressure_bar", "1")])
def test_nonfinite_and_invalid_supply_inputs_rejected(app, key, value):
    project = app.collect_project()
    project["engine"][key] = value
    assert any(issue.field == key for issue in validate_project(project))


@pytest.mark.parametrize("value", ["nan", "inf", "60.9"])
def test_sweep_count_validation_never_raises_or_truncates(app, value):
    project = app.collect_project()
    project["thrust_chamber"].update(throttle_enabled=True, throttle_mode="Throttle values range", throttle_points=value)
    assert any(issue.field == "throttle_points" for issue in validate_project(project))


@pytest.mark.parametrize("changes", [
    {"tbc_enabled": True, "tbc_conductivity_w_mk": "banana"},
    {"tbc_enabled": True, "tbc_thickness_mm": "nan"},
    {"roughness_enabled": True, "roughness_height_mm": "banana"},
    {"roughness_enabled": True, "roughness_step_mm": "inf"},
    {"channel_count": "60.9"},
    {"coolant_inlet_temperature_k": "banana"},
    {"channel_width_1_mm": "nan"},
])
def test_active_segment_inputs_block_apply_and_analysis(app, changes):
    project = cooling_project(app)
    project["thermal"]["segments"][0].update(changes)
    assert any(issue.page == "thermal" for issue in validate_project(project))
    dialog = SegmentDialog(app.pages["thermal_input"], project["thermal"]["segments"][0], [])
    try:
        dialog.update()
        dialog._save()
        assert dialog.result is None
        assert dialog.error.cget("text")
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_duplicate_names_preserve_selected_regen_identity(app):
    a, b = default_segment("Regen", 1), default_segment("Regen", 2)
    a.update(id="a", name="same")
    b.update(id="b", name="same")
    project = cooling_project(app)
    project["thermal"]["segments"] = [a, b]
    app.load_project_data(project)
    film = default_segment("Film", 3)
    film.update(temperature_mode="Temperature from Regen segment", temperature_source_id="a")
    dialog = SegmentDialog(app.pages["thermal_input"], film, [("a", "same"), ("b", "same")])
    try:
        dialog.update()
        assert dialog._selected_regen_id() == "a"
        dialog._save()
        assert dialog.result["temperature_source_id"] == "a"
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_malformed_open_preserves_entire_current_project_and_path(app, monkeypatch, tmp_path):
    before = app.collect_project()
    original = tmp_path / "original.cfg"
    app._project_path = original
    broken = copy.deepcopy(before)
    broken["engine"]["engine_name"] = "BROKEN"
    broken["thermal"]["segments"] = [1]
    target = tmp_path / "broken.cfg"
    target.write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(app_module.filedialog, "askopenfilename", lambda **kwargs: str(target))
    errors = []
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    app.open_project()
    assert errors
    assert app._project_path == original
    assert app.collect_project() == before
    assert app._dirty is False


def test_sparse_legacy_project_uses_defaults_instead_of_previous_engine(app):
    previous = app.collect_project()
    previous["engine"]["chamber_pressure_bar"] = "42"
    previous["thrust_chamber"]["nominal_thrust"] = "9876"
    app.load_project_data(previous)
    app.load_project_data({"engine": {"engine_name": "Sparse"}, "thrust_chamber": {}, "thermal": {}})
    current = app.collect_project()
    assert current["engine"]["chamber_pressure_bar"] == app._default_project["engine"]["chamber_pressure_bar"]
    assert current["thrust_chamber"]["nominal_thrust"] == app._default_project["thrust_chamber"]["nominal_thrust"]


def test_atomic_save_failure_preserves_previous_file(app, tmp_path, monkeypatch):
    target = tmp_path / "engine.cfg"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr(project_module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("blocked")))
    with pytest.raises(OSError):
        save_project(target, app.collect_project())
    assert target.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.iterdir()) == [target]


def test_supply_fields_round_trip_and_supported_frozen_modes(app, tmp_path):
    project = app.collect_project()
    project["engine"].update(oxidizer_temperature_k="90", fuel_temperature_k="280", oxidizer_pressure_bar="25", fuel_pressure_bar="25")
    project["thrust_chamber"].update(flow_model="Frozen at throat", freeze_value="")
    app.load_project_data(project)
    target = tmp_path / "supply.cfg"
    save_project(target, app.collect_project())
    app.load_project_data(load_project(target))
    assert app.collect_project() == project
    assert validate_project(project) == []
    assert app.pages["chamber"].freeze_value.instate(["disabled"])


def test_regen_feed_coupling_toggle_is_saved_and_tracked(app, tmp_path):
    project = cooling_project(app)
    app.load_project_data(project)
    page = app.pages["thermal_input"]
    assert page.variables["regen_feed_feedback_enabled"].get() is False
    page.variables["regen_feed_feedback_enabled"].set(True)
    assert app._dirty
    target = tmp_path / "coupled.cfg"
    save_project(target, app.collect_project())
    app.load_project_data(load_project(target))
    assert page.variables["regen_feed_feedback_enabled"].get() is True
    assert app._dirty is False


def test_unsupported_loaded_modes_require_user_correction(app):
    project = app.collect_project()
    project["thrust_chamber"]["flow_model"] = "Frozen at chamber"
    assert any(issue.field == "flow_model" and "unsupported" in issue.message for issue in validate_project(project))
    project["thrust_chamber"]["flow_model"] = "Shifting equilibrium"
    project["thrust_chamber"]["nozzle_type"] = "Unknown shape"
    assert any(issue.field == "nozzle_type" for issue in validate_project(project))


def test_unavailable_performance_is_displayed_as_missing_not_zero(app):
    data = {"method": "test fixture", "performance": {
        "without_film": {"sea_level_thrust_n": None, "sea_level_isp_s": None,
                         "optimal_thrust_n": 2000, "vacuum_thrust_n": 2500}}}
    page = app.pages["size_result"]
    page.set_result(data)
    def labels(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Label):
                yield str(child.cget("text"))
            yield from labels(child)
    content = list(labels(page))
    assert content.count("—") >= 2
    assert "0.000" not in content


def thermal_fixture():
    count = 35
    return {"method": "test fixture", "warnings": [f"warning-{n}" for n in range(1, 7)],
            "thermal_enabled": True, "thermal": {
                "section_count": count, "resolution": "Low", "converged": True, "iterations": 3,
                "physical_validity": "unsupported", "physical_issues": ["two-phase model unsupported"],
                "x_mm": list(range(count)), "radius_mm": [10.] * count,
                "twg_k": [700. + n for n in range(count)], "twi_k": [700.] * count,
                "twc_k": [600.] * count, "tc_k": [300.] * count, "heat_flux_w_m2": [1e6] * count,
                "coolant_pressure_bar": [25.] * count, "coolant_velocity_m_s": [4.] * count,
                "coolant_density_kg_m3": [800.] * count, "active_segment_id": ["regen"] * count,
                "coolant_phase": ["two-phase"] * count, "metadata": {"model_capabilities": {"two_phase": False}}}}


def test_full_warning_details_and_physical_status_on_every_result_page(app):
    data = thermal_fixture()
    data["reactant_supply_states"] = {"fuel": {"enthalpy_source": "CoolProp fixture", "temperature_k": 350}}
    data["regen_feed_feedback"] = {"enabled": False, "status": "disabled fixture"}
    data["mixture_ratio_optimization"] = {"objective": "maximum theoretical vacuum specific impulse",
                                          "vacuum_isp_s": 321.5, "source": "optimizer fixture"}
    for key in ("size_result", "thermal_result", "thermo_result", "throttle_result", "ambient_result"):
        page = app.pages[key]
        page.set_result(data)
        text = page._diagnostic_text()
        assert "warning-6" in text
        assert "two-phase model unsupported" in text
        assert "unsupported" in text
        assert "Numerical convergence: True" in text
        assert "CoolProp fixture" in text
        assert '"temperature_k": 350' in text
        assert "disabled fixture" in text
        assert "maximum theoretical vacuum specific impulse" in text
        assert '"vacuum_isp_s": 321.5' in text
        assert "optimizer fixture" in text


def test_reactant_supply_model_details_available_without_thermal_analysis(app):
    data = {"thermal_enabled": False, "thermal": {},
            "reactant_supply_states": {"fuel": {"enthalpy_source": "CoolProp fixture", "pressure_bar": 40}},
            "regen_feed_feedback": {"enabled": False, "status": "disabled fixture"}}
    page = app.pages["size_result"]
    page.set_result(data)
    text = page._diagnostic_text()
    assert "CoolProp fixture" in text
    assert '"pressure_bar": 40' in text
    assert "disabled fixture" in text


def test_thermal_csv_exports_every_unsmoothed_station_and_diagnostics(app, tmp_path):
    data = thermal_fixture()
    model_sources = {"material_references": {"fixture material": "reference fixture"},
                     "gas_state_source": "gas-state fixture", "gas_side_model": "gas-side fixture",
                     "coolant_side_model": "coolant-side fixture", "wall_model": "wall fixture",
                     "radiation_model": "radiation fixture", "film_model": "film fixture",
                     "coolant_property_sources": ["coolant fixture"]}
    data["thermal"]["metadata"].update(model_sources)
    data["thermal"]["metadata"]["gas_temperature_k"] = [2000.] * 35
    page = app.pages["thermal_result"]
    page.set_result(data)
    page.smooth.set(True)
    target = tmp_path / "전체 stations.csv"
    page.export_all_stations(target)
    with target.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 35
    assert float(rows[-1]["twg_k"]) == 734.
    assert rows[-1]["physical_validity"] == "unsupported"
    assert rows[-1]["coolant_phase"] == "two-phase"
    assert "warning-6" in rows[-1]["warnings"]
    sources = json.loads(rows[-1]["model_and_property_sources"])
    assert sources["model_capabilities"] == {"two_phase": False}
    assert all(sources[key] == value for key, value in model_sources.items())
    assert "gas_temperature_k" not in sources


def test_unsupported_thermal_result_with_no_finite_temperatures_renders(app):
    data = thermal_fixture()
    for key in ("twg_k", "twi_k", "twc_k", "tc_k"):
        data["thermal"][key] = [None] * 35
    page = app.pages["thermal_result"]
    page.set_result(data)
    app.show_page("thermal_result")
    app.update_idletasks()
    assert page.axis.get_ylim()[0] == 0.0
    assert "unsupported" in page._diagnostic_text()


def test_shared_film_display_selects_same_performance_basis_in_sweeps(app):
    page = app.pages["throttle_result"]
    row = {"with_film": {"thrust_n": 90.}, "without_film": {"thrust_n": 100.}}
    app.film_correction_var.set(False)
    assert page._select_sweep_rows([row])[0]["thrust_n"] == 100.
    app.film_correction_var.set(True)
    assert page._select_sweep_rows([row])[0]["thrust_n"] == 90.
    assert app.pages["size_result"].film_blc_var is page.film_display_var
    app.film_correction_var.set(False)


@pytest.mark.parametrize("model,phase,choked", [
    ("compressible ideal-gas Cd equation; choked", "gas", True),
    ("single-phase incompressible Cd equation; linked Regen outlet state and local gas pressure", "liquid", False),
])
def test_orifice_report_states_actual_outlet_pressure_and_restriction_model(app, model, phase, choked):
    data = thermal_fixture()
    data["thermal"]["film_orifices"] = [{"name": "Film example", "diameter_mm": .5,
        "orifice_count": 30, "pressure_drop_bar": 10, "mass_flow_kg_s": .03,
        "temperature_k": 350, "upstream_pressure_bar": 30, "gas_pressure_bar": 20,
        "model": model, "phase": phase, "choked": choked, "physical_validity": "screening"}]
    page = app.pages["thermal_result"]
    page.set_result(data)
    app.show_page("thermal_result")
    app.update_idletasks()
    def labels(parent):
        for widget in parent.winfo_children():
            if isinstance(widget, ttk.Label):
                yield str(widget.cget("text"))
            yield from labels(widget)
    text = "\n".join(labels(page))
    assert model in text
    assert "Regen outlet: 350.00 K, 30.000 bar(a)" in text
    assert "local gas: 20.000 bar(a)" in text
    assert f"phase: {phase}" in text
    assert f"choked: {'yes' if choked else 'not applicable'}" in text
    assert "state only" in text
    assert "Regen inlet pressure" not in text


@pytest.mark.parametrize("key,value", [("exit_condition_value", "0.8"),
                                      ("flow_model", "Frozen at throat"),
                                      ("nozzle_half_angle_deg", "18"),
                                      ("nozzle_type", "Parabolic contour (Rao)"),
                                      ("rn_rt", "0.6"),
                                      ("nozzle_efficiency_pct", "94")])
def test_auto_of_preview_recalculates_after_exit_flow_or_nozzle_edit_and_clears_results(app, monkeypatch, key, value):
    calls = []
    def optimum(**settings):
        calls.append(settings)
        return MixtureRatioOptimum(2. + .1 * len(calls), 300., 5., "rocketcea",
                                   objective="maximum theoretical vacuum specific impulse")
    monkeypatch.setattr(input_module, "optimize_mixture_ratio", optimum)
    engine = app.pages["engine"]
    engine._optimum_cache.clear()
    engine.mixture_ratio_auto_var.set(True)
    engine.values()
    assert len(calls) == 1
    app.pages["size_result"].set_result({"method": "test fixture"})
    revision = app._project_revision
    app.pages["chamber"].variables[key].set(value)
    assert app.pages["size_result"].data is None
    assert app._project_revision > revision
    assert float(engine.values()["mixture_ratio"]) == pytest.approx(2.2)
    assert len(calls) == 2
    if key == "flow_model":
        assert calls[-1]["equilibrium_mode"] is EquilibriumMode.FROZEN_AREA
    if key == "exit_condition_value":
        assert calls[-1]["ambient_pressure_atm"] == .8


def test_auto_of_legacy_freezing_criteria_are_normalized_and_reported(app, monkeypatch):
    calls = []
    def optimum(**settings):
        calls.append(settings)
        return MixtureRatioOptimum(2., 300., 5., "rocketcea")
    monkeypatch.setattr(input_module, "optimize_mixture_ratio", optimum)
    engine = app.pages["engine"]
    engine._optimum_cache.clear()
    chamber = app.pages["chamber"]
    chamber.variables["flow_model"].set("Frozen at throat")
    chamber.variables["freeze_value"].set("")
    engine.mixture_ratio_auto_var.set(True)
    engine.values()
    assert len(calls) == 1
    chamber.variables["flow_model"].set("Freezing at area ratio")
    chamber.variables["freeze_value"].set("1.7")
    engine.values()
    assert len(calls) == 2
    assert "A/At=1.7" in engine.mixture_ratio_status.cget("text")
    assert "throat-frozen approximation" in engine.mixture_ratio_status.cget("text")
    chamber.variables["freeze_value"].set("1.8")
    engine.values()
    assert len(calls) == 3
    chamber.variables["flow_model"].set("Frozen at chamber")
    engine.values()
    assert len(calls) == 3
    assert "unsupported" in engine.mixture_ratio_status.cget("text")


def test_auto_of_exit_mode_and_explicit_supply_state_pass_through_to_optimizer(app, monkeypatch):
    calls = []
    def optimum(**settings):
        calls.append(settings)
        return MixtureRatioOptimum(2., 300., 5., "rocketcea")
    monkeypatch.setattr(input_module, "optimize_mixture_ratio", optimum)
    engine = app.pages["engine"]
    engine._optimum_cache.clear()
    engine.mixture_ratio_auto_var.set(True)
    engine.values()
    chamber = app.pages["chamber"]
    chamber.variables["exit_condition_mode"].set("Expansion area ratio")
    chamber.variables["exit_condition_value"].set("30")
    engine.variables["fuel_temperature_k"].set("310")
    engine.variables["fuel_pressure_bar"].set("25")
    engine.values()
    assert len(calls) == 2
    assert calls[-1]["expansion_ratio"] == 30
    assert calls[-1]["ambient_pressure_atm"] is None
    assert calls[-1]["engine"].fuel_temperature_k == 310
    assert calls[-1]["engine"].fuel_pressure_bar == 25


def test_auto_of_help_and_supply_pressure_hint_describe_actual_model(app, monkeypatch):
    engine = app.pages["engine"]
    assert engine.automatic_mixture_ratio_checkbox.cget("text") == "Auto O/F: maximum theoretical vacuum Isp"
    style = ttk.Style(app)
    original_font = style.lookup("TCheckbutton", "font")
    try:
        # Larger text must fit the minimum window's allocated operating field.
        style.configure("TCheckbutton", font=("Segoe UI", 15))
        app.show_page("engine")
        app.update_idletasks()
        checkbox = engine.automatic_mixture_ratio_checkbox
        assert checkbox.winfo_reqwidth() <= checkbox.master.winfo_width()
    finally:
        style.configure("TCheckbutton", font=original_font)
    text = []
    def walk(parent):
        for child in parent.winfo_children():
            if isinstance(child, ttk.Label):
                text.append(str(child.cget("text")))
            walk(child)
    walk(engine)
    assert sum("reference pressure: 1.01325 bar; LNG uses 5 bar" in item for item in text) == 2
    assert not any("Blank uses chamber pressure" in item for item in text)
    dialogs = []
    monkeypatch.setattr(app_module.messagebox, "showinfo", lambda title, message, **kwargs: dialogs.append(message))
    app._show_methods()
    app._show_about()
    assert all("theoretical vacuum specific impulse" in message for message in dialogs)
    assert "Performance losses and Film correction are excluded" in dialogs[0]


def test_auto_of_coupled_dc_sizing_preserves_throat_freezing_and_active_rao_settings(app, monkeypatch):
    calls = []
    def optimum(inputs):
        calls.append(inputs)
        return MixtureRatioOptimum(2., 300., 5., "rocketcea")
    monkeypatch.setattr(input_module, "optimize_mixture_ratio_for_inputs", optimum)
    engine = app.pages["engine"]
    engine._optimum_cache.clear()
    chamber = app.pages["chamber"]
    for key, value in {"contraction_mode": "Chamber diameter (Dc)", "sizing_mode": "Engine nominal thrust",
                       "contraction_area_ratio": "inactive", "flow_model": "Frozen at throat", "freeze_value": "",
                       "nozzle_type": "Conical nozzle", "nozzle_efficiency_mode": "Estimate",
                       "nozzle_efficiency_pct": "inactive", "rao_length_pct": "inactive",
                       "rao_start_angle_deg": "inactive", "rao_exit_angle_deg": "inactive"}.items():
        chamber.variables[key].set(value)
    engine.mixture_ratio_auto_var.set(True)
    engine.values()
    assert len(calls) == 1
    assert calls[-1].thrust_chamber.contraction_area_ratio == 4.
    assert calls[-1].thrust_chamber.equilibrium.freeze_area_ratio == 1.
    assert calls[-1].thrust_chamber.nozzle.bell_length_percent == 80.
    assert calls[-1].thrust_chamber.nozzle.rao_initial_angle_deg is None
    for key, value in {"nozzle_type": "Parabolic contour (Rao)", "rao_length_pct": "85",
                       "nozzle_half_angle_deg": "inactive", "rao_start_angle_deg": "25", "rao_exit_angle_deg": "12"}.items():
        chamber.variables[key].set(value)
    engine.values()
    assert len(calls) == 2
    assert calls[-1].thrust_chamber.nozzle.conical_half_angle_deg == 15.
    assert calls[-1].thrust_chamber.nozzle.bell_length_percent == 85.
    assert calls[-1].thrust_chamber.nozzle.rao_initial_angle_deg == 25.
    assert calls[-1].thrust_chamber.nozzle.rao_exit_angle_deg == 12.
