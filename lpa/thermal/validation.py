"""Cross-segment validation independent of GUI widget state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from math import isfinite
from typing import Any

from .models import SegmentValidationReport, ValidationIssue


_MISSING = object()


def value_of(obj: object, *names: str, default: Any = _MISSING) -> Any:
    """Read the first mapping key or attribute present on an input model."""

    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    if default is _MISSING:
        joined = ", ".join(names)
        raise AttributeError(f"none of these fields are available: {joined}")
    return default


def enum_value(value: object) -> object:
    return getattr(value, "value", value)


def segment_id(segment: object, fallback_index: int | None = None) -> str:
    identifier = value_of(segment, "segment_id", "id", "name", default=None)
    if identifier is None:
        suffix = "" if fallback_index is None else f"-{fallback_index + 1}"
        return f"thermal-segment{suffix}"
    return str(identifier).strip()


def segment_kind(segment: object) -> str:
    explicit = value_of(segment, "kind", "type", "segment_type", default=None)
    text = str(enum_value(explicit) if explicit is not None else type(segment).__name__)
    normalised = "".join(character for character in text.casefold() if character.isalnum())
    if "regen" in normalised or "regenerative" in normalised:
        return "regen"
    if "radiat" in normalised:
        return "radiation"
    if "film" in normalised:
        return "film"
    return "unknown"


def thermal_segments(value: object) -> tuple[object, ...]:
    """Accept ThermalAnalysisInput, a sequence, or any iterable of segments."""

    if value is None:
        return ()
    if isinstance(value, Mapping) and "segments" in value:
        value = value["segments"]
    elif hasattr(value, "segments"):
        value = getattr(value, "segments")
    if isinstance(value, (str, bytes, Mapping)):
        if isinstance(value, Mapping):
            return (value,)
        raise TypeError("thermal segments must be an iterable, not text")
    if isinstance(value, Sequence):
        return tuple(value)
    if isinstance(value, Iterable):
        return tuple(value)
    raise TypeError("thermal segments must be an iterable")


def contour_x_coordinates(contour: object) -> tuple[float, ...]:
    """Extract SI axial coordinates from core results or a loose dictionary."""

    values = value_of(
        contour,
        "x_m",
        "axial_positions_m",
        "positions_m",
        "x",
        default=None,
    )
    scale = 1.0
    if values is None:
        values = value_of(contour, "x_mm", "axial_positions_mm", default=None)
        scale = 1.0e-3
    if values is None and isinstance(contour, Sequence) and contour:
        if isinstance(contour[0], Mapping) or hasattr(contour[0], "x_m"):
            values = [value_of(point, "x_m", "x") for point in contour]
    if values is None:
        raise ValueError("contour must provide x_m coordinates")
    coordinates = tuple(float(value) * scale for value in values)
    if len(coordinates) < 2:
        raise ValueError("contour needs at least two axial coordinates")
    if any(not isfinite(value) for value in coordinates):
        raise ValueError("contour x coordinates must be finite")
    if any(b <= a for a, b in zip(coordinates, coordinates[1:])):
        raise ValueError("contour x coordinates must be strictly increasing")
    return coordinates


_UPSTREAM = {"top", "start", "upstream", "injector", "head", "first", "최상단"}
_DOWNSTREAM = {"bottom", "end", "downstream", "exit", "last", "최하단"}
_BOUNDARY = {
    "boundary",
    "conv_boundary",
    "contraction boundary",
    "convergent boundary",
    "cylindrical boundary",
    "cylinder boundary",
}


def _resolve_location_mm_relative(
    value: object,
    x_min: float,
    x_max: float,
    contraction_boundary: float | None = None,
) -> float:
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in _UPSTREAM:
            return x_min
        if token in _DOWNSTREAM:
            return x_max
        if token in _BOUNDARY:
            if contraction_boundary is None:
                raise ValueError("contour does not provide a chamber/convergent boundary")
            return contraction_boundary
        raise ValueError(f"unsupported symbolic segment location: {value!r}")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError("segment location must be finite")
    return x_min + numeric * 1.0e-3


def resolve_segment_range(segment: object, contour: object) -> tuple[float, float]:
    """Resolve a regen/radiation range to absolute SI x coordinates."""

    x = contour_x_coordinates(contour)
    x_min, x_max = x[0], x[-1]
    boundary_index = value_of(contour, "chamber_end_index", default=None)
    contraction_boundary = x[int(boundary_index)] if boundary_index is not None else None
    start_m = value_of(segment, "x_start_m", "x1_m", default=None)
    end_m = value_of(segment, "x_end_m", "x2_m", default=None)
    if start_m is not None or end_m is not None:
        if start_m is None or end_m is None:
            raise ValueError("both SI segment range endpoints are required")
        start, end = float(start_m), float(end_m)
    else:
        start_mm = value_of(segment, "x_start_mm", "x1_mm", "start_mm", default=None)
        end_mm = value_of(segment, "x_end_mm", "x2_mm", "end_mm", default=None)
        if start_mm is not None or end_mm is not None:
            if start_mm is None or end_mm is None:
                raise ValueError("both segment range endpoints are required")
            start = _resolve_location_mm_relative(start_mm, x_min, x_max, contraction_boundary)
            end = _resolve_location_mm_relative(end_mm, x_min, x_max, contraction_boundary)
        else:
            location = value_of(segment, "location", "range", "position_range", default=None)
            if location is None:
                start_raw = value_of(segment, "start", default="top")
                end_raw = value_of(segment, "end", default="bottom")
            else:
                start_raw = value_of(location, "start", "x1", default="top")
                end_raw = value_of(location, "end", "x2", default="bottom")
            start = _resolve_location_mm_relative(start_raw, x_min, x_max, contraction_boundary)
            end = _resolve_location_mm_relative(end_raw, x_min, x_max, contraction_boundary)
    tolerance = max(1.0e-12, (x_max - x_min) * 1.0e-10)
    if start < x_min - tolerance or end > x_max + tolerance:
        raise ValueError(
            f"segment range [{start:g}, {end:g}] m lies outside contour "
            f"[{x_min:g}, {x_max:g}] m"
        )
    start = max(x_min, start)
    end = min(x_max, end)
    if end - start <= tolerance:
        raise ValueError("segment end must be downstream of its start")
    return start, end


def linked_regen_id(segment: object) -> str | None:
    linked = value_of(
        segment,
        "inherit_coolant_from",
        "linked_from",
        "coolant_source_segment_id",
        "source_segment_id",
        default=None,
    )
    if linked is None:
        return None
    text = str(linked).strip()
    return text or None


def linked_film_temperature_id(segment: object) -> str | None:
    linked = value_of(
        segment,
        "inherit_temperature_from_regen",
        "regen_temperature_source",
        "temperature_source_segment_id",
        default=None,
    )
    if linked is None:
        return None
    text = str(linked).strip()
    return text or None


def film_injection_x(segment: object, contour: object) -> float:
    x = contour_x_coordinates(contour)
    if bool(value_of(segment, "injector_face", "at_injector_face", default=False)):
        return x[0]
    if bool(value_of(segment, "chamber_contraction_boundary", "at_boundary", default=False)):
        index = value_of(contour, "chamber_end_index", default=None)
        if index is not None:
            return x[int(index)]
        radius = value_of(contour, "radius_m", "radius", default=None)
        if radius is not None:
            radius_values = tuple(float(value) for value in radius)
            maximum = max(radius_values)
            tolerance = maximum * 1.0e-6
            candidates = [
                index
                for index, value in enumerate(radius_values[:-1])
                if abs(value - maximum) <= tolerance
            ]
            if candidates:
                return x[candidates[-1]]
        return x[0]
    direct_m = value_of(segment, "injection_location_m", "injection_x_m", default=None)
    if direct_m is not None:
        return float(direct_m)
    direct_mm = value_of(
        segment,
        "injection_location_mm",
        "injection_x_mm",
        "position_mm",
        default=None,
    )
    if direct_mm is None:
        raise ValueError("film segment needs an injection position")
    return _resolve_location_mm_relative(direct_mm, x[0], x[-1])


def _overlap(first: tuple[float, float], second: tuple[float, float]) -> bool:
    scale = max(first[1] - first[0], second[1] - second[0], 1.0)
    return max(first[0], second[0]) < min(first[1], second[1]) - scale * 1.0e-12


def _cycle_nodes(graph: dict[str, str]) -> set[str]:
    cycles: set[str] = set()
    for origin in graph:
        path: list[str] = []
        positions: dict[str, int] = {}
        node: str | None = origin
        while node is not None and node in graph:
            if node in positions:
                cycles.update(path[positions[node] :])
                break
            if node in path:
                break
            positions[node] = len(path)
            path.append(node)
            node = graph.get(node)
    return cycles


def validate_segments(segments: object, contour: object) -> SegmentValidationReport:
    """Validate links, bounds, and mutually exclusive cooling regions.

    Broken links are warnings rather than errors so a GUI can retain and mark
    the affected segment inactive after its source segment is deleted.
    Regen/radiation overlap is an error because their outer boundary conditions
    cannot coexist at the same station.
    """

    segment_values = thermal_segments(segments)
    issues: list[ValidationIssue] = []
    identifiers = [segment_id(segment, index) for index, segment in enumerate(segment_values)]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for identifier in identifiers:
        if identifier in seen:
            duplicates.add(identifier)
        seen.add(identifier)
    for identifier in sorted(duplicates):
        issues.append(
            ValidationIssue(
                "error",
                "duplicate_segment_id",
                f"thermal segment id '{identifier}' is duplicated",
                (identifier,),
            )
        )

    regen_by_id = {
        identifier: segment
        for identifier, segment in zip(identifiers, segment_values)
        if segment_kind(segment) == "regen"
    }
    range_by_id: dict[str, tuple[float, float]] = {}
    for identifier, segment in zip(identifiers, segment_values):
        kind = segment_kind(segment)
        if kind in {"regen", "radiation"}:
            try:
                range_by_id[identifier] = resolve_segment_range(segment, contour)
            except (TypeError, ValueError, AttributeError) as error:
                issues.append(
                    ValidationIssue(
                        "error",
                        "invalid_segment_range",
                        f"segment '{identifier}' has an invalid range: {error}",
                        (identifier,),
                    )
                )
        elif kind == "film":
            try:
                injection = film_injection_x(segment, contour)
                x = contour_x_coordinates(contour)
                if not x[0] <= injection <= x[-1]:
                    raise ValueError("injection is outside the thrust chamber contour")
            except (TypeError, ValueError, AttributeError) as error:
                issues.append(
                    ValidationIssue(
                        "error",
                        "invalid_film_location",
                        f"film segment '{identifier}' is invalid: {error}",
                        (identifier,),
                    )
                )
        else:
            issues.append(
                ValidationIssue(
                    "error",
                    "unknown_segment_type",
                    f"segment '{identifier}' has an unsupported type",
                    (identifier,),
                )
            )

    link_graph: dict[str, str] = {}
    for identifier, segment in zip(identifiers, segment_values):
        kind = segment_kind(segment)
        linked = linked_regen_id(segment) if kind == "regen" else None
        if linked is not None:
            if linked == identifier:
                issues.append(
                    ValidationIssue(
                        "error",
                        "self_link",
                        f"regen segment '{identifier}' cannot inherit its own coolant",
                        (identifier,),
                    )
                )
            elif linked not in regen_by_id:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "unresolved_regen_link",
                        f"regen segment '{identifier}' references deleted/missing segment '{linked}' and is inactive",
                        (identifier, linked),
                    )
                )
            else:
                link_graph[identifier] = linked
        if kind == "film":
            linked = linked_film_temperature_id(segment)
            if linked is not None and linked not in regen_by_id:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "unresolved_film_link",
                        f"film segment '{identifier}' references deleted/missing regen '{linked}' and is inactive",
                        (identifier, linked),
                    )
                )

    cycles = _cycle_nodes(link_graph)
    if cycles:
        ordered = tuple(sorted(cycles))
        issues.append(
            ValidationIssue(
                "error",
                "coolant_link_cycle",
                "regen coolant links form a cycle: " + ", ".join(ordered),
                ordered,
            )
        )

    regens = [
        (identifier, segment)
        for identifier, segment in zip(identifiers, segment_values)
        if segment_kind(segment) == "regen" and identifier in range_by_id
    ]
    radiations = [
        (identifier, segment)
        for identifier, segment in zip(identifiers, segment_values)
        if segment_kind(segment) == "radiation" and identifier in range_by_id
    ]
    for regen_id, _ in regens:
        for radiation_id, _ in radiations:
            if _overlap(range_by_id[regen_id], range_by_id[radiation_id]):
                issues.append(
                    ValidationIssue(
                        "error",
                        "regen_radiation_overlap",
                        f"regen segment '{regen_id}' overlaps radiation segment '{radiation_id}'",
                        (regen_id, radiation_id),
                    )
                )

    for same_kind in (regens, radiations):
        for left_index, (left_id, _) in enumerate(same_kind):
            for right_id, _ in same_kind[left_index + 1 :]:
                if _overlap(range_by_id[left_id], range_by_id[right_id]):
                    is_regen = same_kind is regens
                    issues.append(
                        ValidationIssue(
                            "error" if is_regen else "warning",
                            "regen_overlap" if is_regen else "same_mode_overlap",
                            (
                                f"regen segments '{left_id}' and '{right_id}' overlap"
                                if is_regen
                                else f"thermal segments '{left_id}' and '{right_id}' overlap; the later segment takes precedence"
                            ),
                            (left_id, right_id),
                        )
                    )

    return SegmentValidationReport(tuple(issues))


__all__ = [
    "contour_x_coordinates",
    "enum_value",
    "film_injection_x",
    "linked_film_temperature_id",
    "linked_regen_id",
    "resolve_segment_range",
    "segment_id",
    "segment_kind",
    "thermal_segments",
    "validate_segments",
    "value_of",
]
