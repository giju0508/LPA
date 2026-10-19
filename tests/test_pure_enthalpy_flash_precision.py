"""EOS-consistent pure PH closure for tightly checked regenerative balances."""

import pytest
import CoolProp.CoolProp as CP

from lpa.thermal.coolants import coolant_state, coolant_state_from_enthalpy, coolant_state_from_quality


@pytest.mark.parametrize("enthalpy,pressure", [
    (154864.66477145237, 7670821.507659312),
    (101838.80373663107, 7895448.916000388),
    (143381.7548631951, 7717238.675395309),
])
def test_water_ph_regressions_recover_requested_h_without_fabricating_eos_state(enthalpy, pressure):
    # Native CoolProp8 HmassP misses these targets by .0007-.0011 J/kg,
    # enough to fail a 1e-4 W channel balance at 2 kg/s.
    state = coolant_state_from_enthalpy("H2O", enthalpy, pressure)
    assert state.phase == "liquid"
    assert abs(state.enthalpy_j_kg - enthalpy) < 2e-6
    independently_evaluated = CP.PropsSI("H", "P", pressure, "T", state.temperature_k, "Water")
    assert state.enthalpy_j_kg == pytest.approx(independently_evaluated, abs=1e-8)
    assert state.density_kg_m3 == pytest.approx(CP.PropsSI("D", "P", pressure, "T", state.temperature_k, "Water"), rel=1e-11)


@pytest.mark.parametrize("name,fluid,temperature,pressure", [
    ("LOX", "Oxygen", 95., 3e6),
    ("LCH4", "Methane", 150., 2.5e6),
    ("LH2", "Hydrogen", 23., 3e6),
    ("GOX", "Oxygen", 350., 8e6),
    ("GH2", "Hydrogen", 350., 8e6),
])
def test_other_pure_propellants_preserve_pt_ph_identity(name, fluid, temperature, pressure):
    initial = coolant_state(name, temperature, pressure)
    target = initial.enthalpy_j_kg + 1000.
    advanced = coolant_state_from_enthalpy(name, target, pressure, temperature_hint_k=temperature)
    assert advanced.enthalpy_j_kg == pytest.approx(target, rel=2e-11, abs=2e-6)
    independent = CP.PropsSI("H", "P", pressure, "T", advanced.temperature_k, fluid)
    assert advanced.enthalpy_j_kg == pytest.approx(independent, abs=1e-7)


def test_pure_two_phase_flash_keeps_equilibrium_quality_and_enthalpy():
    saturated = coolant_state_from_quality("H2O", 2e6, .35)
    flashed = coolant_state_from_enthalpy("H2O", saturated.enthalpy_j_kg, 2e6)
    assert flashed.phase == "two_phase"
    assert flashed.vapor_quality_mass_fraction == pytest.approx(.35, abs=1e-10)
    assert flashed.enthalpy_j_kg == pytest.approx(saturated.enthalpy_j_kg, abs=1e-7)
