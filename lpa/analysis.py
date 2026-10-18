"""Integration layer between GUI-shaped projects and calculation modules."""

from __future__ import annotations

import importlib.util
import math
import copy
from dataclasses import asdict, fields, is_dataclass
from enum import Enum
from typing import Any

from .core import (
    ATM_PA, altitude_for_pressure, analyze_engine, standard_atmosphere,
    analysis_input_from_dict, optimize_mixture_ratio_for_inputs,
)
from .core.composition import engine_coolant_name, engine_selection


def _float(value: Any, default: float = 0.0) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Expected a finite number, got {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"Expected a finite number, got {value!r}")
    return number


def _optional_float(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _float(value)


def _int(value: Any, default: int = 0) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    number = _float(value)
    if isinstance(value, bool) or not number.is_integer():
        raise ValueError(f"Expected an integer, got {value!r}")
    return int(number)


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value))


def _jsonable(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _propellant(value: Any) -> str:
    text = str(value).strip()
    replacements = {
        "H2O2 70%": "H2O2 (70%)",
        "H2O2 80%": "H2O2 (80%)",
        "H2O2 90%": "H2O2 (90%)",
        "H2O2 100%": "H2O2 (100%)",
        "Ethanol 70%": "Ethanol (70%)",
        "Ethanol 80%": "Ethanol (80%)",
        "Ethanol 90%": "Ethanol (90%)",
        "Ethanol 100%": "Ethanol (100%)",
    }
    return replacements.get(text, text)


def _location(value: Any) -> float | str:
    text = str(value).strip()
    if text.casefold() in {"top", "injector", "start", "upstream"}:
        return "top"
    if text.casefold() in {"bottom", "exit", "end", "downstream"}:
        return "bottom"
    if text.casefold() in {
        "conv_boundary",
        "boundary",
        "contraction boundary",
        "convergent boundary",
    }:
        return "boundary"
    return float(text)


def _triplet(segment: dict[str, Any], prefix: str) -> dict[str, float]:
    return {
        "inlet": _float(segment.get(f"{prefix}_1_mm")),
        "minimum": _float(segment.get(f"{prefix}_min_mm")),
        "outlet": _float(segment.get(f"{prefix}_2_mm")),
    }


def _coating(segment: dict[str, Any]) -> dict[str, float] | None:
    if not segment.get("tbc_enabled"):
        return None
    return {
        "conductivity_w_mk": _float(segment.get("tbc_conductivity_w_mk"), 1.5),
        "thickness_mm": _float(segment.get("tbc_thickness_mm"), 0.01),
    }


def _effective_regen_coolant_name(
    regen_id: str,
    segments: list[dict[str, Any]],
    engine: dict[str, Any] | None = None,
) -> str | None:
    """Resolve a Regen coolant identity through linked circuit definitions."""

    by_id = {
        str(item.get("id", "")): item
        for item in segments
        if item.get("type") == "Regen"
    }
    current = by_id.get(str(regen_id))
    visited: set[str] = set()
    while current is not None:
        identifier = str(current.get("id", ""))
        if not identifier or identifier in visited:
            return None
        visited.add(identifier)
        source_mode = str(
            current.get(
                "coolant_source_mode",
                "Receive from Regen segment"
                if current.get("coolant_definition_mode") == "Receive from Regen segment"
                else "Custom coolant",
            )
        )
        if source_mode == "Receive from Regen segment":
            current = by_id.get(str(current.get("coolant_source_id", "")))
            continue
        if source_mode == "Engine oxidizer":
            value = engine_coolant_name(engine or {}, "oxidizer")
        elif source_mode == "Engine fuel":
            value = engine_coolant_name(engine or {}, "fuel")
        else:
            value = current.get("coolant")
        text = str(value or "").strip()
        return text or None
    return None


def _normalised_segment(
    segment: dict[str, Any],
    engine: dict[str, Any] | None = None,
    segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert one UI cooling segment to the calculation-layer naming scheme."""

    kind = str(segment.get("type", "")).strip().casefold()
    segment_id = str(segment.get("id", segment.get("segment_id", segment.get("name", kind)))).strip()
    if kind == "regen":
        material_mode = segment.get("conductivity_mode") == "Material"
        width_label = str(segment.get("channel_width_mode", "Channel width"))
        width_mode = {
            "Channel width": "channel_width",
            "Rib width": "rib_width",
            "Channel occupied angle": "channel_angle",
        }.get(width_label, "channel_width")
        source_mode = str(
            segment.get(
                "coolant_source_mode",
                "Receive from Regen segment"
                if segment.get("coolant_definition_mode") == "Receive from Regen segment"
                else "Custom coolant",
            )
        )
        define_coolant = source_mode != "Receive from Regen segment"
        coolant = None
        inherited = None
        if define_coolant:
            mixture_ratio = max(1.0e-12, _float((engine or {}).get("mixture_ratio"), 1.0))
            # Engine O/F describes the hot propellant streams. Film is an
            # additional stream in PerformanceResult.total_mass_flow_kg_s.
            film_fraction = sum(
                _float(item.get("relative_mass_flow_pct")) / 100.0
                for item in (segments or [])
                if str(item.get("type", "")).casefold() == "film"
            )
            hot_fraction = 1.0 - film_fraction
            coolant_name = segment.get("coolant", "H2O")
            relative_flow = _float(segment.get("relative_mass_flow_pct")) if source_mode == "Custom coolant" else 0.0
            if source_mode == "Engine oxidizer" and engine is not None:
                coolant_name = engine_coolant_name(engine, "oxidizer")
                relative_flow = 100.0 * hot_fraction * mixture_ratio / (1.0 + mixture_ratio)
            elif source_mode == "Engine fuel" and engine is not None:
                coolant_name = engine_coolant_name(engine, "fuel")
                relative_flow = 100.0 * hot_fraction / (1.0 + mixture_ratio)
            coolant = {
                "coolant": _propellant(coolant_name),
                "inlet_pressure_bar": _float(segment.get("coolant_inlet_pressure_bar")),
                "inlet_temperature_k": _float(segment.get("coolant_inlet_temperature_k")),
                "relative_mass_flow_percent": relative_flow,
            }
        else:
            inherited = str(segment.get("coolant_source_id", "")).strip() or None
        result: dict[str, Any] = {
            "type": "regen",
            "segment_id": segment_id,
            "name": segment.get("name", segment_id),
            "location": {"start": _location(segment.get("x1", "top")), "end": _location(segment.get("x2", "bottom"))},
            "wall_thickness_mm": _float(segment.get("wall_thickness_mm")),
            "channel_height_mm": _triplet(segment, "channel_height"),
            "channel_count": _int(segment.get("channel_count")),
            "coolant": coolant,
            "inherit_coolant_from": inherited,
            "wall_conductivity_w_mk": None if material_mode else _float(segment.get("thermal_conductivity")),
            "material": str(segment.get("material")) if material_mode else None,
            "width_mode": width_mode,
            "widths_mm": None,
            "channel_angle_deg": None,
            "wall_roughness_enabled": bool(segment.get("roughness_enabled")),
            "roughness_height_mm": _float(segment.get("roughness_height_mm"), 0.04) if segment.get("roughness_enabled") else 0.04,
            "roughness_step_mm": _float(segment.get("roughness_step_mm"), 0.10) if segment.get("roughness_enabled") else 0.10,
            "coflow": bool(segment.get("reverse_coolant_flow")),
            "coating": _coating(segment),
        }
        if width_mode == "channel_width":
            result["widths_mm"] = _triplet(segment, "channel_width")
        elif width_mode == "rib_width":
            result["widths_mm"] = _triplet(segment, "rib_width")
        else:
            result["channel_angle_deg"] = _float(segment.get("channel_angle_deg"))
        return result
    if kind == "film":
        position_mode = str(segment.get("position_mode", "Specified location")).strip()
        boundary = position_mode == "Chamber/convergent boundary"
        injector_face = position_mode == "Injector Face"
        linked = segment.get("temperature_mode") == "Temperature from Regen segment"
        coolant_name = segment.get("coolant", "H2O")
        if linked and segments is not None:
            coolant_name = _effective_regen_coolant_name(
                str(segment.get("temperature_source_id", "")), segments, engine
            ) or coolant_name
        return {
            "type": "film",
            "segment_id": segment_id,
            "name": segment.get("name", segment_id),
            "coolant": _propellant(coolant_name),
            "coolant_temperature_k": None if linked else _float(segment.get("coolant_temperature_k")),
            "relative_mass_flow_percent": _float(segment.get("relative_mass_flow_pct")),
            "injection_location_mm": (
                None if boundary or injector_face else _float(segment.get("position_mm"))
            ),
            "chamber_contraction_boundary": boundary,
            "injector_face": injector_face,
            "inherit_temperature_from_regen": str(segment.get("temperature_source_id", "")).strip() or None if linked else None,
            "discharge_coefficient": _float(segment.get("discharge_coefficient"), 0.6) if segment.get("orifice_enabled") else 0.6,
            "orifice_count": _int(segment.get("orifice_count"), 30) if segment.get("orifice_enabled") else 30,
            "orifice_enabled": bool(segment.get("orifice_enabled")),
        }
    if kind == "radiation":
        material_mode = segment.get("conductivity_mode") == "Material"
        return {
            "type": "radiation",
            "segment_id": segment_id,
            "name": segment.get("name", segment_id),
            "location": {"start": _location(segment.get("x1", "top")), "end": _location(segment.get("x2", "bottom"))},
            "wall_thickness_mm": _float(segment.get("wall_thickness_mm"), 1.0),
            "emissivity": _float(segment.get("emissivity"), 0.8),
            "wall_conductivity_w_mk": None if material_mode else _float(segment.get("thermal_conductivity")),
            "material": str(segment.get("material")) if material_mode else None,
            "coating": _coating(segment),
        }
    raise ValueError(f"Unsupported thermal segment type: {segment.get('type')!r}")


def _core_segment(
    segment: dict[str, Any],
    engine: dict[str, Any] | None = None,
    segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = _normalised_segment(segment, engine, segments)
    # Core dataclasses are intentionally narrower than the thermal solver's
    # loose dictionary contract. Remove GUI/report-only values before parsing.
    result.pop("name", None)
    result.pop("orifice_enabled", None)
    if result["type"] == "radiation":
        result.pop("wall_thickness_mm", None)
    return result


def _core_project(project: dict[str, Any]) -> dict[str, Any]:
    engine = project["engine"]
    oxidizer, oxidizer_fraction = engine_selection(engine, "oxidizer")
    fuel, fuel_fraction = engine_selection(engine, "fuel")
    chamber = project["thrust_chamber"]
    thermal = project["thermal"]
    exit_area = chamber.get("exit_condition_mode") == "Expansion area ratio"
    flow_label = str(chamber.get("flow_model", "Shifting equilibrium"))
    flow_mode = {
        "Shifting equilibrium": "shifting_equilibrium",
        "Freezing at pressure ratio": "freezing_at_pressure_ratio",
        "Freezing at area ratio": "freezing_at_area_ratio",
        "Frozen at chamber": "freezing_at_pressure_ratio",
        "Frozen at throat": "freezing_at_area_ratio",
    }.get(flow_label, "shifting_equilibrium")
    size_thrust = chamber.get("sizing_mode") == "Engine nominal thrust"
    thrust_n = _float(chamber.get("nominal_thrust")) if size_thrust else 0.0
    if chamber.get("thrust_unit") == "kN":
        thrust_n *= 1000.0
    throttle_range = chamber.get("throttle_mode") == "Throttle values range"
    ambient_range = chamber.get("ambient_mode") == "Ambient pressure range"
    throttle_enabled = bool(chamber.get("throttle_enabled"))
    ambient_enabled = bool(chamber.get("ambient_enabled"))
    direct_chamber_diameter = chamber.get("contraction_mode") == "Chamber diameter (Dc)"
    direct_length = chamber.get("chamber_length_mode") == "Direct Lc and Lcyl"
    bell = chamber.get("nozzle_type") == "Parabolic contour (Rao)"
    return {
        "engine": {
            "name": str(engine.get("engine_name", "Untitled engine")),
            "description": str(engine.get("description", "")),
            "chamber_pressure_bar": _float(engine.get("chamber_pressure_bar")),
            "mixture_ratio": _float(engine.get("mixture_ratio")),
            "oxidizer": oxidizer,
            "fuel": fuel,
            "oxidizer_mass_fraction": oxidizer_fraction,
            "fuel_mass_fraction": fuel_fraction,
            "oxidizer_temperature_k": _optional_float(engine.get("oxidizer_temperature_k")),
            "fuel_temperature_k": _optional_float(engine.get("fuel_temperature_k")),
            "oxidizer_pressure_bar": _optional_float(engine.get("oxidizer_pressure_bar")),
            "fuel_pressure_bar": _optional_float(engine.get("fuel_pressure_bar")),
        },
        "thrust_chamber": {
            "contraction_mode": "chamber_diameter" if direct_chamber_diameter else "area_ratio",
            "contraction_area_ratio": 4.0 if direct_chamber_diameter else _float(chamber.get("contraction_area_ratio")),
            "chamber_diameter_mm": (
                _float(chamber.get("chamber_diameter_mm"))
                if direct_chamber_diameter
                else None
            ),
            "exit_condition": {
                "mode": "expansion_ratio" if exit_area else "ambient_pressure",
                "expansion_area_ratio": _float(chamber.get("exit_condition_value")) if exit_area else None,
                "ambient_pressure_atm": None if exit_area else _float(chamber.get("exit_condition_value")),
            },
            "equilibrium": {
                "mode": flow_mode,
                "freeze_pressure_ratio": (10.0 if flow_label == "Frozen at chamber" else _float(chamber.get("freeze_value"))) if flow_mode == "freezing_at_pressure_ratio" else None,
                "freeze_area_ratio": (1.0 if flow_label == "Frozen at throat" else _float(chamber.get("freeze_value"))) if flow_mode == "freezing_at_area_ratio" else None,
            },
            "reaction_efficiency_percent": _float(chamber.get("reaction_efficiency_pct")),
            "nozzle_efficiency": {
                "mode": "estimate" if chamber.get("nozzle_efficiency_mode") == "Estimate" else "direct",
                "value_percent": None if chamber.get("nozzle_efficiency_mode") == "Estimate" else _float(chamber.get("nozzle_efficiency_pct")),
            },
            "throttle": {
                "enabled": throttle_enabled,
                "mode": "range" if throttle_range else "fixed",
                "fixed_percent": _float(chamber.get("throttle_fixed_pct")) if throttle_enabled and not throttle_range else 100.0,
                "range": {
                    "minimum": _float(chamber.get("throttle_min_pct")),
                    "maximum": _float(chamber.get("throttle_max_pct")),
                    "points": _int(chamber.get("throttle_points")),
                } if throttle_range and throttle_enabled else None,
            },
            "ambient": {
                "enabled": ambient_enabled,
                "mode": "range" if ambient_range else "fixed",
                "fixed_pressure_atm": _float(chamber.get("ambient_fixed_atm")) if ambient_enabled and not ambient_range else 1.0,
                "range": {
                    "minimum": _float(chamber.get("ambient_min_atm")),
                    "maximum": _float(chamber.get("ambient_max_atm")),
                    "points": _int(chamber.get("ambient_points")),
                } if ambient_range and ambient_enabled else None,
            },
            "size": {
                "mode": "nominal_thrust" if size_thrust else "throat_diameter",
                "nominal_thrust_n": thrust_n if size_thrust else None,
                "thrust_ambient_pressure_atm": _float(chamber.get("nominal_thrust_ambient_atm")) if size_thrust else 1.0,
                "throat_diameter_mm": None if size_thrust else _float(chamber.get("throat_diameter_mm")),
            },
            "length": {
                "mode": "direct" if direct_length else "characteristic_length",
                "chamber_length_mm": _float(chamber.get("chamber_length_mm")) if direct_length else None,
                "cylindrical_length_mm": _float(chamber.get("cylindrical_length_mm")) if direct_length else None,
                "characteristic_length_mm": None if direct_length else _float(chamber.get("characteristic_length_mm")),
            },
            "contraction_angle_deg": _float(chamber.get("contraction_angle_deg")),
            "chamber_radius_ratio": _float(chamber.get("r2_ratio")),
            "throat_upstream_radius_ratio": _float(chamber.get("r1_rt")),
            "nozzle": {
                "contour_type": "rao_bell" if bell else "conical",
                "conical_half_angle_deg": 15.0 if bell else _float(chamber.get("nozzle_half_angle_deg")),
                "bell_length_percent": _float(chamber.get("rao_length_pct")) if bell else 80.0,
                "throat_radius_ratio": _float(chamber.get("rn_rt")),
                "rao_initial_angle_deg": (
                    _optional_float(chamber.get("rao_start_angle_deg")) if bell else None
                ),
                "rao_exit_angle_deg": (
                    _optional_float(chamber.get("rao_exit_angle_deg")) if bell else None
                ),
            },
        },
        "thermal": {
            "enabled": bool(thermal.get("thermal_enabled")),
            "resolution": str(thermal.get("thermal_resolution", "Medium")).casefold(),
            "segments": (
                [
                    _core_segment(segment, engine, thermal.get("segments", []))
                    for segment in thermal.get("segments", [])
                ]
                if thermal.get("thermal_enabled")
                else []
            ),
        },
    }


def _delivered(value: Any) -> dict[str, float]:
    raw = _jsonable(value)
    return {
        **raw,
        "design_thrust_n": raw.get("thrust_design_n"),
        "sea_level_thrust_n": raw.get("thrust_sea_level_n"),
        "optimal_thrust_n": raw.get("thrust_optimum_n"),
        "vacuum_thrust_n": raw.get("thrust_vacuum_n"),
        "design_isp_s": raw.get("isp_design_s"),
        "sea_level_isp_s": raw.get("isp_sea_level_s"),
        "optimal_isp_s": raw.get("isp_optimum_s"),
        "vacuum_isp_s": raw.get("isp_vacuum_s"),
    }


def _external_regen_coolant_flows(
    project: dict[str, Any], total_engine_mass_flow_kg_s: float
) -> list[dict[str, Any]]:
    """Return independently supplied Regen coolant streams.

    A linked Regen segment is another section of its source circuit and must
    not be counted twice.  Engine oxidizer and fuel sources are already shown
    in the propellant mass-flow totals, so only root ``Custom coolant``
    circuits are reported here.
    """

    thermal = project.get("thermal", {})
    if not thermal.get("thermal_enabled"):
        return []
    flows: list[dict[str, Any]] = []
    for segment in thermal.get("segments", []):
        if str(segment.get("type", "")).casefold() != "regen":
            continue
        source_mode = str(
            segment.get(
                "coolant_source_mode",
                "Receive from Regen segment"
                if segment.get("coolant_definition_mode")
                == "Receive from Regen segment"
                else "Custom coolant",
            )
        )
        if source_mode != "Custom coolant":
            continue
        percent = _float(segment.get("relative_mass_flow_pct"))
        if percent <= 0:
            continue
        identifier = str(
            segment.get("id", segment.get("segment_id", segment.get("name", "Regen")))
        ).strip()
        flows.append(
            {
                "segment_id": identifier,
                "segment_name": str(segment.get("name", identifier or "Regen")),
                "coolant": str(segment.get("coolant", "Coolant")),
                "relative_mass_flow_percent": percent,
                "kg_s": total_engine_mass_flow_kg_s * percent / 100.0,
            }
        )
    return flows


def _performance(
    value: Any, external_regen_coolants: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    raw = _jsonable(value)
    result = dict(raw)
    result["without_film"] = _delivered(value.without_film)
    result["with_film"] = _delivered(value.with_film)
    result["mass_flow"] = {
        "total_kg_s": value.total_mass_flow_kg_s,
        "oxidizer_kg_s": value.oxidizer_mass_flow_kg_s,
        "fuel_kg_s": value.fuel_mass_flow_kg_s,
        "film_kg_s": value.film_mass_flow_kg_s,
        "external_regen_coolants": list(external_regen_coolants or []),
    }
    return result


def _station(value: Any) -> dict[str, Any]:
    raw = _jsonable(value)
    return {
        **raw,
        "pressure_bar": _float(raw.get("pressure_pa")) / 100_000.0,
        "enthalpy_kj_kg": _float(raw.get("enthalpy_j_kg")) / 1000.0,
        "entropy_kj_kgk": _float(raw.get("entropy_j_kgk")) / 1000.0,
        "cp_kj_kgk": _float(raw.get("specific_heat_j_kgk")) / 1000.0,
        "mass_flux_kg_m2s": _float(raw.get("mass_flux_kg_m2_s")),
    }


def _thermodynamics(value: Any) -> dict[str, Any]:
    raw = _jsonable(value)
    x_m = tuple(value.x_m)
    axial = {
        **raw,
        "x_mm": [number * 1000.0 for number in x_m],
        "pressure_bar": [number / 100_000.0 for number in value.pressure_pa],
        "enthalpy_kj_kg": [number / 1000.0 for number in value.enthalpy_j_kg],
        "entropy_kj_kgk": [number / 1000.0 for number in value.entropy_j_kgk],
        "cp_kj_kgk": [number / 1000.0 for number in value.specific_heat_j_kgk],
        "mass_flux_kg_m2s": list(value.mass_flux_kg_m2_s),
    }
    axial.pop("stations", None)
    axial.pop("source", None)
    stations = {name: _station(station) for name, station in value.stations.items()}
    return {**axial, "source": value.source, "stations": stations, "axial": axial}


def _geometry(core_result: Any) -> dict[str, Any]:
    contour = core_result.contour
    performance = core_result.performance
    metadata = dict(contour.metadata)
    thermodynamics = core_result.thermodynamics
    velocities = [
        max(1.0e-9, mach * sonic)
        for mach, sonic in zip(thermodynamics.mach, thermodynamics.sonic_velocity_m_s)
    ]
    residence_s = 0.0
    for index in range(contour.throat_index):
        dx = contour.x_m[index + 1] - contour.x_m[index]
        residence_s += 2.0 * dx / (velocities[index] + velocities[index + 1])
    characteristic_length_mm = _float(metadata.get("characteristic_length_mm"))
    return {
        **metadata,
        "throat_diameter_mm": performance.throat_diameter_mm,
        "chamber_diameter_mm": 2.0 * _float(metadata.get("chamber_radius_mm")),
        "exit_diameter_mm": performance.exit_diameter_mm,
        "chamber_length_mm": contour.throat_x_m * 1000.0,
        "cylindrical_length_mm": _float(metadata.get("cylindrical_length_mm")),
        "nozzle_length_mm": _float(metadata.get("nozzle_length_mm")),
        "expansion_ratio": performance.expansion_ratio,
        "rao_start_angle_deg": _float(metadata.get("nozzle_initial_angle_deg")),
        "rao_exit_angle_deg": _float(metadata.get("nozzle_exit_angle_deg")),
        "contraction_angle_deg": _float(metadata.get("actual_contraction_angle_deg"), core_result.inputs.thrust_chamber.contraction_angle_deg),
        "characteristic_length_mm": _float(characteristic_length_mm),
        "gas_residence_time_ms": residence_s * 1000.0,
    }


def _throttle_sweep_rows(core_result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for point in core_result.throttle_sweep.points:
        result = point.result
        rows.append(
            {
                "throttle_pct": point.value,
                "ambient_atm": result.design_ambient_pressure_atm,
                "chamber_pressure_bar": result.chamber_pressure_bar,
                "thrust_n": result.with_film.thrust_design_n,
                "isp_s": result.with_film.isp_design_s,
                "mass_flow_kg_s": result.total_mass_flow_kg_s,
                "thrust_coefficient": result.with_film.thrust_design_n
                / (
                    result.chamber_pressure_bar
                    * 100_000.0
                    * result.throat_area_m2
                ),
                "status": result.source,
                "warnings": list(result.warnings),
                "with_film": _sweep_metrics(result, True),
                "without_film": _sweep_metrics(result, False),
            }
        )
    return rows


def _ambient_pressure_rows(core_result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for point in core_result.ambient_sweep.points:
        result = point.result
        atmosphere = altitude_for_pressure(point.value * ATM_PA)
        rows.append(
            {
                "ambient_pressure_atm": point.value,
                "ambient_pressure_bar": point.value * ATM_PA / 100_000.0,
                "standard_altitude_km": (
                    atmosphere.geometric_altitude_m / 1000.0
                    if atmosphere is not None
                    else None
                ),
                "standard_temperature_k": (
                    atmosphere.temperature_k if atmosphere is not None else None
                ),
                "standard_density_kg_m3": (
                    atmosphere.density_kg_m3 if atmosphere is not None else None
                ),
                "chamber_pressure_bar": result.chamber_pressure_bar,
                "thrust_n": result.with_film.thrust_design_n,
                "isp_s": result.with_film.isp_design_s,
                "mass_flow_kg_s": result.total_mass_flow_kg_s,
                "thrust_coefficient": result.with_film.thrust_design_n
                / (
                    result.chamber_pressure_bar
                    * 100_000.0
                    * result.throat_area_m2
                ),
                "status": result.source,
                "warnings": list(result.warnings),
                "with_film": _sweep_metrics(result, True),
                "without_film": _sweep_metrics(result, False),
            }
        )
    return rows


def _altitude_sweep_rows(core_result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for point in core_result.altitude_sweep.points:
        result = point.result
        atmosphere = standard_atmosphere(point.value * 1000.0)
        rows.append(
            {
                "standard_altitude_km": point.value,
                "ambient_pressure_atm": atmosphere.pressure_pa / ATM_PA,
                "ambient_pressure_bar": atmosphere.pressure_pa / 100_000.0,
                "standard_temperature_k": atmosphere.temperature_k,
                "standard_density_kg_m3": atmosphere.density_kg_m3,
                "chamber_pressure_bar": result.chamber_pressure_bar,
                "thrust_n": result.with_film.thrust_design_n,
                "isp_s": result.with_film.isp_design_s,
                "mass_flow_kg_s": result.total_mass_flow_kg_s,
                "thrust_coefficient": result.with_film.thrust_design_n
                / (
                    result.chamber_pressure_bar
                    * 100_000.0
                    * result.throat_area_m2
                ),
                "status": result.source,
                "warnings": list(result.warnings),
                "with_film": _sweep_metrics(result, True),
                "without_film": _sweep_metrics(result, False),
            }
        )
    return rows


def _sweep_metrics(result: Any, with_film: bool) -> dict[str, Any]:
    selected = result.with_film if with_film else result.without_film
    return _jsonable({
        "thrust_n": selected.thrust_design_n,
        "isp_s": selected.isp_design_s,
        "mass_flow_kg_s": result.total_mass_flow_kg_s if with_film else result.hot_gas_mass_flow_kg_s,
        "thrust_coefficient": selected.thrust_design_n / (
            result.chamber_pressure_bar * 100_000.0 * result.throat_area_m2
        ),
    })


def _root_regen(segment_id: str, by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    visited: set[str] = set()
    current = by_id.get(segment_id)
    while current is not None:
        current_id = str(current.get("id", ""))
        if current_id in visited:
            return None
        visited.add(current_id)
        source_mode = str(
            current.get(
                "coolant_source_mode",
                "Receive from Regen segment"
                if current.get("coolant_definition_mode") == "Receive from Regen segment"
                else "Custom coolant",
            )
        )
        if source_mode != "Receive from Regen segment":
            return current
        current = by_id.get(str(current.get("coolant_source_id", "")))
    return None


def _film_orifice_results(
    project: dict[str, Any],
    core_result: Any,
    thermal_result: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Size single-phase Film restrictions from the linked circuit outlet.

    Gas restrictions use the compressible, potentially choked mass-flow law.
    Flashing and nonideal gas restrictions are unsupported, never silently
    passed through the liquid Cd equation.
    """

    from .thermal.coolants import get_coolant_model

    segments = project["thermal"].get("segments", [])
    regen_by_id = {
        str(segment.get("id", "")): segment
        for segment in segments
        if segment.get("type") == "Regen"
    }
    x_values = list(thermal_result.x_m)
    coolant_values = list(thermal_result.Tc_K)
    active = list(thermal_result.active_segment_id)
    completion_by_segment = (getattr(thermal_result, "metadata", {}) or {}).get("regen_segment_completion", {})
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for film in segments:
        if film.get("type") != "Film" or not film.get("orifice_enabled"):
            continue
        name = str(film.get("name", "Film"))
        source_id = str(film.get("temperature_source_id", ""))
        source = regen_by_id.get(source_id)
        root = _root_regen(source_id, regen_by_id)
        if source is None or root is None:
            warnings.append(f"Film '{name}' orifice sizing skipped: Regen source is unavailable.")
            continue
        if completion_by_segment.get(source_id, {}).get("wall_march_completed") is False:
            warnings.append(
                f"Film '{name}' orifice sizing skipped: linked Regen source '{source_id}' "
                "did not complete its coolant march; a partial state is not a usable outlet."
            )
            continue
        if film.get("position_mode") == "Injector Face":
            injection_x = core_result.contour.x_m[0]
        elif film.get("position_mode") == "Chamber/convergent boundary":
            injection_x = core_result.contour.x_m[core_result.contour.chamber_end_index]
        else:
            injection_x = core_result.contour.x_m[0] + _float(film.get("position_mm")) / 1000.0
        candidates = [
            index
            for index, identifier in enumerate(active)
            if identifier == source_id and math.isfinite(_float(coolant_values[index], math.nan))
        ]
        outlets_t = getattr(thermal_result, "coolant_outlet_temperature_k", {})
        outlets_p = getattr(thermal_result, "coolant_outlet_pressure_bar", {})
        if source_id in outlets_t and source_id in outlets_p:
            temperature_k = float(outlets_t[source_id])
            coolant_pressure_bar = float(outlets_p[source_id])
        elif candidates and getattr(thermal_result, "coolant_pressure_bar", None):
            index = min(candidates, key=lambda item: abs(x_values[item] - injection_x))
            temperature_k = float(coolant_values[index])
            coolant_pressure_bar = float(thermal_result.coolant_pressure_bar[index])
        else:
            warnings.append(f"Film '{name}' orifice sizing skipped: linked Regen outlet pressure and temperature are unavailable.")
            continue
        coolant_name = _propellant(
            _effective_regen_coolant_name(source_id, segments, project.get("engine"))
            or film.get("coolant", root.get("coolant", "H2O"))
        )
        chamber_pressure_bar = core_result.performance.chamber_pressure_bar
        gas_axial = getattr(core_result, "thermodynamics", None)
        if gas_axial is not None:
            chamber_pressure_bar = _interpolate_state(
                injection_x, gas_axial.x_m, gas_axial.pressure_pa
            ) / 100000.0
        pressure_drop_pa = (coolant_pressure_bar - chamber_pressure_bar) * 100_000.0
        if not math.isfinite(pressure_drop_pa) or pressure_drop_pa <= 0:
            warnings.append(
                f"Film '{name}' orifice sizing skipped: linked outlet pressure must exceed gas pressure at injection."
            )
            continue
        try:
            model = get_coolant_model(coolant_name)
            state = model.at_state(temperature_k, coolant_pressure_bar * 100000.0)
            density = state.density_kg_m3
        except (KeyError, ValueError, AttributeError) as error:
            warnings.append(f"Film '{name}' orifice sizing skipped: {error}")
            continue
        coefficient = _float(film.get("discharge_coefficient"), 0.6)
        count = _int(film.get("orifice_count"), 30)
        if coefficient <= 0 or count < 1:
            warnings.append(f"Film '{name}' orifice sizing skipped: Cd and hole count are invalid.")
            continue
        film_mass_flow = (
            core_result.performance.total_mass_flow_kg_s
            * _float(film.get("relative_mass_flow_pct"))
            / 100.0
        )
        upstream_pa = coolant_pressure_bar * 100000.0
        downstream_pa = chamber_pressure_bar * 100000.0
        phase = str(getattr(state, "phase", "unknown")).casefold()
        source_text = str(getattr(state, "source", "screening"))
        saturation_pressure = getattr(state, "saturation_pressure_pa", None)
        has_saturation_pressure = (isinstance(saturation_pressure, (int, float))
                                   and math.isfinite(saturation_pressure) and saturation_pressure > 0)
        validity = "screening"
        choked = False
        if "twophase" in phase or "two_phase" in phase:
            warnings.append(f"Film '{name}' orifice sizing skipped: {phase} restriction requires a validated real-fluid flow model.")
            continue
        if "gas" in phase or "supercritical" in phase:
            cv = getattr(state, "specific_heat_cv_j_kgk", None)
            gas_constant = getattr(state, "gas_constant_j_kgk", None)
            if not cv or not gas_constant:
                warnings.append(f"Film '{name}' orifice sizing skipped: gas Cv and gas constant are unavailable.")
                continue
            gamma = state.specific_heat_j_kgk / cv
            compressibility = upstream_pa / (density * gas_constant * temperature_k)
            if not 1.0 < gamma < 2.0 or abs(compressibility - 1.0) > 0.10:
                warnings.append(f"Film '{name}' orifice sizing skipped: nonideal gas restriction is outside the ideal-gas screening model (Z={compressibility:.3g}).")
                continue
            pressure_ratio = downstream_pa / upstream_pa
            critical_ratio = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))
            choked = pressure_ratio <= critical_ratio
            effective_ratio = max(pressure_ratio, critical_ratio)
            mass_flux = upstream_pa * math.sqrt(
                2.0 * gamma / (gas_constant * temperature_k * (gamma - 1.0))
                * (effective_ratio ** (2.0 / gamma) - effective_ratio ** ((gamma + 1.0) / gamma))
            )
            restriction_model = "compressible ideal-gas Cd equation; choked" if choked else "compressible ideal-gas Cd equation; unchoked"
            warnings.append(f"Film '{name}' gas restriction is a screening estimate (constant Cp/Cv, |Z-1| <= 0.10); validate discharge coefficient and real-fluid effects.")
        else:
            if has_saturation_pressure and downstream_pa <= saturation_pressure:
                warnings.append(f"Film '{name}' orifice sizing skipped: flashing/cavitation possible because downstream pressure is below coolant saturation pressure.")
                continue
            mass_flux = math.sqrt(2.0 * density * pressure_drop_pa)
            restriction_model = "single-phase incompressible Cd equation; linked Regen outlet state and local gas pressure"
            if has_saturation_pressure and "coolprop" in source_text.casefold():
                validity = "valid"
            else:
                warnings.append(f"Film '{name}' liquid restriction uses screening properties; vapor pressure/cavitation and the discharge coefficient require validation.")
        if not math.isfinite(mass_flux) or mass_flux <= 0:
            warnings.append(f"Film '{name}' orifice sizing skipped: nonpositive restriction mass flux.")
            continue
        total_area_m2 = film_mass_flow / (coefficient * mass_flux)
        diameter_m = math.sqrt(4.0 * total_area_m2 / (math.pi * count))
        rows.append(
            {
                "segment_id": str(film.get("id", "")),
                "name": name,
                "regen_source_id": source_id,
                "coolant": coolant_name,
                "temperature_k": temperature_k,
                "density_kg_m3": density,
                "pressure_drop_bar": pressure_drop_pa / 100_000.0,
                "upstream_pressure_bar": coolant_pressure_bar,
                "gas_pressure_bar": chamber_pressure_bar,
                "phase": phase,
                "physical_validity": validity,
                "plumbing_model": "independent Film stream; Regen outlet is a state reference, not a mass-withdrawal connection",
                "choked": choked,
                "mass_flow_kg_s": film_mass_flow,
                "discharge_coefficient": coefficient,
                "orifice_count": count,
                "total_area_mm2": total_area_m2 * 1.0e6,
                "diameter_mm": diameter_m * 1000.0,
                "model": restriction_model,
            }
        )
    return rows, warnings


