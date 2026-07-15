"""Validated input models for LGJ Propulsion Analysis.

The UI is deliberately kept out of this module.  Every quantity has an explicit
engineering unit in its name so the calculation layer can also be used from a
script without relying on labels in the GUI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Iterable, TypeVar


class _ValueEnum(str, Enum):
    """String enum whose values are stable for project files."""

    def __str__(self) -> str:
        return self.value


class Oxidizer(_ValueEnum):
    LOX = "LOX"
    GOX = "GOX"
    H2O2_70 = "H2O2 (70%)"
    H2O2_80 = "H2O2 (80%)"
    H2O2_90 = "H2O2 (90%)"
    H2O2_100 = "H2O2 (100%)"
    N2O = "N2O"


class Fuel(_ValueEnum):
    ETHANOL_70 = "Ethanol (70%)"
    ETHANOL_80 = "Ethanol (80%)"
    ETHANOL_90 = "Ethanol (90%)"
    ETHANOL_100 = "Ethanol (100%)"
    RP1 = "RP-1"
    JET_A1 = "Jet A-1"
    LCH4 = "LCH4"
    GCH4 = "GCH4"
    LH2 = "LH2"
    GH2 = "GH2"
    PROPANE = "Propane"


class Coolant(_ValueEnum):
    LOX = "LOX"
    GOX = "GOX"
    H2O2_70 = "H2O2 (70%)"
    H2O2_80 = "H2O2 (80%)"
    H2O2_90 = "H2O2 (90%)"
    H2O2_100 = "H2O2 (100%)"
    N2O = "N2O"
    ETHANOL_70 = "Ethanol (70%)"
    ETHANOL_80 = "Ethanol (80%)"
    ETHANOL_90 = "Ethanol (90%)"
    ETHANOL_100 = "Ethanol (100%)"
    RP1 = "RP-1"
    JET_A1 = "Jet A-1"
    LCH4 = "LCH4"
    GCH4 = "GCH4"
    LH2 = "LH2"
    GH2 = "GH2"
    PROPANE = "Propane"
    WATER = "H2O"


class ExitConditionMode(_ValueEnum):
    EXPANSION_RATIO = "expansion_ratio"
    AMBIENT_PRESSURE = "ambient_pressure"


class EquilibriumMode(_ValueEnum):
    SHIFTING = "shifting_equilibrium"
    FROZEN_PRESSURE = "freezing_at_pressure_ratio"
    FROZEN_AREA = "freezing_at_area_ratio"


class EfficiencyMode(_ValueEnum):
    ESTIMATE = "estimate"
    DIRECT = "direct"


class SweepMode(_ValueEnum):
    FIXED = "fixed"
    RANGE = "range"


class SizeMode(_ValueEnum):
    NOMINAL_THRUST = "nominal_thrust"
    THROAT_DIAMETER = "throat_diameter"


class ContractionDefinitionMode(_ValueEnum):
    AREA_RATIO = "area_ratio"
    CHAMBER_DIAMETER = "chamber_diameter"


class LengthMode(_ValueEnum):
    DIRECT = "direct"
    CHARACTERISTIC_LENGTH = "characteristic_length"


class NozzleContourType(_ValueEnum):
    CONICAL = "conical"
    RAO_BELL = "rao_bell"


class Resolution(_ValueEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def section_count(self) -> int:
        return {self.LOW: 120, self.MEDIUM: 300, self.HIGH: 700}[self]


class RegenMaterial(_ValueEnum):
    CUCRZR = "CuCrZr"
    IN625 = "IN625"
    IN718 = "IN718"
    ALSI10MG = "AlSi10Mg"


class RadiationMaterial(_ValueEnum):
    C103 = "C103"
    TI64 = "Ti64"


class ChannelWidthMode(_ValueEnum):
    CHANNEL_WIDTH = "channel_width"
    RIB_WIDTH = "rib_width"
    CHANNEL_ANGLE = "channel_angle"


E = TypeVar("E", bound=Enum)


def _enum(value: E | str, enum_type: type[E], field_name: str) -> E:
    if isinstance(value, enum_type):
        return value
    text = str(value).strip().casefold()
    for member in enum_type:
        if text in (str(member.value).casefold(), member.name.casefold()):
            return member
    options = ", ".join(str(item.value) for item in enum_type)
    raise ValueError(f"{field_name} must be one of: {options}")


def _positive(value: float, field_name: str, *, allow_zero: bool = False) -> None:
    if not isfinite(value) or (value < 0 if allow_zero else value <= 0):
        relation = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field_name} must be finite and {relation}")


@dataclass(slots=True)
class RangeSpec:
    minimum: float
    maximum: float
    points: int

    def __post_init__(self) -> None:
        if not isfinite(self.minimum) or not isfinite(self.maximum):
            raise ValueError("range limits must be finite")
        if self.maximum <= self.minimum:
            raise ValueError("range maximum must be greater than minimum")
        if isinstance(self.points, bool) or self.points < 2:
            raise ValueError("range points must be an integer >= 2")
        self.points = int(self.points)

    def values(self) -> tuple[float, ...]:
        step = (self.maximum - self.minimum) / (self.points - 1)
        return tuple(self.minimum + index * step for index in range(self.points))


@dataclass(slots=True)
class EngineDefinition:
    name: str = "Untitled engine"
    description: str = ""
    chamber_pressure_bar: float = 20.0
    mixture_ratio: float = 2.5
    oxidizer: Oxidizer | str = Oxidizer.LOX
    fuel: Fuel | str = Fuel.RP1

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("engine name cannot be empty")
        _positive(self.chamber_pressure_bar, "chamber pressure")
        _positive(self.mixture_ratio, "mixture ratio")
        self.oxidizer = _enum(self.oxidizer, Oxidizer, "oxidizer")
        self.fuel = _enum(self.fuel, Fuel, "fuel")


@dataclass(slots=True)
class NozzleExitCondition:
    mode: ExitConditionMode | str = ExitConditionMode.AMBIENT_PRESSURE
    expansion_area_ratio: float | None = None
    ambient_pressure_atm: float | None = 1.0

    def __post_init__(self) -> None:
        self.mode = _enum(self.mode, ExitConditionMode, "exit condition mode")
        if self.mode is ExitConditionMode.EXPANSION_RATIO:
            if self.expansion_area_ratio is None or self.expansion_area_ratio <= 1.0:
                raise ValueError("expansion area ratio must be greater than 1")
        elif self.ambient_pressure_atm is None:
            raise ValueError("ambient pressure is required")
        else:
            _positive(self.ambient_pressure_atm, "ambient pressure")


@dataclass(slots=True)
class EquilibriumFlow:
    mode: EquilibriumMode | str = EquilibriumMode.SHIFTING
    freeze_pressure_ratio: float | None = None
    freeze_area_ratio: float | None = None

    def __post_init__(self) -> None:
        self.mode = _enum(self.mode, EquilibriumMode, "equilibrium mode")
        if self.mode is EquilibriumMode.FROZEN_PRESSURE:
            if self.freeze_pressure_ratio is None or self.freeze_pressure_ratio <= 1:
                raise ValueError("freeze pressure ratio must be greater than 1")
        if self.mode is EquilibriumMode.FROZEN_AREA:
            if self.freeze_area_ratio is None or self.freeze_area_ratio < 1:
                raise ValueError("freeze area ratio must be at least 1")


@dataclass(slots=True)
class NozzleEfficiency:
    mode: EfficiencyMode | str = EfficiencyMode.ESTIMATE
    value_percent: float | None = None

    def __post_init__(self) -> None:
        self.mode = _enum(self.mode, EfficiencyMode, "nozzle efficiency mode")
        if self.mode is EfficiencyMode.DIRECT:
            if self.value_percent is None or not 0 < self.value_percent <= 100:
                raise ValueError("direct nozzle efficiency must be in (0, 100]")


@dataclass(slots=True)
class ThrottleSettings:
    enabled: bool = False
    mode: SweepMode | str = SweepMode.FIXED
    fixed_percent: float = 100.0
    range: RangeSpec | None = None

    def __post_init__(self) -> None:
        self.mode = _enum(self.mode, SweepMode, "throttle mode")
        if not self.enabled:
            return
        if self.mode is SweepMode.FIXED:
            if not 0 < self.fixed_percent <= 100:
                raise ValueError("fixed throttle must be in (0, 100]")
        else:
            if self.range is None:
                raise ValueError("throttle range is required")
            if self.range.minimum <= 0 or self.range.maximum > 100:
                raise ValueError("throttle range must lie in (0, 100]")


@dataclass(slots=True)
class AmbientConditions:
    enabled: bool = False
    mode: SweepMode | str = SweepMode.FIXED
    fixed_pressure_atm: float = 1.0
    range: RangeSpec | None = None

    def __post_init__(self) -> None:
        self.mode = _enum(self.mode, SweepMode, "ambient mode")
        if not self.enabled:
            return
        if self.mode is SweepMode.FIXED:
            _positive(self.fixed_pressure_atm, "fixed ambient pressure", allow_zero=True)
        elif self.range is None:
            raise ValueError("ambient pressure range is required")
        elif self.range.minimum < 0:
            raise ValueError("ambient pressure cannot be negative")


@dataclass(slots=True)
class ThrustChamberSize:
    mode: SizeMode | str = SizeMode.NOMINAL_THRUST
    nominal_thrust_n: float | None = 1000.0
    thrust_ambient_pressure_atm: float = 1.0
    throat_diameter_mm: float | None = None

    def __post_init__(self) -> None:
        self.mode = _enum(self.mode, SizeMode, "size mode")
        if self.mode is SizeMode.NOMINAL_THRUST:
            if self.nominal_thrust_n is None:
                raise ValueError("nominal thrust is required")
            _positive(self.nominal_thrust_n, "nominal thrust")
            _positive(
                self.thrust_ambient_pressure_atm,
                "thrust ambient pressure",
                allow_zero=True,
            )
        elif self.throat_diameter_mm is None:
            raise ValueError("throat diameter is required")
        else:
            _positive(self.throat_diameter_mm, "throat diameter")


@dataclass(slots=True)
class ChamberLength:
    mode: LengthMode | str = LengthMode.CHARACTERISTIC_LENGTH
    chamber_length_mm: float | None = None
    cylindrical_length_mm: float | None = None
    characteristic_length_mm: float | None = 1000.0

    def __post_init__(self) -> None:
        self.mode = _enum(self.mode, LengthMode, "chamber length mode")
        if self.mode is LengthMode.DIRECT:
            if self.chamber_length_mm is None or self.cylindrical_length_mm is None:
                raise ValueError("Lc and Lcyl are required in direct length mode")
            _positive(self.chamber_length_mm, "Lc")
            _positive(self.cylindrical_length_mm, "Lcyl")
            if self.cylindrical_length_mm >= self.chamber_length_mm:
                raise ValueError("Lcyl must be smaller than Lc")
        elif self.characteristic_length_mm is None:
            raise ValueError("characteristic length L* is required")
        else:
            _positive(self.characteristic_length_mm, "characteristic length")


@dataclass(slots=True)
class NozzleGeometry:
    contour_type: NozzleContourType | str = NozzleContourType.CONICAL
    conical_half_angle_deg: float = 15.0
    bell_length_percent: float = 80.0
    throat_radius_ratio: float = 0.382

    def __post_init__(self) -> None:
        self.contour_type = _enum(self.contour_type, NozzleContourType, "contour type")
        if not 1 <= self.conical_half_angle_deg < 45:
            raise ValueError("conical nozzle half angle must be in [1, 45) degrees")
        if not 50 <= self.bell_length_percent <= 120:
            raise ValueError("bell length must be between 50% and 120% of a 15 degree cone")
        _positive(self.throat_radius_ratio, "Rn/Rt")


@dataclass(slots=True)
class ThrustChamberInput:
    contraction_mode: ContractionDefinitionMode | str = ContractionDefinitionMode.AREA_RATIO
    contraction_area_ratio: float = 4.0
    chamber_diameter_mm: float | None = None
    exit_condition: NozzleExitCondition = field(default_factory=NozzleExitCondition)
    equilibrium: EquilibriumFlow = field(default_factory=EquilibriumFlow)
    reaction_efficiency_percent: float = 98.0
    nozzle_efficiency: NozzleEfficiency = field(default_factory=NozzleEfficiency)
    throttle: ThrottleSettings = field(default_factory=ThrottleSettings)
    ambient: AmbientConditions = field(default_factory=AmbientConditions)
    size: ThrustChamberSize = field(default_factory=ThrustChamberSize)
    length: ChamberLength = field(default_factory=ChamberLength)
    contraction_angle_deg: float = 30.0
    chamber_radius_ratio: float = 0.5
    throat_upstream_radius_ratio: float = 1.5
    nozzle: NozzleGeometry = field(default_factory=NozzleGeometry)

    def __post_init__(self) -> None:
        self.contraction_mode = _enum(
            self.contraction_mode,
            ContractionDefinitionMode,
            "contraction definition mode",
        )
        if self.contraction_mode is ContractionDefinitionMode.AREA_RATIO:
            if not isfinite(self.contraction_area_ratio) or self.contraction_area_ratio <= 1:
                raise ValueError("contraction area ratio must be greater than 1")
        elif self.chamber_diameter_mm is None:
            raise ValueError("chamber diameter Dc is required")
        else:
            _positive(self.chamber_diameter_mm, "chamber diameter Dc")
        if not 0 < self.reaction_efficiency_percent <= 100:
            raise ValueError("reaction efficiency must be in (0, 100]")
        if not 5 <= self.contraction_angle_deg < 90:
            raise ValueError("contraction angle must be in [5, 90) degrees")
        if not 0 <= self.chamber_radius_ratio <= 1:
            raise ValueError("R2/R2max must be between 0 and 1")
        _positive(self.throat_upstream_radius_ratio, "R1/Rt")

    def resolved_contraction_area_ratio(self, throat_diameter_mm: float) -> float:
        """Return Ac/At for the selected contraction-definition basis.

        A direct ``Dc`` becomes determinate only after the throat diameter is
        known.  Keeping this conversion in the validated core model ensures
        CEA, performance sizing, contour generation, and reports all use the
        same circular-area relationship.
        """

        _positive(throat_diameter_mm, "throat diameter")
        if self.contraction_mode is ContractionDefinitionMode.AREA_RATIO:
            return float(self.contraction_area_ratio)
        chamber_diameter_mm = float(self.chamber_diameter_mm)  # type: ignore[arg-type]
        ratio = (chamber_diameter_mm / throat_diameter_mm) ** 2
        if not isfinite(ratio) or ratio <= 1.0:
            raise ValueError("chamber diameter Dc must be greater than throat diameter Dt")
        return ratio


@dataclass(slots=True)
class ThermalBarrierCoating:
    conductivity_w_mk: float = 1.5
    thickness_mm: float = 0.01

    def __post_init__(self) -> None:
        _positive(self.conductivity_w_mk, "coating conductivity")
        _positive(self.thickness_mm, "coating thickness")


@dataclass(slots=True)
class ChannelTriplet:
    inlet: float
    minimum: float
    outlet: float

    def __post_init__(self) -> None:
        for name, value in (
            ("inlet", self.inlet),
            ("minimum", self.minimum),
            ("outlet", self.outlet),
        ):
            _positive(value, name)


Location = float | str


def _location(value: Location, field_name: str) -> Location:
    if isinstance(value, str):
        normalized = value.strip().casefold()
        aliases = {
            "top": "top",
            "upstream": "top",
            "injector": "top",
            "bottom": "bottom",
            "downstream": "bottom",
            "exit": "bottom",
            "conv_boundary": "boundary",
            "contraction boundary": "boundary",
            "convergent boundary": "boundary",
            "cylindrical boundary": "boundary",
            "boundary": "boundary",
        }
        if normalized not in aliases:
            raise ValueError(f"{field_name} must be a distance in mm, 'top', or 'bottom'")
        return aliases[normalized]
    if not isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative finite distance")
    return float(value)


@dataclass(slots=True)
class SegmentRange:
    start: Location = "top"
    end: Location = "bottom"

    def __post_init__(self) -> None:
        self.start = _location(self.start, "segment start")
        self.end = _location(self.end, "segment end")
        if isinstance(self.start, float) and isinstance(self.end, float) and self.end <= self.start:
            raise ValueError("segment end must be downstream of segment start")

    def resolved(
        self,
        contour_length_mm: float,
        contraction_boundary_mm: float | None = None,
    ) -> tuple[float, float]:
        def resolve(value: Location) -> float:
            if value == "top":
                return 0.0
            if value == "bottom":
                return contour_length_mm
            if value == "boundary":
                if contraction_boundary_mm is None:
                    raise ValueError("contraction boundary location is required")
                return contraction_boundary_mm
            return float(value)

        start = resolve(self.start)
        end = resolve(self.end)
        if not 0 <= start < end <= contour_length_mm:
            raise ValueError("segment range lies outside the thrust chamber contour")
        return float(start), float(end)


@dataclass(slots=True)
class CoolantDefinition:
    coolant: Coolant | str
    inlet_pressure_bar: float
    inlet_temperature_k: float
    relative_mass_flow_percent: float

    def __post_init__(self) -> None:
        self.coolant = _enum(self.coolant, Coolant, "coolant")
        _positive(self.inlet_pressure_bar, "coolant inlet pressure")
        _positive(self.inlet_temperature_k, "coolant inlet temperature")
        if not 0 < self.relative_mass_flow_percent <= 100:
            raise ValueError("coolant relative mass flow must be in (0, 100]")


@dataclass(slots=True)
class RegenSegment:
    segment_id: str
    location: SegmentRange
    wall_thickness_mm: float
    channel_height_mm: ChannelTriplet
    channel_count: int
    coolant: CoolantDefinition | None = None
    inherit_coolant_from: str | None = None
    wall_conductivity_w_mk: float | None = None
    material: RegenMaterial | str | None = None
    width_mode: ChannelWidthMode | str = ChannelWidthMode.CHANNEL_WIDTH
    widths_mm: ChannelTriplet | None = None
    channel_angle_deg: float | None = None
    wall_roughness_enabled: bool = False
    roughness_height_mm: float = 0.04
    roughness_step_mm: float = 0.1
    coflow: bool = False
    coating: ThermalBarrierCoating | None = None

    def __post_init__(self) -> None:
        self.segment_id = self.segment_id.strip()
        if not self.segment_id:
            raise ValueError("regen segment id cannot be empty")
        _positive(self.wall_thickness_mm, "wall thickness")
        if isinstance(self.channel_count, bool) or self.channel_count < 1:
            raise ValueError("channel count must be an integer >= 1")
        self.channel_count = int(self.channel_count)
        if (self.coolant is None) == (self.inherit_coolant_from is None):
            raise ValueError("define coolant or inherit it from exactly one regen segment")
        if self.material is not None:
            self.material = _enum(self.material, RegenMaterial, "regen material")
        if (self.wall_conductivity_w_mk is None) == (self.material is None):
            raise ValueError("define either wall conductivity or wall material")
        if self.wall_conductivity_w_mk is not None:
            _positive(self.wall_conductivity_w_mk, "wall conductivity")
        self.width_mode = _enum(self.width_mode, ChannelWidthMode, "channel width mode")
        if self.width_mode is ChannelWidthMode.CHANNEL_ANGLE:
            if self.channel_angle_deg is None or not 0 < self.channel_angle_deg < 360 / self.channel_count:
                raise ValueError("channel angle must fit within each channel pitch")
        elif self.widths_mm is None:
            raise ValueError("channel/rib width triplet is required")
        if self.wall_roughness_enabled:
            _positive(self.roughness_height_mm, "roughness height")
            _positive(self.roughness_step_mm, "roughness step")


@dataclass(slots=True)
class FilmSegment:
    segment_id: str
    coolant: Coolant | str
    coolant_temperature_k: float | None
    relative_mass_flow_percent: float
    injection_location_mm: float | None = None
    chamber_contraction_boundary: bool = False
    inherit_temperature_from_regen: str | None = None
    discharge_coefficient: float = 0.6
    orifice_count: int = 30
    injector_face: bool = False

    def __post_init__(self) -> None:
        self.segment_id = self.segment_id.strip()
        if not self.segment_id:
            raise ValueError("film segment id cannot be empty")
        self.coolant = _enum(self.coolant, Coolant, "film coolant")
        location_modes = sum(
            (
                bool(self.chamber_contraction_boundary),
                bool(self.injector_face),
                self.injection_location_mm is not None,
            )
        )
        if location_modes != 1:
            raise ValueError(
                "select exactly one of injector face, chamber boundary, or an injection location"
            )
        if self.injection_location_mm is not None:
            _positive(self.injection_location_mm, "film injection location", allow_zero=True)
        if self.inherit_temperature_from_regen is None:
            if self.coolant_temperature_k is None:
                raise ValueError("film coolant temperature is required")
            _positive(self.coolant_temperature_k, "film coolant temperature")
        if not 0 < self.relative_mass_flow_percent < 100:
            raise ValueError("film mass flow percentage must be in (0, 100)")
        if not 0 < self.discharge_coefficient <= 1:
            raise ValueError("film discharge coefficient must be in (0, 1]")
        if isinstance(self.orifice_count, bool) or self.orifice_count < 1:
            raise ValueError("film orifice count must be an integer >= 1")
        self.orifice_count = int(self.orifice_count)


@dataclass(slots=True)
class RadiationSegment:
    segment_id: str
    location: SegmentRange
    emissivity: float = 0.8
    wall_conductivity_w_mk: float | None = None
    material: RadiationMaterial | str | None = None
    coating: ThermalBarrierCoating | None = None

    def __post_init__(self) -> None:
        self.segment_id = self.segment_id.strip()
        if not self.segment_id:
            raise ValueError("radiation segment id cannot be empty")
        if (self.wall_conductivity_w_mk is None) == (self.material is None):
            raise ValueError("define either radiation wall conductivity or material")
        if self.wall_conductivity_w_mk is not None:
            _positive(self.wall_conductivity_w_mk, "radiation wall conductivity")
        if self.material is not None:
            self.material = _enum(self.material, RadiationMaterial, "radiation material")
        if not 0 <= self.emissivity <= 1:
            raise ValueError("emissivity must be between 0 and 1")


ThermalSegment = RegenSegment | FilmSegment | RadiationSegment


@dataclass(slots=True)
class ThermalAnalysisInput:
    enabled: bool = False
    resolution: Resolution | str = Resolution.MEDIUM
    segments: list[ThermalSegment] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.resolution = _enum(self.resolution, Resolution, "thermal resolution")
        ids = [segment.segment_id for segment in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("thermal segment ids must be unique")
        if sum(
            segment.relative_mass_flow_percent
            for segment in self.segments
            if isinstance(segment, FilmSegment)
        ) >= 100:
            raise ValueError("total film mass flow percentage must be below 100")

    @property
    def section_count(self) -> int:
        return self.resolution.section_count

    @property
    def film_mass_fraction(self) -> float:
        if not self.enabled:
            return 0.0
        return sum(
            segment.relative_mass_flow_percent
            for segment in self.segments
            if isinstance(segment, FilmSegment)
        ) / 100.0

    def unresolved_links(self) -> tuple[str, ...]:
        regen_ids = {
            segment.segment_id
            for segment in self.segments
            if isinstance(segment, RegenSegment)
        }
        unresolved: list[str] = []
        for segment in self.segments:
            linked = None
            if isinstance(segment, RegenSegment):
                linked = segment.inherit_coolant_from
            elif isinstance(segment, FilmSegment):
                linked = segment.inherit_temperature_from_regen
            if linked is not None and linked not in regen_ids:
                unresolved.append(segment.segment_id)
        return tuple(unresolved)

    def overlap_warnings(
        self,
        contour_length_mm: float,
        contraction_boundary_mm: float | None = None,
    ) -> tuple[str, ...]:
        regens = [segment for segment in self.segments if isinstance(segment, RegenSegment)]
        radiations = [segment for segment in self.segments if isinstance(segment, RadiationSegment)]
        warnings: list[str] = []
        for regen in regens:
            r0, r1 = regen.location.resolved(contour_length_mm, contraction_boundary_mm)
            for radiation in radiations:
                q0, q1 = radiation.location.resolved(contour_length_mm, contraction_boundary_mm)
                if max(r0, q0) < min(r1, q1):
                    warnings.append(
                        f"regen segment '{regen.segment_id}' overlaps radiation segment "
                        f"'{radiation.segment_id}'"
                    )
        for index, left in enumerate(regens):
            l0, l1 = left.location.resolved(contour_length_mm, contraction_boundary_mm)
            for right in regens[index + 1 :]:
                r0, r1 = right.location.resolved(contour_length_mm, contraction_boundary_mm)
                if max(l0, r0) < min(l1, r1):
                    warnings.append(
                        f"regen segment '{left.segment_id}' overlaps regen segment "
                        f"'{right.segment_id}'"
                    )
        return tuple(warnings)


@dataclass(slots=True)
class AnalysisInput:
    engine: EngineDefinition = field(default_factory=EngineDefinition)
    thrust_chamber: ThrustChamberInput = field(default_factory=ThrustChamberInput)
    thermal: ThermalAnalysisInput = field(default_factory=ThermalAnalysisInput)


def validate_inputs(inputs: AnalysisInput) -> tuple[str, ...]:
    """Return non-fatal project warnings after dataclass validation.

    Constructors reject unsafe/ambiguous numerical input.  Broken segment links
    are warnings because a GUI project can temporarily contain one after the
    referenced segment is deleted; the UI can mark those segments inactive.
    """

    return tuple(
        f"thermal segment '{segment_id}' has an unresolved regen reference"
        for segment_id in inputs.thermal.unresolved_links()
    )


def film_segments(segments: Iterable[ThermalSegment]) -> tuple[FilmSegment, ...]:
    return tuple(segment for segment in segments if isinstance(segment, FilmSegment))
