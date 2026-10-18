from __future__ import annotations

import copy
import math
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Iterator
from pathlib import Path
from tkinter import ttk
from typing import Any

import pytest

import lpa.ui.input_views as input_views
from lpa import __version__
from lpa.analysis import AnalysisService
from lpa.app import APP_TITLE, LPAApplication
from lpa.core import MixtureRatioOptimum
from lpa.project import validate_project
from lpa.ui.input_views import SegmentDialog, default_segment
from lpa.ui.widgets import Card, ScrollableFrame


EXPECTED_PAGES = {
    "engine",
    "chamber",
    "thermal_input",
    "size_result",
    "thermal_result",
    "thermo_result",
    "throttle_result",
    "ambient_result",
}


def _walk(widget: tk.Misc) -> Iterator[tk.Misc]:
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _labels(widget: tk.Misc) -> list[ttk.Label]:
    return [child for child in _walk(widget) if isinstance(child, ttk.Label)]


def _label_texts(widget: tk.Misc) -> list[str]:
    return [str(label.cget("text")) for label in _labels(widget)]


def _treeviews(widget: tk.Misc) -> list[ttk.Treeview]:
    return [child for child in _walk(widget) if isinstance(child, ttk.Treeview)]


def _labelframe_texts(widget: tk.Misc) -> list[str]:
    return [
        str(child.cget("text"))
        for child in _walk(widget)
        if isinstance(child, ttk.LabelFrame)
    ]


@pytest.fixture(scope="module")
def application() -> Iterator[LPAApplication]:
    application = LPAApplication()
    application.geometry("1080x700+0+0")
    application.deiconify()
    application.update()
    assert application._dirty is False, "Startup defaults must not trigger an unsaved-project prompt"
    try:
        yield application
    finally:
        application._executor.shutdown(wait=False, cancel_futures=True)
        if application.winfo_exists():
            application.destroy()


@pytest.fixture
def app(application: LPAApplication) -> Iterator[LPAApplication]:
    application._project_path = None
    application.load_project_data(copy.deepcopy(application._default_project))
    application.geometry("1080x700+0+0")
    application.deiconify()
    application.update()
    yield application
    application.clear_results()
    application._set_dirty(False)


def _rich_project(application: LPAApplication) -> dict[str, Any]:
    project = copy.deepcopy(application.collect_project())
    project["engine"].update(
        {
            "engine_name": "Round-trip 엔진",
            "description": "Unicode 설명과 줄바꿈\n두 번째 줄",
            "chamber_pressure_bar": "35.5",
            "mixture_ratio": "2.7",
            "oxidizer": "H2O2",
            "oxidizer_mass_fraction_pct": "90",
            "fuel": "RP-1",
        }
    )
    project["thrust_chamber"].update(
        {
            "exit_condition_mode": "Expansion area ratio",
            "exit_condition_value": "12",
            "flow_model": "Freezing at area ratio",
            "freeze_value": "4",
            "nozzle_efficiency_mode": "Specified",
            "nozzle_efficiency_pct": "94.5",
            "throttle_enabled": True,
            "throttle_mode": "Throttle values range",
            "throttle_min_pct": "35",
            "throttle_max_pct": "100",
            "throttle_points": "9",
            "ambient_enabled": True,
            "ambient_mode": "Ambient pressure range",
            "ambient_min_atm": "0",
            "ambient_max_atm": "1.2",
            "ambient_points": "5",
            "sizing_mode": "Chamber throat diameter",
            "throat_diameter_mm": "42",
            "chamber_length_mode": "Direct Lc and Lcyl",
            "chamber_length_mm": "250",
            "cylindrical_length_mm": "150",
            "nozzle_type": "Parabolic contour (Rao)",
            "rao_length_pct": "85",
        }
    )

    regen = default_segment("Regen", 1)
    regen.update({"id": "regen-a", "name": "Regen A", "x2": "200"})
    film = default_segment("Film", 2)
    film.update(
        {
            "id": "film-a",
            "name": "Film A",
            # Linked Film identity follows the effective Regen coolant.  The
            # default Regen source is the engine fuel selected above.
            "coolant": "RP-1",
            "temperature_mode": "Temperature from Regen segment",
            "temperature_source_id": "regen-a",
        }
    )
    radiation = default_segment("Radiation", 3)
    radiation.update({"id": "radiation-a", "name": "Radiation A", "x1": "200"})
    project["thermal"].update(
        {
            "thermal_enabled": True,
            "thermal_resolution": "High",
            "thermal_max_iterations": "120",
            "segments": [regen, film, radiation],
        }
    )
    return project


