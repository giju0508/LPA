"""Axial Bartz/regenerative/radiation/film thermal-analysis solver."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
import logging
from math import isfinite, nan, pi, sqrt
from typing import Any

from .coolants import (CoolantState, CoolantPropertyModel, coolant_state,
    coolant_state_from_enthalpy, coolant_saturation_pressure, get_coolant_model)
from .two_phase import TwoPhaseApplicabilityError, saturated_boiling
from .correlations import (
    adiabatic_wall_temperature,
    annular_wall_area,
    bartz_heat_transfer_coefficient,
    film_effectiveness as film_effectiveness_correlation,
    internal_flow_heat_transfer,
    radiative_heat_flux,
    rectangular_channel_geometry,
    rectangular_fin_area_ratio,
    cylindrical_conduction_resistance,
)
from .materials import get_material, material_reference_metadata
from .models import (
    MESH_SECTION_COUNTS,
    Resolution,
    ThermalAnalysisResult,
    mesh_section_count,
    normalise_resolution,
)
from .validation import (
    contour_x_coordinates,
    enum_value,
    film_injection_x,
    linked_film_temperature_id,
    linked_regen_id,
    resolve_segment_range,
    segment_id,
    segment_kind,
    thermal_segments,
    validate_segments,
    value_of,
)

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


@dataclass(slots=True)
class ThermalSolverSettings:
    """Optional numerical/physical overrides for :func:`analyze_thermal`."""

    resolution: Resolution | str = Resolution.MEDIUM
    chamber_pressure_pa: float | None = None
    stagnation_temperature_k: float | None = None
    characteristic_velocity_m_s: float | None = None
    total_mass_flow_kg_s: float | None = None
    throat_radius_curvature_ratio: float = 1.5
    gas_emissivity: float = 0.08
    ambient_temperature_k: float = 293.15
    external_convection_w_m2k: float = 0.0
    default_radiation_wall_thickness_mm: float = 1.0
    internal_flow_correlation: str = "gnielinski"
    film_mixing_coefficient: float = 1.0e-3
    film_surface_layer_mass_fraction: float = 0.10
    film_boundary_layer_thickness_m: float | None = None
    max_iterations: int = 200
    relative_tolerance: float = 2.0e-5
    strict_validation: bool = True
    coolant_properties: Mapping[str, object] = field(default_factory=dict)
    coolant_property_backend: str = "coolprop"
    coupled_max_iterations: int = 40
    two_phase_model: str = "auto"
    two_phase_max_quality: float = 0.7

    def __post_init__(self) -> None:
        normalise_resolution(self.resolution)
        if self.coolant_property_backend not in {"coolprop", "refprop", "screening"}:
            raise ValueError("coolant property backend must be coolprop, refprop or screening")
        if self.two_phase_model not in {"auto", "disabled", "chen_bennett", "li_wu"}:
            raise ValueError("unknown two-phase model")
        if not 0 < self.two_phase_max_quality <= 0.7:
            raise ValueError("Beta two-phase quality limit must be in (0,0.7]")
        if self.coupled_max_iterations < 2:
            raise ValueError("coupled max iterations must be >= 2")
        for name in (
            "throat_radius_curvature_ratio",
            "ambient_temperature_k",
            "default_radiation_wall_thickness_mm",
            "film_mixing_coefficient",
            "film_surface_layer_mass_fraction",
            "relative_tolerance",
        ):
            if not isfinite(float(getattr(self, name))) or float(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.film_boundary_layer_thickness_m is not None and self.film_boundary_layer_thickness_m <= 0:
            raise ValueError("film boundary-layer thickness must be positive")
        if not 0 <= self.gas_emissivity <= 1:
            raise ValueError("gas emissivity must be between zero and one")
        if self.external_convection_w_m2k < 0:
            raise ValueError("external convection coefficient cannot be negative")
        if isinstance(self.max_iterations, bool) or not isinstance(self.max_iterations,int) or self.max_iterations < 5:
            raise ValueError("max_iterations must be an integer >= 5")


def _read_setting(raw: object, *names: str, default: Any) -> Any:
    if raw is None:
        return default
    return value_of(raw, *names, default=default)


def _settings_from(raw: object, resolution_hint: object | None) -> ThermalSolverSettings:
    if isinstance(raw, ThermalSolverSettings):
        if resolution_hint is None:
            return raw
        # An explicitly constructed settings object owns its resolution.
        return raw
    resolution = _read_setting(
        raw,
        "resolution",
        "mesh_level",
        "thermal_resolution",
        default=resolution_hint if resolution_hint is not None else Resolution.MEDIUM,
    )
    return ThermalSolverSettings(
        resolution=resolution,
        chamber_pressure_pa=_read_setting(raw, "chamber_pressure_pa", default=None),
        stagnation_temperature_k=_read_setting(
            raw, "stagnation_temperature_k", "combustion_temperature_k", default=None
        ),
        characteristic_velocity_m_s=_read_setting(
            raw,
            "characteristic_velocity_m_s",
            "cstar_m_s",
            "delivered_cstar_m_s",
            default=None,
        ),
        total_mass_flow_kg_s=_read_setting(
            raw, "total_mass_flow_kg_s", "mass_flow_kg_s", default=None
        ),
        throat_radius_curvature_ratio=float(
            _read_setting(
                raw,
                "throat_radius_curvature_ratio",
                "throat_upstream_radius_ratio",
                default=1.5,
            )
        ),
        gas_emissivity=float(_read_setting(raw, "gas_emissivity", default=0.08)),
        ambient_temperature_k=float(
            _read_setting(raw, "ambient_temperature_k", default=293.15)
        ),
        external_convection_w_m2k=float(
            _read_setting(
                raw,
                "external_convection_w_m2k",
                "external_heat_transfer_coefficient_w_m2k",
                default=0.0,
            )
        ),
        default_radiation_wall_thickness_mm=float(
            _read_setting(raw, "default_radiation_wall_thickness_mm", default=1.0)
        ),
        internal_flow_correlation=str(
            _read_setting(raw, "internal_flow_correlation", default="gnielinski")
        ),
        film_mixing_coefficient=float(
            _read_setting(raw, "film_mixing_coefficient", default=1.0e-3)
        ),
        film_surface_layer_mass_fraction=float(
            _read_setting(raw, "film_surface_layer_mass_fraction", default=0.10)
        ),
        film_boundary_layer_thickness_m=_read_setting(
            raw, "film_boundary_layer_thickness_m", default=None
        ),
        max_iterations=int(_read_setting(raw, "max_iterations", default=200)),
        relative_tolerance=float(
            _read_setting(raw, "relative_tolerance", "tolerance", default=2.0e-5)
        ),
        strict_validation=bool(_read_setting(raw, "strict_validation", default=True)),
        coolant_properties=_read_setting(raw, "coolant_properties", default={}),
        coolant_property_backend=str(_read_setting(raw, "coolant_property_backend", default="coolprop")),
        coupled_max_iterations=int(_read_setting(raw, "coupled_max_iterations", default=40)),
        two_phase_model=str(_read_setting(raw, "two_phase_model", default="auto")),
        two_phase_max_quality=float(_read_setting(raw, "two_phase_max_quality", default=0.7)),
    )


def _linspace(start: float, stop: float, count: int) -> tuple[float, ...]:
    if count < 2:
        raise ValueError("mesh needs at least two stations")
    step = (stop - start) / (count - 1)
    return tuple(start + index * step for index in range(count))


def _interpolate(
    source_x: Sequence[float], source_y: Sequence[float], target_x: Sequence[float]
) -> tuple[float, ...]:
    if len(source_x) != len(source_y) or len(source_x) < 2:
        raise ValueError("interpolation source arrays must have equal lengths >= 2")
    output: list[float] = []
    right = 1
    for target in target_x:
        if target <= source_x[0]:
            output.append(float(source_y[0]))
            continue
        if target >= source_x[-1]:
            output.append(float(source_y[-1]))
            continue
        while right < len(source_x) - 1 and source_x[right] < target:
            right += 1
        left = right - 1
        fraction = (target - source_x[left]) / (source_x[right] - source_x[left])
        output.append(float(source_y[left]) + fraction * (float(source_y[right]) - float(source_y[left])))
    return tuple(output)


def _extract_radius(contour: object, source_x: Sequence[float]) -> tuple[float, ...]:
    values = value_of(contour, "radius_m", "r_m", "radius", "radii_m", default=None)
    scale = 1.0
    if values is None:
        values = value_of(contour, "radius_mm", "radii_mm", default=None)
        scale = 1.0e-3
    if values is None and isinstance(contour, Sequence) and contour:
        values = [value_of(point, "radius_m", "radius", "r_m") for point in contour]
    if values is None:
        area = value_of(contour, "area_m2", "areas_m2", default=None)
        if area is not None:
            values = [sqrt(float(item) / pi) for item in area]
    if values is None:
        raise ValueError("contour must provide radius_m or area_m2")
    radii = tuple(float(value) * scale for value in values)
    if len(radii) != len(source_x):
        raise ValueError("contour x and radius arrays must have equal length")
    if any(value <= 0 or not isfinite(value) for value in radii):
        raise ValueError("contour radii must be finite and positive")
    return radii


@dataclass(frozen=True, slots=True)
class _Mesh:
    x_m: tuple[float, ...]
    radius_m: tuple[float, ...]
    area_m2: tuple[float, ...]
    source_x_m: tuple[float, ...]
    source_radius_m: tuple[float, ...]
    throat_index: int
    chamber_end_index: int
    cell_left_m: tuple[float, ...]
    cell_right_m: tuple[float, ...]


def _build_mesh(contour: object, station_count: int) -> _Mesh:
    source_x = contour_x_coordinates(contour)
    source_radius = _extract_radius(contour, source_x)
    if len(source_x) == station_count:
        x_values = source_x
        radii = source_radius
    else:
        x_values = _linspace(source_x[0], source_x[-1], station_count)
        radii = _interpolate(source_x, source_radius, x_values)
    throat_x = value_of(contour, "throat_x_m", default=None)
    if throat_x is None:
        source_throat_index = int(
            value_of(
                contour,
                "throat_index",
                default=min(range(len(source_radius)), key=source_radius.__getitem__),
            )
        )
        throat_x = source_x[source_throat_index]
    throat_index = min(range(len(x_values)), key=lambda index: abs(x_values[index] - float(throat_x)))
    chamber_end_index_raw = value_of(contour, "chamber_end_index", default=None)
    if chamber_end_index_raw is None:
        chamber_end_x = source_x[0]
    else:
        chamber_end_x = source_x[int(chamber_end_index_raw)]
    if tuple(x_values) != tuple(source_x):
        # Retain geometric breakpoints while preserving the public array count.
        protected = {0, len(x_values) - 1}
        grid = list(x_values)
        for breakpoint in (float(throat_x), float(chamber_end_x)):
            if breakpoint <= grid[0] or breakpoint >= grid[-1]:
                continue
            nearest = min(
                (i for i in range(1, len(grid)-1) if i not in protected),
                key=lambda i: abs(grid[i]-breakpoint),
            )
            grid[nearest] = breakpoint
            protected.add(nearest)
        x_values = tuple(sorted(grid))
        radii = _interpolate(source_x, source_radius, x_values)
        throat_index = min(range(len(x_values)), key=lambda i: abs(x_values[i]-float(throat_x)))
    areas = tuple(pi * radius * radius for radius in radii)
    chamber_end_index = min(
        range(len(x_values)), key=lambda index: abs(x_values[index] - chamber_end_x)
    )
    left: list[float] = []
    right: list[float] = []
    for index, x_value in enumerate(x_values):
        left.append(source_x[0] if index == 0 else 0.5 * (x_values[index - 1] + x_value))
        right.append(source_x[-1] if index == len(x_values) - 1 else 0.5 * (x_value + x_values[index + 1]))
    return _Mesh(
        x_m=x_values,
        radius_m=radii,
        area_m2=areas,
        source_x_m=source_x,
        source_radius_m=source_radius,
        throat_index=throat_index,
        chamber_end_index=chamber_end_index,
        cell_left_m=tuple(left),
        cell_right_m=tuple(right),
    )


def _numeric_sequence(value: object) -> tuple[float, ...] | None:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return None
    if isinstance(value, Sequence):
        return tuple(float(item) for item in value)
    return None


def _resampled_field(
    source: object,
    names: tuple[str, ...],
    source_x: Sequence[float],
    target_x: Sequence[float],
    default: float | None = None,
) -> tuple[float, ...] | None:
    raw = value_of(source, *names, default=None)
    if raw is None:
        return None if default is None else (float(default),) * len(target_x)
    if isinstance(raw, (int, float)):
        return (float(raw),) * len(target_x)
    sequence = _numeric_sequence(raw)
    if sequence is None:
        raise ValueError(f"gas field {names[0]} must be numeric")
    if len(sequence) == 1:
        return (sequence[0],) * len(target_x)
    if len(sequence) == len(target_x) and tuple(source_x) == tuple(target_x):
        return sequence
    if len(sequence) != len(source_x):
        raise ValueError(
            f"gas field {names[0]} has {len(sequence)} values, expected {len(source_x)}"
        )
    return _interpolate(source_x, sequence, target_x)


def _area_mach_ratio(mach: float, gamma: float) -> float:
    exponent = (gamma + 1.0) / (2.0 * (gamma - 1.0))
    factor = 2.0 / (gamma + 1.0) * (1.0 + 0.5 * (gamma - 1.0) * mach * mach)
    return factor**exponent / mach


def _mach_from_area(area_ratio: float, gamma: float, supersonic: bool) -> float:
    area_ratio = max(1.0, float(area_ratio))
    if abs(area_ratio - 1.0) < 1.0e-10:
        return 1.0
    if supersonic:
        low, high = 1.0, 3.0
        while _area_mach_ratio(high, gamma) < area_ratio and high < 50.0:
            high *= 1.6
        for _ in range(80):
            middle = 0.5 * (low + high)
            if _area_mach_ratio(middle, gamma) < area_ratio:
                low = middle
            else:
                high = middle
    else:
        low, high = 1.0e-6, 1.0
        for _ in range(80):
            middle = 0.5 * (low + high)
            if _area_mach_ratio(middle, gamma) > area_ratio:
                low = middle
            else:
                high = middle
    return 0.5 * (low + high)


def _sutherland_viscosity(temperature_k: float) -> float:
    return 1.716e-5 * (temperature_k / 273.15) ** 1.5 * (273.15 + 110.4) / (
        temperature_k + 110.4
    )


@dataclass(frozen=True, slots=True)
class _GasData:
    chamber_pressure_pa: float
    stagnation_temperature_k: float
    characteristic_velocity_m_s: float
    total_mass_flow_kg_s: float
    throat_diameter_m: float
    throat_radius_of_curvature_m: float
    temperature_k: tuple[float, ...]
    gamma: tuple[float, ...]
    mach: tuple[float, ...]
    specific_heat_j_kgk: tuple[float, ...]
    viscosity_pa_s: tuple[float, ...]
    prandtl: tuple[float, ...]
    recovery_temperature_k: tuple[float, ...]
    reference_specific_heat_j_kgk: float
    reference_viscosity_pa_s: float
    reference_prandtl: float
    reference_gamma: float
    reference_source: str
    source: str
    pressure_pa: tuple[float, ...]
    h2o_mole_fraction: tuple[float, ...]
    co2_mole_fraction: tuple[float, ...]
    nozzle_regime: str
    property_issues: tuple[str, ...]


def _gas_sources(gas: object) -> tuple[object, object]:
    axial = value_of(gas, "thermodynamics", "axial_thermodynamics", default=None)
    performance = value_of(gas, "performance", default=None)
    if axial is None and value_of(gas, "mach", default=None) is not None:
        axial = gas
    if performance is None:
        performance = gas
    return axial, performance


def _prepare_gas(
    gas: object,
    contour: object,
    mesh: _Mesh,
    settings: ThermalSolverSettings,
) -> _GasData:
    if gas is None:
        raise ValueError("gas thermodynamics or performance result is required")
    axial, performance = _gas_sources(gas)
    if axial is not None:
        source_x = value_of(axial, "x_m", default=mesh.source_x_m)
        source_x = tuple(float(value) for value in source_x)
    else:
        source_x = mesh.source_x_m

    gamma_raw = value_of(performance, "gamma", default=1.22)
    gamma_sequence = _numeric_sequence(gamma_raw)
    gamma_default = float(gamma_sequence[0] if gamma_sequence else gamma_raw)
    gamma = (
        _resampled_field(axial, ("gamma",), source_x, mesh.x_m, gamma_default)
        if axial is not None
        else (gamma_default,) * len(mesh.x_m)
    )
    assert gamma is not None
    if any(value <= 1.0 for value in gamma):
        raise ValueError("gas gamma must be greater than one")

    throat_area = min(pi * radius * radius for radius in mesh.source_radius_m)
    throat_radius = sqrt(throat_area / pi)
    area_ratio = tuple(max(1.0, area / throat_area) for area in mesh.area_m2)
    mach = (
        _resampled_field(axial, ("mach", "mach_number"), source_x, mesh.x_m)
        if axial is not None
        else None
    )
    if mach is None:
        mach = tuple(
            _mach_from_area(ratio, gamma[index], index > mesh.throat_index)
            for index, ratio in enumerate(area_ratio)
        )

    chamber_pressure = settings.chamber_pressure_pa
    if chamber_pressure is None:
        pressure_bar = value_of(performance, "chamber_pressure_bar", default=None)
        pressure_pa = value_of(performance, "chamber_pressure_pa", default=None)
        if pressure_pa is not None:
            chamber_pressure = float(pressure_pa)
        elif pressure_bar is not None:
            chamber_pressure = float(pressure_bar) * 100_000.0
        elif axial is not None:
            pressure = _resampled_field(
                axial, ("pressure_pa", "pressure"), source_x, mesh.x_m
            )
            chamber_pressure = max(pressure) if pressure is not None else None
    if chamber_pressure is None or chamber_pressure <= 0:
        raise ValueError("chamber pressure is required for Bartz heat transfer")

    stagnation_temperature = settings.stagnation_temperature_k
    if stagnation_temperature is None:
        stagnation_temperature = value_of(
            performance,
            "combustion_temperature_k",
            "stagnation_temperature_k",
            default=None,
        )
    raw_temperature = (
        _resampled_field(
            axial,
            ("temperature_k", "temperature", "static_temperature_k"),
            source_x,
            mesh.x_m,
        )
        if axial is not None
        else None
    )
    if stagnation_temperature is None and raw_temperature is not None:
        stagnation_temperature = max(raw_temperature)
    if stagnation_temperature is None or float(stagnation_temperature) <= 0:
        raise ValueError("combustion/stagnation temperature is required")
    stagnation_temperature = float(stagnation_temperature)
    if raw_temperature is None:
        temperature = tuple(
            stagnation_temperature
            / (1.0 + 0.5 * (gamma[index] - 1.0) * mach[index] ** 2)
            for index in range(len(mesh.x_m))
        )
    else:
        temperature = raw_temperature

    gas_constant = float(value_of(performance, "gas_constant_j_kgk", default=355.0))
    property_issues: list[str] = list(value_of(axial, "warnings", default=()) or ())
    specific_heat = (
        _resampled_field(
            axial,
            ("specific_heat_j_kgk", "specific_heat", "cp_j_kgk", "cp"),
            source_x,
            mesh.x_m,
        )
        if axial is not None
        else None
    )
    if specific_heat is None:
        property_issues.append("gas cp derived from constant gamma/R; combustion-product cp not supplied")
        specific_heat = tuple(
            gamma_value * gas_constant / (gamma_value - 1.0) for gamma_value in gamma
        )
    viscosity = (
        _resampled_field(
            axial,
            ("viscosity_pa_s", "viscosity", "dynamic_viscosity_pa_s"),
            source_x,
            mesh.x_m,
        )
        if axial is not None
        else None
    )
    if viscosity is None:
        property_issues.append("gas viscosity uses air Sutherland fallback; combustion-product transport not supplied")
        viscosity = tuple(_sutherland_viscosity(value) for value in temperature)
    prandtl = (
        _resampled_field(axial, ("prandtl", "prandtl_number"), source_x, mesh.x_m)
        if axial is not None
        else None
    )
    if prandtl is None:
        property_issues.append("gas Prandtl uses constant 0.70 fallback; combustion-product transport not supplied")
        prandtl = (0.70,) * len(mesh.x_m)

    mass_flux = (
        _resampled_field(
            axial,
            ("mass_flux_kg_m2_s", "mass_flux"),
            source_x,
            mesh.x_m,
        )
        if axial is not None
        else None
    )
    total_mass_flow = settings.total_mass_flow_kg_s
    if total_mass_flow is None:
        total_mass_flow = value_of(
            performance,
            "total_mass_flow_kg_s",
            "mass_flow_kg_s",
            "hot_gas_mass_flow_kg_s",
            default=None,
        )
    if total_mass_flow is None and mass_flux is not None:
        total_mass_flow = mass_flux[mesh.throat_index] * throat_area

    characteristic_velocity = settings.characteristic_velocity_m_s
    if characteristic_velocity is None:
        characteristic_velocity = value_of(
            performance,
            "delivered_cstar_m_s",
            "ideal_cstar_m_s",
            "characteristic_velocity_m_s",
            "cstar_m_s",
            default=None,
        )
    if characteristic_velocity is None and mass_flux is not None:
        characteristic_velocity = chamber_pressure / mass_flux[mesh.throat_index]
    if characteristic_velocity is None or float(characteristic_velocity) <= 0:
        raise ValueError("characteristic velocity c* is required")
    characteristic_velocity = float(characteristic_velocity)
    if total_mass_flow is None:
        total_mass_flow = chamber_pressure / characteristic_velocity * throat_area
    if float(total_mass_flow) <= 0:
        raise ValueError("total engine mass flow must be positive")

    reference = {}
    missing_reference = False
    for suffix, fallback in (("specific_heat_j_kgk",specific_heat[0]),
                             ("viscosity_pa_s",viscosity[0]),("prandtl",prandtl[0]),
                             ("gamma",gamma[0])):
        candidate = value_of(axial, "bartz_reference_"+suffix, default=None)
        if candidate is None or not isfinite(float(candidate)) or float(candidate)<=0:
            missing_reference=True
            reference[suffix]=fallback
        else:
            reference[suffix]=float(candidate)
    reference_source = str(value_of(axial,"bartz_reference_source",default="") or "")
    if missing_reference or reference_source in {"","unavailable"}:
        reference_source = "provided first-station transport; frozen boundary-layer reference unavailable"
        property_issues.append("Bartz frozen chamber reference unavailable; first-station gas properties used for screening")
    recovery = tuple(
        adiabatic_wall_temperature(
            stagnation_temperature, mach[index], reference["gamma"], reference["prandtl"]
        )
        for index in range(len(mesh.x_m))
    )
    curvature = settings.throat_radius_curvature_ratio * throat_radius
    metadata = value_of(contour, "metadata", default={})
    if isinstance(metadata, Mapping):
        actual_mm = metadata.get("throat_upstream_curvature_radius_mm",metadata.get("R1_mm"))
        curvature = float(actual_mm)/1000 if actual_mm is not None else float(metadata.get("R1/Rt",settings.throat_radius_curvature_ratio))*throat_radius
    source_name = str(
        value_of(axial, "source", default=value_of(performance, "source", default="provided"))
    )
    return _GasData(
        chamber_pressure_pa=float(chamber_pressure),
        stagnation_temperature_k=stagnation_temperature,
        characteristic_velocity_m_s=characteristic_velocity,
        total_mass_flow_kg_s=float(total_mass_flow),
        throat_diameter_m=2.0 * throat_radius,
        throat_radius_of_curvature_m=curvature,
        temperature_k=tuple(temperature),
        gamma=tuple(gamma),
        mach=tuple(mach),
        specific_heat_j_kgk=tuple(specific_heat),
        viscosity_pa_s=tuple(viscosity),
        prandtl=tuple(prandtl),
        recovery_temperature_k=recovery,
        reference_specific_heat_j_kgk=reference["specific_heat_j_kgk"],
        reference_viscosity_pa_s=reference["viscosity_pa_s"],
        reference_prandtl=reference["prandtl"],
        reference_gamma=reference["gamma"],
        reference_source=reference_source,
        source=source_name,
        pressure_pa=tuple(_resampled_field(axial,("pressure_pa",),source_x,mesh.x_m) or (
            chamber_pressure/(1+0.5*(gamma[i]-1)*mach[i]**2)**(gamma[i]/(gamma[i]-1)) for i in range(len(mesh.x_m))
        )),
        h2o_mole_fraction=tuple(_resampled_field(axial,("h2o_mole_fraction",),source_x,mesh.x_m,nan) or (nan,)*len(mesh.x_m)),
        co2_mole_fraction=tuple(_resampled_field(axial,("co2_mole_fraction",),source_x,mesh.x_m,nan) or (nan,)*len(mesh.x_m)),
        nozzle_regime=str(value_of(axial,"nozzle_regime",default=value_of(performance,"nozzle_regime",default="unknown"))),
        property_issues=tuple(property_issues),
    )


@dataclass(frozen=True, slots=True)
class _Wall:
    thickness_m: float
    direct_conductivity_w_mk: float | None
    material: object | None
    coating_thickness_m: float
    coating_conductivity_w_mk: float

    def conductivity(self, temperature_k: float) -> float:
        if self.direct_conductivity_w_mk is not None:
            return self.direct_conductivity_w_mk
        return get_material(self.material).conductivity(temperature_k)


def _wall_for(
    segment: object,
    settings: ThermalSolverSettings,
    *,
    radiation: bool = False,
) -> _Wall:
    thickness_m = value_of(segment, "wall_thickness_m", "thickness_m", default=None)
    if thickness_m is None:
        thickness_mm = value_of(segment, "wall_thickness_mm", "thickness_mm", default=None)
        if thickness_mm is None and radiation:
            thickness_mm = settings.default_radiation_wall_thickness_mm
        if thickness_mm is None:
            raise ValueError(f"segment '{segment_id(segment)}' needs wall thickness")
        thickness_m = float(thickness_mm) * 1.0e-3
    thickness_m = float(thickness_m)
    if thickness_m <= 0:
        raise ValueError("wall thickness must be positive")
    direct = value_of(
        segment,
        "wall_conductivity_w_mk",
        "thermal_conductivity_w_mk",
        "conductivity_w_mk",
        default=None,
    )
    material = value_of(segment, "material", "wall_material", default=None)
    if direct is None and material is None:
        raise ValueError(f"segment '{segment_id(segment)}' needs wall material/conductivity")
    if direct is not None and float(direct) <= 0:
        raise ValueError("wall conductivity must be positive")
    coating = value_of(segment, "coating", "tbc", "thermal_barrier_coating", default=None)
    if coating is None:
        coating_thickness = 0.0
        coating_conductivity = 1.0
    else:
        coating_thickness = value_of(coating, "thickness_m", default=None)
        if coating_thickness is None:
            coating_thickness = float(value_of(coating, "thickness_mm")) * 1.0e-3
        coating_conductivity = float(
            value_of(coating, "conductivity_w_mk", "thermal_conductivity_w_mk")
        )
        if coating_thickness <= 0 or coating_conductivity <= 0:
            raise ValueError("TBC thickness and conductivity must be positive")
    return _Wall(
        thickness_m=thickness_m,
        direct_conductivity_w_mk=None if direct is None else float(direct),
        material=material,
        coating_thickness_m=float(coating_thickness),
        coating_conductivity_w_mk=coating_conductivity,
    )


def _triplet(value: object, scale: float) -> tuple[float, float, float]:
    if isinstance(value, (int, float)):
        result = (float(value) * scale,) * 3
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != 3:
            raise ValueError("channel geometry triplet must contain three values")
        result = tuple(float(item) * scale for item in value)  # type: ignore[assignment]
    else:
        result = (
            float(value_of(value, "inlet", "first", "value1")) * scale,
            float(value_of(value, "minimum", "min", "value_min")) * scale,
            float(value_of(value, "outlet", "last", "value2")) * scale,
        )
    if any(item <= 0 for item in result):
        raise ValueError("channel geometry values must be positive")
    return result


def _geometry_triplet(segment: object, base_name: str) -> tuple[float, float, float]:
    value_m = value_of(segment, f"{base_name}_m", default=None)
    if value_m is not None:
        return _triplet(value_m, 1.0)
    value_mm = value_of(segment, f"{base_name}_mm", default=None)
    if value_mm is not None:
        return _triplet(value_mm, 1.0e-3)
    raise ValueError(f"segment '{segment_id(segment)}' needs {base_name}")


def _triplet_at(
    values: tuple[float, float, float],
    x_m: float,
    start_m: float,
    throat_x_m: float,
    end_m: float,
) -> float:
    pivot = min(end_m - 1.0e-12, max(start_m + 1.0e-12, throat_x_m))
    if x_m <= pivot:
        fraction = (x_m - start_m) / max(1.0e-12, pivot - start_m)
        return values[0] + max(0.0, min(1.0, fraction)) * (values[1] - values[0])
    fraction = (x_m - pivot) / max(1.0e-12, end_m - pivot)
    return values[1] + max(0.0, min(1.0, fraction)) * (values[2] - values[1])


def _channel_dimensions(
    segment: object,
    x_m: float,
    radius_m: float,
    start_m: float,
    throat_x_m: float,
    end_m: float,
) -> tuple[float, float, int, float]:
    height_values = _geometry_triplet(segment, "channel_height")
    height = _triplet_at(height_values, x_m, start_m, throat_x_m, end_m)
    channel_count = int(value_of(segment, "channel_count", "channels", default=1))
    if channel_count < 1:
        raise ValueError("channel count must be >= 1")
    mode = str(enum_value(value_of(segment, "width_mode", "channel_width_mode", default="channel_width")))
    mode = mode.casefold().replace("-", "_").replace(" ", "_")
    pitch = 2.0 * pi * radius_m / channel_count
    if "angle" in mode:
        angle_deg = float(value_of(segment, "channel_angle_deg", "angle_deg"))
        width = radius_m * angle_deg * pi / 180.0
    else:
        width_values = _geometry_triplet(segment, "widths")
        specified = _triplet_at(width_values, x_m, start_m, throat_x_m, end_m)
        width = pitch - specified if "rib" in mode else specified
    if width <= 0 or width >= pitch * 1.001:
        raise ValueError(
            f"segment '{segment_id(segment)}' channel/rib geometry does not fit the circumference"
        )
    roughness = 0.0
    if bool(value_of(segment, "wall_roughness_enabled", "roughness_enabled", default=False)):
        roughness = value_of(segment, "roughness_height_m", default=None)
        if roughness is None:
            roughness = float(value_of(segment, "roughness_height_mm", default=0.04)) * 1.0e-3
        roughness = float(roughness)
    return width, height, channel_count, roughness


def _coolant_definition(segment: object) -> object | None:
    candidate = value_of(segment, "coolant", "coolant_definition", default=None)
    # On loose dictionaries ``coolant`` may be the coolant name itself.
    if candidate is not None and isinstance(candidate, (str, bytes)):
        return segment
    return candidate


def _coolant_name(definition: object) -> object:
    return value_of(definition, "coolant", "coolant_name", "name", "type")


def _property_override(
    source: object,
    name: str,
    default: float,
) -> float:
    aliases = {
        "density_kg_m3": ("density_kg_m3", "density"),
        "specific_heat_j_kgk": ("specific_heat_j_kgk", "cp_j_kgk", "specific_heat", "cp"),
        "conductivity_w_mk": ("conductivity_w_mk", "thermal_conductivity_w_mk", "conductivity"),
        "viscosity_pa_s": ("viscosity_pa_s", "dynamic_viscosity_pa_s", "viscosity"),
    }[name]
    value = value_of(source, *aliases, default=None) if source is not None else None
    return default if value is None else float(value)


def _coolant_state(
    definition: object,
    temperature_k: float,
    settings: ThermalSolverSettings,
    identifier: str,
    pressure_pa: float | None = None,
) -> CoolantState:
    name = _coolant_name(definition)
    model = get_coolant_model(name)
    if pressure_pa is None:
        pressure_pa = _coolant_inlet_pressure_pa(definition)
    base = (
        model.at_state(temperature_k, pressure_pa)
        if settings.coolant_property_backend == "coolprop"
        else coolant_state(name,temperature_k,pressure_pa,backend="REFPROP")
        if settings.coolant_property_backend == "refprop"
        else replace(model.at_temperature(temperature_k), pressure_pa=pressure_pa)
    )
    overrides: object | None = None
    if isinstance(settings.coolant_properties, Mapping):
        canonical = str(enum_value(name))
        overrides = settings.coolant_properties.get(identifier)
        if overrides is None:
            overrides = settings.coolant_properties.get(canonical)
    # A custom model can supply a temperature-aware state.
    if overrides is not None and (hasattr(overrides, "at_state") or hasattr(overrides, "at_temperature")):
        state = (
            overrides.at_temperature(temperature_k) if isinstance(overrides,CoolantPropertyModel) else
            overrides.at_state(temperature_k, pressure_pa)
            if hasattr(overrides, "at_state") else overrides.at_temperature(temperature_k)
        )
        if isinstance(state, CoolantState):
            state = replace(state,temperature_k=temperature_k,pressure_pa=pressure_pa)
            if not isfinite(state.enthalpy_j_kg):
                state = replace(state, temperature_k=temperature_k, pressure_pa=pressure_pa,
                    enthalpy_j_kg=state.specific_heat_j_kgk*temperature_k,
                    source="custom properties", issues=(*state.issues, "custom properties without thermodynamic enthalpy/phase model"))
            elif state.phase=="unknown":
                state=replace(state,issues=(*state.issues,"custom thermodynamic model does not identify coolant phase"))
            return state
        overrides = state
    density = _property_override(overrides, "density_kg_m3", base.density_kg_m3)
    density = _property_override(definition, "density_kg_m3", density)
    cp = _property_override(overrides, "specific_heat_j_kgk", base.specific_heat_j_kgk)
    cp = _property_override(definition, "specific_heat_j_kgk", cp)
    conductivity = _property_override(overrides, "conductivity_w_mk", base.conductivity_w_mk)
    conductivity = _property_override(definition, "conductivity_w_mk", conductivity)
    viscosity = _property_override(overrides, "viscosity_pa_s", base.viscosity_pa_s)
    viscosity = _property_override(definition, "viscosity_pa_s", viscosity)
    direct_names = ("density_kg_m3", "specific_heat_j_kgk", "cp_j_kgk", "conductivity_w_mk", "viscosity_pa_s")
    explicit = overrides is not None or any(value_of(definition, n, default=None) is not None for n in direct_names)
    if explicit:
        if not all(isfinite(v) and v > 0 for v in (density, cp, conductivity, viscosity)):
            raise ValueError("custom coolant thermophysical properties must be finite and positive")
        cp_override=any(value_of(source,n,default=None) is not None
            for source in (overrides,definition) if source is not None
            for n in ("specific_heat_j_kgk","cp_j_kgk","specific_heat","cp"))
        if not cp_override and base.source.startswith("CoolProp"):
            return replace(base,density_kg_m3=density,specific_heat_j_kgk=cp,
                conductivity_w_mk=conductivity,viscosity_pa_s=viscosity,
                issues=(*base.issues,"user property overrides require independent validation"))
        return CoolantState(density, cp, conductivity, viscosity,
            temperature_k=temperature_k, pressure_pa=pressure_pa, enthalpy_j_kg=cp*temperature_k,
            source="custom constant properties", issues=("custom properties have no independently validated phase boundary",))
    return base


def _coolant_inlet_temperature(definition: object) -> float:
    value = float(
        value_of(
            definition,
            "inlet_temperature_k",
            "coolant_temperature_k",
            "temperature_k",
        )
    )
    if value <= 0:
        raise ValueError("coolant inlet temperature must be positive")
    return value


def _coolant_inlet_pressure_pa(definition: object) -> float:
    pressure_bar = float(
        value_of(
            definition,
            "inlet_pressure_bar",
            "coolant_inlet_pressure_bar",
            "pressure_bar",
        )
    )
    if pressure_bar <= 0:
        raise ValueError("coolant inlet pressure must be positive")
    return pressure_bar * 100_000.0


def _coolant_mass_flow(
    definition: object, gas: _GasData
) -> float:
    direct = value_of(definition, "mass_flow_kg_s", "coolant_mass_flow_kg_s", default=None)
    if direct is not None:
        mass_flow = float(direct)
    else:
        percent = float(
            value_of(
                definition,
                "relative_mass_flow_percent",
                "mass_flow_percent",
                "relative_mass_flow_rate",
            )
        )
        mass_flow = gas.total_mass_flow_kg_s * percent / 100.0
    if mass_flow <= 0:
        raise ValueError("coolant mass flow must be positive")
    return mass_flow


def _gas_coefficient(
    index: int,
    wall_temperature_k: float,
    mesh: _Mesh,
    gas: _GasData,
) -> float:
    throat_area = pi * (0.5 * gas.throat_diameter_m) ** 2
    return bartz_heat_transfer_coefficient(
        chamber_pressure_pa=gas.chamber_pressure_pa,
        characteristic_velocity_m_s=gas.characteristic_velocity_m_s,
        throat_diameter_m=gas.throat_diameter_m,
        throat_radius_of_curvature_m=gas.throat_radius_of_curvature_m,
        area_ratio=max(1.0, mesh.area_m2[index] / throat_area),
        wall_temperature_k=max(1.0, wall_temperature_k),
        stagnation_temperature_k=gas.stagnation_temperature_k,
        mach=gas.mach[index],
        viscosity_pa_s=gas.reference_viscosity_pa_s,
        specific_heat_j_kgk=gas.reference_specific_heat_j_kgk,
        prandtl=gas.reference_prandtl,
        gamma=gas.reference_gamma,
    )


@dataclass(frozen=True, slots=True)
class _StationSolution:
    Twg: float
    Twi: float
    Twc: float
    heat_flux: float
    gas_h: float
    coolant_h: float
    iterations: int
    converged: bool
    coolant_cp: float
    coolant_pressure_gradient_pa_m: float = nan
    coolant_velocity_m_s: float = nan
    coolant_density_kg_m3: float = nan
    coolant_phase: str | None = None
    physical_issues: tuple[str, ...] = ()
    coolant_source: str = ""
    effective_cooling_area_ratio: float = nan
    fin_efficiency: float = nan
    coolant_flow_regime: str = "single_phase"
    coolant_reynolds: float = nan
    coolant_nusselt: float = nan
    coolant_raw_coefficient_w_m2k: float = nan
    applicability: str = "screening"


def _solve_regen_station(
    *,
    index: int,
    segment: object,
    identifier: str,
    wall: _Wall,
    coolant_definition: object,
    coolant_temperature_k: float,
    coolant_pressure_pa: float,
    coolant_mass_flow_kg_s: float,
    effective_recovery_temperature_k: float,
    segment_range: tuple[float, float],
    mesh: _Mesh,
    gas: _GasData,
    settings: ThermalSolverSettings,
    coolant_bulk_state: CoolantState | None = None,
    distance_from_inlet_m: float | None = None,
    cell_length_m: float | None = None,
) -> _StationSolution:
    start_m, end_m = segment_range
    cold_radius = mesh.radius_m[index] + wall.coating_thickness_m + wall.thickness_m
    width, height, channels, roughness = _channel_dimensions(
        segment,
        mesh.x_m[index],
        cold_radius,
        start_m,
        mesh.x_m[mesh.throat_index],
        end_m,
    )
    flow_area, hydraulic_diameter = rectangular_channel_geometry(width, height, channels)
    relative_roughness = roughness / hydraulic_diameter if roughness > 0 else 0.0
    wall_gas_temperature = min(
        effective_recovery_temperature_k - 1.0,
        max(coolant_temperature_k + 1.0, 0.45 * effective_recovery_temperature_k),
    )
    wall_cold_temperature = coolant_temperature_k + 20.0
    wall_interface_temperature = wall_gas_temperature
    heat_flux = 0.0
    gas_h = 1.0
    coolant_h = 1.0
    coolant_cp = 1.0
    converged = False
    physical_issues: list[str] = []
    bulk_state = coolant_bulk_state or _coolant_state(coolant_definition, coolant_temperature_k, settings, identifier, coolant_pressure_pa)
    boiling = None
    for iteration in range(1, settings.max_iterations + 1):
        # Internal-flow correlations use bulk thermodynamic/transport values.
        # Wall-film sampling would also corrupt the coolant energy balance.
        coolant_state = (bulk_state.saturated_liquid if bulk_state.phase == "two_phase" else bulk_state)
        if coolant_state is None:
            raise TwoPhaseApplicabilityError("saturated liquid transport unavailable")
        coolant_cp = coolant_state.specific_heat_j_kgk
        internal = internal_flow_heat_transfer(
            mass_flow_kg_s=coolant_mass_flow_kg_s,
            total_flow_area_m2=flow_area,
            hydraulic_diameter_m=hydraulic_diameter,
            density_kg_m3=coolant_state.density_kg_m3,
            viscosity_pa_s=coolant_state.viscosity_pa_s,
            conductivity_w_mk=coolant_state.conductivity_w_mk,
            specific_heat_j_kgk=coolant_state.specific_heat_j_kgk,
            relative_roughness=relative_roughness,
            correlation=settings.internal_flow_correlation,
            channel_aspect_ratio=width/height,
            heated_length_m=end_m-start_m,
            distance_from_inlet_m=distance_from_inlet_m,
            cell_length_m=cell_length_m,
        )
        physical_issues.extend(internal.warnings)
        if bulk_state.phase == "two_phase":
            wall_pressure = coolant_saturation_pressure(_coolant_name(coolant_definition),
                wall_cold_temperature, backend="REFPROP" if settings.coolant_property_backend=="refprop" else "HEOS")
            # Flux is per actual coolant heated area, not hot-wall area. The
            # previous fin-area estimate is updated along with the wall solve.
            heated_ratio = area_ratio if iteration > 1 else cold_radius/mesh.radius_m[index]
            boiling = saturated_boiling(state=bulk_state,
                mass_flow_kg_s=coolant_mass_flow_kg_s,total_flow_area_m2=flow_area,
                hydraulic_diameter_m=hydraulic_diameter,
                wall_temperature_k=wall_cold_temperature,
                wall_heat_flux_w_m2=heat_flux/heated_ratio if iteration>1 else 1.0,
                wall_saturation_pressure_pa=wall_pressure,
                model=settings.two_phase_model,max_quality=settings.two_phase_max_quality)
            internal = replace(internal,coefficient_w_m2k=boiling.coefficient_w_m2k,
                               velocity_m_s=boiling.velocity_m_s)
            physical_issues.extend(boiling.warnings)
        # Heat is referred to the hot gas surface; channel floor and both
        # sidewalls are weighted by rib fin efficiency at their actual radius.
        mean_wall_temperature = max(
            1.0, 0.5 * (wall_interface_temperature + wall_cold_temperature)
        )
        wall_k = wall.conductivity(mean_wall_temperature)
        area_ratio, fin_efficiency = rectangular_fin_area_ratio(
            channel_width_m=width, channel_height_m=height,
            pitch_m=2*pi*cold_radius/channels,
            coolant_coefficient_w_m2k=internal.coefficient_w_m2k,
            wall_conductivity_w_mk=wall_k,
        )
        area_ratio *= cold_radius/mesh.radius_m[index]
        coolant_h = internal.coefficient_w_m2k*area_ratio
        wall_resistance = cylindrical_conduction_resistance(
            mesh.radius_m[index]+wall.coating_thickness_m, wall.thickness_m, wall_k,
            reference_radius_m=mesh.radius_m[index],
        )
        coating_resistance = (
            cylindrical_conduction_resistance(mesh.radius_m[index], wall.coating_thickness_m, wall.coating_conductivity_w_mk)
            if wall.coating_thickness_m > 0
            else 0.0
        )
        post_gas_resistance = 1.0 / coolant_h + wall_resistance + coating_resistance
        gas_h = _gas_coefficient(index, wall_gas_temperature, mesh, gas)
        gas_radiation = radiative_heat_flux(
            gas.temperature_k[index], wall_gas_temperature, settings.gas_emissivity
        )
        numerator = gas_h * (
            effective_recovery_temperature_k - coolant_temperature_k
        ) + gas_radiation
        new_heat_flux = numerator / (1.0 + gas_h * post_gas_resistance)
        new_cold = coolant_temperature_k + new_heat_flux / coolant_h
        new_interface = new_cold + new_heat_flux * wall_resistance
        new_gas = new_interface + new_heat_flux * coating_resistance
        scale = max(1.0, new_gas)
        error = max(
            abs(new_gas - wall_gas_temperature),
            abs(new_interface - wall_interface_temperature),
            abs(new_cold - wall_cold_temperature),
        ) / scale
        # Under-relax wall-dependent Bartz and material conductivity.
        relaxation = 0.62
        wall_gas_temperature += relaxation * (new_gas - wall_gas_temperature)
        wall_interface_temperature += relaxation * (
            new_interface - wall_interface_temperature
        )
        wall_cold_temperature += relaxation * (new_cold - wall_cold_temperature)
        heat_flux += relaxation * (new_heat_flux - heat_flux)
        if error <= settings.relative_tolerance:
            converged = True
            break
    return _StationSolution(
        Twg=wall_gas_temperature,
        Twi=wall_interface_temperature,
        Twc=wall_cold_temperature,
        heat_flux=heat_flux,
        gas_h=gas_h,
        coolant_h=coolant_h,
        iterations=iteration,
        converged=converged,
        coolant_cp=bulk_state.specific_heat_j_kgk,
        # Darcy-Weisbach distributed loss.  The caller integrates this along
        # the actual contour-following channel length of each mesh cell.
        coolant_pressure_gradient_pa_m=boiling.pressure_gradient_pa_m if boiling else (
            internal.friction_factor
            / internal.hydraulic_diameter_m
            * 0.5
            * coolant_state.density_kg_m3
            * internal.velocity_m_s**2
        ),
        coolant_velocity_m_s=internal.velocity_m_s,
        coolant_density_kg_m3=boiling.homogeneous_density_kg_m3 if boiling else coolant_state.density_kg_m3,
        coolant_phase=bulk_state.phase,
        physical_issues=tuple(dict.fromkeys((*physical_issues, *bulk_state.issues))),
        coolant_source=bulk_state.source,
        effective_cooling_area_ratio=area_ratio,
        fin_efficiency=fin_efficiency,
        coolant_flow_regime=(boiling.model if boiling else "unknown_phase_screening"
            if bulk_state.phase == "unknown" else internal.flow_regime),
        coolant_reynolds=nan if boiling else internal.reynolds,
        coolant_nusselt=nan if boiling else internal.nusselt,
        coolant_raw_coefficient_w_m2k=internal.coefficient_w_m2k,
        applicability="screening" if boiling else getattr(internal, "applicability", "screening"),
    )


@dataclass(slots=True)
class _Arrays:
    Twg: list[float]
    Twi: list[float]
    Twc: list[float]
    Tc: list[float]
    heat_flux: list[float]
    gas_h: list[float]
    coolant_h: list[float]
    coolant_pressure_bar: list[float]
    coolant_velocity_m_s: list[float]
    coolant_density_kg_m3: list[float]
    active: list[str | None]
    coolant_phase: list[str | None]
    coolant_vapor_quality: list[float]
    coolant_flow_regime: list[str | None]
    coolant_reynolds: list[float]
    coolant_nusselt: list[float]
    coolant_raw_coefficient_w_m2k: list[float]
    station_applicability: list[str | None]

    @classmethod
    def empty(cls, count: int) -> "_Arrays":
        return cls(
            Twg=[nan] * count,
            Twi=[nan] * count,
            Twc=[nan] * count,
            Tc=[nan] * count,
            heat_flux=[nan] * count,
            gas_h=[nan] * count,
            coolant_h=[nan] * count,
            coolant_pressure_bar=[nan] * count,
            coolant_velocity_m_s=[nan] * count,
            coolant_density_kg_m3=[nan] * count,
            active=[None] * count,
            coolant_phase=[None] * count,
            coolant_vapor_quality=[nan] * count,
            coolant_flow_regime=[None] * count,
            coolant_reynolds=[nan] * count,
            coolant_nusselt=[nan] * count,
            coolant_raw_coefficient_w_m2k=[nan] * count,
            station_applicability=[None] * count,
        )


@dataclass(slots=True)
class _SolveStats:
    iterations: int = 0
    converged: bool = True

    def include(self, solution: _StationSolution) -> None:
        self.iterations = max(self.iterations, solution.iterations)
        self.converged = self.converged and solution.converged


@dataclass(slots=True)
class _RegenSolveResult:
    arrays: _Arrays
    outlet_temperatures_k: dict[str, float]
    inlet_temperatures_k: dict[str, float]
    outlet_pressures_bar: dict[str, float]
    inlet_pressures_bar: dict[str, float]
    pressure_drops_bar: dict[str, float]
    links: dict[str, str]
    stats: _SolveStats
    warnings: list[str]
    physical_issues: list[str] = field(default_factory=list)
    physical_validity: str = "valid"
    property_sources: dict[str, str] = field(default_factory=dict)
    fin_area_by_segment: dict[str, tuple[float, float]] = field(default_factory=dict)
    energy_balance_by_segment: dict[str, dict[str, float]] = field(default_factory=dict)
    outlet_phases: dict[str, str] = field(default_factory=dict)
    outlet_enthalpies_j_kg: dict[str, float] = field(default_factory=dict)
    property_metadata: dict[str,object] = field(default_factory=dict)
    segment_completion: dict[str, dict[str, object]] = field(default_factory=dict)
    inactive_ids: set[str] = field(default_factory=set)


def _inactive_segments(report: object) -> set[str]:
    inactive: set[str] = set()
    for issue in value_of(report, "warnings", default=()):
        if str(value_of(issue, "code", default="")).startswith("unresolved_"):
            identifiers = value_of(issue, "segment_ids", default=())
            if identifiers:
                inactive.add(str(identifiers[0]))
    return inactive


def _regen_order(regens: Sequence[object], inactive: set[str]) -> tuple[object, ...]:
    by_id = {segment_id(segment, index): segment for index, segment in enumerate(regens)}
    ordered: list[object] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visited or identifier in inactive:
            return
        if identifier in visiting:
            raise ValueError("regen coolant links contain a cycle")
        visiting.add(identifier)
        linked = linked_regen_id(by_id[identifier])
        if linked is not None and linked in by_id:
            visit(linked)
        visiting.remove(identifier)
        visited.add(identifier)
        ordered.append(by_id[identifier])

    for identifier in by_id:
        visit(identifier)
    return tuple(ordered)


def _root_coolant_definition(
    segment: object,
    regen_by_id: Mapping[str, object],
) -> object:
    current = segment
    visited: set[str] = set()
    while True:
        identifier = segment_id(current)
        if identifier in visited:
            raise ValueError("regen coolant links contain a cycle")
        visited.add(identifier)
        definition = _coolant_definition(current)
        linked = linked_regen_id(current)
        if linked is None:
            if definition is None:
                raise ValueError(f"regen segment '{identifier}' has no coolant definition")
            return definition
        if linked not in regen_by_id:
            raise ValueError(f"regen segment '{identifier}' has an unresolved coolant link")
        current = regen_by_id[linked]


def _coolant_identity_by_segment(
    regens: Sequence[object],
    inactive: set[str],
) -> dict[str, str]:
    """Return the effective coolant name for every solved Regen circuit.

    Linked Regen segments do not carry their own coolant definition, so the
    identity must be resolved through the same source chain used by the
    thermal calculation.  Keeping this in solver metadata prevents the UI
    from having to reconstruct that chain from project-editor fields.
    """

    regen_by_id = {
        segment_id(segment, index): segment
        for index, segment in enumerate(regens)
    }
    identities: dict[str, str] = {}
    for identifier, segment in regen_by_id.items():
        if identifier in inactive:
            continue
        try:
            definition = _root_coolant_definition(segment, regen_by_id)
            name = _coolant_name(definition)
        except (KeyError, TypeError, ValueError):
            continue
        if name is not None and str(enum_value(name)).strip():
            identities[identifier] = str(enum_value(name)).strip()
    return identities


def _indices_in_range(mesh: _Mesh, bounds: tuple[float, float]) -> list[int]:
    start, end = bounds
    indices = [i for i in range(len(mesh.x_m)) if
        max(mesh.cell_left_m[i], start) < min(mesh.cell_right_m[i], end)]
    if not indices:
        midpoint = 0.5 * (start + end)
        indices = [min(range(len(mesh.x_m)), key=lambda index: abs(mesh.x_m[index] - midpoint))]
    return indices


def _cell_width_in_range(mesh: _Mesh, index: int, bounds: tuple[float, float]) -> float:
    return max(
        0.0,
        min(mesh.cell_right_m[index], bounds[1])
        - max(mesh.cell_left_m[index], bounds[0]),
    )


def _channel_path_length_in_range(
    mesh: _Mesh, index: int, bounds: tuple[float, float]
) -> float:
    """Return the contour-following channel length inside one axial cell."""

    axial_width = _cell_width_in_range(mesh, index, bounds)
    if axial_width <= 0:
        return 0.0
    if index == 0:
        left, right = 0, 1
    elif index == len(mesh.x_m) - 1:
        left, right = index - 1, index
    else:
        left, right = index - 1, index + 1
    axial_span = mesh.x_m[right] - mesh.x_m[left]
    slope = (
        (mesh.radius_m[right] - mesh.radius_m[left]) / axial_span
        if axial_span > 0
        else 0.0
    )
    return axial_width * sqrt(1.0 + slope * slope)


def _advance_coolant_state(
    definition: object, identifier: str, state: CoolantState,
    enthalpy_j_kg: float, pressure_pa: float, settings: ThermalSolverSettings,
) -> CoolantState:
    name = _coolant_name(definition)
    override = settings.coolant_properties.get(identifier, settings.coolant_properties.get(str(enum_value(name))))
    if isinstance(override,CoolantPropertyModel):
        return override.screening_at_enthalpy(enthalpy_j_kg,pressure_pa)
    if override is not None and hasattr(override, "at_enthalpy"):
        return override.at_enthalpy(enthalpy_j_kg, pressure_pa)
    if override is not None and (hasattr(override,"at_state") or hasattr(override,"at_temperature")):
        temperature = state.temperature_k
        for _ in range(40):
            candidate = _coolant_state(definition,temperature,settings,identifier,pressure_pa)
            residual = candidate.enthalpy_j_kg-enthalpy_j_kg
            if abs(residual) < max(1.0,abs(enthalpy_j_kg))*1e-9:
                return candidate
            temperature = max(1.0,temperature-residual/candidate.specific_heat_j_kgk)
        raise ValueError("custom coolant enthalpy inversion failed; provide at_enthalpy")
    if settings.coolant_property_backend in {"coolprop", "refprop"}:
        advanced = coolant_state_from_enthalpy(name, enthalpy_j_kg, pressure_pa,
            temperature_hint_k=state.temperature_k,
            backend="REFPROP" if settings.coolant_property_backend=="refprop" else "HEOS")
        if override is not None or any(value_of(definition,n,default=None) is not None
                for n in ("density_kg_m3","conductivity_w_mk","viscosity_pa_s")):
            return _coolant_state(definition,advanced.temperature_k,settings,identifier,pressure_pa)
        return advanced
    if state.source.startswith("custom"):
        # Constant deterministic override contract; an external variable-cp
        # model must provide enthalpy and at_enthalpy for thermodynamic closure.
        temperature = state.temperature_k + (enthalpy_j_kg-state.enthalpy_j_kg)/state.specific_heat_j_kgk
        return _coolant_state(definition, max(1.0, temperature), settings, identifier, pressure_pa)
    model = get_coolant_model(name)
    temperature = state.temperature_k
    for _ in range(40):
        candidate = model.at_temperature(temperature)
        error = candidate.enthalpy_j_kg-enthalpy_j_kg
        if abs(error) < max(1.0, abs(enthalpy_j_kg))*1e-10:
            return replace(candidate, pressure_pa=pressure_pa)
        temperature = max(1.0, temperature-error/candidate.specific_heat_j_kgk)
    raise ValueError("screening coolant enthalpy inversion failed")


def _material_range_issue(wall: _Wall, minimum_k: float, maximum_k: float) -> str | None:
    if wall.material is None or wall.direct_conductivity_w_mk is not None:
        return None
    material = get_material(wall.material)
    low, high = material.valid_temperature_range_k
    if minimum_k < low or maximum_k > high:
        return (f"{material.name}: wall temperature outside conductivity data range [{low:g}, {high:g}] K; "
                "out-of-range conductivity queries clamp to endpoints; wall solution is diagnostic only")
    return None


def _solve_regens(
    *,
    regens: Sequence[object],
    inactive: set[str],
    effective_recovery_k: Sequence[float],
    contour: object,
    mesh: _Mesh,
    gas: _GasData,
    settings: ThermalSolverSettings,
) -> _RegenSolveResult:
    arrays = _Arrays.empty(len(mesh.x_m))
    outlets: dict[str, float] = {}
    inlets: dict[str, float] = {}
    pressure_outlets: dict[str, float] = {}
    pressure_inlets: dict[str, float] = {}
    pressure_drops: dict[str, float] = {}
    links: dict[str, str] = {}
    stats = _SolveStats()
    warnings: list[str] = []
    physical_issues: list[str] = []
    physical_validity = "valid"
    sources: dict[str, str] = {}
    fin_areas: dict[str, tuple[float, float]] = {}
    balances: dict[str, dict[str, float]] = {}
    outlet_phases: dict[str,str] = {}
    outlet_enthalpies: dict[str,float] = {}
    outlet_states: dict[str,CoolantState] = {}
    completed_segments: set[str] = set()
    property_metadata: dict[str,object] = {}
    heated_path_lengths: dict[str, float] = {}
    segment_completion: dict[str, dict[str, object]] = {}
    def issue(text: str, validity: str = "screening") -> None:
        nonlocal physical_validity
        if text not in physical_issues:
            LOGGER.warning("thermal applicability=%s: %s",validity,text)
        physical_issues.append(text)
        priorities = {"valid": 0, "screening": 1, "unsupported": 2, "invalid": 3}
        if priorities[validity] > priorities[physical_validity]:
            physical_validity = validity
    regen_by_id = {
        segment_id(segment, index): segment for index, segment in enumerate(regens)
    }
    for segment in _regen_order(regens, inactive):
        identifier = segment_id(segment)
        linked = linked_regen_id(segment)
        if linked is not None:
            if linked not in outlets:
                inactive.add(identifier)
                warnings.append(
                    f"regen segment '{identifier}' is inactive because source '{linked}' was not solved"
                )
                continue
            inlet_temperature = outlets[linked]
            inlet_pressure_pa = pressure_outlets[linked] * 100_000.0
            links[identifier] = linked
            source_state = outlet_states.get(linked)
            if (linked not in completed_segments or inlet_pressure_pa <= 0 or source_state is None
                    or getattr(source_state,"property_applicability","")=="unsupported"
                    or (source_state.phase=="unknown" and "EOS" in " ".join(source_state.issues))):
                inactive.add(identifier)
                issue(f"{identifier}: source circuit '{linked}' has no usable physical outlet state; linked circuit stopped", "unsupported")
                continue
        else:
            definition = _coolant_definition(segment)
            if definition is None:
                inactive.add(identifier)
                warnings.append(f"regen segment '{identifier}' has no coolant and is inactive")
                continue
            inlet_temperature = _coolant_inlet_temperature(definition)
            inlet_pressure_pa = _coolant_inlet_pressure_pa(definition)
        definition = _root_coolant_definition(segment, regen_by_id)
        mass_flow = _coolant_mass_flow(definition, gas)
        bounds = resolve_segment_range(segment, contour)
        wall = _wall_for(segment, settings)
        indices = _indices_in_range(mesh, bounds)
        coflow = bool(value_of(segment, "coflow", "same_direction", default=False))
        march = indices if coflow else list(reversed(indices))
        heated_distance = 0.0
        entrance_basis = "new specified channel inlet"
        if linked is not None:
            previous_segment = regen_by_id[linked]
            previous_bounds = resolve_segment_range(previous_segment, contour)
            previous_coflow = bool(value_of(previous_segment,"coflow","same_direction",default=False))
            previous_exit = previous_bounds[1] if previous_coflow else previous_bounds[0]
            this_inlet = bounds[0] if coflow else bounds[1]
            continuous = previous_coflow == coflow and abs(previous_exit-this_inlet) <= 1e-9
            if continuous:
                previous_wall = _wall_for(previous_segment, settings)
                junction_radius = _radius_at(mesh,this_inlet)
                previous_geometry = _channel_dimensions(previous_segment,this_inlet,
                    junction_radius+previous_wall.thickness_m+previous_wall.coating_thickness_m,
                    previous_bounds[0],mesh.x_m[mesh.throat_index],previous_bounds[1])
                this_geometry = _channel_dimensions(segment,this_inlet,
                    junction_radius+wall.thickness_m+wall.coating_thickness_m,
                    bounds[0],mesh.x_m[mesh.throat_index],bounds[1])
                continuous = all(abs(a-b) <= 1e-9*max(1.0,abs(a),abs(b))
                                 for a,b in zip(previous_geometry[:3],this_geometry[:3]))
            if continuous:
                heated_distance = heated_path_lengths.get(linked,0.0)
                entrance_basis = "continued from contiguous equal-section source channel"
            else:
                entrance_basis = "restarted at linked segment; boundary-layer continuity unverified"
                issue(f"{identifier}: linked channel entrance redevelopment assumed; boundary-layer continuity unverified")
        current_temperature = inlet_temperature
        current_pressure_pa = inlet_pressure_pa
        state = outlet_states[linked] if linked is not None else _coolant_state(definition, inlet_temperature, settings, identifier, inlet_pressure_pa)
        inlet_enthalpy = state.enthalpy_j_kg
        property_metadata[identifier]={"thermodynamic_source":state.thermodynamic_source,
            "transport_source":state.transport_source,
            "limits":asdict(state.property_limits) if state.property_limits is not None else None,
            "property_applicability":getattr(state,"property_applicability","screening"),
            "thermodynamic_applicability":getattr(state,"thermodynamic_applicability","screening"),
            "transport_applicability":getattr(state,"transport_applicability","screening"),
            "property_notes":getattr(state,"property_notes",()),
            "property_references":getattr(state,"property_references",()),
            "property_evidence":getattr(state,"property_evidence",()),
            "thermal_entrance_basis":entrance_basis}
        sources[identifier] = state.source
        LOGGER.info("regen start id=%s coolant=%s T_K=%g p_bar=%g mdot_kg_s=%g source=%s phase=%s",
            identifier,_coolant_name(definition),inlet_temperature,inlet_pressure_pa/1e5,mass_flow,state.source,state.phase)
        current_enthalpy = inlet_enthalpy
        integrated_heat = 0.0
        kinetic_energy_change_w = 0.0
        pressure_depleted = False
        inlets[identifier] = inlet_temperature
        pressure_inlets[identifier] = inlet_pressure_pa / 100_000.0
        for index in march:
            # Record the first unsupported state as well, so the UI can shade
            # detected phase boundaries without inventing a wall solution.
            arrays.Tc[index] = current_temperature
            arrays.coolant_pressure_bar[index] = current_pressure_pa/100_000.0
            arrays.coolant_phase[index] = state.phase
            arrays.coolant_vapor_quality[index] = state.vapor_quality_mass_fraction
            arrays.coolant_flow_regime[index] = state.phase
            arrays.active[index] = identifier
            arrays.station_applicability[index] = "unsupported"
            if current_pressure_pa <= 0:
                issue(f"{identifier}: coolant supply pressure exhausted; remaining stations unsupported", "invalid")
                break
            if state.phase == "unknown" and "EOS" in " ".join(state.issues):
                issue(f"{identifier}: EOS flash unavailable; coolant physical state unsupported", "unsupported")
                break
            if getattr(state,"property_applicability","")=="unsupported":
                arrays.coolant_flow_regime[index] = "unsupported_properties"
                for diagnostic in state.issues:
                    issue(f"{identifier}: {diagnostic}","unsupported")
                issue(f"{identifier}: coolant outside supported property data; wall march stopped", "unsupported")
                break
            if not all(isfinite(v) and v > 0 for v in (state.temperature_k,state.density_kg_m3,
                    state.specific_heat_j_kgk,state.conductivity_w_mk,state.viscosity_pa_s)):
                arrays.coolant_flow_regime[index] = "unsupported_properties"
                issue(f"{identifier}: finite positive coolant properties unavailable; wall march stopped", "unsupported")
                break
            arrays.Tc[index] = current_temperature
            channel_path_length = _channel_path_length_in_range(mesh,index,bounds)
            try:
                solution = _solve_regen_station(
                    index=index,segment=segment,identifier=identifier,wall=wall,
                    coolant_definition=definition,coolant_temperature_k=current_temperature,
                    coolant_pressure_pa=current_pressure_pa,coolant_mass_flow_kg_s=mass_flow,
                    effective_recovery_temperature_k=effective_recovery_k[index],
                    segment_range=bounds,mesh=mesh,gas=gas,settings=settings,coolant_bulk_state=state,
                    distance_from_inlet_m=heated_distance,cell_length_m=channel_path_length)
            except TwoPhaseApplicabilityError as error:
                arrays.coolant_flow_regime[index] = "unsupported_two_phase"
                issue(f"{identifier}: {error}; two-phase wall solution stopped", "unsupported")
                break
            stats.include(solution)
            arrays.Twg[index] = solution.Twg
            arrays.Twi[index] = solution.Twi
            arrays.Twc[index] = solution.Twc
            arrays.heat_flux[index] = solution.heat_flux
            arrays.gas_h[index] = solution.gas_h
            arrays.coolant_h[index] = solution.coolant_h
            arrays.coolant_pressure_bar[index] = current_pressure_pa / 100_000.0
            arrays.coolant_velocity_m_s[index] = solution.coolant_velocity_m_s
            arrays.coolant_density_kg_m3[index] = solution.coolant_density_kg_m3
            arrays.coolant_phase[index] = solution.coolant_phase
            arrays.coolant_flow_regime[index] = solution.coolant_flow_regime
            arrays.coolant_reynolds[index] = solution.coolant_reynolds
            arrays.coolant_nusselt[index] = solution.coolant_nusselt
            arrays.coolant_raw_coefficient_w_m2k[index] = solution.coolant_raw_coefficient_w_m2k
            arrays.station_applicability[index] = solution.applicability
            arrays.active[index] = identifier
            sources[identifier] = solution.coolant_source
            fin_areas[identifier] = (solution.effective_cooling_area_ratio, solution.fin_efficiency)
            for diagnostic in solution.physical_issues:
                issue(f"{identifier}: {diagnostic}")
            if solution.applicability == "unsupported":
                issue(f"{identifier}: coolant heat-transfer correlation outside its supported domain", "unsupported")
            if state.phase == "unknown":
                arrays.station_applicability[index] = "unsupported"
                issue(f"{identifier}: coolant phase unverified; single-phase correlation is diagnostic only", "unsupported")
            saturation = state.saturation_temperature_k
            if state.phase != "two_phase" and isfinite(saturation) and solution.Twc >= saturation:
                arrays.station_applicability[index] = "unsupported"
                issue(f"{identifier}: coolant-side wall exceeds saturation/bubble temperature; subcooled boiling/CHF/dryout unsupported", "unsupported")
            if state.phase in {"supercritical", "supercritical_liquid", "critical_point"}:
                issue(f"{identifier}: supercritical convection/heat-transfer deterioration requires validated variable-property correlation")
            if isfinite(state.pseudocritical_temperature_k) and min(current_temperature,solution.Twc) <= state.pseudocritical_temperature_k <= max(current_temperature,solution.Twc):
                arrays.station_applicability[index] = "unsupported"
                issue(f"{identifier}: wall/bulk temperature straddles pseudocritical cp peak; heat-transfer deterioration correlation unsupported", "unsupported")
            if state.phase in {"gas", "supercritical_gas", "supercritical"} and isfinite(state.speed_of_sound_m_s):
                if solution.coolant_velocity_m_s/state.speed_of_sound_m_s >= 0.3:
                    arrays.station_applicability[index] = "unsupported"
                    issue(f"{identifier}: coolant Mach >= 0.3; compressible channel momentum/energy model unavailable", "unsupported")
            model = get_coolant_model(_coolant_name(definition))
            liquid_identity = model.name in {"H2O","LOX", "LCH4", "LH2", "N2O", "Propane","LNG"} or model.name.startswith("Ethanol")
            if liquid_identity and index == march[0] and state.phase in {"gas", "supercritical_gas"}:
                arrays.station_applicability[index] = "invalid"
                issue(f"{identifier}: specified liquid coolant inlet is gaseous at its pressure/temperature", "invalid")
            material_issue = _material_range_issue(wall, solution.Twc, solution.Twi)
            if material_issue:
                arrays.station_applicability[index] = "unsupported"
                issue(f"{identifier}: {material_issue}", "unsupported")
            if wall.material is not None and get_material(wall.material).name in {"CuCrZr","C103","AlSi10Mg"}:
                issue(f"{identifier}: {get_material(wall.material).name} conductivity uses selected source/screening data; actual lot/build and manufacturing-condition validation required")
            if model.name.startswith("H2O2") or model.name == "N2O":
                issue(f"{identifier}: reactive coolant decomposition/material compatibility not modelled; temperature alone is not a stability criterion")
            if model.name in {"RP-1", "Jet A-1", "Propane", "LNG"}:
                issue(f"{identifier}: hydrocarbon cracking/coking and deposit resistance/lifetime require fuel/material-specific validation")
            heated_distance += channel_path_length
            if channel_path_length > 0:
                area = annular_wall_area(mesh.radius_m[index], channel_path_length)
                heat = solution.heat_flux*area
                integrated_heat += heat
                current_enthalpy += heat/mass_flow
                previous_state = state
                pressure_loss_pa = (
                    solution.coolant_pressure_gradient_pa_m
                    * channel_path_length
                )
                if pressure_loss_pa >= current_pressure_pa:
                    current_pressure_pa = 0.0
                    pressure_depleted = True
                else:
                    current_pressure_pa -= pressure_loss_pa
                if current_pressure_pa > 0:
                    state = _advance_coolant_state(definition, identifier, state,
                        current_enthalpy, current_pressure_pa, settings)
                    if previous_state.phase == "two_phase" or state.phase == "two_phase":
                        # Couple homogeneous acceleration with the outlet h-p
                        # flash. No slip/flow-pattern or choking claim is made.
                        cold_radius = mesh.radius_m[index]+wall.coating_thickness_m+wall.thickness_m
                        w,h,n,_ = _channel_dimensions(segment,mesh.x_m[index],cold_radius,
                            bounds[0],mesh.x_m[mesh.throat_index],bounds[1])
                        def boundary_mass_flux(position: float) -> float:
                            rad=_radius_at(mesh,position)+wall.coating_thickness_m+wall.thickness_m
                            bw,bh,bn,_=_channel_dimensions(segment,position,rad,
                                bounds[0],mesh.x_m[mesh.throat_index],bounds[1])
                            return mass_flow/(bw*bh*bn)
                        left=max(bounds[0],mesh.cell_left_m[index])
                        right=min(bounds[1],mesh.cell_right_m[index])
                        inlet_flux=boundary_mass_flux(left if coflow else right)
                        outlet_flux=boundary_mass_flux(right if coflow else left)
                        friction_outlet_pressure = current_pressure_pa
                        total_energy_target=previous_state.enthalpy_j_kg+heat/mass_flow
                        inlet_velocity=inlet_flux/previous_state.density_kg_m3
                        for momentum_iteration in range(30):
                            if state.phase == "unknown":
                                break
                            acceleration_loss = 0.5*(inlet_flux+outlet_flux)*(
                                outlet_flux/state.density_kg_m3-inlet_flux/previous_state.density_kg_m3)
                            target_pressure = friction_outlet_pressure-acceleration_loss
                            outlet_velocity=outlet_flux/state.density_kg_m3
                            target_enthalpy=total_energy_target-0.5*(outlet_velocity**2-inlet_velocity**2)
                            if target_pressure <= 0:
                                current_pressure_pa=0.0
                                pressure_depleted=True
                                state=replace(state,phase="unknown",pressure_pa=0.0)
                                break
                            if (abs(target_pressure-current_pressure_pa)<=max(.1,1e-7*current_pressure_pa)
                                    and abs(target_enthalpy-state.enthalpy_j_kg)<=max(.001,1e-8*abs(state.enthalpy_j_kg))):
                                break
                            current_pressure_pa=0.5*(current_pressure_pa+target_pressure)
                            current_enthalpy=0.5*(state.enthalpy_j_kg+target_enthalpy)
                            state=_advance_coolant_state(definition,identifier,state,
                                current_enthalpy,current_pressure_pa,settings)
                        else:
                            issue(f"{identifier}: two-phase momentum/enthalpy coupling did not converge", "unsupported")
                            state=replace(state,phase="unknown",issues=(*state.issues,"EOS/momentum outlet state not converged"))
                        kinetic_energy_change_w+=mass_flow*(total_energy_target-state.enthalpy_j_kg)
                        current_enthalpy=state.enthalpy_j_kg
                    current_temperature = state.temperature_k
                else:
                    state=replace(state,enthalpy_j_kg=current_enthalpy,phase="unknown",pressure_pa=0.0)
        # The final HP flash has no following cell to validate it. Classify
        # its phase and EOS issues before exposing this state to linked circuits
        # or an engine-feed feedback calculation.
        outlet_phases[identifier]=state.phase if current_pressure_pa>0 else "unknown"
        property_metadata[identifier]["last_state"] = {
            "temperature_k":state.temperature_k,"pressure_pa":current_pressure_pa,"phase":state.phase,
            "property_applicability":getattr(state,"property_applicability","screening"),
            "thermodynamic_applicability":getattr(state,"thermodynamic_applicability","screening"),
            "transport_applicability":getattr(state,"transport_applicability","screening"),
            "property_evidence":getattr(state,"property_evidence",()),
        }
        outlet_enthalpies[identifier]=state.enthalpy_j_kg
        if getattr(state,"property_applicability","")=="unsupported":
            issue(f"{identifier}: outlet coolant outside supported property data", "unsupported")
        if state.phase=="two_phase":
            issue(f"{identifier}: outlet coolant is bulk two-phase; Beta pre-dryout assumption, CHF/dryout not predicted")
            if ("&" in state.source or settings.two_phase_model=="disabled"
                    or not isfinite(state.vapor_quality_mass_fraction)
                    or state.saturated_liquid is None or state.saturated_vapor is None
                    or state.vapor_quality_mass_fraction>settings.two_phase_max_quality):
                issue(f"{identifier}: outlet two-phase state outside configured heat-transfer model", "unsupported")
        for diagnostic in state.issues:
            validity="unsupported" if state.phase=="unknown" and "EOS" in diagnostic else "screening"
            issue(f"{identifier} outlet: {diagnostic}",validity)
        if state.phase=="unknown" and "EOS" in " ".join(state.issues):
            issue(f"{identifier}: outlet EOS physical state unavailable", "unsupported")
        balances[identifier] = {
            "heat_pickup_w": integrated_heat,
            "coolant_enthalpy_rise_w": mass_flow*(state.enthalpy_j_kg-inlet_enthalpy),
            "two_phase_kinetic_energy_change_w":kinetic_energy_change_w,
            "residual_w": integrated_heat-mass_flow*(state.enthalpy_j_kg-inlet_enthalpy)-kinetic_energy_change_w,
        }
        if (bool(march) and all(isfinite(arrays.Twg[i]) for i in march) and current_pressure_pa>0
                and getattr(state,"property_applicability","")!="unsupported"
                and not (state.phase=="unknown" and "EOS" in " ".join(state.issues))):
            completed_segments.add(identifier)
        heated_path_lengths[identifier] = heated_distance
        segment_completion[identifier] = {
            "solved_wall_stations":sum(isfinite(arrays.Twg[i]) for i in march),
            "requested_wall_stations":len(march),
            "wall_march_completed":identifier in completed_segments,
            "heated_distance_at_outlet_m":heated_distance,
            "thermal_entrance_basis":entrance_basis,
            "outlet_property_applicability":getattr(state,"property_applicability","screening"),
        }
        outlets[identifier] = current_temperature
        outlet_states[identifier] = state
        LOGGER.info("regen outlet id=%s T_K=%g p_bar=%g h_J_kg=%g phase=%s x_mass=%g solved=%d/%d",
            identifier,current_temperature,current_pressure_pa/1e5,state.enthalpy_j_kg,state.phase,
            state.vapor_quality_mass_fraction,sum(isfinite(arrays.Twg[i]) for i in march),len(march))
        pressure_outlets[identifier] = current_pressure_pa / 100_000.0
        pressure_drops[identifier] = (
            inlet_pressure_pa - current_pressure_pa
        ) / 100_000.0
        if pressure_depleted:
            issue(f"{identifier}: pressure depleted; imposed coolant mass flow infeasible", "invalid")
            warnings.append(
                f"regen segment '{identifier}' Darcy-Weisbach pressure loss exhausted "
                "the available coolant inlet pressure"
            )
    return _RegenSolveResult(
        arrays=arrays,
        outlet_temperatures_k=outlets,
        inlet_temperatures_k=inlets,
        outlet_pressures_bar=pressure_outlets,
        inlet_pressures_bar=pressure_inlets,
        pressure_drops_bar=pressure_drops,
        links=links,
        stats=stats,
        warnings=warnings,
        physical_issues=list(dict.fromkeys(physical_issues)),
        physical_validity=physical_validity,
        property_sources=sources,
        fin_area_by_segment=fin_areas,
        energy_balance_by_segment=balances,
        outlet_phases=outlet_phases,
        outlet_enthalpies_j_kg=outlet_enthalpies,
        property_metadata=property_metadata,
        inactive_ids=set(inactive),
        segment_completion=segment_completion,
    )


def _film_temperature(
    film: object,
    identifier: str,
    injection_x_m: float,
    arrays: _Arrays | None,
    outlets: Mapping[str, float],
    mesh: _Mesh,
) -> float | None:
    linked = linked_film_temperature_id(film)
    if linked is None:
        temperature = value_of(
            film,
            "coolant_temperature_k",
            "temperature_k",
            "inlet_temperature_k",
            default=None,
        )
        return None if temperature is None else float(temperature)
    # A linked film is supplied from the circuit outlet. Sampling a channel
    # beside the injection coordinate can select an unrelated inlet state.
    if linked in outlets:
        return outlets[linked]
    if arrays is not None:
        candidates = [
            index
            for index, active in enumerate(arrays.active)
            if active == linked and isfinite(arrays.Tc[index])
        ]
        if candidates:
            nearest = min(candidates, key=lambda index: abs(mesh.x_m[index] - injection_x_m))
            return arrays.Tc[nearest]
    return outlets.get(linked)


def _film_profiles(
    *,
    films: Sequence[object],
    inactive: set[str],
    base_recovery_k: Sequence[float],
    source_arrays: _Arrays | None,
    source_outlets: Mapping[str, float],
    contour: object,
    mesh: _Mesh,
    settings: ThermalSolverSettings,
    source_completion: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...], list[str]]:
    effective_temperature = list(float(value) for value in base_recovery_k)
    total_effectiveness = [0.0] * len(mesh.x_m)
    warnings: list[str] = []
    film_rows: list[tuple[float, object, str]] = []
    for index, film in enumerate(films):
        identifier = segment_id(film, index)
        if identifier in inactive:
            continue
        injection = film_injection_x(film, contour)
        film_rows.append((injection, film, identifier))
    # Applying films in gas-flow order gives deterministic sequential mixing.
    film_rows.sort(key=lambda item: item[0])
    for injection, film, identifier in film_rows:
        linked = linked_film_temperature_id(film)
        if linked is not None and source_completion is not None and not source_completion.get(linked, {}).get("wall_march_completed", False):
            inactive.add(identifier)
            warnings.append(f"film segment '{identifier}' is inactive because linked Regen '{linked}' has no complete usable outlet state")
            continue
        coolant_temperature = _film_temperature(
            film,
            identifier,
            injection,
            source_arrays,
            source_outlets,
            mesh,
        )
        if coolant_temperature is None or coolant_temperature <= 0:
            inactive.add(identifier)
            warnings.append(
                f"film segment '{identifier}' has no valid coolant temperature and is inactive"
            )
            continue
        percent = float(
            value_of(
                film,
                "relative_mass_flow_percent",
                "mass_flow_percent",
                "film_mass_flow_percent",
            )
        )
        mass_fraction = percent / 100.0
        nearest = min(range(len(mesh.x_m)), key=lambda index: abs(mesh.x_m[index] - injection))
        boundary_thickness = value_of(
            film, "boundary_layer_thickness_m", "surface_layer_thickness_m", default=None
        )
        if boundary_thickness is None:
            boundary_thickness = settings.film_boundary_layer_thickness_m
        if boundary_thickness is None:
            boundary_thickness = max(1.0e-3, 0.02 * mesh.radius_m[nearest])
        mixing_coefficient = float(
            value_of(
                film,
                "mixing_coefficient",
                default=settings.film_mixing_coefficient,
            )
        )
        surface_fraction = float(
            value_of(
                film,
                "surface_layer_mass_fraction",
                default=settings.film_surface_layer_mass_fraction,
            )
        )
        for index, x_value in enumerate(mesh.x_m):
            effectiveness = film_effectiveness_correlation(
                x_value - injection,
                mass_fraction,
                float(boundary_thickness),
                mixing_coefficient=mixing_coefficient,
                surface_layer_mass_fraction=surface_fraction,
            )
            if effectiveness <= 0:
                continue
            effective_temperature[index] = (
                (1.0 - effectiveness) * effective_temperature[index]
                + effectiveness * coolant_temperature
            )
            total_effectiveness[index] = 1.0 - (
                1.0 - total_effectiveness[index]
            ) * (1.0 - effectiveness)
    return tuple(effective_temperature), tuple(total_effectiveness), warnings


def _radiation_station(
    *,
    index: int,
    wall: _Wall,
    effective_recovery_temperature_k: float,
    emissivity: float,
    mesh: _Mesh,
    gas: _GasData,
    settings: ThermalSolverSettings,
) -> _StationSolution:
    ambient = settings.ambient_temperature_k

    def state(cold_wall_temperature: float) -> tuple[float, float, float, float, float]:
        hot_radius = mesh.radius_m[index]
        interface_radius = hot_radius+wall.coating_thickness_m
        outer_radius = interface_radius+wall.thickness_m
        external_flux = (radiative_heat_flux(
            cold_wall_temperature, ambient, emissivity
        ) + settings.external_convection_w_m2k * (cold_wall_temperature - ambient)) * outer_radius/hot_radius
        interface = cold_wall_temperature
        wall_k = wall.conductivity(cold_wall_temperature)
        for _ in range(8):
            interface = cold_wall_temperature + external_flux * cylindrical_conduction_resistance(
                interface_radius, wall.thickness_m, wall_k, reference_radius_m=hot_radius,
            )
            wall_k = wall.conductivity(0.5 * (interface + cold_wall_temperature))
        gas_wall = interface + external_flux * (
            cylindrical_conduction_resistance(hot_radius, wall.coating_thickness_m, wall.coating_conductivity_w_mk)
            if wall.coating_thickness_m > 0
            else 0.0
        )
        gas_h = _gas_coefficient(index, gas_wall, mesh, gas)
        internal_flux = gas_h * (effective_recovery_temperature_k - gas_wall)
        internal_flux += radiative_heat_flux(
            gas.temperature_k[index], gas_wall, settings.gas_emissivity
        )
        return internal_flux - external_flux, gas_wall, interface, external_flux, gas_h

    low = ambient
    high = max(ambient + 1.0, effective_recovery_temperature_k, gas.temperature_k[index])
    low_residual = state(low)[0]
    high_residual = state(high)[0]
    expansions = 0
    while high_residual > 0 and expansions < 12:
        high = ambient + 1.5 * (high - ambient)
        high_residual = state(high)[0]
        expansions += 1
    if low_residual < 0:
        low = max(1.0, 0.5 * ambient)
        low_residual = state(low)[0]
    bracketed = low_residual >= 0 and high_residual <= 0
    converged = False
    iteration = 0
    if bracketed:
        for iteration in range(1, settings.max_iterations + 1):
            middle = 0.5 * (low + high)
            residual, gas_wall, interface, heat_flux, gas_h = state(middle)
            if abs(residual) <= max(1.0, abs(heat_flux)) * settings.relative_tolerance:
                low = high = middle
                converged = True
                break
            if residual > 0:
                low = middle
            else:
                high = middle
        cold_wall = 0.5 * (low + high)
        if not converged and abs(high - low) <= max(1.0, high) * settings.relative_tolerance:
            converged = True
    else:
        # Adiabatic limiting state if no numerical bracket is found.
        cold_wall = high
    _, gas_wall, interface, heat_flux, gas_h = state(cold_wall)
    return _StationSolution(
        Twg=gas_wall,
        Twi=interface,
        Twc=cold_wall,
        heat_flux=max(0.0, heat_flux),
        gas_h=gas_h,
        coolant_h=nan,
        iterations=iteration or settings.max_iterations,
        converged=converged,
        coolant_cp=nan,
    )


def _solve_radiation(
    *,
    radiations: Sequence[object],
    inactive: set[str],
    effective_recovery_k: Sequence[float],
    contour: object,
    mesh: _Mesh,
    gas: _GasData,
    settings: ThermalSolverSettings,
    arrays: _Arrays,
    stats: _SolveStats,
) -> list[str]:
    warnings: list[str] = []
    # Validation promises that the later radiation definition wins.
    for segment_index in reversed(range(len(radiations))):
        segment = radiations[segment_index]
        identifier = segment_id(segment, segment_index)
        if identifier in inactive:
            continue
        bounds = resolve_segment_range(segment, contour)
        wall = _wall_for(segment, settings, radiation=True)
        emissivity = float(
            value_of(segment, "emissivity", "outer_emissivity", default=0.8)
        )
        if not 0 <= emissivity <= 1:
            raise ValueError("radiation wall emissivity must be between zero and one")
        for index in _indices_in_range(mesh, bounds):
            if arrays.active[index] is not None:
                if not any(segment_id(row, i)==arrays.active[index] for i,row in enumerate(radiations)):
                    warnings.append(f"radiation segment '{identifier}' skipped an occupied regen station")
                continue
            solution = _radiation_station(
                index=index,
                wall=wall,
                effective_recovery_temperature_k=effective_recovery_k[index],
                emissivity=emissivity,
                mesh=mesh,
                gas=gas,
                settings=settings,
            )
            stats.include(solution)
            arrays.Twg[index] = solution.Twg
            arrays.Twi[index] = solution.Twi
            arrays.Twc[index] = solution.Twc
            arrays.Tc[index] = settings.ambient_temperature_k
            arrays.heat_flux[index] = solution.heat_flux
            arrays.gas_h[index] = solution.gas_h
            arrays.coolant_h[index] = nan
            arrays.active[index] = identifier
            arrays.station_applicability[index] = "screening"
            material_issue = _material_range_issue(wall, solution.Twc, solution.Twi)
            if material_issue:
                warnings.append(material_issue)
                arrays.station_applicability[index] = "unsupported"
            if wall.material is not None and get_material(wall.material).name in {"CuCrZr","C103","AlSi10Mg"}:
                warnings.append(f"{get_material(wall.material).name} conductivity uses selected source/screening data; actual lot/build and manufacturing-condition validation required")
    return warnings


def _disabled_result(
    mesh: _Mesh,
    resolution: str,
    section_count: int,
) -> ThermalAnalysisResult:
    missing = (nan,) * section_count
    return ThermalAnalysisResult(
        resolution=resolution,
        section_count=section_count,
        x_m=mesh.x_m,
        radius_m=mesh.radius_m,
        Twg_K=missing,
        Twi_K=missing,
        Twc_K=missing,
        Tc_K=missing,
        heat_flux_w_m2=missing,
        gas_coefficient_w_m2k=missing,
        coolant_coefficient_w_m2k=missing,
        coolant_pressure_bar=missing,
        coolant_velocity_m_s=missing,
        coolant_density_kg_m3=missing,
        film_effectiveness=(0.0,) * section_count,
        active_segment_id=(None,) * section_count,
        metadata={"enabled": False, "mesh_section_counts": dict(MESH_SECTION_COUNTS)},
    )


def _radius_at(mesh: _Mesh, x_m: float) -> float:
    """Linearly interpolate the thermal-mesh radius at an exact location."""

    if x_m <= mesh.x_m[0]:
        return mesh.radius_m[0]
    if x_m >= mesh.x_m[-1]:
        return mesh.radius_m[-1]
    for right in range(1, len(mesh.x_m)):
        if mesh.x_m[right] >= x_m:
            left = right - 1
            span = mesh.x_m[right] - mesh.x_m[left]
            fraction = (x_m - mesh.x_m[left]) / max(1.0e-15, span)
            return mesh.radius_m[left] + fraction * (
                mesh.radius_m[right] - mesh.radius_m[left]
            )
    return mesh.radius_m[-1]


def _contour_radius_at(contour: object, mesh: _Mesh, x_m: float) -> float:
    """Interpolate the original contour, retaining exact geometry breakpoints."""

    x_values = value_of(contour, "x_m", default=None)
    radius_values = value_of(contour, "radius_m", default=None)
    if x_values is None or radius_values is None or len(x_values) != len(radius_values):
        return _radius_at(mesh, x_m)
    if x_m <= x_values[0]:
        return float(radius_values[0])
    if x_m >= x_values[-1]:
        return float(radius_values[-1])
    for right in range(1, len(x_values)):
        if x_values[right] >= x_m:
            left = right - 1
            span = float(x_values[right]) - float(x_values[left])
            fraction = (x_m - float(x_values[left])) / max(1.0e-15, span)
            return float(radius_values[left]) + fraction * (
                float(radius_values[right]) - float(radius_values[left])
            )
    return float(radius_values[-1])


def _angle_channel_geometry_by_segment(
    regens: Sequence[object],
    inactive: set[str],
    contour: object,
    mesh: _Mesh,
    settings: ThermalSolverSettings,
) -> dict[str, dict[str, tuple[float, float, float]]]:
    """Report width/rib triplets implied by an occupied angle definition.

    The three stations follow the input convention: segment start, throat
    (clamped into the segment range), and segment end.  Values are emitted in
    millimetres so consumers do not need to reconstruct geometry from the
    project-editor representation.
    """

    result: dict[str, dict[str, tuple[float, float, float]]] = {}
    throat_x_m = float(
        value_of(contour, "throat_x_m", default=mesh.x_m[mesh.throat_index])
    )
    for index, segment in enumerate(regens):
        identifier = segment_id(segment, index)
        if identifier in inactive:
            continue
        mode = str(
            enum_value(
                value_of(
                    segment,
                    "width_mode",
                    "channel_width_mode",
                    default="channel_width",
                )
            )
        ).casefold().replace("-", "_").replace(" ", "_")
        if "angle" not in mode:
            continue
        start_m, end_m = resolve_segment_range(segment, contour)
        middle_m = min(end_m, max(start_m, throat_x_m))
        points = (start_m, middle_m, end_m)
        angle_rad = float(
            value_of(segment, "channel_angle_deg", "angle_deg")
        ) * pi / 180.0
        channel_count = int(value_of(segment, "channel_count", "channels", default=1))
        wall = _wall_for(segment,settings)
        radii = tuple(_contour_radius_at(contour, mesh, x_value)+wall.thickness_m+wall.coating_thickness_m for x_value in points)
        widths_m = tuple(radius * angle_rad for radius in radii)
        ribs_m = tuple(
            2.0 * pi * radius / channel_count - width
            for radius, width in zip(radii, widths_m)
        )
        result[identifier] = {
            "channel_width_mm": tuple(value * 1000.0 for value in widths_m),
            "rib_width_mm": tuple(value * 1000.0 for value in ribs_m),
        }
    return result


def analyze_thermal(
    contour: object,
    gas: object | None = None,
    segments: object | None = None,
    settings: object | None = None,
) -> ThermalAnalysisResult:
    """Run preliminary thrust-chamber thermal analysis.

    Parameters accept either core dataclasses or project dictionaries.  For
    convenience, an ``AnalysisResult`` may be supplied as the first argument;
    its contour, thermodynamics, performance and thermal input are discovered
    automatically.
    """

    analysis_result = None
    if gas is None and value_of(contour, "contour", default=None) is not None:
        analysis_result = contour
        contour = value_of(analysis_result, "contour")
        gas = analysis_result
    elif value_of(gas, "contour", default=None) is not None:
        analysis_result = gas
    if segments is None and analysis_result is not None:
        inputs = value_of(analysis_result, "inputs", default=None)
        if inputs is not None:
            segments = value_of(inputs, "thermal", default=None)
    if isinstance(segments, Mapping) and "thermal" in segments:
        segments = segments["thermal"]
    if segments is None:
        segments = ()
    resolution_hint = value_of(segments, "resolution", default=None)
    solver_settings = _settings_from(settings, resolution_hint)
    resolution = normalise_resolution(solver_settings.resolution)
    section_count = mesh_section_count(solver_settings.resolution)
    mesh = _build_mesh(contour, section_count)
    enabled = value_of(segments, "enabled", default=True)
    if enabled is False:
        return _disabled_result(mesh, resolution, section_count)

    segment_values = thermal_segments(segments)
    report = validate_segments(segment_values, contour)
    if solver_settings.strict_validation:
        report.raise_for_errors()
    inactive = _inactive_segments(report)
    gas_data = _prepare_gas(gas, contour, mesh, solver_settings)
    regens = tuple(segment for segment in segment_values if segment_kind(segment) == "regen")
    films = tuple(segment for segment in segment_values if segment_kind(segment) == "film")
    radiations = tuple(
        segment for segment in segment_values if segment_kind(segment) == "radiation"
    )

    # First pass resolves coolant temperatures needed by film segments linked
    # to a regenerative circuit. Direct-temperature films participate already.
    initial_recovery, _, film_warnings_first = _film_profiles(
        films=tuple(film for film in films if linked_film_temperature_id(film) is None),
        inactive=inactive,
        base_recovery_k=gas_data.recovery_temperature_k,
        source_arrays=None,
        source_outlets={},
        contour=contour,
        mesh=mesh,
        settings=solver_settings,
    )
    first_regen_result = _solve_regens(
        regens=regens,
        inactive=set(inactive),
        effective_recovery_k=initial_recovery,
        contour=contour,
        mesh=mesh,
        gas=gas_data,
        settings=solver_settings,
    )
    regen_result = first_regen_result
    full_recovery = initial_recovery
    film_profile = (0.0,)*len(mesh.x_m)
    film_warnings: list[str] = []
    coupled_converged = not any(linked_film_temperature_id(film) for film in films)
    coupled_iterations = 0
    for coupled_iterations in range(1, solver_settings.coupled_max_iterations+1):
        target_recovery, film_profile, current_film_warnings = _film_profiles(
            films=films, inactive=inactive,
            base_recovery_k=gas_data.recovery_temperature_k,
            source_arrays=regen_result.arrays,
            source_outlets=regen_result.outlet_temperatures_k,
            source_completion=regen_result.segment_completion,
            contour=contour, mesh=mesh, settings=solver_settings,
        )
        film_warnings.extend(current_film_warnings)
        change = max(abs(a-b)/max(1.0,abs(a)) for a,b in zip(target_recovery,full_recovery))
        if change <= solver_settings.relative_tolerance:
            coupled_converged = True
            break
        # Relax the coupled temperature field, independently of the local
        # Bartz/wall nonlinear iterations. Film source temperature therefore
        # corresponds to the returned regenerative solution within tolerance.
        full_recovery = tuple(0.55*a+0.45*b for a,b in zip(target_recovery,full_recovery))
        regen_result = _solve_regens(
            regens=regens, inactive=set(inactive), effective_recovery_k=full_recovery,
            contour=contour, mesh=mesh, gas=gas_data, settings=solver_settings,
        )
    arrays = regen_result.arrays
    inactive.update(regen_result.inactive_ids)
    stats = regen_result.stats
    stats.converged = stats.converged and coupled_converged
    radiation_warnings = _solve_radiation(
        radiations=radiations,
        inactive=inactive,
        effective_recovery_k=full_recovery,
        contour=contour,
        mesh=mesh,
        gas=gas_data,
        settings=solver_settings,
        arrays=arrays,
        stats=stats,
    )
    warnings = [issue.message for issue in report.issues]
    warnings.extend(film_warnings_first)
    warnings.extend(first_regen_result.warnings)
    warnings.extend(film_warnings)
    warnings.extend(regen_result.warnings)
    warnings.extend(radiation_warnings)
    if not coupled_converged:
        warnings.append("coupled regenerative/film temperature iteration did not converge")
    if not stats.converged:
        warnings.append(
            "one or more thermal stations reached the iteration limit; inspect temperature margins"
        )
    warnings = list(dict.fromkeys(warnings))
    physical_issues = list(regen_result.physical_issues)
    physical_issues.extend(gas_data.property_issues)
    physical_validity = regen_result.physical_validity
    if report.errors:
        physical_validity = "invalid"
        physical_issues.append("thermal segment validation errors were bypassed; boundary conditions invalid")
    if gas_data.nozzle_regime.startswith("unsupported"):
        physical_validity = "invalid"
        physical_issues.append("gas nozzle flow regime is unsupported; attached-flow thermal boundary invalid")
    if "air-transport" in gas_data.source or "fallback" in gas_data.source:
        physical_issues.append("gas thermodynamics/transport use a screening fallback, not local combustion-product data")
    # These are explicit remaining model domains, not numerical successes.
    model_limits = [
        "steady axisymmetric wall/channel model: transient storage, ablation, axial/circumferential conduction and structural life unavailable",
        "rib fins assume straight fins with adiabatic closeout; conjugate channel validation required",
        "gas-side Bartz empirical correlation requires combustion/boundary-layer validation",
    ]
    if solver_settings.gas_emissivity > 0:
        physical_issues.append("gas radiation uses specified grey emissivity; species/pressure/path-dependent spectral model not validated")
    for diagnostic in radiation_warnings:
        if "data range" in diagnostic or "source/screening" in diagnostic:
            physical_issues.append(diagnostic)
        if "data range" in diagnostic and physical_validity != "invalid":
            physical_validity = "unsupported"
    for film in films:
        if segment_id(film) in inactive:
            continue
        physical_issues.append("gaseous-film mixing/layer parameters and injection coverage require experimental validation")
        name = value_of(film,"coolant","coolant_name",default=None)
        if name is None:
            physical_issues.append("film coolant identity unavailable; gaseous mixing model unvalidated")
            continue
        injection = film_injection_x(film,contour)
        temperature = _film_temperature(film,segment_id(film),injection,arrays,
            regen_result.outlet_temperatures_k,mesh)
        if temperature is None:
            continue
        nearest = min(range(len(mesh.x_m)),key=lambda i:abs(mesh.x_m[i]-injection))
        local_gas_pressure = gas_data.pressure_pa[nearest]
        film_state = get_coolant_model(name).at_state(temperature,local_gas_pressure)
        if film_state.phase not in {"gas","supercritical_gas","supercritical"}:
            physical_issues.append(f"{segment_id(film)}: liquid/unknown film evaporation, latent heat and coverage model unsupported")
            if physical_validity != "invalid":
                physical_validity = "unsupported"
        physical_issues.extend(film_state.issues)
        if str(enum_value(name)).startswith("H2O2"):
            physical_issues.append("peroxide film decomposition/chemical heat release unsupported")
    if physical_validity == "valid" and physical_issues:
        physical_validity = "screening"
    unsolved_stations = sum(not isfinite(temperature) for temperature in arrays.Twg)
    if unsolved_stations == len(arrays.active):
        if physical_validity != "invalid":
            physical_validity = "unsupported"
        physical_issues.append("no thermal wall stations solved; specify a supported cooling boundary condition")
    elif unsolved_stations:
        physical_issues.append("thermal wall boundary unavailable for part of the contour; omitted stations have no predicted temperature")
        if physical_validity == "valid":
            physical_validity = "screening"
    physical_issues = list(dict.fromkeys(physical_issues))
    warnings.extend(physical_issues)
    warnings = list(dict.fromkeys(warnings))
    radiation_bounds = tuple(
        (min(0.0,radiative_heat_flux(gas_data.temperature_k[i], max(1.0,arrays.Twg[i]),1.0)),
         max(0.0,radiative_heat_flux(gas_data.temperature_k[i], max(1.0,arrays.Twg[i]),1.0)))
        if isfinite(arrays.Twg[i]) else (nan,nan) for i in range(len(mesh.x_m))
    )
    metadata = {
        "enabled": True,
        "mesh_level": resolution,
        "mesh_section_count": section_count,
        "mesh_section_counts": dict(MESH_SECTION_COUNTS),
        "gas_state_source": gas_data.source,
        "gas_side_model": "Bartz with frozen chamber boundary-layer transport and upstream throat curvature",
        "bartz_reference": {"source":gas_data.reference_source,
            "specific_heat_j_kgk":gas_data.reference_specific_heat_j_kgk,
            "viscosity_pa_s":gas_data.reference_viscosity_pa_s,
            "prandtl":gas_data.reference_prandtl,"gamma":gas_data.reference_gamma,
            "throat_upstream_curvature_radius_m":gas_data.throat_radius_of_curvature_m},
        "coolant_side_model": solver_settings.internal_flow_correlation+" with developing rectangular laminar flow, Re 2300–4000 transition and rib fin effective area",
        "coolant_pressure_model": "Darcy-Weisbach single phase; Lockhart-Martinelli two-phase friction plus homogeneous variable-area acceleration",
        "two_phase_model": "Beta pure-fluid Li-Wu/Chen-Bennett pre-dryout boiling; Lockhart-Martinelli friction; homogeneous acceleration",
        "two_phase_model_by_segment": {
            segment_id(seg): {"configured_model":solver_settings.two_phase_model,
                "max_vapor_mass_quality":solver_settings.two_phase_max_quality,
                "quality_limit_is_dryout_prediction":False,
                "regimes":tuple(sorted({str(arrays.coolant_flow_regime[i]) for i in range(section_count)
                    if arrays.active[i]==segment_id(seg) and arrays.coolant_flow_regime[i]}))}
            for seg in regens},
        "angle_channel_geometry_by_segment": _angle_channel_geometry_by_segment(
            regens, inactive, contour, mesh, solver_settings
        ),
        "wall_model": "steady one-dimensional cylindrical wall/TBC conduction with surface area conversion",
        "wall_thickness_convention":"radial offset; local cylindrical ring approximation on sloped contour",
        "radiation_model": "diffuse-grey external steady-state balance",
        "film_model": "RPA gaseous-film mixing effectiveness screening model",
        "inactive_segment_ids": tuple(sorted(inactive)),
        "coolant_identity_by_segment": _coolant_identity_by_segment(regens, inactive),
        "material_references": material_reference_metadata(),
        "physical_validity": physical_validity,
        "physical_issues": tuple(physical_issues),
        "model_limits": tuple(model_limits),
        "model_capabilities": {
            "pressure_dependent_eos": solver_settings.coolant_property_backend in {"coolprop","refprop"},
            "bulk_enthalpy_march": True, "rib_fin_effective_area": True,
            "cylindrical_conduction": True, "coupled_film_regen_iteration": True,
            "two_phase_heat_transfer": solver_settings.two_phase_model!="disabled", "critical_heat_flux": False,
            "two_phase_mixture_heat_transfer":False,
            "two_phase_thermodynamic_quality":True,
            "dryout": False, "supercritical_htd_validated": False,
            "ablation": False, "transient_heat_storage": False,
            "gas_spectral_radiation": False,
            "film_withdrawal_from_regen": False,
            "reactive_coolant_decomposition": False, "coking_deposit_lifetime": False,
            "axial_solid_conduction":False, "closeout_2d_conduction":False,
            "local_feed_losses":False, "acceleration_pressure_loss":False,
            "two_phase_homogeneous_acceleration":True,
            "manifold_flow_distribution":False, "structural_life":False,
        },
        "coolant_property_sources": regen_result.property_sources,
        "coolant_property_metadata":regen_result.property_metadata,
        "regen_segment_completion":regen_result.segment_completion,
        "fin_area_by_segment": regen_result.fin_area_by_segment,
        "energy_balance_by_segment": regen_result.energy_balance_by_segment,
        "coolant_outlet_phase":regen_result.outlet_phases,
        "coolant_outlet_enthalpy_j_kg":regen_result.outlet_enthalpies_j_kg,
        "coupled_iterations": coupled_iterations,
        "coupled_converged": coupled_converged,
        "effective_recovery_temperature_k": full_recovery,
        "gas_radiation_flux_bounds_w_m2": radiation_bounds,
        "gas_radiation_inputs": {
            "specified_emissivity":solver_settings.gas_emissivity,
            "h2o_mole_fraction":gas_data.h2o_mole_fraction,
            "co2_mole_fraction":gas_data.co2_mole_fraction,
            "pressure_pa":gas_data.pressure_pa,
            "mean_beam_length_m":tuple(2*r for r in mesh.radius_m),
            "bounds_basis":"emissivity in [0,1], fixed calculated wall temperature; not calibrated uncertainty interval",
        },
        "unsolved_station_count":unsolved_stations,
        "solved_wall_station_count": section_count-unsolved_stations,
        "wall_solution_complete": unsolved_stations == 0,
        "unsupported_station_count":sum(value in {"unsupported","invalid"} for value in arrays.station_applicability),
        "temperature_labels": {
            "Twg": "hot-gas-facing surface",
            "Twi": "TBC/base-wall interface",
            "Twc": "coolant/outer-side wall",
            "Tc": "bulk coolant or ambient",
        },
    }
    return ThermalAnalysisResult(
        resolution=resolution,
        section_count=section_count,
        x_m=mesh.x_m,
        radius_m=mesh.radius_m,
        Twg_K=tuple(arrays.Twg),
        Twi_K=tuple(arrays.Twi),
        Twc_K=tuple(arrays.Twc),
        Tc_K=tuple(arrays.Tc),
        heat_flux_w_m2=tuple(arrays.heat_flux),
        gas_coefficient_w_m2k=tuple(arrays.gas_h),
        coolant_coefficient_w_m2k=tuple(arrays.coolant_h),
        coolant_pressure_bar=tuple(arrays.coolant_pressure_bar),
        coolant_velocity_m_s=tuple(arrays.coolant_velocity_m_s),
        coolant_density_kg_m3=tuple(arrays.coolant_density_kg_m3),
        film_effectiveness=film_profile,
        active_segment_id=tuple(arrays.active),
        coolant_outlet_temperature_k=regen_result.outlet_temperatures_k,
        coolant_inlet_temperature_k=regen_result.inlet_temperatures_k,
        coolant_outlet_pressure_bar=regen_result.outlet_pressures_bar,
        coolant_inlet_pressure_bar=regen_result.inlet_pressures_bar,
        coolant_pressure_drop_bar=regen_result.pressure_drops_bar,
        linked_coolant_source=regen_result.links,
        warnings=tuple(warnings),
        iterations=stats.iterations,
        converged=stats.converged and unsolved_stations < section_count,
        metadata=metadata,
        physical_validity=physical_validity,
        physical_issues=tuple(physical_issues),
        coolant_phase=tuple(arrays.coolant_phase),
        coolant_vapor_quality=tuple(arrays.coolant_vapor_quality),
        coolant_flow_regime=tuple(arrays.coolant_flow_regime),
        coolant_outlet_phase=regen_result.outlet_phases,
        coolant_outlet_enthalpy_j_kg=regen_result.outlet_enthalpies_j_kg,
        coolant_reynolds=tuple(arrays.coolant_reynolds),
        coolant_nusselt=tuple(arrays.coolant_nusselt),
        coolant_raw_coefficient_w_m2k=tuple(arrays.coolant_raw_coefficient_w_m2k),
        station_applicability=tuple(arrays.station_applicability),
    )


def thermal_radiation_sensitivity(
    contour: object, gas: object, segments: object,
    *, settings: object | None = None,
    emissivities: Sequence[float] = (0.02,0.08,0.16),
) -> dict[str, object]:
    """Re-solve the wall/coolant system for specified grey-gas emissivities.

    This is a sensitivity experiment, not a calibrated statistical uncertainty
    interval. Film/regenerative coupling is solved anew for every case.
    """
    baseline = _settings_from(settings,value_of(segments,"resolution",default=None))
    cases=[]
    for emissivity in emissivities:
        result=analyze_thermal(contour,gas,segments,replace(baseline,gas_emissivity=float(emissivity)))
        hot=[t for t in result.Twg_K if isfinite(t)]
        flux=[q for q in result.heat_flux_w_m2 if isfinite(q)]
        cases.append({
            "gas_emissivity":float(emissivity),
            "peak_hot_wall_temperature_k":max(hot,default=nan),
            "peak_heat_flux_w_m2":max(flux,default=nan),
            "coolant_outlet_temperature_k":result.coolant_outlet_temperature_k,
            "physical_validity":result.physical_validity,
            "physical_issues":result.physical_issues,
            "converged":result.converged,
            "energy_balance_by_segment":result.metadata["energy_balance_by_segment"],
        })
    return {
        "model":"grey-gas radiation emissivity sensitivity, fully re-solved wall/coolant balance",
        "interpretation":"specified scenario envelope; not validated spectral emissivity or a statistical uncertainty interval",
        "cases":cases,
    }


__all__ = ["ThermalSolverSettings", "analyze_thermal", "thermal_radiation_sensitivity"]
