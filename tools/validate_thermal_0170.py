"""Record property health and optional user-case diagnostics without copying inputs."""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from math import isfinite
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lpa import __version__
from lpa.analysis import AnalysisService
from lpa.thermal.coolants import coolant_state, coolant_state_from_quality


def clean(value):
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, dict):
        return {key:clean(item) for key,item in value.items()}
    if isinstance(value, (tuple,list)):
        return [clean(item) for item in value]
    return value


def review_case(project, height):
    case = copy.deepcopy(project)
    segment = case["thermal"]["segments"][0]
    segment["id"] = "circuit_1"
    segment["name"] = "RP-1 review circuit"
    for key in ("channel_height_1_mm","channel_height_min_mm","channel_height_2_mm"):
        segment[key] = str(height)
    result = AnalysisService().analyze(case)
    thermal = result["thermal"]
    metadata = thermal["metadata"]
    hot = thermal["twg_k"]
    solved = [i for i,value in enumerate(hot) if value is not None and isfinite(value)]
    peak = max(solved,key=lambda i:hot[i]) if solved else None
    last_index = min(solved) if solved else None  # Counterflow review circuit.
    return {
        "height_mm":height, "numerically_converged":thermal["converged"],
        "physical_validity":thermal["physical_validity"],
        "solved_wall_station_count":metadata["solved_wall_station_count"],
        "unsolved_station_count":metadata["unsolved_station_count"],
        "wall_solution_complete":metadata["wall_solution_complete"],
        "segment_completion":metadata["regen_segment_completion"],
        "property_metadata":metadata["coolant_property_metadata"],
        "diagnostic_peak_Twg_K":None if peak is None else hot[peak],
        "diagnostic_peak_x_mm":None if peak is None else thermal["x_mm"][peak],
        "last_solved_index":last_index,
        "last_available_coolant_temperature_K":thermal["coolant_outlet_temperature_k"],
        "pressure_drop_for_solved_path_bar":thermal["coolant_pressure_drop_bar"],
        "energy_balance":metadata["energy_balance_by_segment"],
        "phase_counts":{str(p):thermal["coolant_phase"].count(p) for p in set(thermal["coolant_phase"])},
        "warnings":thermal["warnings"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",type=Path)
    parser.add_argument("--output-directory",type=Path,required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    samples = [
        ("H2O",290,40e5),("H2O",3000,40e5),
        ("LOX",90,30e5),("LOX",150,20e5),
        ("LCH4",150,25e5),("LCH4",200,50e5),("LH2",21,20e5),
        ("LNG",150,25e5),("LNG",180,25e5),
        ("Ethanol (70%)",293.15,25e5),("Ethanol (100%)",293.15,25e5),
        ("Ethanol (100%)",620,25e5),("N2O",280,50e5),
        ("RP-1",293,20e5),("RP-1",400,20e5),("RP-1",450,20e5),
        ("Jet A-1",293,20e5),("IPA (100%)",293,25e5),("H2O2 (90%)",293,25e5),
        ("Propane",280,25e5),("GH2",300,100e5),
    ]
    matrix = []
    for name,temperature,pressure in samples:
        state = coolant_state(name,temperature,pressure)
        matrix.append({"name":name,"specified_T_K":temperature,"specified_p_Pa":pressure,"state":asdict(state)})
    saturation = []
    for name,pressure in [("H2O",40e5),("LOX",20e5),("LCH4",20e5),("LH2",5e5),
                          ("Propane",20e5),("Ethanol (100%)",20e5),("LNG",25e5),("Ethanol (70%)",25e5)]:
        state = coolant_state_from_quality(name,pressure,.1)
        saturation.append({"name":name,"state":asdict(state)})
    record = {"version":__version__,"generated_utc":datetime.now(timezone.utc).isoformat(),
              "property_matrix":matrix,"saturated_x_mass_0p1":saturation}
    if args.project:
        raw = args.project.read_bytes()
        project = json.loads(raw.decode("utf-8-sig"))
        segments=project.get("thermal",{}).get("segments",[])
        if (project.get("engine",{}).get("fuel") != "RP-1" or len(segments)!=1
                or segments[0].get("type") != "Regen" or segments[0].get("reverse_coolant_flow",False)):
            parser.error("optional channel review requires one counterflow RP-1 Regen circuit")
        record["review_input_sha256"] = hashlib.sha256(raw).hexdigest()
        record["channel_cases"] = [review_case(project,height) for height in (1.3,1.8)]
        assert args.project.read_bytes() == raw, "review must not modify the input project"
        record["input_unchanged"] = True
    args.output_directory.mkdir(parents=True,exist_ok=True)
    output = args.output_directory/"property_and_channel_review.json"
    output.write_text(json.dumps(clean(record),ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Wrote {output}; {len(matrix)} PT states and {len(saturation)} saturation states")


if __name__ == "__main__":
    main()
