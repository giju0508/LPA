from __future__ import annotations

from types import SimpleNamespace

from lpa.analysis import (
    _effective_regen_coolant_name,
    _film_orifice_results,
    _normalised_segment,
)
from lpa.ui.input_views import default_segment, resolve_effective_regen_coolant


def _linked_segments() -> tuple[dict[str, object], list[dict[str, object]]]:
    root = default_segment("Regen", 1)
    root.update(
        {
            "id": "root",
            "coolant_source_mode": "Engine fuel",
            "coolant_inlet_pressure_bar": "50",
        }
    )
    linked = default_segment("Regen", 2)
    linked.update(
        {
            "id": "linked",
            "coolant_source_mode": "Receive from Regen segment",
            "coolant_definition_mode": "Receive from Regen segment",
            "coolant_source_id": "root",
        }
    )
    film = default_segment("Film", 3)
    film.update(
        {
            "id": "film",
            "coolant": "LOX",  # deliberately stale editor value
            "temperature_mode": "Temperature from Regen segment",
            "temperature_source_id": "linked",
            "orifice_enabled": True,
        }
    )
    return film, [root, linked, film]


def test_linked_film_resolves_root_regen_engine_coolant() -> None:
    film, segments = _linked_segments()
    engine = {"oxidizer": "LOX", "fuel": "RP-1", "mixture_ratio": "2.5"}

    assert resolve_effective_regen_coolant("linked", segments, engine) == "RP-1"
    assert _effective_regen_coolant_name("linked", segments, engine) == "RP-1"
    assert _normalised_segment(film, engine, segments)["coolant"] == "RP-1"


def test_film_orifice_uses_linked_regen_coolant_not_stale_film_value() -> None:
    _film, segments = _linked_segments()
    project = {
        "engine": {"oxidizer": "LOX", "fuel": "RP-1", "mixture_ratio": "2.5"},
        "thermal": {"segments": segments},
    }
    core_result = SimpleNamespace(
        contour=SimpleNamespace(x_m=(0.0, 0.1), chamber_end_index=0),
        performance=SimpleNamespace(chamber_pressure_bar=10.0, total_mass_flow_kg_s=1.0),
    )
    thermal_result = SimpleNamespace(
        x_m=(0.0, 0.1),
        Tc_K=(300.0, 320.0),
        active_segment_id=("linked", "linked"),
        coolant_outlet_temperature_k={"linked": 320.0},
        coolant_inlet_temperature_k={"linked": 300.0},
        coolant_outlet_pressure_bar={"linked": 40.0},
    )

    rows, warnings = _film_orifice_results(project, core_result, thermal_result)

    assert all("screening properties" in message for message in warnings)
    assert len(rows) == 1
    assert rows[0]["coolant"] == "RP-1"

