"""Inlet annotations and finite-cell interpretation preserve underlying results."""

import csv
import json
import tkinter as tk
from types import SimpleNamespace

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from lpa.ui.result_views import (
    ResultPage, ThermalResultsPage, _coolant_inlet_markers,
    _reference_melting_lines, _thermal_wall_sampling_note,
)
from lpa.ui.theme import apply_theme
from tests.test_two_phase_ui import phase_fixture


def inlet_fixture():
    data = phase_fixture()
    thermal = data["thermal"]
    thermal["segment_names"] = {"a": "Regen 1", "b": "Regen 2"}
    thermal["metadata"].update(
        wall_sampling={"basis": "cell-average local conjugate wall solutions",
                       "inlet_endpoint_is_point_temperature": False},
        coolant_entrance_diagnostics_by_segment={
            "a": {"inlet_x_m": .006, "outlet_x_m": 0., "flow_direction": "counterflow",
                  "inlet_regime": "laminar", "inlet_reynolds": 700.,
                  "first_cell_path_length_m": .0005},
            "b": {"inlet_x_m": .003, "outlet_x_m": .006, "flow_direction": "coflow"},
        },
    )
    return data


def test_legacy_and_empty_metadata_do_not_invent_sampling_basis_or_inlet():
    for thermal in ({}, phase_fixture()["thermal"], {"metadata": {
        "wall_sampling": {}, "coolant_entrance_diagnostics_by_segment": {}}}):
        assert _thermal_wall_sampling_note(thermal) == ""
        assert _coolant_inlet_markers(thermal) == []
    malformed = {"metadata": {"coolant_entrance_diagnostics_by_segment": {
        "a": {}, "b": {"inlet_x_m": None}, "c": {"inlet_x_m": "nan"}}}}
    assert _coolant_inlet_markers(malformed) == []


def test_inlet_plot_uses_reported_positions_without_changing_raw_wall_values():
    page = object.__new__(ThermalResultsPage)
    page.data = inlet_fixture()
    page.figure = Figure(figsize=(10.5, 5.2))
    page.panel = None
    page.smooth = SimpleNamespace(get=lambda: False)
    page._draw()
    FigureCanvasAgg(page.figure).draw()
    wall = next(line for line in page.axis.lines if line.get_label() == "Twg")
    assert np.array_equal(wall.get_xdata(), np.arange(7))
    assert np.allclose(wall.get_ydata(), [700., 710., 720., 730., 740., np.nan, np.nan], equal_nan=True)
    inlet_lines = [line for line in page.contour_axis.lines if line.get_label() == "_coolant_inlet"]
    assert [list(line.get_xdata()) for line in inlet_lines] == [[6., 6.], [3., 3.]]
    labels = [text.get_text() for text in page.axis.get_legend().get_texts()]
    assert not any("Coolant inlet" in label for label in labels)
    annotations = [text for text in page.contour_axis.texts if text.get_text().startswith("Coolant inlet")]
    assert [item.xy[0] for item in annotations] == [6., 3.]
    assert any("Regen 1" in item.get_text() for item in annotations)


def test_shared_inlet_is_grouped_and_outside_plot_coordinates_are_not_drawn():
    data = inlet_fixture()
    diagnostics = data["thermal"]["metadata"]["coolant_entrance_diagnostics_by_segment"]
    diagnostics["b"]["inlet_x_m"] = .006
    diagnostics["outside"] = {"inlet_x_m": .01}
    markers = _coolant_inlet_markers(data["thermal"])
    assert markers[0] == (6., "Coolant inlet · Regen 1, Regen 2", "counterflow")
    page = object.__new__(ThermalResultsPage)
    page.data, page.figure, page.panel = data, Figure(), None
    page.smooth = SimpleNamespace(get=lambda: False)
    page._draw()
    assert sum(line.get_label() == "_coolant_inlet" for line in page.contour_axis.lines) == 1


