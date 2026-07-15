"""Thermodynamic station table and axial quasi-one-dimensional arrays."""

from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt

from ._numerics import solve_mach
from .contour import ContourResult
from .performance import PerformanceResult


@dataclass(frozen=True, slots=True)
class ThermodynamicStation:
    name: str
    x_m: float
    pressure_pa: float
    temperature_k: float
    enthalpy_j_kg: float
    entropy_j_kgk: float
    specific_heat_j_kgk: float
    gamma: float
    gas_constant_j_kgk: float
    density_kg_m3: float
    sonic_velocity_m_s: float
    mach: float
    mass_flux_kg_m2_s: float
    viscosity_pa_s: float
    prandtl: float


@dataclass(frozen=True, slots=True)
class AxialThermodynamics:
    x_m: tuple[float, ...]
    pressure_pa: tuple[float, ...]
    temperature_k: tuple[float, ...]
    enthalpy_j_kg: tuple[float, ...]
    entropy_j_kgk: tuple[float, ...]
    specific_heat_j_kgk: tuple[float, ...]
    gamma: tuple[float, ...]
    gas_constant_j_kgk: tuple[float, ...]
    density_kg_m3: tuple[float, ...]
    sonic_velocity_m_s: tuple[float, ...]
    mach: tuple[float, ...]
    mass_flux_kg_m2_s: tuple[float, ...]
    viscosity_pa_s: tuple[float, ...]
    prandtl: tuple[float, ...]
    stations: dict[str, ThermodynamicStation]
    source: str

    @property
    def section_count(self) -> int:
        return len(self.x_m)

    @property
    def plot_variables(self) -> tuple[str, ...]:
        return (
            "pressure_pa",
            "temperature_k",
            "enthalpy_j_kg",
            "entropy_j_kgk",
            "specific_heat_j_kgk",
            "gamma",
            "gas_constant_j_kgk",
            "density_kg_m3",
            "sonic_velocity_m_s",
            "mach",
            "mass_flux_kg_m2_s",
            "viscosity_pa_s",
            "prandtl",
        )


def _state_at(
    name: str,
    x_m: float,
    mach: float,
    total_pressure_pa: float,
    total_temperature_k: float,
    gamma: float,
    gas_constant: float,
    mass_flux_override: float | None = None,
) -> ThermodynamicStation:
    temperature_ratio = 1.0 + 0.5 * (gamma - 1.0) * mach * mach
    temperature = total_temperature_k / temperature_ratio
    pressure = total_pressure_pa / temperature_ratio ** (gamma / (gamma - 1.0))
    specific_heat = gamma * gas_constant / (gamma - 1.0)
    enthalpy = specific_heat * temperature
    entropy = specific_heat * log(temperature / 298.15) - gas_constant * log(
        pressure / 101_325.0
    )
    density = pressure / (gas_constant * temperature)
    sonic_velocity = sqrt(gamma * gas_constant * temperature)
    velocity = mach * sonic_velocity
    mass_flux = density * velocity if mass_flux_override is None else mass_flux_override
    # Sutherland form gives a stable engineering gas-viscosity estimate.  CEA
    # station transport data can replace it later without changing the API.
    viscosity = 1.716e-5 * (temperature / 273.15) ** 1.5 * (
        273.15 + 110.4
    ) / (temperature + 110.4)
    prandtl = max(0.62, min(0.78, 0.72 - 0.018 * (gamma - 1.2)))
    return ThermodynamicStation(
        name=name,
        x_m=x_m,
        pressure_pa=pressure,
        temperature_k=temperature,
        enthalpy_j_kg=enthalpy,
        entropy_j_kgk=entropy,
        specific_heat_j_kgk=specific_heat,
        gamma=gamma,
        gas_constant_j_kgk=gas_constant,
        density_kg_m3=density,
        sonic_velocity_m_s=sonic_velocity,
        mach=mach,
        mass_flux_kg_m2_s=mass_flux,
        viscosity_pa_s=viscosity,
        prandtl=prandtl,
    )


def build_thermodynamics(
    contour: ContourResult,
    performance: PerformanceResult,
) -> AxialThermodynamics:
    """Build all requested properties at stations and along the contour."""

    throat_area = performance.throat_area_m2
    station_rows: list[ThermodynamicStation] = []
    for index, (x_value, area) in enumerate(zip(contour.x_m, contour.area_m2)):
        area_ratio = max(1.0, area / throat_area)
        if index == contour.throat_index:
            mach = 1.0
        else:
            mach = solve_mach(
                area_ratio,
                performance.gamma,
                supersonic=index > contour.throat_index,
            )
        station_rows.append(
            _state_at(
                "axial",
                x_value,
                mach,
                performance.chamber_pressure_bar * 100_000.0,
                performance.combustion_temperature_k,
                performance.gamma,
                performance.gas_constant_j_kgk,
                performance.hot_gas_mass_flow_kg_s / area,
            )
        )

    station_indices = {
        "injector": 0,
        "nozzle_inlet": contour.chamber_end_index,
        "nozzle_throat": contour.throat_index,
        "nozzle_exit": len(contour.x_m) - 1,
    }
    stations: dict[str, ThermodynamicStation] = {}
    for name, index in station_indices.items():
        row = station_rows[index]
        stations[name] = ThermodynamicStation(
            name=name,
            x_m=row.x_m,
            pressure_pa=row.pressure_pa,
            temperature_k=row.temperature_k,
            enthalpy_j_kg=row.enthalpy_j_kg,
            entropy_j_kgk=row.entropy_j_kgk,
            specific_heat_j_kgk=row.specific_heat_j_kgk,
            gamma=row.gamma,
            gas_constant_j_kgk=row.gas_constant_j_kgk,
            density_kg_m3=row.density_kg_m3,
            sonic_velocity_m_s=row.sonic_velocity_m_s,
            mach=row.mach,
            mass_flux_kg_m2_s=row.mass_flux_kg_m2_s,
            viscosity_pa_s=row.viscosity_pa_s,
            prandtl=row.prandtl,
        )

    return AxialThermodynamics(
        x_m=contour.x_m,
        pressure_pa=tuple(row.pressure_pa for row in station_rows),
        temperature_k=tuple(row.temperature_k for row in station_rows),
        enthalpy_j_kg=tuple(row.enthalpy_j_kg for row in station_rows),
        entropy_j_kgk=tuple(row.entropy_j_kgk for row in station_rows),
        specific_heat_j_kgk=tuple(row.specific_heat_j_kgk for row in station_rows),
        gamma=tuple(row.gamma for row in station_rows),
        gas_constant_j_kgk=tuple(row.gas_constant_j_kgk for row in station_rows),
        density_kg_m3=tuple(row.density_kg_m3 for row in station_rows),
        sonic_velocity_m_s=tuple(row.sonic_velocity_m_s for row in station_rows),
        mach=tuple(row.mach for row in station_rows),
        mass_flux_kg_m2_s=tuple(row.mass_flux_kg_m2_s for row in station_rows),
        viscosity_pa_s=tuple(row.viscosity_pa_s for row in station_rows),
        prandtl=tuple(row.prandtl for row in station_rows),
        stations=stations,
        source=(
            "rocketcea-combustion-state+isentropic-axial"
            if performance.source == "rocketcea"
            else "ideal-gas-fallback"
        ),
    )
