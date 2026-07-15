"""Axial Bartz/regenerative/radiation/film thermal-analysis solver."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite, nan, pi, sqrt
from typing import Any

from .coolants import CoolantState, get_coolant_model
from .correlations import (
    adiabatic_wall_temperature,
    annular_wall_area,
    bartz_heat_transfer_coefficient,
    film_effectiveness as film_effectiveness_correlation,
    internal_flow_heat_transfer,
    radiative_heat_flux,
    rectangular_channel_geometry,
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


@dataclass(slots=True)
class ThermalSolverSettings:
    """Optional numerical/physical overrides for :func:`analyze_thermal`."""

    resolution: Resolution | str = Resolution.MEDIUM
    chamber_pressure_pa: float | None = None
    stagnation_temperature_k: float | None = None
    characteristic_velocity_m_s: float | None = None
    total_mass_flow_kg_s: float | None = None
    throat_radius_curvature_ratio: float = 0.382
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

    def __post_init__(self) -> None:
        normalise_resolution(self.resolution)
        for name in (
            "throat_radius_curvature_ratio",
            "ambient_temperature_k",
            "default_radiation_wall_thickness_mm",
            "film_mixing_coefficient",
            "film_surface_layer_mass_fraction",
            "relative_tolerance",
        ):
            if float(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.film_boundary_layer_thickness_m is not None and self.film_boundary_layer_thickness_m <= 0:
            raise ValueError("film boundary-layer thickness must be positive")
        if not 0 <= self.gas_emissivity <= 1:
            raise ValueError("gas emissivity must be between zero and one")
        if self.external_convection_w_m2k < 0:
            raise ValueError("external convection coefficient cannot be negative")
        if isinstance(self.max_iterations, bool) or self.max_iterations < 5:
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
                "nozzle_throat_radius_ratio",
                "rn_rt",
                default=0.382,
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
    areas = tuple(pi * radius * radius for radius in radii)
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
    source: str


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
        viscosity = tuple(_sutherland_viscosity(value) for value in temperature)
    prandtl = (
        _resampled_field(axial, ("prandtl", "prandtl_number"), source_x, mesh.x_m)
        if axial is not None
        else None
    )
    if prandtl is None:
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

    recovery = tuple(
        adiabatic_wall_temperature(
            stagnation_temperature, mach[index], gamma[index], prandtl[index]
        )
        for index in range(len(mesh.x_m))
    )
    rn_ratio = settings.throat_radius_curvature_ratio
    metadata = value_of(contour, "metadata", default={})
    if isinstance(metadata, Mapping):
        rn_ratio = float(metadata.get("Rn/Rt", metadata.get("rn_rt", rn_ratio)))
    source_name = str(
        value_of(axial, "source", default=value_of(performance, "source", default="provided"))
    )
    return _GasData(
        chamber_pressure_pa=float(chamber_pressure),
        stagnation_temperature_k=stagnation_temperature,
        characteristic_velocity_m_s=characteristic_velocity,
        total_mass_flow_kg_s=float(total_mass_flow),
        throat_diameter_m=2.0 * throat_radius,
        throat_radius_of_curvature_m=max(1.0e-9, rn_ratio * throat_radius),
        temperature_k=tuple(temperature),
        gamma=tuple(gamma),
        mach=tuple(mach),
        specific_heat_j_kgk=tuple(specific_heat),
        viscosity_pa_s=tuple(viscosity),
        prandtl=tuple(prandtl),
        recovery_temperature_k=recovery,
        reference_specific_heat_j_kgk=specific_heat[0],
        reference_viscosity_pa_s=viscosity[0],
        reference_prandtl=prandtl[0],
        source=source_name,
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
) -> CoolantState:
    name = _coolant_name(definition)
    model = get_coolant_model(name)
    base = model.at_temperature(temperature_k)
    overrides: object | None = None
    if isinstance(settings.coolant_properties, Mapping):
        canonical = str(enum_value(name))
        overrides = settings.coolant_properties.get(identifier)
        if overrides is None:
            overrides = settings.coolant_properties.get(canonical)
    # A custom model can supply a temperature-aware state.
    if overrides is not None and hasattr(overrides, "at_temperature"):
        state = overrides.at_temperature(temperature_k)
        if isinstance(state, CoolantState):
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
    if min(density, cp, conductivity, viscosity) <= 0:
        raise ValueError("coolant thermophysical properties must be positive")
    return CoolantState(density, cp, conductivity, viscosity)


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
        gamma=gas.gamma[index],
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


def _solve_regen_station(
    *,
    index: int,
    segment: object,
    identifier: str,
    wall: _Wall,
    coolant_definition: object,
    coolant_temperature_k: float,
    coolant_mass_flow_kg_s: float,
    effective_recovery_temperature_k: float,
    segment_range: tuple[float, float],
    mesh: _Mesh,
    gas: _GasData,
    settings: ThermalSolverSettings,
) -> _StationSolution:
    start_m, end_m = segment_range
    width, height, channels, roughness = _channel_dimensions(
        segment,
        mesh.x_m[index],
        mesh.radius_m[index],
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
    for iteration in range(1, settings.max_iterations + 1):
        coolant_state = _coolant_state(
            coolant_definition,
            max(1.0, 0.5 * (coolant_temperature_k + wall_cold_temperature)),
            settings,
            identifier,
        )
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
        )
        coolant_h = internal.coefficient_w_m2k
        mean_wall_temperature = max(
            1.0, 0.5 * (wall_interface_temperature + wall_cold_temperature)
        )
        wall_resistance = wall.thickness_m / wall.conductivity(mean_wall_temperature)
        coating_resistance = (
            wall.coating_thickness_m / wall.coating_conductivity_w_mk
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
        new_heat_flux = max(0.0, numerator / (1.0 + gas_h * post_gas_resistance))
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
        coolant_cp=coolant_cp,
        # Darcy-Weisbach distributed loss.  The caller integrates this along
        # the actual contour-following channel length of each mesh cell.
        coolant_pressure_gradient_pa_m=(
            internal.friction_factor
            / internal.hydraulic_diameter_m
            * 0.5
            * coolant_state.density_kg_m3
            * internal.velocity_m_s**2
        ),
        coolant_velocity_m_s=internal.velocity_m_s,
        coolant_density_kg_m3=coolant_state.density_kg_m3,
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
    indices = [index for index, value in enumerate(mesh.x_m) if start <= value <= end]
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
        current_temperature = inlet_temperature
        current_pressure_pa = inlet_pressure_pa
        pressure_depleted = False
        inlets[identifier] = inlet_temperature
        pressure_inlets[identifier] = inlet_pressure_pa / 100_000.0
        for index in march:
            arrays.Tc[index] = current_temperature
            solution = _solve_regen_station(
                index=index,
                segment=segment,
                identifier=identifier,
                wall=wall,
                coolant_definition=definition,
                coolant_temperature_k=current_temperature,
                coolant_mass_flow_kg_s=mass_flow,
                effective_recovery_temperature_k=effective_recovery_k[index],
                segment_range=bounds,
                mesh=mesh,
                gas=gas,
                settings=settings,
            )
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
            arrays.active[index] = identifier
            axial_width = _cell_width_in_range(mesh, index, bounds)
            if axial_width > 0:
                area = annular_wall_area(mesh.radius_m[index], axial_width)
                current_temperature += (
                    solution.heat_flux * area / (mass_flow * solution.coolant_cp)
                )
                pressure_loss_pa = (
                    solution.coolant_pressure_gradient_pa_m
                    * _channel_path_length_in_range(mesh, index, bounds)
                )
                if pressure_loss_pa >= current_pressure_pa:
                    current_pressure_pa = 0.0
                    pressure_depleted = True
                else:
                    current_pressure_pa -= pressure_loss_pa
        outlets[identifier] = current_temperature
        pressure_outlets[identifier] = current_pressure_pa / 100_000.0
        pressure_drops[identifier] = (
            inlet_pressure_pa - current_pressure_pa
        ) / 100_000.0
        if pressure_depleted:
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
        external_flux = radiative_heat_flux(
            cold_wall_temperature, ambient, emissivity
        ) + settings.external_convection_w_m2k * (cold_wall_temperature - ambient)
        interface = cold_wall_temperature
        wall_k = wall.conductivity(cold_wall_temperature)
        for _ in range(8):
            interface = cold_wall_temperature + external_flux * wall.thickness_m / wall_k
            wall_k = wall.conductivity(0.5 * (interface + cold_wall_temperature))
        gas_wall = interface + external_flux * (
            wall.coating_thickness_m / wall.coating_conductivity_w_mk
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
    for segment_index, segment in enumerate(radiations):
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
                warnings.append(
                    f"radiation segment '{identifier}' skipped an occupied regen station"
                )
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
        radii = tuple(_contour_radius_at(contour, mesh, x_value) for x_value in points)
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
    full_recovery, film_profile, film_warnings = _film_profiles(
        films=films,
        inactive=inactive,
        base_recovery_k=gas_data.recovery_temperature_k,
        source_arrays=first_regen_result.arrays,
        source_outlets=first_regen_result.outlet_temperatures_k,
        contour=contour,
        mesh=mesh,
        settings=solver_settings,
    )
    regen_result = _solve_regens(
        regens=regens,
        inactive=inactive,
        effective_recovery_k=full_recovery,
        contour=contour,
        mesh=mesh,
        gas=gas_data,
        settings=solver_settings,
    )
    arrays = regen_result.arrays
    stats = regen_result.stats
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
    if not stats.converged:
        warnings.append(
            "one or more thermal stations reached the iteration limit; inspect temperature margins"
        )
    warnings = list(dict.fromkeys(warnings))
    metadata = {
        "enabled": True,
        "mesh_level": resolution,
        "mesh_section_count": section_count,
        "mesh_section_counts": dict(MESH_SECTION_COUNTS),
        "gas_state_source": gas_data.source,
        "gas_side_model": "Bartz correlation with RPA sigma correction",
        "coolant_side_model": solver_settings.internal_flow_correlation,
        "coolant_pressure_model": "Darcy-Weisbach distributed channel loss",
        "angle_channel_geometry_by_segment": _angle_channel_geometry_by_segment(
            regens, inactive, contour, mesh
        ),
        "wall_model": "steady one-dimensional wall/TBC conduction",
        "radiation_model": "diffuse-grey external steady-state balance",
        "film_model": "RPA gaseous-film mixing effectiveness screening model",
        "inactive_segment_ids": tuple(sorted(inactive)),
        "coolant_identity_by_segment": _coolant_identity_by_segment(regens, inactive),
        "material_references": material_reference_metadata(),
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
        converged=stats.converged,
        metadata=metadata,
    )


__all__ = ["ThermalSolverSettings", "analyze_thermal"]
