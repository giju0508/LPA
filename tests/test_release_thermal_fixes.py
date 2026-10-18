from __future__ import annotations

from math import isfinite, log, pi
from dataclasses import replace

import pytest
from CoolProp.CoolProp import PropsSI

from lpa.thermal import ThermalSolverSettings, analyze_thermal
from lpa.thermal import thermal_radiation_sensitivity
from lpa.thermal.coolants import get_coolant_model
from lpa.thermal.correlations import (
    cylindrical_conduction_resistance, internal_flow_heat_transfer,
    rectangular_fin_area_ratio, radiative_heat_flux,
)
import lpa.thermal.solver as solver


def cylinder():
    return {"x_m": (0.0, 0.025, 0.05), "radius_m": (0.02,)*3,
            "throat_index": 1, "throat_x_m":0.025, "chamber_end_index":0}


def gas(temperature=1000.0):
    return {"combustion_temperature_k":temperature,"chamber_pressure_pa":2e6,
            "characteristic_velocity_m_s":1500.,"total_mass_flow_kg_s":1.,
            "gamma":1.22,"gas_constant_j_kgk":355.}


def regen(identifier="water", start=0., end=.05, inlet_pressure_bar=40.):
    return {"type":"regen","segment_id":identifier,
            "x_start_m":start,"x_end_m":end,"wall_thickness_mm":1.,
            "wall_conductivity_w_mk":300.,"channel_height_mm":2.,
            "channel_count":20,"width_mode":"channel_width","widths_mm":2.,
            "coflow":True,"coolant":{"coolant":"H2O","inlet_temperature_k":290.,
                    "inlet_pressure_bar":inlet_pressure_bar,"mass_flow_kg_s":.5}}


def settings(**kwargs):
    return ThermalSolverSettings(resolution="low",gas_emissivity=0.,**kwargs)


@pytest.mark.parametrize("name,fluid,temperature,pressure",[
    ("LOX","Oxygen",150.,2e6),("N2O","NitrousOxide",300.,3e6),
    ("LH2","Hydrogen",35.,2e6),("LCH4","Methane",200.,5e6),
])
def test_real_fluid_state_and_critical_properties(name,fluid,temperature,pressure):
    state=get_coolant_model(name).at_state(temperature,pressure)
    assert state.source.startswith("CoolProp")
    assert state.density_kg_m3==pytest.approx(PropsSI("D","T",temperature,"P",pressure,fluid),rel=1e-11)
    assert state.specific_heat_j_kgk==pytest.approx(PropsSI("C","T",temperature,"P",pressure,fluid),rel=1e-11)
    assert state.critical_temperature_k==pytest.approx(PropsSI("Tcrit",fluid))
    assert state.phase in {"gas","supercritical"}


def test_pressure_dependent_gas_and_enthalpy_flash():
    model=get_coolant_model("GH2")
    low=model.at_state(300.,1e6); high=model.at_state(300.,1e7)
    assert high.density_kg_m3>9*low.density_kg_m3
    advanced=model.at_enthalpy(high.enthalpy_j_kg+100000.,1e7)
    assert advanced.enthalpy_j_kg-high.enthalpy_j_kg==pytest.approx(100000.,rel=1e-9)
    assert advanced.temperature_k>300.


def test_ethanol_mixture_uses_composition_specific_eos():
    state=get_coolant_model("Ethanol (70%)").at_state(293.15,3e6)
    assert state.source=="CoolProp HEOS: Ethanol&Water"
    assert 850<state.density_kg_m3<870
    assert state.phase=="liquid"
    assert "composition-specific validation" in " ".join(state.issues)


def test_mixture_liquid_root_and_enthalpy_are_stable_at_previous_failure_point():
    from lpa.thermal.coolants import coolant_state_from_enthalpy
    model=get_coolant_model("LNG")
    pressure=5999917.581996463
    state=model.at_state(111.66,pressure)
    advanced=coolant_state_from_enthalpy("LNG",state.enthalpy_j_kg+273.32,pressure,
                                       temperature_hint_k=111.66)
    assert 440<advanced.density_kg_m3<455
    assert 3000<advanced.specific_heat_j_kgk<3500
    assert advanced.phase=="supercritical_liquid"
    assert advanced.enthalpy_j_kg-state.enthalpy_j_kg==pytest.approx(273.32,abs=1e-6)


def test_unsupported_propellant_is_explicit_screening():
    state=get_coolant_model("H2O2 (90%)").at_state(350.,3e6)
    assert state.phase=="unknown"
    assert state.source=="screening"
    assert "no validated pressure/phase" in " ".join(state.issues)


