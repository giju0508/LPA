"""Record complete-channel checks and provider evidence without copying private input."""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
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
from lpa.thermal import analyze_thermal,ThermalSolverSettings
from lpa.thermal.coolants import coolant_state,coolant_state_from_quality


def clean(value):
    if isinstance(value,float) and not isfinite(value): return None
    if isinstance(value,dict): return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [clean(v) for v in value]
    return value


def synthetic_channel(name,inlet,mdot,gas_temperature):
    contour={"x_m":(0.,.025,.05),"radius_m":(.02,)*3,"throat_index":1,
             "throat_x_m":.025,"chamber_end_index":0}
    gas={"combustion_temperature_k":gas_temperature,"chamber_pressure_pa":2e6,
         "characteristic_velocity_m_s":1500.,"total_mass_flow_kg_s":1.,"gamma":1.22,
         "gas_constant_j_kgk":355.}
    segment={"type":"regen","segment_id":"public_cylinder","x_start_m":0.,"x_end_m":.05,
        "wall_thickness_mm":1.,"wall_conductivity_w_mk":300.,"channel_height_mm":2.,
        "channel_count":20,"width_mode":"channel_width","widths_mm":2.,"coflow":True,
        "coolant":{"coolant":name,"inlet_temperature_k":inlet,"inlet_pressure_bar":25.,
                   "mass_flow_kg_s":mdot}}
    result=analyze_thermal(contour,gas,[segment],ThermalSolverSettings(resolution="medium",gas_emissivity=0.))
    quality=[q for q in result.coolant_vapor_quality if isfinite(q)]
    assert result.metadata["wall_solution_complete"]
    assert {"liquid","two_phase","gas"} <= set(result.coolant_phase)
    assert max(quality)>.7
    balance=result.metadata["energy_balance_by_segment"]["public_cylinder"]
    assert abs(balance["residual_w"])<1e-3
    return {"coolant":name,"inlet_K":inlet,"inlet_bar":25.,"mass_flow_kg_s":mdot,
        "gas_temperature_K":gas_temperature,"mesh_stations":result.section_count,
        "wall_solution_complete":result.metadata["wall_solution_complete"],
        "converged":result.converged,"physical_validity":result.physical_validity,
        "phase_counts":{str(p):result.coolant_phase.count(p) for p in set(result.coolant_phase)},
        "two_phase_quality_extent":(min(quality),max(quality)),
        "outlet_K":result.coolant_outlet_temperature_k,"outlet_bar":result.coolant_outlet_pressure_bar,
        "peak_Twg_K":max(result.Twg),"energy_balance":balance,
        "wet_wall_assumed_count":sum(v is True for v in result.coolant_wet_wall_assumed),
        "metadata":result.metadata,"warnings":result.warnings,
        "validation_meaning":"numerical continuation and conservation, not experimental validation or CHF/dryout prediction"}


def private_rp1(project,height):
    case=copy.deepcopy(project)
    segment=case["thermal"]["segments"][0]
    segment["id"]="circuit_1";segment["name"]="RP-1 review circuit"
    for key in ("channel_height_1_mm","channel_height_min_mm","channel_height_2_mm"):
        segment[key]=str(height)
    thermal=AnalysisService().analyze(case)["thermal"]
    meta=thermal["metadata"]
    assert meta["wall_solution_complete"]
    assert abs(meta["energy_balance_by_segment"]["circuit_1"]["residual_w"])<1e-3
    solved=[i for i,v in enumerate(thermal["twg_k"]) if v is not None and isfinite(v)]
    peak=max(solved,key=lambda i:thermal["twg_k"][i])
    return {"channel_height_mm":height,"backend":meta["gas_state_source"],
        "wall_solution_complete":meta["wall_solution_complete"],"converged":thermal["converged"],
        "solved_stations":len(solved),"requested_stations":len(thermal["x_mm"]),
        "physical_validity":thermal["physical_validity"],"peak_Twg_K":thermal["twg_k"][peak],
        "peak_x_mm":thermal["x_mm"][peak],"outlet_K":thermal["coolant_outlet_temperature_k"],
        "pressure_drop_bar":thermal["coolant_pressure_drop_bar"],
        "energy_balance":meta["energy_balance_by_segment"],
        "property_metadata":meta["coolant_property_metadata"],"warnings":thermal["warnings"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",type=Path)
    parser.add_argument("--output-directory",type=Path,required=True)
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    record={"version":__version__,"generated_utc":datetime.now(timezone.utc).isoformat()}
    record["property_matrix"]=[{"name":name,"specified_K":t,"specified_Pa":p,"state":asdict(coolant_state(name,t,p))}
        for name,t,p in [("RP-1",293.15,20e5),("RP-1",400.,20e5),("RP-1",600.,20e5),
                         ("RP-1",650.,20e5),("LNG",150.,25e5),
                         ("Ethanol (70%)",293.15,25e5),("Ethanol (70%)",468.,25e5)]]
    record["equilibrium_quality_checks"]=[{"name":name,"mass_quality":q,
        "state":asdict(coolant_state_from_quality(name,25e5,q))}
        for name in ("LNG","Ethanol (70%)") for q in (0.,.2,.6,.9,.99,1.)]
    record["public_synthetic_channels"]=[]
    for parameters in [("LNG",150.,.04,1500.),("Ethanol (70%)",293.15,.02,2500.)]:
        item=synthetic_channel(*parameters)
        record["public_synthetic_channels"].append(item)
        print(f"{item['coolant']}: {item['mesh_stations']}/{item['mesh_stations']} complete; outlet {item['outlet_K']}",flush=True)
    if args.project:
        raw=args.project.read_bytes();project=json.loads(raw.decode("utf-8-sig"))
        assert project["engine"]["fuel"]=="RP-1" and len(project["thermal"]["segments"])==1
        record["private_input_sha256"]=hashlib.sha256(raw).hexdigest()
        record["private_rp1_summary"]=[private_rp1(project,h) for h in (1.3,1.8)]
        assert args.project.read_bytes()==raw
        record["private_input_unchanged"]=True
    args.output_directory.mkdir(parents=True,exist_ok=True)
    output=args.output_directory/"coolant_channel_validation.json"
    output.write_text(json.dumps(clean(record),ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Saved {output}",flush=True)


if __name__=="__main__": main()
