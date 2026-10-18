"""Run isolated -I -S against an extracted Beta EXE bundle (host interpreter required)."""
from pathlib import Path
import os,sys,json
bundle=Path(sys.argv[1]).resolve();output=Path(sys.argv[2]).resolve()
sys.path.insert(0,str(bundle));sys.path.insert(1,str(bundle/'base_library.zip'))
sys.frozen=True;sys._MEIPASS=str(bundle)
dll_handles=[os.add_dll_directory(str(p)) for p in {bundle,*[f.parent for f in bundle.rglob('*.dll')]}]
import CoolProp
from CoolProp.CoolProp import PropsSI,PhaseSI
import numpy
from lpa.core import AnalysisInput,EngineDefinition,ThrustChamberInput,NozzleExitCondition,AmbientConditions,optimize_mixture_ratio
from lpa.core.analysis import analyze_engine
from lpa.thermal import analyze_thermal,ThermalSolverSettings
from lpa.thermal.coolants import get_coolant_model
assert Path(CoolProp.__file__).resolve().is_relative_to(bundle),CoolProp.__file__
assert Path(numpy.__file__).resolve().is_relative_to(bundle),numpy.__file__
assert CoolProp.__version__=='8.0.0'
rho=PropsSI('Dmass','T',150,'P',2e6,'Oxygen');phase=PhaseSI('T',150,'P',2e6,'Oxygen')
assert 60<rho<63 and phase=='gas'
state=get_coolant_model('LCH4').at_state(200,5e6)
assert 7200<state.specific_heat_j_kgk<7400 and state.phase=='supercritical'
assert state.pseudocritical_temperature_k>190
inputs=AnalysisInput(engine=EngineDefinition(oxidizer='LOX',fuel='RP-1',chamber_pressure_bar=20,mixture_ratio=2.5),thrust_chamber=ThrustChamberInput(exit_condition=NozzleExitCondition(mode="expansion_ratio",expansion_area_ratio=5),ambient=AmbientConditions(enabled=True,fixed_pressure_atm=0)))
engine=analyze_engine(inputs,require_rocketcea=True)
assert engine.performance.source=='rocketcea'
assert engine.thermodynamics.source=='rocketcea-local-stations-and-transport'
assert engine.thermodynamics.bartz_reference_specific_heat_j_kgk>0
optimum=optimize_mixture_ratio(EngineDefinition(fuel='Ethanol',fuel_mass_fraction=.7),contraction_area_ratio=6.25,expansion_ratio=5)
assert optimum.source=='rocketcea' and optimum.objective=='maximum theoretical vacuum specific impulse'
assert abs(optimum.mixture_ratio-1.313420882)<2e-5 and abs(optimum.vacuum_isp_s-278.718641352)<2e-5
contour={'x_m':(0,.025,.05),'radius_m':(.02,.02,.02),'throat_index':1,'throat_x_m':.025,'chamber_end_index':0}
gas={'combustion_temperature_k':1000,'chamber_pressure_pa':2e6,'characteristic_velocity_m_s':1500,'total_mass_flow_kg_s':1,'gamma':1.22,'gas_constant_j_kgk':355}
regen={'type':'regen','segment_id':'water','x_start_m':0,'x_end_m':.05,'wall_thickness_mm':1,'wall_conductivity_w_mk':300,'channel_height_mm':2,'channel_count':20,'width_mode':'channel_width','widths_mm':2,'coflow':True,'coolant':{'coolant':'H2O','inlet_temperature_k':290,'inlet_pressure_bar':40,'mass_flow_kg_s':.5}}
thermal=analyze_thermal(contour,gas,[regen],ThermalSolverSettings(resolution='Low',gas_emissivity=0))
assert thermal.converged and thermal.metadata['coolant_property_sources']['water'].startswith('CoolProp')
assert abs(thermal.metadata['energy_balance_by_segment']['water']['residual_w'])<1e-4
record={'validation_mode':'Extracted EXE modules and native libraries under isolated -I -S CPython 3.14; not a clean-machine frozen-executable run','CoolProp_version':CoolProp.__version__,'CoolProp_file':CoolProp.__file__,'numpy_file':numpy.__file__,'oxygen_150K_20bar_density':rho,'oxygen_phase':phase,'methane_200K_50bar_cp':state.specific_heat_j_kgk,'methane_phase':state.phase,'methane_pseudocritical_T':state.pseudocritical_temperature_k,'performance_source':engine.performance.source,'vacuum_isp_s':engine.performance.with_film.isp_vacuum_s,'thermal_converged':thermal.converged,'thermal_physical_validity':thermal.physical_validity,'thermal_energy_residual_w':thermal.metadata['energy_balance_by_segment']['water']['residual_w']}
import ht,fluids
assert Path(ht.__file__).resolve().is_relative_to(bundle)
assert Path(fluids.__file__).resolve().is_relative_to(bundle)
lng=get_coolant_model('LNG').at_state(150,25e5)
assert lng.phase=='liquid' and 380<lng.density_kg_m3<390
regen['coolant']['mass_flow_kg_s']=.05
gas['combustion_temperature_k']=3400
boiling=analyze_thermal(contour,gas,[regen],ThermalSolverSettings(resolution='Low',gas_emissivity=0))
assert boiling.coolant_phase.count('two_phase')>5
assert all(__import__('math').isfinite(v) for v in boiling.Twg)
assert abs(boiling.metadata['energy_balance_by_segment']['water']['residual_w'])<1e-3
record['beta_boiling']={'two_phase_stations':boiling.coolant_phase.count('two_phase'),'physical_validity':boiling.physical_validity,'energy_balance':boiling.metadata['energy_balance_by_segment']}
record['LNG_150K_25bar_density']=lng.density_kg_m3
rp1=get_coolant_model('RP-1').at_state(450.,20e5)
assert rp1.property_applicability=='unsupported' and __import__('math').isnan(rp1.viscosity_pa_s)
assert 'NISTIR 6646' in rp1.transport_source
record['RP1_450K_20bar']={'property_applicability':rp1.property_applicability,
    'phase':rp1.phase,'viscosity_available':False,'transport_source':rp1.transport_source}
record['thermal_wall_solution_complete']=thermal.metadata['wall_solution_complete']
record['automatic_of']={'objective':optimum.objective,'source':optimum.source,'mixture_ratio':optimum.mixture_ratio,'theoretical_vacuum_isp_s':optimum.vacuum_isp_s}
output.write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record,indent=2))
