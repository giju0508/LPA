"""Project-dictionary adapters used by GUI forms and JSON project files."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Mapping

from .models import (
    AmbientConditions,
    AnalysisInput,
    ChamberLength,
    ChannelTriplet,
    CoolantDefinition,
    EngineDefinition,
    EquilibriumFlow,
    FilmSegment,
    NozzleEfficiency,
    NozzleExitCondition,
    NozzleGeometry,
    RadiationSegment,
    RangeSpec,
    RegenSegment,
    SegmentRange,
    ThermalAnalysisInput,
    ThermalBarrierCoating,
    ThrottleSettings,
    ThrustChamberInput,
    ThrustChamberSize,
)


def _mapping(value: object | None, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return dict(value)


def _range_settings(data: dict[str, Any], cls: type) -> object:
    if isinstance(data.get("range"), Mapping):
        data["range"] = RangeSpec(**dict(data["range"]))
    return cls(**data)


def _coating(value: object | None) -> ThermalBarrierCoating | None:
    if value is None or isinstance(value, ThermalBarrierCoating):
        return value
    return ThermalBarrierCoating(**_mapping(value, "coating"))


def _triplet(value: object | None, field_name: str) -> ChannelTriplet | None:
    if value is None or isinstance(value, ChannelTriplet):
        return value
    return ChannelTriplet(**_mapping(value, field_name))


def _segment(value: object) -> RegenSegment | FilmSegment | RadiationSegment:
    if isinstance(value, (RegenSegment, FilmSegment, RadiationSegment)):
        return value
    data = _mapping(value, "thermal segment")
    kind = str(data.pop("type", data.pop("kind", ""))).strip().casefold()
    if not kind:
        if "channel_height_mm" in data:
            kind = "regen"
        elif "relative_mass_flow_percent" in data and "location" not in data:
            kind = "film"
        elif "emissivity" in data:
            kind = "radiation"
    if kind in {"regen", "regenerative"}:
        if isinstance(data.get("location"), Mapping):
            data["location"] = SegmentRange(**dict(data["location"]))
        if isinstance(data.get("coolant"), Mapping):
            data["coolant"] = CoolantDefinition(**dict(data["coolant"]))
        data["channel_height_mm"] = _triplet(
            data.get("channel_height_mm"), "channel height"
        )
        if "widths_mm" in data:
            data["widths_mm"] = _triplet(data.get("widths_mm"), "channel widths")
        if "coating" in data:
            data["coating"] = _coating(data.get("coating"))
        return RegenSegment(**data)
    if kind == "film":
        return FilmSegment(**data)
    if kind in {"radiation", "radiative"}:
        if isinstance(data.get("location"), Mapping):
            data["location"] = SegmentRange(**dict(data["location"]))
        if "coating" in data:
            data["coating"] = _coating(data.get("coating"))
        return RadiationSegment(**data)
    raise ValueError("thermal segment requires type 'regen', 'film', or 'radiation'")


def analysis_input_from_dict(project: Mapping[str, Any]) -> AnalysisInput:
    """Build validated dataclasses from a JSON/GUI-shaped project mapping."""

    root = dict(project)
    engine_data = _mapping(root.get("engine"), "engine")
    engine = EngineDefinition(**engine_data)

    chamber_data = _mapping(
        root.get("thrust_chamber", root.get("chamber")), "thrust_chamber"
    )
    nested_types = {
        "exit_condition": NozzleExitCondition,
        "equilibrium": EquilibriumFlow,
        "nozzle_efficiency": NozzleEfficiency,
        "size": ThrustChamberSize,
        "length": ChamberLength,
        "nozzle": NozzleGeometry,
    }
    for key, cls in nested_types.items():
        if isinstance(chamber_data.get(key), Mapping):
            chamber_data[key] = cls(**dict(chamber_data[key]))
    if isinstance(chamber_data.get("throttle"), Mapping):
        chamber_data["throttle"] = _range_settings(
            dict(chamber_data["throttle"]), ThrottleSettings
        )
    if isinstance(chamber_data.get("ambient"), Mapping):
        chamber_data["ambient"] = _range_settings(
            dict(chamber_data["ambient"]), AmbientConditions
        )
    chamber = ThrustChamberInput(**chamber_data)

    thermal_data = _mapping(root.get("thermal"), "thermal")
    if "segments" in thermal_data:
        if not isinstance(thermal_data["segments"], (list, tuple)):
            raise TypeError("thermal segments must be a list")
        thermal_data["segments"] = [_segment(item) for item in thermal_data["segments"]]
    thermal = ThermalAnalysisInput(**thermal_data)
    return AnalysisInput(engine, chamber, thermal)


def analysis_input_to_dict(inputs: AnalysisInput) -> dict[str, Any]:
    """Return a JSON-serializable project mapping with segment discriminators."""

    def convert(value: object) -> object:
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            result = {
                item.name: convert(getattr(value, item.name)) for item in fields(value)
            }
            if isinstance(value, RegenSegment):
                result["type"] = "regen"
            elif isinstance(value, FilmSegment):
                result["type"] = "film"
            elif isinstance(value, RadiationSegment):
                result["type"] = "radiation"
            return result
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {str(key): convert(item) for key, item in value.items()}
        return value

    result = convert(inputs)
    if not isinstance(result, dict):
        raise TypeError("analysis input did not serialize to a mapping")
    result["schema_version"] = 1
    return result
