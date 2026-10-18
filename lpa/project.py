"""LPA project serialization and UI-level validation."""

from __future__ import annotations

import json
import copy
import os
import tempfile
from math import isfinite
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .core.composition import engine_selection
from .core.models import Fuel, Oxidizer
from .ui.input_views import validate_segment_layout
from .ui.validation import segment_numeric_issues


PROJECT_SCHEMA = "lpa-project/1"
DEFAULT_PROJECT_EXTENSION = ".cfg"
LEGACY_PROJECT_EXTENSIONS = (".lpa.json", ".json")


@dataclass(slots=True)
class ValidationIssue:
    page: str
    field: str
    message: str


class ProjectValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__("\n".join(issue.message for issue in issues))


def make_project(engine: dict[str, Any], thrust_chamber: dict[str, Any], thermal: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": PROJECT_SCHEMA,
        "application_version": __version__,
        "engine": engine,
        "thrust_chamber": thrust_chamber,
        "thermal": thermal,
    }


def save_project(path: str | Path, project: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(project, indent=2, ensure_ascii=False, allow_nan=False)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    return target


def load_project(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    validate_project_structure(payload)
    return payload


def validate_project_structure(payload: object) -> None:
    """Check types before a file can mutate any live UI state."""
    if not isinstance(payload, dict):
        raise ValueError("The selected file does not contain an LPA project object.")
    schema = payload.get("schema")
    if schema not in (PROJECT_SCHEMA, None):
        raise ValueError(f"Unsupported project schema: {schema}")
    for section in ("engine", "thrust_chamber", "thermal"):
        if section not in payload or not isinstance(payload[section], dict):
            raise ValueError(f"Project section '{section}' is missing or invalid.")
        for key, value in payload[section].items():
            if key in {"mixture_ratio_auto", "thermal_enabled", "throttle_enabled", "ambient_enabled", "regen_feed_feedback_enabled"}:
                if not isinstance(value, bool):
                    raise ValueError(f"Project field '{section}.{key}' must be a boolean.")
            elif key != "segments" and not isinstance(value, (str, int, float, bool, type(None))):
                raise ValueError(f"Project field '{section}.{key}' must be a scalar.")
    segments = payload["thermal"].get("segments", [])
    if not isinstance(segments, list):
        raise ValueError("Thermal segments must be a list.")
    identifiers: set[str] = set()
    for segment in segments:
        if not isinstance(segment, dict) or segment.get("type") not in {"Regen", "Film", "Radiation"}:
            raise ValueError("Each cooling segment must be an object with type Regen, Film, or Radiation.")
        for key, value in segment.items():
            if key.endswith("_enabled") or key in {"reverse_coolant_flow", "link_broken", "temperature_link_broken"}:
                if not isinstance(value, bool):
                    raise ValueError(f"Cooling segment field '{key}' must be a boolean.")
            elif not isinstance(value, (str, int, float, bool, type(None))):
                raise ValueError(f"Cooling segment field '{key}' must be a scalar.")
        identifier = str(segment.get("id", ""))
        if identifier and identifier in identifiers:
            raise ValueError(f"Duplicate cooling segment ID: {identifier}")
        identifiers.add(identifier)


def project_with_defaults(project: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Migrate missing fields from stable defaults, never a previous project."""
    validate_project_structure(project)
    result = copy.deepcopy(defaults)
    for section in ("engine", "thrust_chamber", "thermal"):
        result[section].update(copy.deepcopy(project[section]))
    # Old percent-bearing labels are decoded before loading widgets.
    for kind, enum_type in (("oxidizer", Oxidizer), ("fuel", Fuel)):
        if kind in project["engine"]:
            name, fraction = engine_selection(project["engine"], kind)
            enum_type(name)
            result["engine"][kind] = name
            if name in {"H2O2", "Ethanol", "IPA"}:
                result["engine"][f"{kind}_mass_fraction_pct"] = f"{100 * fraction:.12g}"
    return result


def _positive(
    issues: list[ValidationIssue],
    page: str,
    values: dict[str, Any],
    key: str,
    label: str,
    *,
    allow_zero: bool = False,
) -> float | None:
    try:
        value = float(values.get(key, ""))
    except (TypeError, ValueError):
        issues.append(ValidationIssue(page, key, f"{label} must be a number."))
        return None
    if not isfinite(value):
        issues.append(ValidationIssue(page, key, f"{label} must be finite."))
        return None
    if value < 0 if allow_zero else value <= 0:
        qualifier = "zero or greater" if allow_zero else "greater than zero"
        issues.append(ValidationIssue(page, key, f"{label} must be {qualifier}."))
    return value


def _manual_rao_angles(
    issues: list[ValidationIssue], chamber: dict[str, Any]
) -> bool:
    """Validate the optional manual pair; return whether either was entered."""

    keys = ("rao_start_angle_deg", "rao_exit_angle_deg")
    raw = tuple(chamber.get(key) for key in keys)
    entered = tuple(value is not None and bool(str(value).strip()) for value in raw)
    if not any(entered):
        return False
    if not all(entered):
        missing = keys[entered.index(False)]
        issues.append(
            ValidationIssue(
                "thrust_chamber", missing,
                "Specify both Rao angles Tn and Te, or leave both blank for automatic angles.",
            )
        )
        return True
    angles: list[float] = []
    for key, value, label in zip(keys, raw, ("Tn", "Te")):
        try:
            angle = float(value)
            if not isfinite(angle):
                raise ValueError
        except (TypeError, ValueError):
            issues.append(
                ValidationIssue("thrust_chamber", key, f"Rao angle {label} must be a finite number.")
            )
        else:
            angles.append(angle)
    if len(angles) == 2 and not 0 <= angles[1] < angles[0] < 90:
        issues.append(
            ValidationIssue(
                "thrust_chamber", keys[0],
                "Rao angles must satisfy 0 <= Te < Tn < 90 degrees.",
            )
        )
    return True


def validate_project(project: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    engine = project.get("engine", {})
    chamber = project.get("thrust_chamber", {})
    thermal = project.get("thermal", {})
    choices = {
        "contraction_mode": {"Area ratio (Ac/At)", "Chamber diameter (Dc)"},
        "exit_condition_mode": {"Ambient pressure", "Expansion area ratio"},
        "flow_model": {"Shifting equilibrium", "Frozen at chamber", "Frozen at throat",
                       "Freezing at pressure ratio", "Freezing at area ratio"},
        "nozzle_efficiency_mode": {"Estimate", "Specified"},
        "sizing_mode": {"Engine nominal thrust", "Chamber throat diameter"},
        "thrust_unit": {"N", "kN"},
        "chamber_length_mode": {"Direct Lc and Lcyl", "Characteristic length L*"},
        "nozzle_type": {"Conical nozzle", "Parabolic contour (Rao)"},
    }
    for key, options in choices.items():
        if key in chamber and chamber[key] not in options:
            issues.append(ValidationIssue("thrust_chamber", key, f"Unsupported {key.replace('_', ' ')}: {chamber[key]}"))

    if not str(engine.get("engine_name", "")).strip():
        issues.append(ValidationIssue("engine", "engine_name", "Engine name is required."))
    _positive(issues, "engine", engine, "chamber_pressure_bar", "Chamber pressure")
    _positive(issues, "engine", engine, "mixture_ratio", "Mixture ratio")
    for key in ("oxidizer_temperature_k", "fuel_temperature_k"):
        if engine.get(key) is not None and str(engine.get(key)).strip():
            _positive(issues, "engine", engine, key, key.replace("_", " ").title())
    for key in ("oxidizer_pressure_bar", "fuel_pressure_bar"):
        if engine.get(key) is not None and str(engine.get(key)).strip():
            pressure = _positive(issues, "engine", engine, key, key.replace("_", " ").title())
            try:
                if pressure is not None and pressure < float(engine.get("chamber_pressure_bar", "")):
                    issues.append(ValidationIssue("engine", key, "Supply pressure must be at least chamber pressure."))
            except (TypeError, ValueError):
                pass
    if not engine.get("oxidizer") or not engine.get("fuel"):
        issues.append(ValidationIssue("engine", "propellants", "Select both an oxidizer and a fuel."))
    for kind, enum_type in (("oxidizer", Oxidizer), ("fuel", Fuel)):
        if not engine.get(kind):
            continue
        try:
            name, _fraction = engine_selection(engine, kind)
            enum_type(name)
        except (ValueError, TypeError) as error:
            issues.append(ValidationIssue("engine", f"{kind}_mass_fraction_pct", str(error)))

    direct_chamber_diameter = chamber.get("contraction_mode") == "Chamber diameter (Dc)"
    if direct_chamber_diameter:
        chamber_diameter = _positive(
            issues,
            "thrust_chamber",
            chamber,
            "chamber_diameter_mm",
            "Chamber diameter Dc",
        )
        if chamber.get("sizing_mode") == "Chamber throat diameter":
            try:
                throat_diameter = float(chamber.get("throat_diameter_mm", ""))
            except (TypeError, ValueError):
                throat_diameter = None
            if (
                chamber_diameter is not None
                and throat_diameter is not None
                and chamber_diameter <= throat_diameter
            ):
                issues.append(
                    ValidationIssue(
                        "thrust_chamber",
                        "chamber_diameter_mm",
                        "Chamber diameter Dc must be greater than throat diameter Dt.",
                    )
                )
    else:
        contraction = _positive(
            issues,
            "thrust_chamber",
            chamber,
            "contraction_area_ratio",
            "Contraction area ratio",
        )
        if contraction is not None and contraction <= 1:
            issues.append(ValidationIssue("thrust_chamber", "contraction_area_ratio", "Contraction area ratio must be greater than 1."))
    exit_value = _positive(issues, "thrust_chamber", chamber, "exit_condition_value", "Nozzle exit condition")
    if exit_value is not None and not isfinite(exit_value):
        issues.append(ValidationIssue("thrust_chamber", "exit_condition_value", "Nozzle exit condition must be finite."))
    if chamber.get("exit_condition_mode") == "Expansion area ratio" and exit_value is not None and exit_value <= 1:
        issues.append(ValidationIssue("thrust_chamber", "exit_condition_value", "Expansion area ratio must be greater than 1."))
    flow_model = chamber.get("flow_model")
    if flow_model in {"Frozen at chamber", "Freezing at pressure ratio"}:
        issues.append(ValidationIssue("thrust_chamber", "flow_model",
                                      "Chamber-frozen chemistry is unsupported for the finite-area chamber backend. Select shifting equilibrium or frozen at throat."))
    if flow_model not in {"Shifting equilibrium", "Frozen at chamber", "Frozen at throat"}:
        freeze = _positive(issues, "thrust_chamber", chamber, "freeze_value", "Freezing criterion")
        minimum = 1.0
        if freeze is not None and (freeze <= minimum if flow_model == "Freezing at pressure ratio" else freeze < minimum):
            qualifier = "greater than 1" if flow_model == "Freezing at pressure ratio" else "at least 1"
            issues.append(ValidationIssue("thrust_chamber", "freeze_value", f"Freezing criterion must be {qualifier}."))
    reaction = _positive(issues, "thrust_chamber", chamber, "reaction_efficiency_pct", "Reaction efficiency")
    if reaction is not None and reaction > 100:
        issues.append(ValidationIssue("thrust_chamber", "reaction_efficiency_pct", "Reaction efficiency may not exceed 100%."))
    if chamber.get("nozzle_efficiency_mode") == "Specified":
        nozzle_eff = _positive(issues, "thrust_chamber", chamber, "nozzle_efficiency_pct", "Nozzle efficiency")
        if nozzle_eff is not None and nozzle_eff > 100:
            issues.append(ValidationIssue("thrust_chamber", "nozzle_efficiency_pct", "Nozzle efficiency may not exceed 100%."))

    if chamber.get("sizing_mode") == "Engine nominal thrust":
        _positive(issues, "thrust_chamber", chamber, "nominal_thrust", "Nominal thrust")
        _positive(
            issues,
            "thrust_chamber",
            chamber,
            "nominal_thrust_ambient_atm",
            "Thrust reference ambient pressure",
            allow_zero=True,
        )
    else:
        _positive(issues, "thrust_chamber", chamber, "throat_diameter_mm", "Throat diameter")

    if chamber.get("chamber_length_mode") == "Direct Lc and Lcyl":
        lc = _positive(issues, "thrust_chamber", chamber, "chamber_length_mm", "Total chamber length")
        lcyl = _positive(issues, "thrust_chamber", chamber, "cylindrical_length_mm", "Cylindrical length")
        if lc is not None and lcyl is not None and lcyl >= lc:
            issues.append(ValidationIssue("thrust_chamber", "cylindrical_length_mm", "Lcyl must be smaller than total Lc."))
    else:
        _positive(issues, "thrust_chamber", chamber, "characteristic_length_mm", "Characteristic length")

    contraction_angle = _positive(issues, "thrust_chamber", chamber, "contraction_angle_deg", "Contraction angle")
    if contraction_angle is not None and not 5 <= contraction_angle < 90:
        issues.append(ValidationIssue("thrust_chamber", "contraction_angle_deg", "Contraction angle must be from 5° up to, but not including, 90°."))
    r2_ratio = _positive(issues, "thrust_chamber", chamber, "r2_ratio", "R2/R2max", allow_zero=True)
    if r2_ratio is not None and r2_ratio > 1:
        issues.append(ValidationIssue("thrust_chamber", "r2_ratio", "R2/R2max must be between 0 and 1."))
    _positive(issues, "thrust_chamber", chamber, "r1_rt", "R1/Rt")
    _positive(issues, "thrust_chamber", chamber, "rn_rt", "Rn/Rt")
    if chamber.get("nozzle_type") == "Parabolic contour (Rao)":
        rao = _positive(issues, "thrust_chamber", chamber, "rao_length_pct", "Rao length ratio")
        if rao is not None and (not isfinite(rao) or not 50 <= rao <= 120):
            issues.append(ValidationIssue("thrust_chamber", "rao_length_pct", "Rao length must be finite and between 50% and 120% of Lc15."))
        _manual_rao_angles(issues, chamber)
    else:
        angle = _positive(issues, "thrust_chamber", chamber, "nozzle_half_angle_deg", "Nozzle half-angle")
        if angle is not None and angle >= 45:
            issues.append(ValidationIssue("thrust_chamber", "nozzle_half_angle_deg", "Nozzle half-angle must be below 45°."))

    for enabled_key, mode_key, fixed_key, min_key, max_key, points_key, label in (
        ("throttle_enabled", "throttle_mode", "throttle_fixed_pct", "throttle_min_pct", "throttle_max_pct", "throttle_points", "Throttle"),
        ("ambient_enabled", "ambient_mode", "ambient_fixed_atm", "ambient_min_atm", "ambient_max_atm", "ambient_points", "Ambient pressure"),
    ):
        if not chamber.get(enabled_key):
            continue
        is_range = str(chamber.get(mode_key, "")).endswith("range")
        if is_range:
            minimum = _positive(issues, "thrust_chamber", chamber, min_key, f"{label} minimum", allow_zero=label.startswith("Ambient"))
            maximum = _positive(issues, "thrust_chamber", chamber, max_key, f"{label} maximum", allow_zero=label.startswith("Ambient"))
            points = _positive(issues, "thrust_chamber", chamber, points_key, f"{label} points")
            if minimum is not None and maximum is not None and minimum >= maximum:
                issues.append(ValidationIssue("thrust_chamber", min_key, f"{label} minimum must be lower than maximum."))
            if points is not None and (int(points) != points or points < 2 or points > 501):
                issues.append(ValidationIssue("thrust_chamber", points_key, f"{label} points must be an integer from 2 to 501."))
            if label == "Throttle" and maximum is not None and maximum > 100:
                issues.append(ValidationIssue("thrust_chamber", max_key, "Throttle maximum may not exceed 100%."))
        else:
            fixed = _positive(issues, "thrust_chamber", chamber, fixed_key, f"Fixed {label.lower()}", allow_zero=label.startswith("Ambient"))
            if label == "Throttle" and fixed is not None and fixed > 100:
                issues.append(ValidationIssue("thrust_chamber", fixed_key, "Fixed throttle may not exceed 100%."))

    if thermal.get("thermal_enabled"):
        for key,choices in (("coolant_property_backend",{"CoolProp HEOS","REFPROP (separate installation)"}),
                            ("two_phase_model",{"Auto (Beta)","Pure fluids only","Disabled"}),
                            ("mixture_boiling_model",{"shah_gungor_winterton","disabled"})):
            if key in thermal and thermal[key] not in choices:
                issues.append(ValidationIssue("thermal",key,f"Unknown {key} selection."))
        if "mixture_mass_transfer_coefficient_m_s" in thermal:
            _positive(issues, "thermal", thermal, "mixture_mass_transfer_coefficient_m_s",
                      "Mixture mass-transfer coefficient")
        try:
            iterations = float(thermal.get("thermal_max_iterations", 0))
            if not isfinite(iterations) or not iterations.is_integer() or not 10 <= iterations <= 1000:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            issues.append(ValidationIssue("thermal", "thermal_max_iterations", "Thermal solver iterations must be an integer from 10 to 1000."))
        segments = thermal.get("segments", [])
        if not isinstance(segments, list) or not segments:
            issues.append(ValidationIssue("thermal", "segments", "Add at least one cooling segment when thermal analysis is enabled."))
        elif not all(isinstance(segment, dict) for segment in segments):
            issues.append(ValidationIssue("thermal", "segments", "Each cooling segment must be an object."))
        else:
            for segment in segments:
                name = str(segment.get("name", segment.get("type", "Segment")))
                for message in segment_numeric_issues(segment):
                    issues.append(ValidationIssue("thermal", "segments", f"{name}: {message}"))
            try:
                film_total = sum(
                    float(segment.get("relative_mass_flow_pct", 0) or 0)
                    for segment in segments
                    if segment.get("type") == "Film"
                )
                if film_total >= 100:
                    issues.append(ValidationIssue("thermal", "segments", "Total film mass flow must remain below 100% of engine flow."))
            except (TypeError, ValueError):
                issues.append(ValidationIssue("thermal", "segments", "Film mass-flow values must be numeric."))
            for warning in validate_segment_layout(segments):
                issues.append(ValidationIssue("thermal", "segments", warning["message"]))
    return issues