def test_application_initializes_every_page_and_scrolls_at_minimum_size(app: LPAApplication) -> None:
    assert set(app.pages) == EXPECTED_PAGES
    assert app.winfo_width() == 1080
    assert app.winfo_height() == 700

    # ASCII numeric prefixes avoid missing-glyph boxes when Windows ttk uses a
    # different font fallback for the selected (bold) navigation state.
    assert all(str(button.cget("text")).isascii() for button in app.nav_buttons.values())

    for key in EXPECTED_PAGES:
        app.show_page(key)
        app.update_idletasks()
        assert app.current_page == key
        assert str(app.nav_buttons[key].cget("style")) == "NavActive.TButton"

    for key in ("engine", "chamber", "thermal_input"):
        page = app.pages[key]
        bbox = page.canvas.bbox("all")  # type: ignore[attr-defined]
        assert bbox is not None and bbox[2] > 0 and bbox[3] > 0
        assert bbox[2] == page.canvas.winfo_width()  # type: ignore[attr-defined]

    chamber = app.pages["chamber"]
    assert chamber.canvas.yview()[1] < 1.0  # type: ignore[attr-defined]
    chamber.canvas.yview_moveto(1.0)  # type: ignore[attr-defined]
    app.update_idletasks()
    assert chamber.canvas.yview()[0] > 0.0  # type: ignore[attr-defined]
    app.show_page("chamber")
    assert chamber.canvas.yview()[0] == pytest.approx(0.0)  # type: ignore[attr-defined]


def test_minimum_window_does_not_clip_wrapped_input_labels(app: LPAApplication) -> None:
    clipped: list[tuple[str, str, int, int]] = []
    for key in ("engine", "chamber", "thermal_input"):
        app.show_page(key)
        app.update_idletasks()
        for label in _labels(app.pages[key]):
            text = str(label.cget("text"))
            if text and label.winfo_ismapped() and label.winfo_width() + 2 < label.winfo_reqwidth():
                clipped.append((key, text, label.winfo_width(), label.winfo_reqwidth()))
    assert clipped == []


def test_input_copy_is_compact_and_typography_has_a_consistent_hierarchy(
    app: LPAApplication,
) -> None:
    forbidden = {
        "Used in saved analysis files and exported reports.",
        "CEA equilibrium chemistry is evaluated at this nominal state.",
        "Optional sweeps produce dedicated result tables.",
        "Bartz hot-gas correlation",
        "The exact axial section count is reported with every result.",
        "All lengths use millimetres unless another unit is shown.",
    }
    input_text = {
        text
        for key in ("engine", "chamber", "thermal_input")
        for text in _label_texts(app.pages[key])
    }
    assert forbidden.isdisjoint(input_text)
    assert not any(text.startswith("Blank Tn/Te:") for text in input_text)

    style = ttk.Style(app)

    def font(style_name: str) -> dict[str, Any]:
        return tkfont.Font(root=app, font=style.lookup(style_name, "font")).actual()

    page_font = font("PageTitle.TLabel")
    section_font = font("Section.TLabel")
    field_font = font("Field.TLabel")
    unit_font = font("Unit.TLabel")
    result_section_font = font("TLabelframe.Label")
    assert page_font["size"] > section_font["size"] > field_font["size"] > unit_font["size"]
    assert page_font["weight"] == section_font["weight"] == field_font["weight"] == "bold"
    assert result_section_font["weight"] == "bold"
    assert result_section_font["size"] >= field_font["size"]


def test_collect_load_round_trip_preserves_fields_segments_and_control_states(app: LPAApplication) -> None:
    project = _rich_project(app)
    app.load_project_data(project)
    app.update_idletasks()

    assert app.collect_project() == project
    assert validate_project(app.collect_project()) == []
    assert app.nav_engine_name.cget("text") == "Round-trip 엔진"

    chamber = app.pages["chamber"]
    for widget in (
        chamber.freeze_value,
        chamber.nozzle_eff_value,
        chamber.throat_diameter,
        chamber.lc,
        chamber.lcyl,
        chamber.rao_length,
    ):
        assert "disabled" not in widget.state()
    for widget in (chamber.nominal_thrust, chamber.lstar, chamber.conical_angle):
        assert "disabled" in widget.state()

    thermal = app.pages["thermal_input"]
    assert len(thermal.tree.get_children()) == 3
    assert thermal.tree.item("0", "values")[2] == "Regen A"
    for button in (
        thermal.add_regen_button,
        thermal.add_film_button,
        thermal.add_radiation_button,
        thermal.duplicate_button,
        thermal.remove_button,
        thermal.edit_button,
    ):
        assert "disabled" not in button.state()