def test_bulk_energy_closes_against_independent_eos_enthalpy():
    result=analyze_thermal(cylinder(),gas(),[regen()],settings())
    assert all(isfinite(t) for t in result.Tc)
    h_in=PropsSI("H","T",290.,"P",40e5,"Water")
    h_out=PropsSI("H","T",result.coolant_outlet_temperature_k["water"],
                  "P",result.coolant_outlet_pressure_bar["water"]*1e5,"Water")
    heat=result.metadata["energy_balance_by_segment"]["water"]["heat_pickup_w"]
    assert .5*(h_out-h_in)==pytest.approx(heat,rel=2e-8)
    assert abs(result.metadata["energy_balance_by_segment"]["water"]["residual_w"])<1e-4
    assert set(result.coolant_phase)=={"liquid"}


def test_unsupported_boiling_cannot_be_validated_by_numerical_convergence():
    segment=regen();segment["coolant"]["mass_flow_kg_s"]=.01
    result=analyze_thermal(cylinder(),gas(3400.),[segment],settings())
    assert result.physical_validity in {"unsupported","invalid"}
    assert any("boiling" in issue or "two-phase" in issue for issue in result.physical_issues)


@pytest.mark.parametrize("name,temperature,pressure,mass_flow",[
    ("LCH4",111.,60.,.5),("LH2",21.,20.,.1),
])
def test_pseudocritical_crossing_requires_unsupported_htd_model(name,temperature,pressure,mass_flow):
    segment=regen();segment["coolant"].update(coolant=name,inlet_temperature_k=temperature,
                     inlet_pressure_bar=pressure,mass_flow_kg_s=mass_flow)
    result=analyze_thermal(cylinder(),gas(),[segment],settings())
    assert result.physical_validity=="unsupported"
    assert any("pseudocritical" in issue and "unsupported" in issue for issue in result.physical_issues)


def test_exhausted_supply_invalidates_remaining_circuit():
    result=analyze_thermal(cylinder(),gas(),[regen(inlet_pressure_bar=.001)],settings())
    assert result.physical_validity=="invalid"
    assert any("pressure" in issue for issue in result.physical_issues)


@pytest.mark.parametrize("phase",["two_phase","unknown"])
def test_terminal_enthalpy_flash_is_classified_without_a_following_cell(phase,monkeypatch):
    segment=regen(start=.00998,end=.01002)
    original=solver._advance_coolant_state
    def terminal_flash(*args,**kwargs):
        state=original(*args,**kwargs)
        return replace(state,phase=phase,issues=("EOS enthalpy flash failed",) if phase=="unknown" else ())
    monkeypatch.setattr(solver,"_advance_coolant_state",terminal_flash)
    result=analyze_thermal(cylinder(),gas(),[segment],settings())
    assert result.physical_validity=="unsupported"
    assert result.coolant_outlet_phase["water"]==phase
    assert any("outlet" in issue for issue in result.physical_issues)


def test_segment_cell_intersections_partition_length_exactly():
    mesh=solver._build_mesh(cylinder(),120)
    bounds=(.0099,.0100)
    ids=solver._indices_in_range(mesh,bounds)
    assert sum(solver._cell_width_in_range(mesh,i,bounds) for i in ids)==pytest.approx(.0001,abs=1e-15)
    split=.02013
    lengths=[sum(solver._cell_width_in_range(mesh,i,b) for i in solver._indices_in_range(mesh,b))
             for b in [(0.,split),(split,.05)]]
    assert sum(lengths)==pytest.approx(.05,abs=1e-15)


def test_throat_breakpoint_survives_different_resolution():
    contour={"x_m":(0.,.017,.050),"radius_m":(.03,.01,.03),"throat_x_m":.017,
             "throat_index":1,"chamber_end_index":0}
    mesh=solver._build_mesh(contour,120)
    assert len(mesh.x_m)==120
    assert mesh.x_m[mesh.throat_index]==.017
    assert mesh.radius_m[mesh.throat_index]==pytest.approx(.01,abs=1e-16)


def test_cylindrical_wall_conserves_heat_at_different_surface_areas():
    r=.01;t=.002;k=200.
    resistance=cylindrical_conduction_resistance(r,t,k)
    heat_per_length=2*pi*k*100/log(1.2)
    assert 100/resistance*2*pi*r==pytest.approx(heat_per_length,rel=1e-13)
    assert resistance<t/k


