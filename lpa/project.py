"""LPA project serialization and UI-level validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .ui.input_views import validate_segment_layout


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
    target.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def load_project(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The selected file does not contain an LPA project object.")
    schema = payload.get("schema")
    if schema not in (PROJECT_SCHEMA, None):
        raise ValueError(f"Unsupported project schema: {schema}")
    for section in ("engine", "thrust_chamber", "thermal"):
        if section not in payload or not isinstance(payload[section], dict):
            raise ValueError(f"Project section '{section}' is missing or invalid.")
    return payload


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
    if value < 0 if allow_zero else value <= 0:
        qualifier = "zero or greater" if allow_zero else "greater than zero"
        issues.append(ValidationIssue(page, key, f"{label} must be {qualifier}."))
    return value


def validate_project(project: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    engine = project.get("engine", {})
    chamber = project.get("thrust_chamber", {})
    thermal = project.get("thermal", {})

    if not str(engine.get("engine_name", "")).strip():
        issues.append(ValidationIssue("engine", "engine_name", "Engine name is required."))
    _positive(issues, "engine", engine, "chamber_pressure_bar", "Chamber pressure")
    _positive(issues, "engine", engine, "mixture_ratio", "Mixture ratio")
    if not engine.get("oxidizer") or not engine.get("fuel"):
        issues.append(ValidationIssue("engine", "propellants", "Select both an oxidizer and a fuel."))

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
    if chamber.get("exit_condition_mode") == "Expansion area ratio" and exit_value is not None and exit_value <= 1:
        issues.append(ValidationIssue("thrust_chamber", "exit_condition_value", "Expansion area ratio must be greater than 1."))
    flow_model = chamber.get("flow_model")
    if flow_model != "Shifting equilibrium":
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
        if rao is not None and not 50 <= rao <= 120:
            issues.append(ValidationIssue("thrust_chamber", "rao_length_pct", "Rao length should be between 50% and 120% of Lc15."))
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
        try:
            iterations = int(thermal.get("thermal_max_iterations", 0))
            if not 10 <= iterations <= 1000:
                raise ValueError
        except (TypeError, ValueError):
            issues.append(ValidationIssue("thermal", "thermal_max_iterations", "Thermal solver iterations must be an integer from 10 to 1000."))
        segments = thermal.get("segments", [])
        if not isinstance(segments, list) or not segments:
            issues.append(ValidationIssue("thermal", "segments", "Add at least one cooling segment when thermal analysis is enabled."))
        else:
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