def test_loading_project_stays_clean_after_text_events_are_drained(app: LPAApplication) -> None:
    project = copy.deepcopy(app.collect_project())
    project["engine"]["description"] = "A description loaded from disk"
    app.load_project_data(project)
    app.update()

    assert app._dirty is False
    assert app.pages["engine"].description.edit_modified() == 0
    assert app.title() == APP_TITLE


def test_chamber_contraction_definition_and_card_order(app: LPAApplication) -> None:
    chamber = app.pages["chamber"]
    cards = [child for child in chamber.body.winfo_children() if isinstance(child, Card)]
    card_titles = [_label_texts(card)[0] for card in cards]
    assert card_titles == [
        "Flow & performance model",
        "Thrust chamber size",
        "Contour geometry",
        "Operating envelopes",
    ]
    assert not any(text.startswith("Nozzle flow effect:") for text in _label_texts(chamber))

    chamber.contraction_mode_var.set("Chamber diameter (Dc)")
    chamber.chamber_diameter_var.set("72.5")
    chamber._refresh_states()
    app.update_idletasks()
    assert chamber.contraction_value.cget("textvariable") == str(chamber.chamber_diameter_var)
    assert chamber.contraction_unit.cget("text") == "mm"
    assert app.collect_project()["thrust_chamber"]["chamber_diameter_mm"] == "72.5"

    chamber.contraction_mode_var.set("Area ratio (Ac/At)")
    chamber._refresh_states()
    assert chamber.contraction_value.cget("textvariable") == str(
        chamber.contraction_area_ratio_var
    )
    assert chamber.contraction_unit.cget("text") == "Ac/At"

    chamber.contraction_mode_var.set("Chamber diameter (Dc)")
    chamber.load_values({"contraction_area_ratio": "5.0"})
    assert chamber.contraction_mode_var.get() == "Area ratio (Ac/At)"