def _interpolate_state(x: float, coordinates: Any, values: Any) -> float:
    if not coordinates or len(coordinates) != len(values):
        raise ValueError("State coordinates and values must be aligned")
    if x < coordinates[0] - 1.e-12 or x > coordinates[-1] + 1.e-12:
        raise ValueError("Film injection is outside the engine contour")
    import bisect
    right = bisect.bisect_left(coordinates, x)
    if right == 0:
        return float(values[0])
    if right == len(coordinates):
        return float(values[-1])
    left = right - 1
    weight = (x - coordinates[left]) / (coordinates[right] - coordinates[left])
    return float(values[left]) + weight * (float(values[right]) - float(values[left]))


def _regen_feed_pressure_issues(project: dict[str, Any], core_result: Any, thermal_result: Any) -> list[str]:
    regens = {str(item.get("id")): item for item in project.get("thermal", {}).get("segments", [])
              if item.get("type") == "Regen"}
    parents = {str(item.get("coolant_source_id")) for item in regens.values()
               if item.get("coolant_source_mode") == "Receive from Regen segment"}
    outlets = getattr(thermal_result, "coolant_outlet_pressure_bar", {})
    issues = []
    for identifier, segment in regens.items():
        if identifier in parents:
            continue
        root = _root_regen(identifier, regens)
        if root is None or root.get("coolant_source_mode") not in {"Engine fuel", "Engine oxidizer"}:
            continue
        pressure = outlets.get(identifier)
        if pressure is None or not math.isfinite(pressure) or pressure <= core_result.performance.chamber_pressure_bar:
            issues.append(
                f"Regen '{segment.get('name', identifier)}' engine-feed outlet pressure "
                f"does not exceed chamber pressure; injector/line losses and a downstream pump are not modeled."
            )
    return issues


