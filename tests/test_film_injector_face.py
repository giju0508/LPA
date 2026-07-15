from __future__ import annotations

import pytest

from lpa.analysis import _normalised_segment
from lpa.core import (
    AnalysisInput,
    FilmSegment,
    ThermalAnalysisInput,
    analysis_input_from_dict,
    analysis_input_to_dict,
)
from lpa.project import load_project, make_project, save_project
from lpa.thermal.validation import film_injection_x
from lpa.ui.input_views import default_segment


def test_injector_face_ui_project_cfg_round_trip(tmp_path) -> None:
    film = default_segment("Film", 1)
    film.update(position_mode="Injector Face", position_mm="0")
    project = make_project({}, {}, {"segments": [film]})
    target = save_project(tmp_path / "injector-face.cfg", project)

    restored = load_project(target)["thermal"]["segments"][0]
    assert restored["position_mode"] == "Injector Face"
    assert restored["position_mm"] == "0"


def test_injector_face_normalises_to_an_explicit_core_mode() -> None:
    film = default_segment("Film", 1)
    film.update(position_mode="Injector Face", position_mm="91")
    normalised = _normalised_segment(film)

    assert normalised["injector_face"] is True
    assert normalised["chamber_contraction_boundary"] is False
    assert normalised["injection_location_mm"] is None

    boundary = _normalised_segment(
        {**film, "position_mode": "Chamber/convergent boundary"}
    )
    specified = _normalised_segment(
        {**film, "position_mode": "Specified location", "position_mm": "12.5"}
    )
    assert boundary["chamber_contraction_boundary"] is True
    assert boundary["injector_face"] is False
    assert specified["injection_location_mm"] == pytest.approx(12.5)
    assert specified["injector_face"] is False


def test_injector_face_core_round_trip_and_contour_resolution() -> None:
    film = FilmSegment(
        segment_id="film-face",
        coolant="RP-1",
        coolant_temperature_k=290.0,
        relative_mass_flow_percent=3.0,
        injector_face=True,
    )
    inputs = AnalysisInput(
        thermal=ThermalAnalysisInput(enabled=True, resolution="low", segments=[film])
    )
    payload = analysis_input_to_dict(inputs)
    raw = payload["thermal"]["segments"][0]
    assert raw["injector_face"] is True
    assert raw["injection_location_mm"] is None

    rebuilt = analysis_input_from_dict(payload)
    restored = rebuilt.thermal.segments[0]
    assert isinstance(restored, FilmSegment)
    assert restored.injector_face is True
    assert film_injection_x(restored, {"x_m": (0.125, 0.2, 0.4)}) == pytest.approx(
        0.125
    )

    with pytest.raises(ValueError, match="exactly one"):
        FilmSegment(
            segment_id="ambiguous",
            coolant="RP-1",
            coolant_temperature_k=290.0,
            relative_mass_flow_percent=3.0,
            injector_face=True,
            injection_location_mm=0.0,
        )
