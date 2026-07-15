from __future__ import annotations

import json

import pytest

from lpa.core import (
    AnalysisInput,
    ChannelTriplet,
    Coolant,
    CoolantDefinition,
    EngineDefinition,
    FilmSegment,
    Fuel,
    OXIDIZERS,
    FUELS,
    Oxidizer,
    RadiationMaterial,
    RadiationSegment,
    RangeSpec,
    RegenMaterial,
    RegenSegment,
    Resolution,
    SegmentRange,
    ThermalAnalysisInput,
    analysis_input_from_dict,
    analysis_input_to_dict,
    registration_cards,
    validate_inputs,
)


def _regen(segment_id: str, start: float, end: float, *, inherit: str | None = None):
    return RegenSegment(
        segment_id=segment_id,
        location=SegmentRange(start, end),
        wall_thickness_mm=0.8,
        channel_height_mm=ChannelTriplet(1.0, 0.7, 1.2),
        channel_count=60,
        coolant=(
            None
            if inherit
            else CoolantDefinition(Coolant.RP1, 35.0, 290.0, 8.0)
        ),
        inherit_coolant_from=inherit,
        material=RegenMaterial.CUCRZR,
        widths_mm=ChannelTriplet(0.8, 0.5, 1.0),
    )


def test_default_models_and_string_enum_coercion():
    engine = EngineDefinition(oxidizer="lox", fuel="RP1")
    assert engine.oxidizer is Oxidizer.LOX
    assert engine.fuel is Fuel.RP1
    inputs = AnalysisInput(engine=engine)
    assert inputs.thrust_chamber.contraction_area_ratio == 4.0
    assert inputs.thermal.resolution is Resolution.MEDIUM
    assert inputs.thermal.section_count == 300


@pytest.mark.parametrize(
    "keyword,value",
    [
        ("chamber_pressure_bar", 0.0),
        ("mixture_ratio", -1.0),
        ("name", "   "),
    ],
)
def test_engine_validation_rejects_unsafe_values(keyword, value):
    with pytest.raises(ValueError):
        EngineDefinition(**{keyword: value})


def test_range_is_inclusive_and_validated():
    values = RangeSpec(10.0, 20.0, 3).values()
    assert values == (10.0, 15.0, 20.0)
    with pytest.raises(ValueError):
        RangeSpec(2.0, 1.0, 4)
    with pytest.raises(ValueError):
        RangeSpec(1.0, 2.0, 1)


def test_propellant_catalog_covers_every_ui_choice_and_blend_cards():
    assert set(OXIDIZERS) == set(Oxidizer)
    assert set(FUELS) == set(Fuel)
    cards = registration_cards(Oxidizer.H2O2_80, Fuel.ETHANOL_70)
    assert {record[0] for record in cards} == {"oxidizer", "fuel"}
    assert all("wt%" in record[2] for record in cards)


def test_segment_links_are_nonfatal_and_overlap_is_reported():
    linked = _regen("regen-2", 100.0, 200.0, inherit="deleted-regen")
    radiation = RadiationSegment(
        "rad-1",
        SegmentRange(150.0, 250.0),
        material=RadiationMaterial.C103,
    )
    thermal = ThermalAnalysisInput(True, "high", [linked, radiation])
    inputs = AnalysisInput(thermal=thermal)
    assert thermal.section_count == 700
    assert thermal.unresolved_links() == ("regen-2",)
    assert "unresolved" in validate_inputs(inputs)[0]
    assert "overlaps" in thermal.overlap_warnings(300.0)[0]


def test_top_bottom_locations_resolve_against_contour():
    location = SegmentRange("injector", "exit")
    assert location.resolved(412.0) == (0.0, 412.0)


def test_project_dictionary_round_trip_is_json_serializable():
    project = {
        "engine": {
            "name": "Round trip",
            "chamber_pressure_bar": 30,
            "mixture_ratio": 2.3,
            "oxidizer": "LOX",
            "fuel": "RP-1",
        },
        "thrust_chamber": {
            "throttle": {
                "enabled": True,
                "mode": "range",
                "range": {"minimum": 40, "maximum": 100, "points": 4},
            }
        },
        "thermal": {
            "enabled": True,
            "resolution": "low",
            "segments": [
                {
                    "type": "film",
                    "segment_id": "film-1",
                    "coolant": "RP-1",
                    "coolant_temperature_k": 290,
                    "relative_mass_flow_percent": 3,
                    "chamber_contraction_boundary": True,
                }
            ],
        },
    }
    inputs = analysis_input_from_dict(project)
    assert isinstance(inputs.thermal.segments[0], FilmSegment)
    exported = analysis_input_to_dict(inputs)
    json.dumps(exported)
    rebuilt = analysis_input_from_dict(exported)
    assert rebuilt.engine.name == "Round trip"
    assert rebuilt.thrust_chamber.throttle.range.values() == (40.0, 60.0, 80.0, 100.0)
    assert rebuilt.thermal.film_mass_fraction == pytest.approx(0.03)