class AnalysisService:
    """Single high-level service used by the desktop application and tests."""

    def __init__(self) -> None:
        rocketcea = importlib.util.find_spec("rocketcea") is not None
        self.backend_description = "RocketCEA + Bartz" if rocketcea else "Ideal-gas fallback + Bartz"

    def analyze(self, project: dict[str, Any]) -> dict[str, Any]:
        if not project.get("thermal", {}).get("regen_feed_feedback_enabled"):
            result = self._analyze_once(project)
            result["regen_feed_feedback"] = {"enabled": False, "converged": None}
            if result.get("thermal_enabled") and any(
                item.get("type") == "Regen" and item.get("coolant_source_mode") in {"Engine fuel", "Engine oxidizer"}
                for item in project.get("thermal", {}).get("segments", [])
            ):
                result["warnings"].append("Regen outlet enthalpy is not coupled back to CEA; enable reactant-state coupling or specify the measured injector supply state.")
            return result
        working = copy.deepcopy(project)
        result = None
        converged = False
        status = "no engine-source Regen outlet"
        effective = {}
        for iteration in range(1, 21):
            try:
                result = self._analyze_once(working)
            except ValueError as error:
                if result is None:
                    raise
                status = f"stopped: coupled reactant state unsupported ({error})"
                break
            thermal = result.get("thermal", {})
            if thermal.get("converged") is not True or thermal.get("metadata", {}).get("coupled_converged") is False:
                status = "stopped: inner thermal or linked Film/Regen iteration did not converge"
                break
            if thermal.get("physical_validity") in {"invalid", "unsupported"}:
                status = "stopped: thermal state outside the supported model"
                break
            regens = {str(item.get("id")): item for item in working.get("thermal", {}).get("segments", [])
                      if item.get("type") == "Regen"}
            unsupported_bleed = any(
                item.get("type") == "Film" and item.get("orifice_enabled")
                and (source := _root_regen(str(item.get("temperature_source_id", "")), regens)) is not None
                and source.get("coolant_source_mode") in {"Engine fuel", "Engine oxidizer"}
                for item in working.get("thermal", {}).get("segments", [])
            )
            if unsupported_bleed:
                status = "stopped: engine-feed Film withdrawal needs a split-flow mass ledger; the current link is a state reference only"
                break
            parents = {str(item.get("coolant_source_id")) for item in regens.values()
                       if item.get("coolant_source_mode") == "Receive from Regen segment"}
            targets = {}
            for identifier, segment in regens.items():
                if identifier in parents:
                    continue
                root = _root_regen(identifier, regens)
                if not root:
                    continue
                kind = {"Engine fuel": "fuel", "Engine oxidizer": "oxidizer"}.get(root.get("coolant_source_mode"))
                if kind is None:
                    continue
                temperature = thermal.get("coolant_outlet_temperature_k", {}).get(identifier)
                pressure = thermal.get("coolant_outlet_pressure_bar", {}).get(identifier)
                if temperature is None or pressure is None:
                    continue
                if kind in targets:
                    status = "multiple engine-source outlet states need an explicit mixer/split-flow model"
                    break
                targets[kind] = (temperature, pressure)
            if status.startswith("multiple"):
                break
            if not targets:
                break
            maximum_temperature_error = 0.0
            maximum_pressure_error = 0.0
            for kind, (temperature, pressure) in targets.items():
                old_temperature = _optional_float(working["engine"].get(f"{kind}_temperature_k"))
                old_pressure = _optional_float(working["engine"].get(f"{kind}_pressure_bar"))
                maximum_temperature_error = max(maximum_temperature_error, abs(temperature - old_temperature) if old_temperature is not None else math.inf)
                maximum_pressure_error = max(maximum_pressure_error, abs(pressure - old_pressure) if old_pressure is not None else math.inf)
                working["engine"][f"{kind}_temperature_k"] = temperature if old_temperature is None else old_temperature + 0.65 * (temperature - old_temperature)
                working["engine"][f"{kind}_pressure_bar"] = pressure if old_pressure is None else old_pressure + 0.65 * (pressure - old_pressure)
                effective[kind] = {"temperature_k": temperature, "pressure_bar": pressure}
            if maximum_temperature_error <= 0.05 and maximum_pressure_error <= 1.e-3:
                converged = True
                status = "coupled outlet/reactant state converged"
                break
            status = "coupled iteration limit reached"
        assert result is not None
        result["input_project"] = copy.deepcopy(project)
        result["regen_feed_feedback"] = {
            "enabled": True, "converged": converged, "iterations": iteration,
            "status": status, "outlet_states": effective,
            "temperature_tolerance_k": 0.05, "pressure_tolerance_bar": 1.e-3,
            "model": "steady serial circuit; no propellant mixer, film bleed or feed-system work",
        }
        thermal = result.get("thermal", {})
        thermal.setdefault("metadata", {})["regen_feed_feedback"] = result["regen_feed_feedback"]
        if not converged:
            result["warnings"].append(f"Regen/reactant-state feedback not converged: {status}.")
            if thermal.get("physical_validity") not in {"invalid", "unsupported"}:
                thermal["physical_validity"] = "invalid"
            thermal.setdefault("physical_issues", []).append(f"Regen/reactant-state feedback: {status}.")
            thermal["metadata"]["physical_validity"] = thermal["physical_validity"]
            thermal["metadata"]["physical_issues"] = list(thermal["physical_issues"])
        return result

    def _analyze_once(self, project: dict[str, Any]) -> dict[str, Any]:
        input_snapshot = copy.deepcopy(project)
        optimum = None
        if project["engine"].get("mixture_ratio_auto"):
            # Recompute from this analysis snapshot, including any updated
            # reactant state in a Regen feedback iteration. A cached UI value
            # must not define the backend's automatic-mixture objective.
            seed_project = copy.deepcopy(project)
            # The stored/manual O/F is inactive in automatic mode. Validate
            # the active fields without depending on that stale value.
            seed_project["engine"]["mixture_ratio"] = 1.0
            optimum = optimize_mixture_ratio_for_inputs(
                analysis_input_from_dict(_core_project(seed_project)),
                prefer_rocketcea=True,
            )
            project = copy.deepcopy(project)
            project["engine"]["mixture_ratio"] = optimum.mixture_ratio
        core_project = _core_project(project)
        core_result = analyze_engine(core_project, prefer_rocketcea=True)
        from .core.propellants import propellant_specs
        supplied_engine = core_result.inputs.engine
        supply_specs = propellant_specs(
            supplied_engine.oxidizer, supplied_engine.fuel,
            supplied_engine.oxidizer_mass_fraction, supplied_engine.fuel_mass_fraction,
            supplied_engine.oxidizer_temperature_k, supplied_engine.fuel_temperature_k,
            supplied_engine.oxidizer_pressure_bar, supplied_engine.fuel_pressure_bar,
        )
        contour = core_result.contour
        external_regen_coolants = _external_regen_coolant_flows(
            project, core_result.performance.total_mass_flow_kg_s
        )
        result: dict[str, Any] = {
            "input_project": input_snapshot,
            "mixture_ratio_optimization": {
                "enabled": optimum is not None,
                **(_jsonable(optimum) if optimum is not None else {}),
            },
            "reactant_supply_states": [
                {"name": spec.display_name, "temperature_k": spec.supply_temperature_k,
                 "pressure_bar": spec.supply_pressure_bar, "enthalpy_model": spec.enthalpy_model,
                 "warnings": list(spec.warnings)} for spec in supply_specs
            ],
            "method": f"{core_result.performance.source} + Bartz",
            "performance": _performance(
                core_result.performance, external_regen_coolants
            ),
            "contour": {
                "x_mm": list(contour.x_mm),
                "radius_mm": list(contour.radius_mm),
                "area_m2": list(contour.area_m2),
                "throat_index": contour.throat_index,
                "chamber_end_index": contour.chamber_end_index,
                "metadata": dict(contour.metadata),
            },
            "geometry": _geometry(core_result),
            "thermodynamics": _thermodynamics(core_result.thermodynamics),
            "throttle": _throttle_sweep_rows(core_result),
            "ambient": {
                "model": "U.S. Standard Atmosphere 1976",
                "pressure_rows": _ambient_pressure_rows(core_result),
                "altitude_rows": _altitude_sweep_rows(core_result),
            },
            "ambient_sweep": _jsonable(core_result.ambient_sweep),
            "altitude_sweep": _jsonable(core_result.altitude_sweep),
            "warnings": list(core_result.warnings) + [message for spec in supply_specs for message in spec.warnings],
            "thermal_enabled": bool(project["thermal"].get("thermal_enabled")),
        }
        if optimum is not None and optimum.warning:
            result["warnings"].append(optimum.warning)
        if result["thermal_enabled"]:
            from .thermal import analyze_thermal

            thermal_segments = [
                _normalised_segment(
                    segment,
                    project["engine"],
                    project["thermal"].get("segments", []),
                )
                for segment in project["thermal"].get("segments", [])
            ]
            gas = {
                "performance": core_result.performance,
                "thermodynamics": core_result.thermodynamics,
                "chamber_pressure_pa": core_result.performance.chamber_pressure_bar * 100_000.0,
                "characteristic_velocity_m_s": core_result.performance.delivered_cstar_m_s,
                "stagnation_temperature_k": core_result.performance.combustion_temperature_k,
                "throat_diameter_m": core_result.performance.throat_diameter_mm / 1000.0,
                "throat_radius_of_curvature_m": (
                    core_result.performance.throat_diameter_mm
                    / 2000.0
                    * core_result.inputs.thrust_chamber.nozzle.throat_radius_ratio
                ),
                "mass_flow_kg_s": core_result.performance.hot_gas_mass_flow_kg_s,
                "x_m": core_result.thermodynamics.x_m,
                "pressure_pa": core_result.thermodynamics.pressure_pa,
                "temperature_k": core_result.thermodynamics.temperature_k,
                "specific_heat_j_kgk": core_result.thermodynamics.specific_heat_j_kgk,
                "gamma": core_result.thermodynamics.gamma,
                "mach": core_result.thermodynamics.mach,
                "viscosity_pa_s": core_result.thermodynamics.viscosity_pa_s,
                "prandtl": core_result.thermodynamics.prandtl,
                "h2o_mole_fraction": core_result.thermodynamics.h2o_mole_fraction,
                "co2_mole_fraction": core_result.thermodynamics.co2_mole_fraction,
                "nozzle_regime": core_result.thermodynamics.nozzle_regime,
            }
            settings = {
                "resolution": str(project["thermal"].get("thermal_resolution", "Medium")).casefold(),
                "max_iterations": _int(project["thermal"].get("thermal_max_iterations"), 200),
                "coolant_property_backend": "refprop" if str(project["thermal"].get("coolant_property_backend","CoolProp HEOS")).startswith("REFPROP") else "coolprop",
                "two_phase_model": "disabled" if project["thermal"].get("two_phase_model")=="Disabled" else "auto",
            }
            thermal_result = analyze_thermal(contour, gas, thermal_segments, settings=settings)
            thermal = thermal_result.as_dict() if hasattr(thermal_result, "as_dict") else _jsonable(thermal_result)
            feed_issues = _regen_feed_pressure_issues(project, core_result, thermal_result)
            if feed_issues:
                thermal["physical_validity"] = "invalid"
                thermal["physical_issues"] = list(thermal.get("physical_issues", [])) + feed_issues
                thermal["warnings"] = list(thermal.get("warnings", [])) + feed_issues
                metadata = thermal.setdefault("metadata", {})
                metadata["physical_validity"] = thermal["physical_validity"]
                metadata["physical_issues"] = list(thermal["physical_issues"])
            film_orifices, orifice_warnings = _film_orifice_results(
                project, core_result, thermal_result
            )
            thermal.update(
                {
                    "x_mm": [value * 1000.0 for value in thermal.get("x_m", [])],
                    "radius_mm": [value * 1000.0 for value in thermal.get("radius_m", [])],
                    "twg_k": thermal.get("Twg_K", thermal.get("Twg", [])),
                    "twi_k": thermal.get("Twi_K", thermal.get("Twi", [])),
                    "twc_k": thermal.get("Twc_K", thermal.get("Twc", [])),
                    "tc_k": thermal.get("Tc_K", thermal.get("Tc", [])),
                    "throat_x_mm": contour.throat_x_m * 1000.0,
                    "film_orifices": film_orifices,
                    "segment_names": {
                        str(segment.get("id", "")): str(segment.get("name", segment.get("type", "Segment")))
                        for segment in project["thermal"].get("segments", [])
                    },
                    "segment_types": {
                        str(segment.get("id", "")): str(segment.get("type", ""))
                        for segment in project["thermal"].get("segments", [])
                    },
                    # The thermal solver resolves linked Regen circuits to
                    # their root coolant definition.  Expose that resolved
                    # identity directly for result tables while retaining it
                    # in metadata for non-GUI consumers.
                    "segment_coolants": dict(
                        thermal.get("metadata", {}).get(
                            "coolant_identity_by_segment", {}
                        )
                    ),
                }
            )
            result["thermal"] = thermal
            result["warnings"].extend(thermal.get("warnings", []))
            result["warnings"].extend(orifice_warnings)
        else:
            result["thermal"] = {
                "resolution": str(project["thermal"].get("thermal_resolution", "Medium")),
                "section_count": 0,
            }
        result["warnings"] = list(dict.fromkeys(str(item) for item in result["warnings"]))
        return _jsonable(result)


__all__ = ["AnalysisService"]
