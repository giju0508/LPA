"""Reproducible Bartz and thermal-solver audit for the GOX/GCH4 reference case.

This tool deliberately keeps its Bartz arithmetic independent from
``lpa.thermal.correlations``.  It calls the production solver only to obtain the
wall solution, then reconstructs every gas-side factor and writes inspectable
CSV/JSON files.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
from math import hypot, isfinite, log10, nan, pi, sqrt
from pathlib import Path
import sys
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lpa.core.analysis import analyze_engine
from lpa.core.models import (  # noqa: E402
    AnalysisInput,
    ChamberLength,
    ChannelTriplet,
    CoolantDefinition,
    EngineDefinition,
    NozzleExitCondition,
    RegenSegment,
    SegmentRange,
    ThermalAnalysisInput,
    ThrustChamberInput,
    ThrustChamberSize,
)
from lpa.thermal import MESH_SECTION_COUNTS, analyze_thermal  # noqa: E402


SIGMA_SB_W_M2K4 = 5.670374419e-8


@dataclass(frozen=True, slots=True)
class AuditCase:
    chamber_pressure_bar: float = 10.0
    mixture_ratio: float = 2.6
    throat_diameter_mm: float = 31.79
    contraction_area_ratio: float = 4.0
    expansion_area_ratio: float = 4.0
    characteristic_length_mm: float = 1000.0
    reaction_efficiency_percent: float = 98.0
    throat_curvature_ratio: float = 1.5
    wall_thickness_mm: float = 1.0
    water_inlet_temperature_k: float = 293.15
    water_inlet_pressure_bar: float = 25.0
    water_flow_percent: float = 100.0
    gas_emissivity: float = 0.08


def independent_bartz(
    *,
    chamber_pressure_pa: float,
    characteristic_velocity_m_s: float,
    throat_diameter_m: float,
    throat_radius_of_curvature_m: float,
    area_ratio: float,
    wall_temperature_k: float,
    stagnation_temperature_k: float,
    mach: float,
    viscosity_pa_s: float,
    specific_heat_j_kgk: float,
    prandtl: float,
    gamma: float,
) -> dict[str, float]:
    """Evaluate the printed SI Bartz equation without production helpers."""

    kinetic = 0.5 * (gamma - 1.0) * mach * mach
    recovery = prandtl ** (1.0 / 3.0)
    taw = stagnation_temperature_k * (1.0 + recovery * kinetic) / (1.0 + kinetic)
    sigma = (
        0.5 * wall_temperature_k / stagnation_temperature_k * (1.0 + kinetic)
        + 0.5
    ) ** -0.68 * (1.0 + kinetic) ** -0.12
    leading = 0.026 / throat_diameter_m**0.2
    transport = viscosity_pa_s**0.2 * specific_heat_j_kgk / prandtl**0.6
    pressure_cstar = (chamber_pressure_pa / characteristic_velocity_m_s) ** 0.8
    curvature = (throat_diameter_m / throat_radius_of_curvature_m) ** 0.1
    geometry = (1.0 / area_ratio) ** 0.9
    coefficient = leading * transport * pressure_cstar * curvature * geometry * sigma
    convective_flux = coefficient * (taw - wall_temperature_k)
    return {
        "kinetic_factor": kinetic,
        "recovery_factor": recovery,
        "adiabatic_wall_temperature_k": taw,
        "sigma": sigma,
        "leading_factor": leading,
        "transport_factor": transport,
        "pressure_cstar_factor": pressure_cstar,
        "curvature_factor": curvature,
        "geometry_factor": geometry,
        "coefficient_w_m2k": coefficient,
        "convective_flux_w_m2": convective_flux,
    }


def _build_case(case: AuditCase) -> tuple[object, RegenSegment, dict[str, object]]:
    regen = RegenSegment(
        segment_id="water",
        location=SegmentRange("top", "bottom"),
        wall_thickness_mm=case.wall_thickness_mm,
        channel_height_mm=ChannelTriplet(2.0, 1.0, 2.0),
        channel_count=60,
        coolant=CoolantDefinition(
            "H2O",
            case.water_inlet_pressure_bar,
            case.water_inlet_temperature_k,
            case.water_flow_percent,
        ),
        material="CuCrZr",
        widths_mm=ChannelTriplet(1.4, 0.8, 1.4),
        coflow=False,
    )
    inputs = AnalysisInput(
        engine=EngineDefinition(
            name="GOX/GCH4 thermal audit",
            chamber_pressure_bar=case.chamber_pressure_bar,
            mixture_ratio=case.mixture_ratio,
            oxidizer="GOX",
            fuel="GCH4",
        ),
        thrust_chamber=ThrustChamberInput(
            contraction_area_ratio=case.contraction_area_ratio,
            reaction_efficiency_percent=case.reaction_efficiency_percent,
            size=ThrustChamberSize(
                mode="throat_diameter",
                throat_diameter_mm=case.throat_diameter_mm,
            ),
            exit_condition=NozzleExitCondition(
                mode="expansion_ratio",
                expansion_area_ratio=case.expansion_area_ratio,
            ),
            length=ChamberLength(
                mode="characteristic_length",
                characteristic_length_mm=case.characteristic_length_mm,
            ),
        ),
        thermal=ThermalAnalysisInput(enabled=True, resolution="high", segments=[regen]),
    )
    core = analyze_engine(inputs, require_rocketcea=True)
    thermo = core.thermodynamics
    gas: dict[str, object] = {
        "performance": core.performance,
        "thermodynamics": thermo,
        "chamber_pressure_pa": core.performance.chamber_pressure_bar * 100_000.0,
        "characteristic_velocity_m_s": core.performance.delivered_cstar_m_s,
        "stagnation_temperature_k": core.performance.combustion_temperature_k,
        "throat_diameter_m": core.performance.throat_diameter_mm / 1000.0,
        "mass_flow_kg_s": core.performance.hot_gas_mass_flow_kg_s,
        "x_m": thermo.x_m,
        "pressure_pa": thermo.pressure_pa,
        "temperature_k": thermo.temperature_k,
        "specific_heat_j_kgk": thermo.specific_heat_j_kgk,
        "gamma": thermo.gamma,
        "mach": thermo.mach,
        "viscosity_pa_s": thermo.viscosity_pa_s,
        "prandtl": thermo.prandtl,
    }
    return core, regen, gas


def _solve_count(
    core: object,
    regen: RegenSegment,
    gas: dict[str, object],
    station_count: int,
    emissivity: float,
) -> object:
    existing_name = next(
        (name for name, count in MESH_SECTION_COUNTS.items() if count == station_count),
        None,
    )
    temporary_name = f"audit-{station_count}"
    name = existing_name or temporary_name
    if existing_name is None:
        MESH_SECTION_COUNTS[name] = station_count
    try:
        return analyze_thermal(
            core.contour,
            gas,
            [regen],
            settings={"resolution": name, "gas_emissivity": emissivity},
        )
    finally:
        if existing_name is None:
            MESH_SECTION_COUNTS.pop(name, None)


def _interpolate(
    source_x: Sequence[float], source_y: Sequence[float], targets: Sequence[float]
) -> list[float]:
    values: list[float] = []
    right = 1
    for target in targets:
        while right < len(source_x) - 1 and source_x[right] < target:
            right += 1
        left = right - 1
        span = source_x[right] - source_x[left]
        fraction = 0.0 if span <= 0 else (target - source_x[left]) / span
        values.append(source_y[left] + fraction * (source_y[right] - source_y[left]))
    return values


def _cell_widths(x_m: Sequence[float]) -> list[float]:
    left = [x_m[0], *(0.5 * (x_m[index - 1] + x_m[index]) for index in range(1, len(x_m)))]
    right = [
        *(0.5 * (x_m[index] + x_m[index + 1]) for index in range(len(x_m) - 1)),
        x_m[-1],
    ]
    return [right_value - left_value for left_value, right_value in zip(left, right)]


def _central_derivative(
    ordinate: Sequence[float], abscissa: Sequence[float], index: int
) -> float:
    left = max(0, index - 1)
    right = min(len(ordinate) - 1, index + 1)
    span = abscissa[right] - abscissa[left]
    return 0.0 if span <= 0 else (ordinate[right] - ordinate[left]) / span


def _key_station_names(core: object, x_m: Sequence[float]) -> dict[int, str]:
    targets = {
        "Injector": x_m[0],
        "Cylinder end": core.contour.x_m[core.contour.chamber_end_index],
        "Throat": core.contour.throat_x_m,
        "Exit": x_m[-1],
    }
    names: dict[int, list[str]] = {}
    for name, target in targets.items():
        index = min(range(len(x_m)), key=lambda item: abs(x_m[item] - target))
        names.setdefault(index, []).append(name)
    return {index: "; ".join(values) for index, values in names.items()}


def _station_rows(
    case: AuditCase, core: object, result: object
) -> tuple[list[dict[str, object]], float]:
    thermo = core.thermodynamics
    x = list(result.x_m)
    radius = list(result.radius_m)
    pressure = _interpolate(thermo.x_m, thermo.pressure_pa, x)
    temperature = _interpolate(thermo.x_m, thermo.temperature_k, x)
    gamma = _interpolate(thermo.x_m, thermo.gamma, x)
    mach = _interpolate(thermo.x_m, thermo.mach, x)
    cp = _interpolate(thermo.x_m, thermo.specific_heat_j_kgk, x)
    viscosity = _interpolate(thermo.x_m, thermo.viscosity_pa_s, x)
    prandtl = _interpolate(thermo.x_m, thermo.prandtl, x)
    density = _interpolate(thermo.x_m, thermo.density_kg_m3, x)
    sonic = _interpolate(thermo.x_m, thermo.sonic_velocity_m_s, x)
    velocity = [mach_value * sonic_value for mach_value, sonic_value in zip(mach, sonic)]
    path = [0.0]
    for index in range(1, len(x)):
        path.append(
            path[-1]
            + hypot(x[index] - x[index - 1], radius[index] - radius[index - 1])
        )
    cell_width = _cell_widths(x)
    throat_area = core.performance.throat_area_m2
    dt = core.performance.throat_diameter_mm / 1000.0
    rc = core.contour.metadata["throat_upstream_curvature_radius_mm"] / 1000.0
    t0 = core.performance.combustion_temperature_k
    pc = core.performance.chamber_pressure_bar * 100_000.0
    cstar = core.performance.delivered_cstar_m_s
    mu0 = thermo.bartz_reference_viscosity_pa_s or viscosity[0]
    cp0 = thermo.bartz_reference_specific_heat_j_kgk or cp[0]
    pr0 = thermo.bartz_reference_prandtl or prandtl[0]
    gamma_ref = thermo.bartz_reference_gamma or gamma[0]
    key_names = _key_station_names(core, x)
    rows: list[dict[str, object]] = []
    max_relative_error = 0.0
    for index in range(len(x)):
        area = pi * radius[index] ** 2
        independent = independent_bartz(
            chamber_pressure_pa=pc,
            characteristic_velocity_m_s=cstar,
            throat_diameter_m=dt,
            throat_radius_of_curvature_m=rc,
            area_ratio=area / throat_area,
            wall_temperature_k=result.Twg[index],
            stagnation_temperature_k=t0,
            mach=mach[index],
            viscosity_pa_s=mu0,
            specific_heat_j_kgk=cp0,
            prandtl=pr0,
            gamma=gamma_ref,
        )
        qrad = case.gas_emissivity * SIGMA_SB_W_M2K4 * (
            temperature[index] ** 4 - result.Twg[index] ** 4
        )
        qtotal = independent["convective_flux_w_m2"] + qrad
        production_h = result.gas_coefficient_w_m2k[index]
        relative_error = abs(independent["coefficient_w_m2k"] - production_h) / max(
            1.0, abs(production_h)
        )
        if isfinite(relative_error):
            max_relative_error = max(max_relative_error, relative_error)
        slope = _central_derivative(radius, x, index)
        acceleration = (
            viscosity[index]
            / density[index]
            / max(1.0e-15, velocity[index] ** 2)
            * _central_derivative(velocity, path, index)
        )
        rows.append(
            {
                "station": index,
                "key_position": key_names.get(index, ""),
                "x_m": x[index],
                "radius_m": radius[index],
                "slope_dr_dx": slope,
                "area_m2": area,
                "control_volume_m3": area * cell_width[index],
                "area_ratio_A_At": area / throat_area,
                "mach": mach[index],
                "pressure_pa": pressure[index],
                "static_temperature_k": temperature[index],
                "stagnation_temperature_k": t0,
                "gamma": gamma[index],
                "bartz_reference_gamma": gamma_ref,
                "cstar_m_s": cstar,
                "viscosity_pa_s": viscosity[index],
                "reference_viscosity_pa_s": mu0,
                "specific_heat_j_kgk": cp[index],
                "reference_specific_heat_j_kgk": cp0,
                "gas_conductivity_w_mk": viscosity[index] * cp[index] / prandtl[index],
                "prandtl": prandtl[index],
                "reference_prandtl": pr0,
                "adiabatic_wall_temperature_k": independent[
                    "adiabatic_wall_temperature_k"
                ],
                "hot_wall_temperature_k": result.Twg[index],
                "wall_interface_temperature_k": result.Twi[index],
                "coolant_wall_temperature_k": result.Twc[index],
                "bulk_coolant_temperature_k": result.Tc[index],
                "bartz_sigma": independent["sigma"],
                "bartz_leading_factor": independent["leading_factor"],
                "bartz_transport_factor": independent["transport_factor"],
                "bartz_pressure_cstar_factor": independent["pressure_cstar_factor"],
                "bartz_curvature_factor": independent["curvature_factor"],
                "bartz_geometry_factor": independent["geometry_factor"],
                "independent_h_w_m2k": independent["coefficient_w_m2k"],
                "production_h_w_m2k": production_h,
                "convective_heat_flux_w_m2": independent["convective_flux_w_m2"],
                "radiative_heat_flux_w_m2": qrad,
                "independent_total_heat_flux_w_m2": qtotal,
                "production_total_heat_flux_w_m2": result.heat_flux_w_m2[index],
                "density_kg_m3": density[index],
                "velocity_m_s": velocity[index],
                "reynolds_local_diameter": density[index]
                * velocity[index]
                * (2.0 * radius[index])
                / viscosity[index],
                "acceleration_parameter_k": acceleration,
                "coolant_pressure_bar": result.coolant_pressure_bar[index],
                "coolant_velocity_m_s": result.coolant_velocity_m_s[index],
                "coolant_phase":result.coolant_phase[index],
                "station_solved":isfinite(result.Twg[index]),
                "physical_validity":result.physical_validity,
            }
        )
    return rows, max_relative_error


def _write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    materialized = list(rows)
    if not materialized:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(materialized[0]))
        writer.writeheader()
        writer.writerows(materialized)


def _sensitivity_rows(base_row: dict[str, object], case: AuditCase, core: object) -> list[dict[str, object]]:
    parameters = {
        "chamber_pressure_pa": core.performance.chamber_pressure_bar * 100_000.0,
        "characteristic_velocity_m_s": core.performance.delivered_cstar_m_s,
        "throat_diameter_m": core.performance.throat_diameter_mm / 1000.0,
        "throat_radius_of_curvature_m": core.contour.metadata["throat_upstream_curvature_radius_mm"]/1000.0,
        "area_ratio": float(base_row["area_ratio_A_At"]),
        "wall_temperature_k": float(base_row["hot_wall_temperature_k"]),
        "stagnation_temperature_k": core.performance.combustion_temperature_k,
        "mach": float(base_row["mach"]),
        "viscosity_pa_s": float(base_row["reference_viscosity_pa_s"]),
        "specific_heat_j_kgk": float(base_row["reference_specific_heat_j_kgk"]),
        "prandtl": float(base_row["reference_prandtl"]),
        "gamma": float(base_row["bartz_reference_gamma"]),
    }
    base = independent_bartz(**parameters)
    variables = (
        "chamber_pressure_pa",
        "characteristic_velocity_m_s",
        "viscosity_pa_s",
        "specific_heat_j_kgk",
        "prandtl",
        "area_ratio",
        "throat_radius_of_curvature_m",
    )
    rows: list[dict[str, object]] = []
    for variable in variables:
        for fractional_change in (-0.10, 0.10):
            perturbed = dict(parameters)
            perturbed[variable] *= 1.0 + fractional_change
            value = independent_bartz(**perturbed)
            rows.append(
                {
                    "variable": variable,
                    "input_change_percent": 100.0 * fractional_change,
                    "h_change_percent": 100.0
                    * (value["coefficient_w_m2k"] / base["coefficient_w_m2k"] - 1.0),
                    "qconv_change_percent": 100.0
                    * (
                        value["convective_flux_w_m2"]
                        / base["convective_flux_w_m2"]
                        - 1.0
                    ),
                }
            )
    for fractional_change in (-0.10, 0.10):
        perturbed = dict(parameters)
        perturbed["throat_diameter_m"] *= 1.0 + fractional_change
        perturbed["throat_radius_of_curvature_m"] *= 1.0 + fractional_change
        value = independent_bartz(**perturbed)
        rows.append(
            {
                "variable": "geometrically_similar_Dt_and_rc",
                "input_change_percent": 100.0 * fractional_change,
                "h_change_percent": 100.0
                * (value["coefficient_w_m2k"] / base["coefficient_w_m2k"] - 1.0),
                "qconv_change_percent": 100.0
                * (value["convective_flux_w_m2"] / base["convective_flux_w_m2"] - 1.0),
            }
        )
    return rows


def _water_saturation_temperature_k(pressure_bar: float) -> float:
    from CoolProp.CoolProp import PropsSI
    try:
        return PropsSI("T","P",pressure_bar*1e5,"Q",0,"Water")
    except ValueError:
        return nan


def _finite_max(values: Sequence[float]) -> float:
    return max((value for value in values if isfinite(value)),default=nan)


def run(case: AuditCase, output_dir: Path, station_count: int) -> dict[str, object]:
    core, regen, gas = _build_case(case)
    result = _solve_count(core, regen, gas, station_count, case.gas_emissivity)
    station_rows, maximum_bartz_error = _station_rows(case, core, result)
    _write_csv(output_dir / "station_audit.csv", station_rows)

    throat_row = min(
        station_rows,
        key=lambda row: abs(float(row["x_m"]) - core.contour.throat_x_m),
    )
    _write_csv(
        output_dir / "bartz_sensitivity.csv",
        _sensitivity_rows(throat_row, case, core),
    )

    convergence_rows: list[dict[str, object]] = []
    convergence_results: dict[tuple[int, float], object] = {}
    for count in (350, 700, 1400):
        for emissivity in sorted({0.0,0.02,case.gas_emissivity,0.16}):
            candidate = _solve_count(core, regen, gas, count, emissivity)
            convergence_results[count, emissivity] = candidate
            maximum_index = max(
                range(candidate.station_count), key=lambda index: candidate.Twg[index] if isfinite(candidate.Twg[index]) else -float("inf")
            )
            throat_index = min(
                range(candidate.station_count),
                key=lambda index: abs(candidate.x_m[index] - core.contour.throat_x_m),
            )
            convergence_rows.append(
                {
                    "axial_station_count": count,
                    "gas_emissivity": emissivity,
                    "physical_validity":candidate.physical_validity,
                    "solved_station_count":sum(isfinite(value) for value in candidate.Twg),
                    "energy_residual_w":candidate.metadata["energy_balance_by_segment"].get("water",{}).get("residual_w",nan),
                    "maximum_hot_wall_temperature_k": candidate.Twg[maximum_index],
                    "maximum_hot_wall_x_mm": candidate.x_m[maximum_index] * 1000.0,
                    "throat_hot_wall_temperature_k": candidate.Twg[throat_index],
                    "throat_heat_flux_w_m2": candidate.heat_flux_w_m2[throat_index],
                    "coolant_outlet_temperature_k": candidate.coolant_outlet_temperature_k[
                        "water"
                    ],
                    "coolant_outlet_pressure_bar": candidate.coolant_outlet_pressure_bar[
                        "water"
                    ],
                }
            )
    _write_csv(output_dir / "axial_convergence.csv", convergence_rows)

    valid_pressure = [value for value in result.coolant_pressure_bar if value == value]
    minimum_pressure = min(valid_pressure,default=nan)
    summary: dict[str, object] = {
        "case": asdict(case),
        "rocketcea_performance": {
            "source": core.performance.source,
            "hot_gas_mass_flow_kg_s": core.performance.hot_gas_mass_flow_kg_s,
            "delivered_cstar_m_s": core.performance.delivered_cstar_m_s,
            "combustion_temperature_k": core.performance.combustion_temperature_k,
            "gamma_from_exit": core.performance.gamma,
            "molecular_weight_kg_kmol_from_exit": core.performance.molecular_weight_kg_kmol,
        },
        "station_count": result.station_count,
        "maximum_independent_vs_production_bartz_relative_error": maximum_bartz_error,
        "maximum_hot_wall_temperature_k": _finite_max(result.Twg),
        "maximum_coolant_wall_temperature_k": _finite_max(result.Twc),
        "maximum_bulk_coolant_temperature_k": _finite_max(result.Tc),
        "physical_validity":result.physical_validity,
        "physical_issues":result.physical_issues,
        "solved_station_count":sum(isfinite(value) for value in result.Twg),
        "numerical_converged":result.converged,
        "coolant_property_sources":result.metadata["coolant_property_sources"],
        "energy_balance_by_segment":result.metadata["energy_balance_by_segment"],
        "gas_radiation_inputs":result.metadata["gas_radiation_inputs"],
        "coolant_outlet_temperature_k": result.coolant_outlet_temperature_k["water"],
        "coolant_outlet_pressure_bar": result.coolant_outlet_pressure_bar["water"],
        "coolant_outlet_phase":result.coolant_outlet_phase.get("water"),
        "coolant_outlet_enthalpy_j_kg":result.coolant_outlet_enthalpy_j_kg.get("water"),
        "minimum_local_coolant_pressure_bar": minimum_pressure,
        "water_saturation_temperature_at_inlet_pressure_k": _water_saturation_temperature_k(
            case.water_inlet_pressure_bar
        ),
        "water_saturation_temperature_at_minimum_pressure_k": _water_saturation_temperature_k(
            minimum_pressure
        ),
        "model_capability": {
            "axial_convergence_counts": [350, 700, 1400],
            "radial_mesh": False,
            "time_integration": False,
            "coolant_phase_change": False,
            "real_fluid_eos_phase_detection":True,
            "bulk_enthalpy_march":True,
            "rectangular_rib_fin_area":True,
            "cylindrical_wall_conduction":True,
            "axial_solid_conduction": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "docs" / "thermal_audit_outputs",
    )
    parser.add_argument("--station-count", type=int, default=700)
    parser.add_argument("--pc-bar", type=float, default=10.0)
    parser.add_argument("--mixture-ratio", type=float, default=2.6)
    parser.add_argument("--throat-diameter-mm", type=float, default=31.79)
    parser.add_argument("--water-flow-percent", type=float, default=100.0)
    parser.add_argument("--gas-emissivity", type=float, default=0.08)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.station_count < 3:
        raise SystemExit("--station-count must be at least 3")
    case = AuditCase(
        chamber_pressure_bar=arguments.pc_bar,
        mixture_ratio=arguments.mixture_ratio,
        throat_diameter_mm=arguments.throat_diameter_mm,
        water_flow_percent=arguments.water_flow_percent,
        gas_emissivity=arguments.gas_emissivity,
    )
    summary = run(case, arguments.output_dir.resolve(), arguments.station_count)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
