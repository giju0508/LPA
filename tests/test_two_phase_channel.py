from dataclasses import replace
from math import isfinite, pi
from types import SimpleNamespace

import pytest
from CoolProp.CoolProp import PropsSI

from lpa.thermal import analyze_thermal, coolant_state_from_quality
from lpa.thermal.two_phase import saturated_boiling, TwoPhaseApplicabilityError
from tests.test_release_thermal_fixes import cylinder, gas, regen, settings


def test_chen_bennett_matches_published_example_with_rectangular_mass_flux():
    # ht 1.2.0 published example: D=.0212,m=.106,x=.2 => h=4938.275351.
    # Use a different *total* channel area to exercise the G-preserving adapter.
    liquid=SimpleNamespace(density_kg_m3=567.,viscosity_pa_s=156e-6,
        conductivity_w_mk=.086,specific_heat_j_kgk=2730.,enthalpy_j_kg=1e5,issues=())
    vapor=SimpleNamespace(density_kg_m3=18.09,viscosity_pa_s=7.11e-6,
        conductivity_w_mk=.03,specific_heat_j_kgk=1500.,enthalpy_j_kg=3e5,issues=())
    state=SimpleNamespace(saturated_liquid=liquid,saturated_vapor=vapor,
        vapor_quality_mass_fraction=.2,source="pure test fluid",pressure_pa=1e6,
        critical_pressure_pa=5e6,temperature_k=400.,surface_tension_n_m=.02)
    d=.0212; area=.001; g=.106/(pi*d*d/4)
    result=saturated_boiling(state=state,mass_flow_kg_s=g*area,total_flow_area_m2=area,
        hydraulic_diameter_m=d,wall_temperature_k=403.,wall_heat_flux_w_m2=1e5,
        wall_saturation_pressure_pa=1.1e6)
    assert result.coefficient_w_m2k==pytest.approx(4938.275351219369,rel=1e-12)
    assert result.pressure_gradient_pa_m>0


def test_water_channel_continues_through_boiling_and_conserves_energy():
    segment=regen();segment["coolant"]["mass_flow_kg_s"]=.025
    result=analyze_thermal(cylinder(),gas(3400.),[segment],settings())
    assert all(isfinite(v) for v in result.Twg)
    assert result.coolant_phase.count("two_phase")>5
    quality=[q for q in result.coolant_vapor_quality if isfinite(q)]
    assert 0<min(quality)<max(quality)<.7
    assert quality==sorted(quality)
    assert any("Li-Wu" in str(v) for v in result.coolant_flow_regime)
    assert result.physical_validity!="valid"  # Beta boiling is not hardware validation.
    balance=result.metadata["energy_balance_by_segment"]["water"]
    h_in=PropsSI("Hmass","T",290.,"P",40e5,"Water")
    h_out=result.coolant_outlet_enthalpy_j_kg["water"]
    assert .025*(h_out-h_in)+balance["two_phase_kinetic_energy_change_w"]==pytest.approx(balance["heat_pickup_w"],abs=1e-3)
    assert abs(balance["residual_w"])<1e-3


def test_quality_limit_preserves_first_unsupported_phase_for_plotting():
    segment=regen();segment["coolant"]["mass_flow_kg_s"]=.01
    result=analyze_thermal(cylinder(),gas(3400.),[segment],settings())
    index=next(i for i,v in enumerate(result.coolant_flow_regime) if v=="unsupported_two_phase")
    assert result.coolant_phase[index]=="two_phase"
    assert result.coolant_vapor_quality[index]>.7
    assert not isfinite(result.Twg[index])
    assert all(not isfinite(v) for v in result.Twg[index:])
    assert result.physical_validity=="unsupported"


@pytest.mark.parametrize("wall,flux",[(490.,1e5),(530.,-1.),(float("nan"),1e5),(530.,float("nan"))])
def test_boiling_never_masks_condensation_or_invalid_flux(wall,flux):
    state=coolant_state_from_quality("H2O",40e5,.1)
    with pytest.raises(TwoPhaseApplicabilityError):
        saturated_boiling(state=state,mass_flow_kg_s=.1,total_flow_area_m2=1e-4,
            hydraulic_diameter_m=.002,wall_temperature_k=wall,wall_heat_flux_w_m2=flux,
            wall_saturation_pressure_pa=50e5)


class SaturatedWaterInlet:
    def at_state(self,temperature,pressure):
        return coolant_state_from_quality("H2O",pressure,.1)
    def at_enthalpy(self,enthalpy,pressure):
        from lpa.thermal.coolants import coolant_state_from_enthalpy
        return coolant_state_from_enthalpy("H2O",enthalpy,pressure)


def test_partial_source_circuit_cannot_restart_in_a_linked_segment():
    first=regen("a",0,.025);first["widths_mm"]=.05
    first["coolant"]["inlet_temperature_k"]=523.5039
    second=regen("b",.025,.05);second["inherit_coolant_from"]="a"
    result=analyze_thermal(cylinder(),gas(),[first,second],settings(coolant_properties={"a":SaturatedWaterInlet(),"b":SaturatedWaterInlet()}))
    assert not any(isfinite(v) for v in result.Twg)
    assert "b" in result.metadata["inactive_segment_ids"]
    assert any("source circuit" in v for v in result.physical_issues)


def test_pressure_exhaustion_in_linked_channels_returns_diagnostics_not_exception():
    first=regen("a",0,.025);first["widths_mm"]=.1
    second=regen("b",.025,.05);second["inherit_coolant_from"]="a"
    result=analyze_thermal(cylinder(),gas(),[first,second],settings())
    assert result.physical_validity=="invalid"
    assert "b" in result.metadata["inactive_segment_ids"]


def test_mixture_two_phase_is_detected_but_not_given_a_pure_fluid_correlation():
    state=coolant_state_from_quality("LNG",25e5,.1)
    with pytest.raises(TwoPhaseApplicabilityError,match="mixture"):
        saturated_boiling(state=state,mass_flow_kg_s=.1,total_flow_area_m2=1e-4,
            hydraulic_diameter_m=.002,wall_temperature_k=200.,wall_heat_flux_w_m2=1e5,
            wall_saturation_pressure_pa=float("nan"))
