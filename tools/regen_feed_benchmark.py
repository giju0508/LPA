"""Real CEA/EOS coupling smoke test; partial cooling is not whole-engine validation."""
from __future__ import annotations
import copy
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lpa.analysis import AnalysisService
from lpa.ui.input_views import default_segment

import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=ROOT / "docs" / "thermal_audit_outputs_0140" / "partial_feed_feedback.json")
parser.add_argument("--automatic-of", action="store_true", help="Reoptimize theoretical vacuum Isp in every supply-feedback iteration")
arguments = parser.parse_args()
artifact = arguments.output.resolve()
artifact.parent.mkdir(parents=True, exist_ok=True)
segment = default_segment("Regen", 1)
segment.update(id="short_engine_fuel", name="Only first 5 mm cooled; remainder unsolved",
               x1="0", x2="5", coolant_source_mode="Engine fuel",
               coolant_inlet_temperature_k="300", coolant_inlet_pressure_bar="250",
               conductivity_mode="Specified conductivity", thermal_conductivity="400",
               wall_thickness_mm="0.5", channel_count="100",
               channel_height_1_mm="0.5", channel_height_min_mm="0.5", channel_height_2_mm="0.5",
               channel_width_1_mm="0.4", channel_width_min_mm="0.4", channel_width_2_mm="0.4")
project = {
    "engine": {"engine_name": "Partial 5 mm real CEA/EOS integration smoke test",
               "chamber_pressure_bar": "20", "mixture_ratio": "1.3", "mixture_ratio_auto": arguments.automatic_of,
               "oxidizer": "LOX", "fuel": "Ethanol", "fuel_mass_fraction_pct": "70",
               "fuel_temperature_k": "300", "fuel_pressure_bar": "250"},
    "thrust_chamber": {
        "contraction_mode": "Contraction area ratio", "contraction_area_ratio": "6.25",
        "exit_condition_mode": "Ambient pressure", "exit_condition_value": "1.0",
        "flow_model": "Shifting equilibrium", "reaction_efficiency_pct": "98",
        "nozzle_efficiency_mode": "Estimate", "throttle_enabled": False, "ambient_enabled": False,
        "sizing_mode": "Engine nominal thrust", "nominal_thrust": "2000", "thrust_unit": "N",
        "nominal_thrust_ambient_atm": "1", "chamber_length_mode": "Characteristic length",
        "characteristic_length_mm": "1200", "contraction_angle_deg": "45", "r2_ratio": "0.5",
        "r1_rt": "1.5", "nozzle_type": "Conical", "nozzle_half_angle_deg": "15", "rn_rt": "0.382"},
    "thermal": {"thermal_enabled": True, "thermal_resolution": "Low", "thermal_max_iterations": "200",
                "regen_feed_feedback_enabled": True, "segments": [segment]},
}
service = AnalysisService()
original = service._analyze_once
iterations = []
started = time.perf_counter()
def traced_once(current):
    begin = time.perf_counter()
    result = original(current)
    thermal = result.get("thermal", {})
    summary = {"index": len(iterations)+1, "elapsed_s": time.perf_counter()-begin,
               "supply_temperature_k": current["engine"].get("fuel_temperature_k"),
               "supply_pressure_bar": current["engine"].get("fuel_pressure_bar"),
               "applied_mixture_ratio": result["performance"]["mixture_ratio"],
               "mixture_ratio_optimization": result.get("mixture_ratio_optimization"),
               "thermal_converged": thermal.get("converged"),
               "physical_validity": thermal.get("physical_validity"),
               "outlet_temperature_k": thermal.get("coolant_outlet_temperature_k"),
               "outlet_pressure_bar": thermal.get("coolant_outlet_pressure_bar"),
               "outlet_phase": thermal.get("coolant_outlet_phase"),
               "warnings": result.get("warnings", [])}
    iterations.append(summary)
    print(json.dumps(summary), flush=True)
    return result
service._analyze_once = traced_once
payload = {"purpose": "Real RocketCEA + CoolProp + outer feed-state loop integration smoke test",
           "limitations": ["Only a 5 mm Regen segment; remainder of chamber/nozzle has unsolved wall temperatures",
                           "Not full-engine thermal accuracy, phase-safety, hardware, CFD or experimental validation",
                           "98% reaction efficiency uses explicitly diagnosed screening closure"],
           "input_project": project}
try:
    result = service.analyze(project)
    payload.update(elapsed_s=time.perf_counter()-started, iterations=iterations, result=result)
except Exception as error:
    payload.update(elapsed_s=time.perf_counter()-started, iterations=iterations,
                   error={"type": type(error).__name__, "message": str(error)})
    artifact.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    raise
artifact.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
print(json.dumps({"artifact": str(artifact), "elapsed_s": payload["elapsed_s"],
                  "feedback": result["regen_feed_feedback"],
                  "thermal_validity": result["thermal"].get("physical_validity")}), flush=True)
