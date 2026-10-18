from __future__ import annotations

import csv
import json
import tkinter as tk
from types import SimpleNamespace
from tkinter import ttk

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from lpa.ui.result_views import (
    ResultPage, ThermalResultsPage, _coolant_quality_array,
    _thermal_station_completion, _thermal_two_phase_regions,
)
from lpa.ui.theme import apply_theme


def phase_fixture():
    return {"thermal_enabled": True, "thermal": {
        "section_count": 7, "converged": True, "iterations": 12,
        "x_mm": list(range(7)), "radius_mm": [10.] * 7,
        "twg_k": [700., 710., 720., 730., 740., None, None],
        "twi_k": [690., 700., 710., 720., 730., None, None],
        "twc_k": [500., 510., 520., 530., 540., None, None],
        "tc_k": [300., 320., 320., 320., 320., 320., None],
        "active_segment_id": ["a", "a", "a", "b", "b", None, None],
        "coolant_phase": ["liquid", "two_phase", "two_phase", "two_phase", "liquid", "two_phase", None],
        "coolant_vapor_quality": [None, .05, .15, .25, -1., .45, None],
        "coolant_flow_regime": ["liquid", "saturated_boiling", "saturated_boiling", "saturated_boiling",
                                "liquid", "unsupported_mixture_two_phase", ""],
        "physical_validity": "unsupported",
        "metadata": {"two_phase_model": "Chen-Bennett fixture",
                     "two_phase_model_by_segment": {"a": {"source": "reference fixture"}}},
    }}


def test_two_phase_regions_split_circuits_and_preserve_unsolved_phase_cell():
    data = phase_fixture()["thermal"]
    assert _thermal_two_phase_regions(data, np.asarray(data["x_mm"])) == [
        (.5, 2.5, "a"), (2.5, 3.5, "b"), (4.5, 5.5, None),
    ]
    # An absent/misaligned legacy phase array must not invent shaded regions.
    assert _thermal_two_phase_regions({}, np.arange(7)) == []
    data["coolant_phase"] = ["two_phase"]
    assert _thermal_two_phase_regions(data, np.arange(7)) == []


def test_wall_completion_and_quality_do_not_validate_unsolved_or_sentinel_values():
    thermal = phase_fixture()["thermal"]
    assert _thermal_station_completion(thermal) == (5, 7)
    quality = _coolant_quality_array(thermal)
    assert np.isnan(quality[0]) and np.isnan(quality[4]) and np.isnan(quality[6])
    assert quality[5] == .45  # A diagnosed state need not have a wall solution.
    thermal["coolant_vapor_quality"] = [0., 1., 1.01]
    assert np.allclose(_coolant_quality_array(thermal)[:2], [0., 1.])
    assert np.isnan(_coolant_quality_array(thermal)[2])


def test_temperature_plot_shades_all_phase_regions_without_bridging_gaps():
    page = object.__new__(ThermalResultsPage)
    page.data = phase_fixture()
    page.figure = Figure(figsize=(10.5, 5.2))
    page.panel = None
    page.smooth = SimpleNamespace(get=lambda: False)
    page._draw()
    FigureCanvasAgg(page.figure).draw()
    patches = page.contour_axis.patches
    assert len(patches) == 3
    assert [(patch.get_x(), patch.get_width()) for patch in patches] == [(.5, 2.), (2.5, 1.), (4.5, 1.)]
    labels = [item.get_text() for item in page.axis.get_legend().get_texts()]
    assert labels.count("Two-phase coolant") == 1
    assert page.axis.get_ylim()[0] == 0.


def test_csv_and_diagnostics_preserve_quality_status_and_source_on_unsolved_cell(tmp_path):
    page = SimpleNamespace(data=phase_fixture(), report_warnings=["mixture boiling unsupported"])
    target = tmp_path / "two-phase.csv"
    ThermalResultsPage.export_all_stations(page, target)
    with target.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 7
    assert rows[4]["coolant_vapor_quality"] == ""
    assert rows[5]["coolant_vapor_quality"] == "0.45"
    assert rows[5]["coolant_phase"] == "two_phase"
    assert rows[5]["coolant_flow_regime"] == "unsupported_mixture_two_phase"
    assert rows[5]["twg_k"] == ""
    assert rows[5]["wall_solution_available"] == "False"
    assert rows[5]["numerically_converged"] == "True"
    sources = json.loads(rows[5]["model_and_property_sources"])
    assert sources["two_phase_model"] == "Chen-Bennett fixture"
    assert sources["two_phase_model_by_segment"]["a"]["source"] == "reference fixture"
    diagnostic = ResultPage._diagnostic_text(page)
    assert "Solved wall stations: 5/7; unsolved: 2" in diagnostic
    assert "Vapor mass quality (0–1): 0.05000 to 0.45000" in diagnostic
    assert "unsupported_mixture_two_phase" in diagnostic
    assert "Chen-Bennett fixture" in diagnostic


def test_result_page_reports_partial_completion_and_unsolved_boiling_status():
    root = tk.Tk()
    root.withdraw()
    apply_theme(root)
    try:
        page = ThermalResultsPage(root)
        page.pack(fill="both", expand=True)
        page.set_result(phase_fixture())
        root.update_idletasks()

        def label_texts(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Label):
                    yield str(child.cget("text"))
                yield from label_texts(child)

        labels = list(label_texts(page))
        assert "Solved wall stations 5/7 · Unsolved 2" in labels
        assert any("Numerically converged" in label for label in labels)
        table = page.axial_tree
        row = table.item(table.get_children()[5], "values")
        assert row[2] == "—"
        assert row[-2:] == ("0.4500", "unsupported_mixture_two_phase")
    finally:
        root.destroy()
