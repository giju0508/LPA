"""Reproduce the supplied RP-1 case without publishing or changing its CFG."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime,timezone
import hashlib
import json
import logging
from math import isfinite
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lpa import __version__
from lpa.analysis import AnalysisService


def clean(value):
    if isinstance(value,float) and not isfinite(value):return None
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    return value


def review(project,resolution):
    case=copy.deepcopy(project)
    case["thermal"]["thermal_resolution"]=resolution
    segment=case["thermal"]["segments"][0]
    segment["id"]="circuit_1";segment["name"]="RP-1 review circuit"
    thermal=AnalysisService().analyze(case)["thermal"]
    metadata=thermal["metadata"]
    solved=[i for i,t in enumerate(thermal["twg_k"]) if t is not None and isfinite(t)]
    peak=max(solved,key=lambda i:thermal["twg_k"][i])
    first=max(solved)  # The supplied counterflow circuit enters at nozzle exit.
    assert metadata["wall_solution_complete"] and len(solved)==len(thermal["x_mm"])
    assert abs(metadata["energy_balance_by_segment"]["circuit_1"]["residual_w"])<1e-3
    return {"resolution":resolution,"converged":thermal["converged"],
        "solved_stations":len(solved),"requested_stations":len(thermal["x_mm"]),
        "peak_average_Twg_K":thermal["twg_k"][peak],"peak_x_mm":thermal["x_mm"][peak],
        "peak_sampled_Twg_K":max(thermal["wall_temperature_max_k"]),
        "inlet_cell_average_Twg_K":thermal["twg_k"][first],
        "inlet_cell_sampled_Twg_range_K":(thermal["wall_temperature_min_k"][first],thermal["wall_temperature_max_k"][first]),
        "coolant_outlet_K":thermal["coolant_outlet_temperature_k"],
        "pressure_drop_bar":thermal["coolant_pressure_drop_bar"],
        "energy_balance":metadata["energy_balance_by_segment"],
        "physical_validity":thermal["physical_validity"],
        "invalid_station_count":thermal["station_applicability"].count("invalid"),
        "wall_sampling":metadata["wall_sampling"],
        "entrance_diagnostics":metadata["coolant_entrance_diagnostics_by_segment"],
        "material_assessment":metadata["coolant_property_metadata"]["circuit_1"]["wall_material_assessment"],
        "warnings":thermal["warnings"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--output-directory",type=Path,required=True)
    args=parser.parse_args()
    raw=args.project.read_bytes();project=json.loads(raw.decode("utf-8-sig"))
    assert project["engine"]["fuel"]=="RP-1"
    assert len(project["thermal"]["segments"])==1
    assert not project["thermal"]["segments"][0].get("reverse_coolant_flow",False)
    logging.basicConfig(level=logging.INFO)
    record={"version":__version__,"generated_utc":datetime.now(timezone.utc).isoformat(),
        "input_sha256":hashlib.sha256(raw).hexdigest(),"cases":[]}
    for resolution in ("Low","Medium","High"):
        case=review(project,resolution);record["cases"].append(case)
        print(f"{resolution}: {case['solved_stations']} solved, peak {case['peak_average_Twg_K']:.6f} K, inlet cell {case['inlet_cell_average_Twg_K']:.6f} K, {case['physical_validity']}",flush=True)
    assert args.project.read_bytes()==raw
    record["input_unchanged"]=True
    args.output_directory.mkdir(parents=True,exist_ok=True)
    (args.output_directory/"nozzle_entry_validation.json").write_text(json.dumps(clean(record),ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":main()
