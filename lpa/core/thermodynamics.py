"""Thermodynamic station table and axial quasi-one-dimensional arrays."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import log, nan, sqrt

from ._numerics import solve_mach
from .contour import ContourResult
from .performance import PerformanceResult, RocketCEAAdapter
from .models import AnalysisInput


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
    h2o_mole_fraction: float = nan
    co2_mole_fraction: float = nan


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
    warnings: tuple[str, ...] = ()
    h2o_mole_fraction: tuple[float, ...] = ()
    co2_mole_fraction: tuple[float, ...] = ()
    nozzle_regime: str = "attached"
    # Separate from the reacting-flow station properties above. Defaults keep
    # older/custom adapters usable, with an explicit thermal fallback warning.
    bartz_reference_specific_heat_j_kgk: float | None = None
    bartz_reference_viscosity_pa_s: float | None = None
    bartz_reference_prandtl: float | None = None
    bartz_reference_gamma: float | None = None
    bartz_reference_source: str = "unavailable"

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
    *,
    inputs: AnalysisInput | None = None,
    cea_adapter: RocketCEAAdapter | None = None,
) -> AxialThermodynamics:
    """Build all requested properties at stations and along the contour."""

    throat_area = performance.throat_area_m2
    station_rows: list[ThermodynamicStation] = []
    warnings: list[str] = []
    cea_rows: tuple[dict[str, float], ...] | None = None
    bartz_reference: dict[str, float] = {}
    if performance.source == "rocketcea" and inputs is not None:
        adapter = cea_adapter or RocketCEAAdapter()
        chamber = replace(inputs.thrust_chamber, contraction_area_ratio=performance.contraction_area_ratio)
        try:
            cea_rows = adapter.axial_station_states(
                inputs.engine, chamber, tuple(area / throat_area for area in contour.area_m2), contour.throat_index,
            )
            if len(cea_rows) != contour.section_count:
                raise RuntimeError("CEA axial station count does not match the contour")
        except Exception as error:
            cea_rows = None
            warnings.append(f"Local CEA thermodynamics/transport unavailable ({error}); constant-gas axial screening properties and air transport are used.")
        try:
            bartz_reference = adapter.bartz_reference_properties(inputs.engine, chamber)
        except Exception as error:
            warnings.append(f"Bartz chamber frozen transport unavailable ({error}); the thermal calculation requires a screening reference fallback.")
    elif performance.source == "rocketcea":
        warnings.append("No engine/CEA context supplied: axial states use constant-gas screening properties and air transport, not local CEA data.")
    if performance.design_nozzle_regime.startswith("unsupported"):
        warnings.append("Axial gas states assume attached supersonic flow; the selected design ambient is outside that model's validity. Thermal predictions at this operating condition are unsupported.")
    if cea_rows is not None and performance.reaction_efficiency != 1.0:
        warnings.append("Reaction-efficiency temperature/density closure preserves continuity but retains ideal CEA composition, Cp and transport; the reduced-temperature chemistry/transport is not re-equilibrated. Thermodynamic and heat-transfer states are screening estimates.")
    for index, (x_value, area) in enumerate(zip(contour.x_m, contour.area_m2)):
        if cea_rows is not None:
            values = cea_rows[index].copy()
            ideal_temperature = values["temperature_k"]
            temperature_scale = performance.reaction_efficiency**2
            values["temperature_k"] *= temperature_scale
            values["density_kg_m3"] /= temperature_scale
            values["sonic_velocity_m_s"] *= performance.reaction_efficiency
            values["enthalpy_j_kg"] += values["specific_heat_j_kgk"] * (values["temperature_k"] - ideal_temperature)
            values["entropy_j_kgk"] += values["specific_heat_j_kgk"] * log(temperature_scale)
            station_rows.append(ThermodynamicStation(name="axial", x_m=x_value,
                mass_flux_kg_m2_s=performance.hot_gas_mass_flow_kg_s / area, **values))
            continue
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
            h2o_mole_fraction=row.h2o_mole_fraction,
            co2_mole_fraction=row.co2_mole_fraction,
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
        source=("rocketcea-local-stations-and-transport" if cea_rows is not None else "constant-gas-screening-with-air-transport"),
        warnings=tuple(warnings),
        h2o_mole_fraction=tuple(row.h2o_mole_fraction for row in station_rows),
        co2_mole_fraction=tuple(row.co2_mole_fraction for row in station_rows),
        nozzle_regime=performance.design_nozzle_regime,
        bartz_reference_specific_heat_j_kgk=bartz_reference.get("specific_heat_j_kgk"),
        bartz_reference_viscosity_pa_s=bartz_reference.get("viscosity_pa_s"),
        bartz_reference_prandtl=bartz_reference.get("prandtl"),
        bartz_reference_gamma=bartz_reference.get("gamma"),
        bartz_reference_source=("rocketcea-chamber-stagnation-frozen-transport" if bartz_reference else "unavailable"),
    )