def test_fin_effective_area_has_correct_physical_limits():
    effective,eta=rectangular_fin_area_ratio(channel_width_m=.001,channel_height_m=.002,
        pitch_m=.002,coolant_coefficient_w_m2k=10000.,wall_conductivity_w_mk=1e12)
    assert eta==pytest.approx(1.,abs=1e-10)
    assert effective==pytest.approx(2.5,abs=1e-9)
    poor,eta_poor=rectangular_fin_area_ratio(channel_width_m=.001,channel_height_m=.002,
        pitch_m=.002,coolant_coefficient_w_m2k=10000.,wall_conductivity_w_mk=.01)
    assert .5<poor<effective
    assert eta_poor<.02


def test_rectangular_laminar_flow_uses_square_duct_poiseuille_number():
    internal=internal_flow_heat_transfer(mass_flow_kg_s=.001,total_flow_area_m2=1e-6,
        hydraulic_diameter_m=.001,density_kg_m3=1000.,viscosity_pa_s=.001,
        conductivity_w_mk=.6,specific_heat_j_kgk=4200.,channel_aspect_ratio=1.)
    assert internal.reynolds==1000.
    assert internal.friction_factor*internal.reynolds==pytest.approx(56.9184,rel=1e-10)
    assert internal.nusselt==pytest.approx(3.610224,rel=.002)


def test_later_radiation_segment_takes_precedence_and_outer_area_is_used():
    def rad(name,epsilon):
        return {"type":"radiation","segment_id":name,"x_start_m":0.,"x_end_m":.05,
                "wall_thickness_mm":2.,"wall_conductivity_w_mk":100.,"emissivity":epsilon}
    result=analyze_thermal(cylinder(),gas(),[rad("first",.1),rad("last",.9)],settings())
    assert set(result.active_segment_id)=={"last"}
    expected=radiative_heat_flux(result.Twc[50],293.15,.9)*1.1
    assert result.heat_flux_w_m2[50]==pytest.approx(expected,rel=1e-10)


def test_linked_film_uses_final_outlet_and_coupled_temperature_converges():
    segment=regen();segment["coolant"]["mass_flow_kg_s"]=.15
    film={"type":"film","segment_id":"film","coolant":"H2O",
          "inherit_temperature_from_regen":"water","relative_mass_flow_percent":5.,
          "injection_location_mm":0.,"boundary_layer_thickness_m":.004}
    result=analyze_thermal(cylinder(),gas(),[segment,film],settings(coolant_property_backend="screening"))
    assert result.metadata["coupled_converged"]
    outlet=result.coolant_outlet_temperature_k["water"]
    # At the exact injector position eta=1: the converged recovery field must
    # agree with the returned source outlet, not a stale first-pass state.
    assert result.metadata["effective_recovery_temperature_k"][0]==pytest.approx(outlet,abs=.02)
    assert result.metadata["coupled_iterations"]>2


def test_material_and_unsupported_nozzle_diagnostics_are_exported():
    segment=regen();segment.pop("wall_conductivity_w_mk");segment["material"]="AlSi10Mg"
    hot_gas=gas(500.);hot_gas["nozzle_regime"]="unsupported_separated"
    result=analyze_thermal(cylinder(),hot_gas,[segment],settings())
    assert result.physical_validity=="invalid"
    assert any("conductivity data range" in issue for issue in result.physical_issues)
    assert any("nozzle flow" in issue for issue in result.physical_issues)
    assert result.as_dict()["physical_validity"]=="invalid"
    unsupported=("axial_solid_conduction","closeout_2d_conduction","local_feed_losses",
                 "acceleration_pressure_loss","manifold_flow_distribution","structural_life")
    assert all(result.metadata["model_capabilities"][name] is False for name in unsupported)


def test_alsi_selected_build_warning_is_present_inside_the_data_range():
    segment=regen();segment.pop("wall_conductivity_w_mk");segment["material"]="AlSi10Mg"
    result=analyze_thermal(cylinder(),gas(),[segment],settings())
    assert all(373.15<=t<=673.15 for t in (*result.Twc,*result.Twi))
    assert any("AlSi10Mg" in issue and "manufacturing-condition" in issue for issue in result.physical_issues)


def test_radiation_sensitivity_resolves_wall_and_bulk_energy_for_each_scenario():
    segment=regen();segment["channel_count"]=100;segment["widths_mm"]=.5
    segment["coolant"].update(mass_flow_kg_s=2.,inlet_pressure_bar=80.)
    experiment=thermal_radiation_sensitivity(cylinder(),gas(3400.),[segment],settings=settings())
    cases=experiment["cases"]
    peaks=[row["peak_hot_wall_temperature_k"] for row in cases]
    assert peaks==sorted(peaks)
    assert peaks[-1]-peaks[0]>5.
    assert all(row["converged"] for row in cases)
    assert all(abs(row["energy_balance_by_segment"]["water"]["residual_w"])<1e-4 for row in cases)
