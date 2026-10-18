"""Mass-based aqueous compositions shared by projects, CEA and cooling."""

from __future__ import annotations

from math import isfinite
import re
from typing import Any, Mapping


AQUEOUS_PROPELLANTS = {"h2o2": "H2O2", "ethanol": "Ethanol", "ipa": "IPA"}
_AQUEOUS = re.compile(
    r"(H2O2|Ethanol|IPA)(?:\s*\(?\s*([\d.eE+\-]+)\s*%\s*\)?)?", re.IGNORECASE
)


def mass_fraction(value: object, label: str = "propellant mass fraction") -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a number in (0, 1]") from error
    if not isfinite(result) or not 0.0 < result <= 1.0:
        raise ValueError(f"{label} must be finite and in (0, 1]")
    return result


def aqueous_composition(value: object) -> tuple[str, float | None] | None:
    """Recognize both base names and old percent-bearing project labels."""
    match = _AQUEOUS.fullmatch(str(value).strip())
    if match is None:
        return None
    base = AQUEOUS_PROPELLANTS[match[1].casefold()]
    fraction = None if match[2] is None else mass_fraction(float(match[2]) / 100.0)
    return base, fraction


def solution_name(base: str, fraction: float) -> str:
    return f"{base} ({100.0 * mass_fraction(fraction):.12g}%)"


def engine_selection(engine: Mapping[str, Any], kind: str) -> tuple[str, float]:
    """Decode a UI project without reinterpreting old percentages as volume %."""
    name = str(engine.get(kind, "")).strip()
    aqueous = aqueous_composition(name)
    if aqueous is None:
        return name, 1.0
    base, legacy_fraction = aqueous
    # An old label is authoritative, even when a caller merged it into new UI
    # defaults containing an unrelated, inactive percentage field.
    if legacy_fraction is not None:
        return base, legacy_fraction
    key = f"{kind}_mass_fraction_pct"
    try:
        fraction = float(engine.get(key, 100.0)) / 100.0
    except (ValueError, TypeError) as error:
        raise ValueError(f"{kind.capitalize()} mass fraction must be a number in (0, 100]%") from error
    return base, mass_fraction(fraction, f"{kind} mass fraction")


def engine_coolant_name(engine: Mapping[str, Any], kind: str) -> str:
    name, fraction = engine_selection(engine, kind)
    return solution_name(name, fraction) if aqueous_composition(name) else name