def test_automatic_mixture_ratio_is_displayed_locked_and_serialized(
    app: LPAApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_optimum(**settings: Any) -> MixtureRatioOptimum:
        calls.append(settings)
        return MixtureRatioOptimum(2.7345, 351.2, 4.25, "rocketcea")

    monkeypatch.setattr(input_views, "optimize_mixture_ratio", fake_optimum)
    monkeypatch.setattr("lpa.analysis.optimize_mixture_ratio_for_inputs",
                        lambda inputs, **settings: MixtureRatioOptimum(2.7345, 351.2, 4.25, "rocketcea"))
    page = app.pages["engine"]
    page.mixture_ratio_auto_var.set(True)
    page._on_auto_mixture_ratio()

    assert page.mixture_ratio_var.get() == "2.7345"
    assert "readonly" in page.mixture_ratio_entry.state()
    assert page.mixture_ratio_status.cget("text") == ""
    assert not page.mixture_ratio_status.winfo_manager()
    assert calls[0]["engine"].oxidizer.value == "LOX"
    assert calls[0]["engine"].fuel.value == "Ethanol"
    assert calls[0]["engine"].fuel_mass_fraction == pytest.approx(0.7)
    project = app.collect_project()
    assert project["engine"]["mixture_ratio_auto"] is True
    assert project["engine"]["mixture_ratio"] == "2.7345"
    assert AnalysisService().analyze(project)["performance"]["mixture_ratio"] == pytest.approx(2.7345)

    page.mixture_ratio_auto_var.set(False)
    page._on_auto_mixture_ratio()
    assert "readonly" not in page.mixture_ratio_entry.state()


def test_demonstrator_defaults_and_sizing(app: LPAApplication) -> None:
    from lpa.analysis import _core_project
    from lpa.core import analyze_engine

    project = app.collect_project()
    engine, chamber = project["engine"], project["thrust_chamber"]
    assert engine["engine_name"] == "LPA Demonstrator"
    assert float(engine["chamber_pressure_bar"]) == 20
    assert float(engine["mixture_ratio"]) == 1.3
    assert engine["mixture_ratio_auto"] is False
    assert engine["oxidizer"] == "LOX"
    assert engine["fuel"] == "Ethanol"
    assert float(engine["fuel_mass_fraction_pct"]) == 70
    assert float(chamber["nominal_thrust"]) == 2000
    assert chamber["thrust_unit"] == "N"
    assert float(chamber["nominal_thrust_ambient_atm"]) == 1
    assert float(chamber["contraction_area_ratio"]) == 6.25
    assert float(chamber["characteristic_length_mm"]) == 1200
    result = analyze_engine(_core_project(project), prefer_rocketcea=False)
    assert result.performance.with_film.thrust_design_n == pytest.approx(2000)
    assert result.contour.metadata["characteristic_length_mm"] == pytest.approx(1200)


def test_concentration_fields_follow_selection_and_validate_mass_percent(app: LPAApplication) -> None:
    page = app.pages["engine"]
    app.show_page("engine")
    assert tuple(page.oxidizer_combo.cget("values")) == ("LOX", "GOX", "H2O2", "N2O")
    assert {"IPA", "LNG", "Ethanol"} <= set(page.fuel_combo.cget("values"))
    assert not any("%" in name for name in page.fuel_combo.cget("values"))
    for name in input_views.OXIDIZERS:
        page.oxidizer_var.set(name)
        app.update_idletasks()
        assert bool(page.oxidizer_fraction_box.winfo_ismapped()) == (name == "H2O2")
    for name in input_views.FUELS:
        page.fuel_var.set(name)
        app.update_idletasks()
        assert bool(page.fuel_fraction_box.winfo_ismapped()) == (name in {"Ethanol", "IPA"})
        assert bool(page.lng_description.winfo_ismapped()) == (name == "LNG")
        for label in _labels(page):
            if label.winfo_ismapped():
                assert label.winfo_width() + 2 >= label.winfo_reqwidth(), label.cget("text")
    page.fuel_var.set("IPA")
    for invalid in ("0", "-1", "101", "nan", "inf", "", "bad"):
        page.variables["fuel_mass_fraction_pct"].set(invalid)
        issues = validate_project(app.collect_project())
        assert any(issue.field == "fuel_mass_fraction_pct" for issue in issues)


def test_arbitrary_concentration_cfg_and_legacy_migration(app: LPAApplication, tmp_path: Path) -> None:
    from lpa.project import load_project, save_project

    page = app.pages["engine"]
    page.oxidizer_var.set("H2O2")
    page.variables["oxidizer_mass_fraction_pct"].set("87.125")
    page.fuel_var.set("IPA")
    page.variables["fuel_mass_fraction_pct"].set("72.625")
    project = app.collect_project()
    path = save_project(tmp_path / "aqueous.cfg", project)
    app.load_project_data(load_project(path))
    assert app.collect_project() == project
    legacy = copy.deepcopy(project)
    legacy["engine"].update(oxidizer="H2O2 80%", fuel="Ethanol 90%")
    legacy["engine"].pop("oxidizer_mass_fraction_pct")
    legacy["engine"].pop("fuel_mass_fraction_pct")
    app.load_project_data(legacy)
    restored = app.collect_project()["engine"]
    assert restored["oxidizer"] == "H2O2"
    assert restored["fuel"] == "Ethanol"
    assert float(restored["oxidizer_mass_fraction_pct"]) == 80
    assert float(restored["fuel_mass_fraction_pct"]) == 90


def test_auto_of_recalculates_when_mass_fraction_changes(app: LPAApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def optimum(**settings: Any) -> MixtureRatioOptimum:
        fraction = settings["engine"].fuel_mass_fraction
        calls.append(fraction)
        return MixtureRatioOptimum(2 * fraction, 300, 5, "rocketcea", ideal_cstar_m_s=1600)

    monkeypatch.setattr(input_views, "optimize_mixture_ratio", optimum)
    page = app.pages["engine"]
    page._optimum_cache.clear()
    page.mixture_ratio_auto_var.set(True)
    assert float(page.values()["mixture_ratio"]) == pytest.approx(1.4)
    page.variables["fuel_mass_fraction_pct"].set("73.125")
    assert float(page.values()["mixture_ratio"]) == pytest.approx(1.4625)
    assert calls == [0.7, 0.73125]


def test_window_title_and_compact_page_context_replace_breadcrumbs(app: LPAApplication) -> None:
    app._project_path = None
    app._set_dirty(True)
    assert app.title() == APP_TITLE
    assert not hasattr(app, "logo_image")

    app._project_path = Path("named-project.cfg")
    app._set_dirty(False)
    assert app.title() == APP_TITLE
    assert not hasattr(app, "breadcrumb")
    assert not hasattr(app, "page_heading")

    expected_titles = {
        "engine": "Engine Definition",
        "chamber": "Thrust Chamber",
        "thermal_input": "Thermal Analysis",
        "size_result": "Thrust Chamber Size",
        "thermal_result": "Thermal Analysis",
        "thermo_result": "Thermodynamics",
        "throttle_result": "Throttled Performance",
        "ambient_result": "Ambient Condition Performance",
    }
    for key, title in expected_titles.items():
        app.show_page(key)
        assert app.title() == APP_TITLE
        assert app.context_title.cget("text") == title
        description = str(app.context_description.cget("text")).strip()
        if key in {"engine", "chamber", "thermal_input"}:
            assert description == ""
            assert not app.context_description.winfo_manager()
        else:
            assert description
            assert app.context_description.winfo_manager() == "pack"
        assert not any(str(label.cget("style")) == "Title.TLabel" for label in _labels(app.pages[key]))


def test_segment_dialogs_scroll_without_clipping_at_minimum_size(app: LPAApplication) -> None:
    clipped: list[tuple[str, str, int, int]] = []
    for kind in ("Regen", "Film", "Radiation"):
        dialog = SegmentDialog(app, default_segment(kind, 1), [])
        try:
            dialog.geometry("680x620+0+0")
            dialog.update()
            for label in _labels(dialog):
                text = str(label.cget("text"))
                if label.winfo_ismapped() and text and label.winfo_width() + 2 < label.winfo_reqwidth():
                    clipped.append((kind, text, label.winfo_width(), label.winfo_reqwidth()))
            scrolls = [child for child in _walk(dialog) if isinstance(child, ScrollableFrame)]
            assert len(scrolls) == 1
            assert scrolls[0].canvas.yview()[1] < 1.0
            scrolls[0].canvas.yview_moveto(1.0)
            dialog.update_idletasks()
            assert scrolls[0].canvas.yview()[0] > 0.0
        finally:
            if dialog.winfo_exists():
                dialog.destroy()
            app.update()
    assert clipped == []


def test_film_dialog_rejects_invalid_specified_position(app: LPAApplication) -> None:
    dialog = SegmentDialog(app, default_segment("Film", 1), [])
    try:
        dialog.vars["position_mode"].set("Specified location")
        dialog.vars["position_mm"].set("not-a-position")
        dialog._save()

        assert dialog.winfo_exists()
        assert dialog.result is None
        assert "non-negative number" in str(dialog.error.cget("text"))

        dialog.vars["position_mm"].set("25.5")
        dialog._save()
        assert not dialog.winfo_exists()
        assert dialog.result is not None
        assert dialog.result["position_mm"] == "25.5"
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_linked_film_coolant_updates_and_restores_manual_selection(app: LPAApplication) -> None:
    thermal_page = app.pages["thermal_input"]
    app.pages["engine"].variables["fuel"].set("RP-1")
    root = default_segment("Regen", 1)
    root.update({"id": "root", "name": "Root", "coolant_source_mode": "Engine fuel"})
    linked = default_segment("Regen", 2)
    linked.update(
        {
            "id": "linked",
            "name": "Linked",
            "coolant_source_mode": "Receive from Regen segment",
            "coolant_definition_mode": "Receive from Regen segment",
            "coolant_source_id": "root",
        }
    )
    thermal_page.segments = [root, linked]
    film = default_segment("Film", 3)
    film.update({"coolant": "GOX", "manual_coolant": "GOX"})
    dialog = SegmentDialog(thermal_page, film, thermal_page._regen_options())
    try:
        dialog.vars["temperature_mode"].set("Temperature from Regen segment")
        dialog.linked_regen_label.set("Linked")
        dialog.update_idletasks()
        assert dialog.vars["coolant"].get() == "RP-1"
        assert dialog.film_coolant_combo.instate(["disabled"])

        dialog.vars["temperature_mode"].set("Specified temperature")
        assert dialog.vars["coolant"].get() == "GOX"
        dialog.vars["coolant"].set("LCH4")
        dialog._remember_manual_film_coolant()

        dialog.vars["temperature_mode"].set("Temperature from Regen segment")
        dialog._save()
        assert dialog.result is not None
        assert dialog.result["coolant"] == "RP-1"
        assert dialog.result["manual_coolant"] == "LCH4"
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_film_dialog_offers_and_persists_injector_face(app: LPAApplication) -> None:
    dialog = SegmentDialog(app, default_segment("Film", 1), [])
    try:
        dialog.update()
        position_boxes = [
            widget
            for widget in _walk(dialog)
            if isinstance(widget, ttk.Combobox)
            and "Injector Face" in tuple(widget.cget("values"))
        ]
        assert len(position_boxes) == 1

        dialog.vars["position_mm"].set("37.5")
        dialog.vars["position_mode"].set("Injector Face")
        dialog.update_idletasks()

        assert dialog.position_entry.instate(["disabled"])
        assert dialog.vars["position_mm"].get() == "0"
        dialog._save()

        assert dialog.result is not None
        assert dialog.result["position_mode"] == "Injector Face"
        assert dialog.result["position_mm"] == "0"
        assert input_views.segment_location_text(dialog.result) == "Injector Face (0 mm)"
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_default_thermal_off_analysis_and_every_result_page_render(app: LPAApplication) -> None:
    project = app.collect_project()
    assert validate_project(project) == []
    assert project["thermal"]["thermal_enabled"] is False

    result = AnalysisService().analyze(project)
    assert result["thermal_enabled"] is False
    assert result["thermal"] == {"resolution": "Medium", "section_count": 0}
    assert len(result["contour"]["x_mm"]) == 300
    assert len(result["contour"]["radius_mm"]) == 300
    assert set(result["thermodynamics"]["stations"]) == {
        "injector",
        "nozzle_inlet",
        "nozzle_throat",
        "nozzle_exit",
    }
    assert math.isfinite(result["performance"]["with_film"]["vacuum_isp_s"])

    for key in (
        "size_result",
        "thermal_result",
        "thermo_result",
        "throttle_result",
        "ambient_result",
    ):
        app.pages[key].set_result(result)
        app.show_page(key)
        app.update_idletasks()
        assert app.pages[key].data is result

    size_page = app.pages["size_result"]
    frame_texts = _labelframe_texts(size_page)
    assert any("Performance" in text for text in frame_texts)
    assert any("Rao contour geometry reference" in text for text in frame_texts)
    assert size_page.film_blc_var.get() is False
    assert size_page.rao_reference_image is not None
    assert not any("including film cooling" in text for text in frame_texts)
    assert not any("ignoring film cooling" in text for text in frame_texts)

    size_cards = [
        child
        for child in _walk(size_page)
        if isinstance(child, ttk.LabelFrame)
    ]
    performance_card = next(
        child for child in size_cards if "Performance" in str(child.cget("text"))
    )
    mass_flow_card = next(
        child for child in size_cards if "Mass flow rates" in str(child.cget("text"))
    )
    geometry_card = next(
        child for child in size_cards if "Chamber & Rao geometry" in str(child.cget("text"))
    )
    assert performance_card.master is mass_flow_card.master
    assert performance_card.winfo_manager() == "grid"
    assert mass_flow_card.winfo_manager() == "grid"
    assert performance_card.grid_info()["row"] == mass_flow_card.grid_info()["row"]
    assert performance_card.grid_info()["column"] != mass_flow_card.grid_info()["column"]
    performance_labels = _label_texts(performance_card)
    assert "Chamber pressure" in performance_labels
    assert "Nozzle exit pressure" in performance_labels
    assert "Gas residence time" in performance_labels
    assert "Gas residence time" not in _label_texts(geometry_card)
    expected_geometry_labels = [
        "Chamber radius Rc",
        "Throat radius Rt",
        "Exit radius Re",
        "Cylindrical length Lcyl",
        "Chamber length Lc",
        "Nozzle length Le",
        "Upstream throat radius R1",
        "Chamber blend radius R2",
        "Nozzle throat radius Rn",
        "Contraction angle b",
        "Rao start angle Tn",
        "Rao exit angle Te",
        "Contraction area ratio Ac/At",
        "Expansion area ratio Ae/At",
        "Characteristic length L*",
    ]
    geometry_labels = [
        text for text in _label_texts(geometry_card) if text in expected_geometry_labels
    ]
    assert geometry_labels == expected_geometry_labels

    thermal_page = app.pages["thermal_result"]
    assert any("Thermal analysis was disabled" in text for text in _label_texts(thermal_page))

    thermo_page = app.pages["thermo_result"]
    app.show_page("thermo_result")
    app.update_idletasks()
    assert thermo_page.scroll._scrollable is True
    assert thermo_page.plot_frame.winfo_height() >= 400
    station_tables = [tree for tree in _treeviews(thermo_page) if tree.cget("height") == 13]
    assert len(station_tables) == 1
    station_table = station_tables[0]
    assert not any(isinstance(child, ttk.Scrollbar) and str(child.cget("orient")) == "vertical"
                   for child in station_table.master.winfo_children())
    assert len(station_table.get_children()) == 13
    for item in station_table.get_children():
        values = station_table.item(item, "values")
        assert len(values) == 6
        assert all(value != "—" for value in values[2:])

    throttle_page = app.pages["throttle_result"]
    assert any("Throttle analysis was not selected" in text for text in _label_texts(throttle_page))

    ambient_page = app.pages["ambient_result"]
    assert any("Ambient-condition analysis was not selected" in text for text in _label_texts(ambient_page))

    app.clear_results()
    for key in (
        "size_result",
        "thermal_result",
        "thermo_result",
        "throttle_result",
        "ambient_result",
    ):
        assert app.pages[key].data is None
        assert app.pages[key].empty.winfo_manager() == "pack"


def test_mass_flow_card_lists_external_regen_coolant_below_propellants(
    app: LPAApplication,
) -> None:
    page = app.pages["size_result"]
    result = AnalysisService().analyze(app.collect_project())
    result["performance"]["mass_flow"]["external_regen_coolants"] = [
        {
            "segment_name": "Water circuit",
            "coolant": "H2O",
            "kg_s": 1.25,
        }
    ]
    page.set_result(result)
    app.update_idletasks()

    mass_flow_card = next(
        child
        for child in _walk(page)
        if isinstance(child, ttk.LabelFrame)
        and "Mass flow rates" in str(child.cget("text"))
    )
    labels = _label_texts(mass_flow_card)
    assert labels.index("H2O coolant (Water circuit)") > labels.index("Fuel")


def test_ambient_condition_result_separates_pressure_and_standard_altitude(
    app: LPAApplication,
) -> None:
    project = app.collect_project()
    project["thrust_chamber"].update(
        {
            "throttle_enabled": False,
            "ambient_enabled": True,
            "ambient_mode": "Ambient pressure range",
            "ambient_min_atm": "0.05",
            "ambient_max_atm": "1.0",
            "ambient_points": "5",
        }
    )
    result = AnalysisService().analyze(project)
    assert result["throttle"] == []
    assert result["ambient"]["model"] == "U.S. Standard Atmosphere 1976"
    assert len(result["ambient"]["pressure_rows"]) == 5
    assert len(result["ambient"]["altitude_rows"]) == 5
    assert result["ambient"]["altitude_rows"][0]["standard_altitude_km"] == pytest.approx(0.0)
    assert result["ambient"]["altitude_rows"][0]["ambient_pressure_atm"] == pytest.approx(1.0)
    assert result["ambient"]["altitude_rows"][-1]["ambient_pressure_atm"] == pytest.approx(0.05)

    page = app.pages["ambient_result"]
    page.set_result(result)
    app.show_page("ambient_result")
    app.update_idletasks()
    tables = _treeviews(page)
    assert len(tables) == 2
    assert all(len(table.get_children()) == 5 for table in tables)


def test_thermal_contour_uses_visible_upper_half_at_true_scale(app: LPAApplication) -> None:
    page = app.pages["thermal_result"]
    page.set_result(
        {
            "thermal_enabled": True,
            "thermal": {
                "resolution": "Low",
                "section_count": 4,
                "iterations": 2,
                "converged": True,
                "x_mm": [0.0, 100.0, 200.0, 300.0],
                "twg_k": [700.0, 850.0, 900.0, 750.0],
                "twi_k": [680.0, 820.0, 870.0, 720.0],
                "twc_k": [500.0, 560.0, 580.0, 520.0],
                "tc_k": [290.0, 310.0, 330.0, 350.0],
                "active_segment_id": ["regen-1"] * 4,
                "segment_types": {"regen-1": "Regen"},
                "segment_names": {"regen-1": "Regen 1"},
                "radius_mm": [25.0, 25.0, 9.0, 21.0],
            },
            "contour": {
                "x_mm": [0.0, 100.0, 200.0, 300.0],
                "radius_mm": [25.0, 25.0, 9.0, 21.0],
            },
        }
    )
    app.update_idletasks()

    assert page.contour_axis is not None
    assert page.panel is not None
    page.panel.canvas.draw()
    temperature_ylim = page.axis.get_ylim()
    assert temperature_ylim[0] == pytest.approx(0.0)
    assert temperature_ylim[1] > 900.0
    assert float(page.contour_axis.get_aspect()) == pytest.approx(1.0)
    assert page.contour_axis.get_ylim()[0] >= 0.0
    assert page.axis.get_position().bounds == pytest.approx(page.contour_axis.get_position().bounds)
    for axial_location in (0.0, 100.0, 200.0, 300.0):
        temperature_pixel = page.axis.transData.transform((axial_location, 0.0))[0]
        contour_pixel = page.contour_axis.transData.transform((axial_location, 0.0))[0]
        assert contour_pixel == pytest.approx(temperature_pixel)
    x_pixels_per_mm = abs(
        page.contour_axis.transData.transform((1.0, 0.0))[0]
        - page.contour_axis.transData.transform((0.0, 0.0))[0]
    )
    y_pixels_per_mm = abs(
        page.contour_axis.transData.transform((0.0, 1.0))[1]
        - page.contour_axis.transData.transform((0.0, 0.0))[1]
    )
    assert y_pixels_per_mm == pytest.approx(x_pixels_per_mm)
    for line in page.contour_axis.lines:
        assert min(float(value) for value in line.get_ydata()) >= 0.0
    lowest_temperature = min(
        float(value)
        for line in page.axis.lines
        for value in line.get_ydata()
        if math.isfinite(float(value))
    )
    highest_radius = max(
        float(value)
        for line in page.contour_axis.lines
        for value in line.get_ydata()
        if math.isfinite(float(value))
    )
    assert page.axis.transData.transform((0.0, lowest_temperature))[1] > page.contour_axis.transData.transform(
        (0.0, highest_radius)
    )[1]


def test_thermal_regen_summary_includes_pressure_columns(app: LPAApplication) -> None:
    page = app.pages["thermal_result"]
    count = 35
    page.set_result(
        {
            "thermal_enabled": True,
            "thermal": {
                "resolution": "Low",
                "section_count": count,
                "iterations": 2,
                "converged": True,
                "x_mm": [float(index) for index in range(count)],
                "twg_k": [700.0 + index for index in range(count)],
                "twi_k": [680.0 + index for index in range(count)],
                "twc_k": [500.0 + index for index in range(count)],
                "tc_k": [290.0 + index for index in range(count)],
                "heat_flux_w_m2": [1.0e6 + 1000.0 * index for index in range(count)],
                "coolant_pressure_bar": [30.0 - 0.01 * index for index in range(count)],
                "coolant_velocity_m_s": [4.0 + 0.1 * index for index in range(count)],
                "coolant_density_kg_m3": [800.0 - index for index in range(count)],
                "active_segment_id": ["regen-1"] * count,
                "segment_types": {"regen-1": "Regen"},
                "segment_names": {"regen-1": "Regen 1"},
                "segment_coolants": {"regen-1": "LOX"},
                "coolant_inlet_temperature_k": {"regen-1": 290.0},
                "coolant_outlet_temperature_k": {"regen-1": 340.0},
                "coolant_inlet_pressure_bar": {"regen-1": 30.0},
                "coolant_outlet_pressure_bar": {"regen-1": 28.75},
                "coolant_pressure_drop_bar": {"regen-1": 1.25},
                "metadata": {
                    "angle_channel_geometry_by_segment": {
                        "regen-1": {
                            "channel_width_mm": (1.2, 0.8, 1.5),
                            "rib_width_mm": (0.7, 0.5, 0.9),
                        }
                    }
                },
            },
        }
    )
    app.update_idletasks()

    assert page.circuit_tree is not None
    assert sum(
        int(page.circuit_tree.column(column, "width"))
        for column in page.circuit_tree.cget("columns")
    ) <= page.circuit_tree.winfo_width()
    assert tuple(page.circuit_tree.cget("columns")) == (
        "Segment",
        "Coolant / propellant",
        "Inlet temperature",
        "Outlet temperature",
        "Temperature rise",
        "Inlet pressure",
        "Outlet pressure",
        "Pressure drop",
    )
    row = page.circuit_tree.item(page.circuit_tree.get_children()[0], "values")
    assert row == (
        "Regen 1",
        "LOX",
        "290.00 K",
        "340.00 K",
        "+50.00 K",
        "30.000 bar",
        "28.750 bar",
        "1.250 bar",
    )
    assert page.smooth.get() is False
    assert page.channel_geometry_tree is not None
    channel_row = page.channel_geometry_tree.item(
        page.channel_geometry_tree.get_children()[0], "values"
    )
    assert channel_row == ("Regen 1", "1.2000", "0.8000", "1.5000", "0.7000", "0.5000", "0.9000")
    assert page.axial_tree is not None
    assert tuple(page.axial_tree.cget("columns")) == (
        "x", "q", "Twg", "Twi", "Twc", "Tc", "pc", "wc", "rho", "Re", "Nu", "hc_raw",
        "glide", "F_TS", "F_BG", "wet_wall",
        "applicability", "phase", "quality", "regime"
    )
    assert len(page.axial_tree.get_children()) == 30
    first = page.axial_tree.item(page.axial_tree.get_children()[0], "values")
    last = page.axial_tree.item(page.axial_tree.get_children()[-1], "values")
    assert first == ("0.000", "1.0000", "700.00", "680.00", "500.00", "290.00", "30.000", "4.000", "800.00",
                     "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—")
    assert last[0] == "34.000"