def test_csv_and_diagnostics_keep_sampling_and_entrance_assumptions(tmp_path):
    page = SimpleNamespace(data=inlet_fixture(), report_warnings=[])
    page.data["thermal"].update(wall_temperature_min_k=[690., 700., 710., 720., 730., None, None],
                                wall_temperature_max_k=[710., 720., 730., 740., 750., None, None])
    target = tmp_path/"inlet.csv"
    ThermalResultsPage.export_all_stations(page, target)
    with target.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    metadata = json.loads(rows[0]["model_and_property_sources"])
    assert metadata["wall_sampling"]["inlet_endpoint_is_point_temperature"] is False
    assert metadata["coolant_entrance_diagnostics_by_segment"]["a"]["first_cell_path_length_m"] == .0005
    text = ResultPage._diagnostic_text(page)
    assert "finite-cell averages" in text
    assert "not an exact boundary-point temperature" in text
    assert "Unsupported results remain diagnostic" in text
    assert rows[5]["twg_k"] == ""
    assert rows[0]["sampled_cell_twg_min_k"] == "690.0"
    assert rows[0]["sampled_cell_twg_max_k"] == "710.0"
    assert rows[5]["sampled_cell_twg_min_k"] == ""
    assert rows[5]["sampled_cell_twg_max_k"] == ""


def test_invalid_physical_state_is_not_presented_only_as_unsupported():
    thermal = inlet_fixture()["thermal"]
    thermal["physical_validity"] = "invalid"
    text = _thermal_wall_sampling_note(thermal)
    assert "Physical applicability is invalid" in text
    assert "valid solid-wall or coolant state" in text
    assert "Unsupported results remain diagnostic" not in text


def test_melting_reference_requires_an_active_exceeded_invalid_circuit_and_is_deduplicated():
    thermal = inlet_fixture()["thermal"]
    assessment = {"material": "CuCrZr", "reference_melting_temperature_k": 1358.15,
                  "cells_above_reference_melting_point": 2}
    thermal["metadata"]["coolant_property_metadata"] = {
        "a": {"wall_material_assessment": assessment},
        "b": {"wall_material_assessment": dict(assessment)},
        "inactive": {"wall_material_assessment": {**assessment, "material": "IN718"}},
    }
    assert _reference_melting_lines(thermal) == []  # A mere unsupported result is not a melt diagnosis.
    thermal["physical_validity"] = "invalid"
    assert _reference_melting_lines(thermal) == [(1358.15, "CuCrZr reference melting")]
    thermal["metadata"]["coolant_property_metadata"]["a"]["wall_material_assessment"] = {**assessment,
        "cells_above_reference_melting_point": 0}
    thermal["metadata"]["coolant_property_metadata"]["b"]["wall_material_assessment"] = {**assessment,
        "reference_melting_temperature_k": None}
    assert _reference_melting_lines(thermal) == []
    assert _reference_melting_lines({}) == []


def test_melting_reference_is_labelled_without_changing_temperature_limits_or_raw_samples():
    data = inlet_fixture()
    thermal = data["thermal"]
    thermal["physical_validity"] = "invalid"
    thermal["metadata"]["coolant_property_metadata"] = {"a": {"wall_material_assessment": {
        "material": "CuCrZr", "reference_melting_temperature_k": 1358.15,
        "cells_above_reference_melting_point": 2}}}
    page = object.__new__(ThermalResultsPage)
    page.data, page.figure, page.panel = data, Figure(), None
    page.smooth = SimpleNamespace(get=lambda: False)
    page._draw()
    line = next(line for line in page.axis.lines if line.get_label() == "CuCrZr reference melting")
    assert list(line.get_ydata()) == [1358.15, 1358.15]
    assert line.get_linestyle() == ":"
    assert page.axis.get_ylim()[1] < 1358.15  # A reference does not inflate the raw-data scale.
    assert "CuCrZr reference melting" in [label.get_text() for label in page.axis.get_legend().get_texts()]
    data["thermal"]["metadata"].pop("coolant_property_metadata")
    page._draw()
    assert not any("reference melting" in line.get_label() for line in page.axis.lines)


def test_note_wraps_at_minimum_window_and_clears_when_loading_legacy_result():
    window = tk.Tk()
    window.geometry("1080x700")
    apply_theme(window)
    try:
        page = ThermalResultsPage(window)
        page.pack(fill="both", expand=True)
        page.set_result(inlet_fixture())
        window.update()
        note = page.wall_sampling_note
        assert note is not None
        assert note.winfo_reqheight() < 100
        assert note.winfo_rootx()+note.winfo_width() <= page.scroll.winfo_rootx()+page.scroll.winfo_width()
        assert "Unsupported results remain diagnostic" in note.cget("text")
        page.set_result(phase_fixture())
        window.update()
        assert page.wall_sampling_note is None
        assert not any(text.get_text().startswith("Coolant inlet") for text in page.contour_axis.texts)
    finally:
        window.destroy()
