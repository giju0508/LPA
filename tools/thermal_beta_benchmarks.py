"""Reproducible Beta property, RPA-reference and two-phase balance evidence.

Run: python -B -m tools.thermal_beta_benchmarks
The boiling cylinder is a numerical screening benchmark, not a hot-fire test.
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import csv
import importlib.metadata
import json
from math import isfinite
from pathlib import Path

from lpa import __version__
from lpa.thermal import (analyze_thermal, coolant_state, coolant_state_from_enthalpy,
                        bartz_heat_transfer_coefficient,adiabatic_wall_temperature)


def finite(value):
    if isinstance(value,float) and not isfinite(value): return None
    if isinstance(value,dict): return {str(k):finite(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [finite(v) for v in value]
    return value


def run(output_dir=Path("docs/thermal_beta_outputs_0160")):
    output_dir.mkdir(parents=True,exist_ok=True)
    properties=[]
    for name,t,p in [("LNG",150.,20.),("LNG",150.,25.),("LNG",150.,30.),
                     ("H2O",500.,40.),("LCH4",111.,60.),("LH2",21.,20.),
                     ("LOX",90.,40.),("Ethanol (100%)",600.,100.)]:
        state=coolant_state(name,t,p*1e5)
        advanced=coolant_state_from_enthalpy(name,state.enthalpy_j_kg+2500.,p*1e5-1000.,temperature_hint_k=t)
        properties.append(dict(coolant=name,inlet_T_K=t,inlet_p_bar=p,
            phase=state.phase,density_kg_m3=state.density_kg_m3,Cp_J_kgK=state.specific_heat_j_kgk,
            outlet_phase=advanced.phase,outlet_T_K=advanced.temperature_k,
            enthalpy_rise_J_kg=advanced.enthalpy_j_kg-state.enthalpy_j_kg,
            source=state.source,issues=state.issues,limits=asdict(state.property_limits) if state.property_limits else None))
    fixture=json.loads(Path("tests/fixtures/rpa_bartz_fixed_wall_4_0_13.json").read_text(encoding="utf-8"))
    cfg,ref=fixture["configuration"],fixture["gas_reference"]
    cp,pr=ref["frozen_specific_heat_j_kgk"],ref["frozen_prandtl"]
    gamma=cp/(cp-ref["gas_constant_j_kgk"])
    comparison=[]
    for station in fixture["stations"]:
        coefficient=bartz_heat_transfer_coefficient(chamber_pressure_pa=cfg["chamber_pressure_pa"],
            characteristic_velocity_m_s=ref["characteristic_velocity_m_s"],
            throat_diameter_m=cfg["throat_diameter_m"],
            throat_radius_of_curvature_m=cfg["upstream_throat_radius_ratio"]*cfg["throat_diameter_m"]/2,
            area_ratio=station["area_ratio"],wall_temperature_k=cfg["fixed_wall_temperature_k"],
            stagnation_temperature_k=ref["stagnation_temperature_k"],mach=station["mach"],
            viscosity_pa_s=ref["viscosity_pa_s"],specific_heat_j_kgk=cp,prandtl=pr,gamma=gamma)
        flux=coefficient*(adiabatic_wall_temperature(ref["stagnation_temperature_k"],station["mach"],gamma,pr)-cfg["fixed_wall_temperature_k"])
        comparison.append(dict(station=station,computed_h_W_m2K=coefficient,computed_q_W_m2=flux,
            relative_h_error=coefficient/station["heat_transfer_coefficient_w_m2k"]-1,
            relative_q_error=flux/station["convective_heat_flux_w_m2"]-1))
    contour={"x_m":(0.,.025,.05),"radius_m":(.02,)*3,"throat_index":1,"throat_x_m":.025,"chamber_end_index":0}
    gas={"combustion_temperature_k":3400.,"chamber_pressure_pa":2e6,"characteristic_velocity_m_s":1500.,
         "total_mass_flow_kg_s":1.,"gamma":1.22,"gas_constant_j_kgk":355.}
    segment={"type":"regen","segment_id":"water","x_start_m":0.,"x_end_m":.05,
        "wall_thickness_mm":1.,"wall_conductivity_w_mk":300.,"channel_height_mm":2.,
        "channel_count":20,"width_mode":"channel_width","widths_mm":2.,"coflow":True,
        "coolant":{"coolant":"H2O","inlet_temperature_k":290.,"inlet_pressure_bar":40.,"mass_flow_kg_s":.025}}
    result=analyze_thermal(contour,gas,[segment],{"resolution":"low","gas_emissivity":0.})
    rows=[dict(x_mm=x*1000,Twg_K=result.Twg[i],Twc_K=result.Twc[i],Tc_K=result.Tc[i],
        phase=result.coolant_phase[i],vapor_mass_quality=result.coolant_vapor_quality[i],
        regime=result.coolant_flow_regime[i],pressure_bar=result.coolant_pressure_bar[i]) for i,x in enumerate(result.x_m)]
    with (output_dir/"two_phase_stations.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    payload=dict(version=__version__,timestamp_kst=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        dependencies={name:importlib.metadata.version(name) for name in ("CoolProp","rocketcea","ht","fluids")},
        property_roundtrips=properties,rpa_fixed_wall_comparison=comparison,
        boiling_benchmark_definition={"contour":contour,"gas":gas,"segment":segment,
            "limitation":"Specified constant-gamma gas screening benchmark, not hot-fire or CEA validation"},
        boiling_result={"physical_validity":result.physical_validity,"issues":result.physical_issues,
            "converged":result.converged,"solved":sum(isfinite(v) for v in result.Twg),
            "two_phase_stations":result.coolant_phase.count("two_phase"),
            "outlet_T_K":result.coolant_outlet_temperature_k,"outlet_p_bar":result.coolant_outlet_pressure_bar,
            "energy_balance":result.metadata["energy_balance_by_segment"],"metadata":result.metadata})
    (output_dir/"summary.json").write_text(json.dumps(finite(payload),ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    fig,ax=plt.subplots(figsize=(10,4.8))
    x=[row["x_mm"] for row in rows]
    for field,label in (("Twg_K","Hot wall"),("Twc_K","Coolant wall"),("Tc_K","Bulk coolant")):
        ax.plot(x,[row[field] for row in rows],label=label)
    ii=[i for i,row in enumerate(rows) if row["phase"]=="two_phase"]
    if ii: ax.axvspan(x[min(ii)],x[max(ii)],color="#f5ad42",alpha=.25,hatch="//",label="Two-phase coolant (Beta)")
    ax.set(xlabel="Axial position (mm)",ylabel="Temperature (K)",ylim=(0,None),
        title="LPA 0.16.0b1: numerical boiling benchmark (screening)")
    ax.legend();ax.grid(alpha=.2);fig.tight_layout();fig.savefig(output_dir/"two_phase_channel.png",dpi=160);plt.close(fig)
    return payload


if __name__=="__main__":
    data=run()
    print(json.dumps({"version":__version__,"boiling_result":{k:v for k,v in data["boiling_result"].items() if k!="metadata"}},ensure_ascii=False,indent=2))
