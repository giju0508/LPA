"""Public data contracts for thermal-analysis inputs, validation, and results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any, Literal

from lpa.core.models import (
    ChannelTriplet,
    CoolantDefinition,
    FilmSegment,
    RadiationSegment,
    RegenSegment,
    Resolution,
    SegmentRange,
    ThermalAnalysisInput,
    ThermalBarrierCoating,
    ThermalSegment,
)


# These values intentionally mirror lpa.core.models.Resolution.section_count.
# The core uses "section count" for the number of axial computation stations,
# so thermal arrays retain exactly this many samples and align with contours.
MESH_SECTION_COUNTS: dict[str, int] = {
    "low": 120,
    "medium": 300,
    "high": 700,
}
MESH_COUNTS = MESH_SECTION_COUNTS


def normalise_resolution(value: object) -> str:
    value = getattr(value, "value", value)
    text = str(value).strip().casefold()
    if text.startswith("resolution."):
        text = text.split(".", 1)[1]
    if text not in MESH_SECTION_COUNTS:
        options = ", ".join(MESH_SECTION_COUNTS)
        raise ValueError(f"thermal resolution must be one of: {options}")
    return text


def mesh_section_count(value: object) -> int:
    """Return the explicit Low/Medium/High axial cell count."""

    name = normalise_resolution(value)
    count = MESH_SECTION_COUNTS[name]
    model_count = getattr(value, "section_count", count)
    if int(model_count) != count:
        raise ValueError(
            f"resolution model mismatch: thermal.{name} is {count}, got {model_count}"
        )
    return count


class SegmentValidationError(ValueError):
    """Raised when a thermal segment set cannot be solved safely."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: Literal["error", "warning"]
    code: str
    message: str
    segment_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SegmentValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            details = "; ".join(issue.message for issue in self.errors)
            raise SegmentValidationError(details)


