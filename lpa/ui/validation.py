"""Strict validation shared by cooling dialogs and project analysis."""

from __future__ import annotations

import math
from typing import Any


def segment_numeric_issues(segment: dict[str, Any]) -> list[str]:
    """Validate active inputs without substituting or truncating user values."""
    issues: list[str] = []

    def number(key: str, *, zero: bool = False, integer: bool = False,
               maximum: float | None = None) -> None:
        label = key.replace("_", " ").replace(" mm", " (mm)").title()
        try:
            value = float(segment.get(key, ""))
            if not math.isfinite(value) or (value < 0 if zero else value <= 0):
                raise ValueError
            if integer and not value.is_integer():
                raise ValueError
            if maximum is not None and value > maximum:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            qualifier = "non-negative" if zero else "positive"
            kind = "integer" if integer else "number"
            limit = f" and no greater than {maximum:g}" if maximum is not None else ""
            issues.append(f"{label} must be a finite {qualifier} {kind}{limit}.")

    kind = segment.get("type")
    if kind in {"Regen", "Radiation"}:
        number("wall_thickness_mm")
        if segment.get("conductivity_mode") != "Material":
            number("thermal_conductivity")
        if segment.get("tbc_enabled"):
            number("tbc_conductivity_w_mk")
            number("tbc_thickness_mm")
        for key in ("x1", "x2"):
            if str(segment.get(key, "")).strip().upper() not in {
                "TOP", "BOTTOM", "CONV_BOUNDARY", "BOUNDARY",
                "CONTRACTION BOUNDARY", "CONVERGENT BOUNDARY",
            }:
                number(key, zero=True)
    if kind == "Regen":
        number("channel_count", integer=True)
        for key in ("channel_height_1_mm", "channel_height_min_mm", "channel_height_2_mm"):
            number(key)
        mode = segment.get("channel_width_mode", "Channel width")
        if mode == "Channel occupied angle":
            number("channel_angle_deg", maximum=360)
        else:
            prefix = "rib_width" if mode == "Rib width" else "channel_width"
            for suffix in ("1_mm", "min_mm", "2_mm"):
                number(f"{prefix}_{suffix}")
        source = segment.get("coolant_source_mode", "Custom coolant")
        if source != "Receive from Regen segment":
            number("coolant_inlet_pressure_bar")
            number("coolant_inlet_temperature_k")
        if source == "Custom coolant":
            number("relative_mass_flow_pct")
        if segment.get("roughness_enabled"):
            number("roughness_height_mm", zero=True)
            number("roughness_step_mm")
    elif kind == "Film":
        number("relative_mass_flow_pct", zero=True, maximum=100)
        if segment.get("position_mode") == "Specified location":
            number("position_mm", zero=True)
        if segment.get("temperature_mode") != "Temperature from Regen segment":
            number("coolant_temperature_k")
        if segment.get("orifice_enabled"):
            number("discharge_coefficient", maximum=1)
            number("orifice_count", integer=True)
    elif kind == "Radiation":
        number("emissivity", maximum=1)
    return issues
