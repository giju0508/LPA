"""Reproduce release thermal EOS, applicability, and radiation scenarios.

This is a numerical benchmark with a specified 50 mm cylinder, constant gamma,
and screening gas transport. It is not experimental validation of a combustor
or a calibrated radiation/boiling/critical-heat-flux model.

Run: python -B -m tools.thermal_release_benchmarks --output-dir <directory>
"""

from __future__ import annotations

import argparse
import csv
import json
from math import isfinite
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import CoolProp
from lpa.thermal import ThermalSolverSettings, analyze_thermal, thermal_radiation_sensitivity
from lpa.thermal.coolants import get_coolant_model


def _contour() -> dict[str, object]:
    return {
        "x_m": (0.0, 0.025, 0.05), "radius_m": (0.02,) * 3,
        "throat_index": 1, "throat_x_m": 0.025, "chamber_end_index": 0,
    }


def _gas(temperature: float = 1000.0) -> dict[str, object]:
    return {
        "combustion_temperature_k": temperature, "chamber_pressure_pa": 2e6,
        "characteristic_velocity_m_s": 1500.0, "total_mass_flow_kg_s": 1.0,
        "gamma": 1.22, "gas_constant_j_kgk": 355.0,
    }


def _regen() -> dict[str, object]:
    return {
        "type": "regen", "segment_id": "water", "x_start_m": 0.0,
        "x_end_m": 0.05, "wall_thickness_mm": 1.0,
        "wall_conductivity_w_mk": 300.0, "channel_height_mm": 2.0,
        "channel_count": 20, "width_mode": "channel_width", "widths_mm": 2.0,
        "coflow": True,
        "coolant": {
            "coolant": "H2O", "inlet_temperature_k": 290.0,
            "inlet_pressure_bar": 40.0, "mass_flow_kg_s": 0.5,
        },
    }


def _json_finite(value: object) -> object:
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_finite(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_finite(item) for item in value]
    return value


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = ThermalSolverSettings(resolution="low", gas_emissivity=0.0)
    cases = (
        ("H2O", 290.0, 40.0, 0.5), ("LOX", 90.0, 40.0, 0.5),
        ("LCH4", 111.0, 60.0, 0.5), ("LH2", 21.0, 20.0, 0.1),
        ("N2O", 285.0, 60.0, 0.5), ("Ethanol (70%)", 293.15, 40.0, 0.5),
        ("LNG", 111.66, 60.0, 0.5), ("H2O2 (90%)", 293.15, 40.0, 0.5),
    )
    rows: list[dict[str, object]] = []
    for name, temperature, pressure, mass_flow in cases:
        started = perf_counter()
        segment = _regen()
        segment["coolant"].update(
            coolant=name, inlet_temperature_k=temperature,
            inlet_pressure_bar=pressure, mass_flow_kg_s=mass_flow,
        )
        result = analyze_thermal(_contour(), _gas(), [segment], settings)
        balance = result.metadata["energy_balance_by_segment"]["water"]
        rows.append({
            "coolant": name, "inlet_T_K": temperature, "inlet_p_bar": pressure,
            "mass_flow_kg_s": mass_flow, "physical_validity": result.physical_validity,
            "numerical_converged": result.converged,
            "solved_stations": sum(isfinite(item) for item in result.Twg),
            "outlet_T_K": result.coolant_outlet_temperature_k["water"],
            "outlet_p_bar": result.coolant_outlet_pressure_bar["water"],
            "energy_residual_W": balance["residual_w"],
            "elapsed_s": perf_counter() - started,
            "physical_issues": list(result.physical_issues),
        })
    pressure_rows: list[dict[str, object]] = []
    for name in ("GOX", "GCH4", "GH2"):
        for pressure in (10.0, 30.0, 100.0):
            state = get_coolant_model(name).at_state(300.0, pressure * 1e5)
            pressure_rows.append({
                "coolant": name, "temperature_K": 300.0, "pressure_bar": pressure,
                "density_kg_m3": state.density_kg_m3, "phase": state.phase,
                "source": state.source, "critical_T_K": state.critical_temperature_k,
                "critical_p_bar": state.critical_pressure_pa / 1e5,
            })
    segment = _regen()
    segment.update(channel_count=100, widths_mm=0.5)
    segment["coolant"].update(mass_flow_kg_s=2.0, inlet_pressure_bar=80.0)
    sensitivity = thermal_radiation_sensitivity(
        _contour(), _gas(3400.0), [segment], settings=settings,
    )
    payload = {
        "CoolProp_version": CoolProp.__version__,
        "benchmark_definition": (
            "Independent 50 mm cylindrical thermal test, 20 mm hot radius, "
            "constant-gamma screening gas model; not hot-fire validation"
        ),
        "coolant_cases": rows, "pressure_state_matrix": pressure_rows,
        "radiation_sensitivity_3400K": sensitivity,
    }
    (output_dir / "thermal_method_benchmarks.json").write_text(
        json.dumps(_json_finite(payload), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _write_csv(output_dir / "coolant_case_matrix.csv", rows)
    _write_csv(output_dir / "pressure_state_matrix.csv", pressure_rows)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs" / "thermal_audit_outputs_0140")
    arguments = parser.parse_args()
    result = run(arguments.output_dir.resolve())
    print(json.dumps({
        "output_dir": str(arguments.output_dir.resolve()),
        "coolant_cases": len(result["coolant_cases"]),
        "pressure_states": len(result["pressure_state_matrix"]),
        "radiation_scenarios": len(result["radiation_sensitivity_3400K"]["cases"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