@dataclass(slots=True)
class ThermalAnalysisResult:
    """Axial temperature and heat-transfer arrays for plotting/reporting.

    Naming follows RPA: ``Twg`` is the hot-gas-facing surface, ``Twi`` is the
    TBC/base-wall interface (equal to Twg without coating), ``Twc`` is the cold
    side of the structural wall, and ``Tc`` is bulk coolant/environment.
    """

    resolution: str
    section_count: int
    x_m: tuple[float, ...]
    radius_m: tuple[float, ...]
    Twg_K: tuple[float, ...]
    Twi_K: tuple[float, ...]
    Twc_K: tuple[float, ...]
    Tc_K: tuple[float, ...]
    heat_flux_w_m2: tuple[float, ...]
    gas_coefficient_w_m2k: tuple[float, ...]
    coolant_coefficient_w_m2k: tuple[float, ...]
    coolant_pressure_bar: tuple[float, ...]
    coolant_velocity_m_s: tuple[float, ...]
    coolant_density_kg_m3: tuple[float, ...]
    film_effectiveness: tuple[float, ...]
    active_segment_id: tuple[str | None, ...]
    coolant_outlet_temperature_k: dict[str, float] = field(default_factory=dict)
    coolant_inlet_temperature_k: dict[str, float] = field(default_factory=dict)
    coolant_outlet_pressure_bar: dict[str, float] = field(default_factory=dict)
    coolant_inlet_pressure_bar: dict[str, float] = field(default_factory=dict)
    coolant_pressure_drop_bar: dict[str, float] = field(default_factory=dict)
    linked_coolant_source: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    iterations: int = 0
    converged: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    physical_validity: str = "screening"
    physical_issues: tuple[str, ...] = ()
    coolant_phase: tuple[str | None, ...] = ()
    coolant_vapor_quality: tuple[float, ...] = ()
    coolant_flow_regime: tuple[str | None, ...] = ()
    coolant_outlet_phase: dict[str, str] = field(default_factory=dict)
    coolant_outlet_enthalpy_j_kg: dict[str, float] = field(default_factory=dict)
    coolant_reynolds: tuple[float, ...] = ()
    coolant_nusselt: tuple[float, ...] = ()
    coolant_raw_coefficient_w_m2k: tuple[float, ...] = ()
    station_applicability: tuple[str | None, ...] = ()
    coolant_temperature_glide_k: tuple[float, ...] = ()
    coolant_boiling_mass_transfer_factor: tuple[float, ...] = ()
    coolant_boiling_convective_factor: tuple[float, ...] = ()
    coolant_wet_wall_assumed: tuple[bool | None, ...] = ()
    wall_temperature_min_k: tuple[float, ...] = ()
    wall_temperature_max_k: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        station_count = self.section_count
        if not self.coolant_phase:
            self.coolant_phase = (None,) * station_count
        if not self.coolant_vapor_quality:
            self.coolant_vapor_quality = (float("nan"),) * station_count
        if not self.coolant_flow_regime:
            self.coolant_flow_regime = (None,) * station_count
        for name in ("coolant_reynolds", "coolant_nusselt", "coolant_raw_coefficient_w_m2k",
                     "coolant_temperature_glide_k", "coolant_boiling_mass_transfer_factor",
                     "coolant_boiling_convective_factor","wall_temperature_min_k","wall_temperature_max_k"):
            if not getattr(self, name):
                setattr(self, name, (float("nan"),) * station_count)
        if not self.station_applicability:
            self.station_applicability = (None,) * station_count
        if not self.coolant_wet_wall_assumed:
            self.coolant_wet_wall_assumed = (None,) * station_count
        if self.physical_validity not in {"valid", "screening", "invalid", "unsupported"}:
            raise ValueError("unknown physical validity")
        arrays = {
            "x_m": self.x_m,
            "radius_m": self.radius_m,
            "Twg_K": self.Twg_K,
            "Twi_K": self.Twi_K,
            "Twc_K": self.Twc_K,
            "Tc_K": self.Tc_K,
            "heat_flux_w_m2": self.heat_flux_w_m2,
            "gas_coefficient_w_m2k": self.gas_coefficient_w_m2k,
            "coolant_coefficient_w_m2k": self.coolant_coefficient_w_m2k,
            "coolant_pressure_bar": self.coolant_pressure_bar,
            "coolant_velocity_m_s": self.coolant_velocity_m_s,
            "coolant_density_kg_m3": self.coolant_density_kg_m3,
            "film_effectiveness": self.film_effectiveness,
            "active_segment_id": self.active_segment_id,
            "coolant_phase": self.coolant_phase,
            "coolant_vapor_quality": self.coolant_vapor_quality,
            "coolant_flow_regime": self.coolant_flow_regime,
            "coolant_reynolds": self.coolant_reynolds,
            "coolant_nusselt": self.coolant_nusselt,
            "coolant_raw_coefficient_w_m2k": self.coolant_raw_coefficient_w_m2k,
            "station_applicability": self.station_applicability,
            "coolant_temperature_glide_k": self.coolant_temperature_glide_k,
            "coolant_boiling_mass_transfer_factor": self.coolant_boiling_mass_transfer_factor,
            "coolant_boiling_convective_factor": self.coolant_boiling_convective_factor,
            "coolant_wet_wall_assumed": self.coolant_wet_wall_assumed,
            "wall_temperature_min_k":self.wall_temperature_min_k,
            "wall_temperature_max_k":self.wall_temperature_max_k,
        }
        wrong = [name for name, values in arrays.items() if len(values) != station_count]
        if wrong:
            raise ValueError(
                f"thermal result arrays must contain {station_count} stations: "
                + ", ".join(wrong)
            )
        if any(not isfinite(value) for value in (*self.x_m, *self.radius_m)):
            raise ValueError("thermal mesh coordinates must be finite")

    @property
    def station_count(self) -> int:
        return self.section_count

    # GUI-friendly exact RPA labels.
    @property
    def Twg(self) -> tuple[float, ...]:
        return self.Twg_K

    @property
    def Twi(self) -> tuple[float, ...]:
        return self.Twi_K

    @property
    def Twc(self) -> tuple[float, ...]:
        return self.Twc_K

    @property
    def Tc(self) -> tuple[float, ...]:
        return self.Tc_K

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON/project-file friendly representation."""

        return asdict(self)


__all__ = [
    "ChannelTriplet",
    "CoolantDefinition",
    "FilmSegment",
    "MESH_COUNTS",
    "MESH_SECTION_COUNTS",
    "RadiationSegment",
    "RegenSegment",
    "Resolution",
    "SegmentRange",
    "SegmentValidationError",
    "SegmentValidationReport",
    "ThermalAnalysisInput",
    "ThermalAnalysisResult",
    "ThermalBarrierCoating",
    "ThermalSegment",
    "ValidationIssue",
    "mesh_section_count",
    "normalise_resolution",
]
