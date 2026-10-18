"""Thermodynamic regressions for physical mixture roots and latent energy."""

from math import isfinite, isnan

import CoolProp
import CoolProp.CoolProp as CP
import pytest

import lpa.thermal.coolants as coolants
from lpa.core.propellants import LNG_COMPONENTS


@pytest.mark.parametrize("pressure_bar", [20.0, 24.9, 25.0, 25.1, 30.0])
def test_lng_150_k_compressed_liquid_is_continuous_across_bad_blind_pt_root(pressure_bar):
    pressure = pressure_bar * 1e5
    reference = CoolProp.AbstractState("HEOS", "Methane&Ethane&Propane&n-Butane&Nitrogen")
    reference.set_mole_fractions([row[1] for row in LNG_COMPONENTS])
    reference.update(CP.PQ_INPUTS, pressure, 0.0)
    assert reference.T() > 167.0  # 150 K is proved subcooled, independently of the PT root.
    reference.specify_phase(CP.iphase_liquid)
    reference.update(CP.PT_INPUTS, pressure, 150.0)
    state = coolants.coolant_state("LNG", 150.0, pressure)
    assert state.phase == "liquid"
    assert 380.0 < state.density_kg_m3 < 390.0
    assert 3500.0 < state.specific_heat_j_kgk < 3800.0
    assert state.density_kg_m3 == pytest.approx(reference.rhomass(), rel=1e-10)
    assert state.enthalpy_j_kg == pytest.approx(reference.hmass(), abs=1e-5)
    assert not any("conductivity unavailable" in issue for issue in state.issues)
    advanced = coolants.coolant_state_from_enthalpy(
        "LNG", state.enthalpy_j_kg + 2500.0, pressure - 1000.0, temperature_hint_k=150.0,
    )
    assert advanced.phase == "liquid"
    assert 150.5 < advanced.temperature_k < 151.0
    assert advanced.enthalpy_j_kg - state.enthalpy_j_kg == pytest.approx(2500.0, abs=1e-5)


def test_pure_two_phase_flash_preserves_latent_energy_and_individual_transport():
    pressure, quality = 25e5, .2
    state = coolants.coolant_state_from_quality("H2O", pressure, quality)
    liquid, vapor = state.saturated_liquid, state.saturated_vapor
    assert liquid is not None and vapor is not None
    assert state.phase == "two_phase"
    assert state.vapor_quality_mass_fraction == pytest.approx(quality)
    assert state.temperature_k == pytest.approx(CP.PropsSI("T", "P", pressure, "Q", 0, "Water"))
    assert state.enthalpy_j_kg == pytest.approx(
        (1-quality)*liquid.enthalpy_j_kg + quality*vapor.enthalpy_j_kg, abs=1e-6,
    )
    assert vapor.enthalpy_j_kg-liquid.enthalpy_j_kg > 1.8e6
    for phase, expected_quality in [(liquid, 0), (vapor, 1)]:
        assert not phase.issues
        assert phase.conductivity_w_mk == pytest.approx(
            CP.PropsSI("L", "P", pressure, "Q", expected_quality, "Water"), rel=1e-10,
        )
        assert phase.viscosity_pa_s > 0
    assert .03 < state.surface_tension_n_m < .04
    inverse = coolants.coolant_state_from_enthalpy("H2O", state.enthalpy_j_kg, pressure)
    assert inverse.vapor_quality_mass_fraction == pytest.approx(quality, abs=1e-10)
    assert coolants.coolant_saturation_pressure("H2O", state.temperature_k) == pytest.approx(pressure, rel=1e-10)


@pytest.mark.parametrize("name,pressure,temperature,hint", [
    ("Ethanol (70%)", 25e5, 470.0, 450.0),
    ("LNG", 25e5, 180.0, 150.0),
])
def test_mixture_enthalpy_flash_crosses_bubble_boundary_with_a_mass_quality(name, pressure, temperature, hint):
    target = coolants.coolant_state(name, temperature, pressure)
    assert target.phase == "two_phase"
    advanced = coolants.coolant_state_from_enthalpy(
        name, target.enthalpy_j_kg, pressure, temperature_hint_k=hint,
    )
    assert advanced.phase == "two_phase"
    assert advanced.temperature_k == pytest.approx(temperature, abs=1e-7)
    assert advanced.enthalpy_j_kg == pytest.approx(target.enthalpy_j_kg, abs=1e-4)
    quality = advanced.vapor_quality_mass_fraction
    liquid, vapor = advanced.saturated_liquid, advanced.saturated_vapor
    assert liquid is not None and vapor is not None and 0 < quality < 1
    assert advanced.enthalpy_j_kg == pytest.approx(
        (1-quality)*liquid.enthalpy_j_kg+quality*vapor.enthalpy_j_kg, rel=5e-5,
    )
    assert abs(advanced.equilibrium_energy_residual_j_kg) < 5e-5*abs(advanced.enthalpy_j_kg)
    quality_flash = coolants.coolant_state_from_quality(name, pressure, quality)
    assert quality_flash.enthalpy_j_kg == pytest.approx(advanced.enthalpy_j_kg, abs=1e-4)


def test_pure_eos_extrapolation_is_not_silently_accepted():
    state = coolants.coolant_state("Ethanol (100%)", 700.0, 100e5)
    assert state.phase == "unknown"
    assert "outside documented bounds" in " ".join(state.issues)
    state = coolants.coolant_state("LCH4", 150.0, 1001e6)
    assert state.phase == "unknown"
    assert "exceeds documented maximum" in " ".join(state.issues)
    limits = coolants.coolant_property_limits("H2O")
    assert limits.maximum_temperature_k == 1273.0
    assert limits.maximum_pressure_pa == 1e9
    assert coolants.coolant_property_limits("Ethanol (70%)").maximum_temperature_k == 650.0
    assert coolants.coolant_state("Ethanol (70%)", 700.0, 100e5).phase == "unknown"


def test_thermodynamic_and_transport_validity_are_separate():
    state = coolants.coolant_state("Ethanol (100%)", 620.0, 100e5)
    assert state.source == "CoolProp HEOS: Ethanol"
    assert isfinite(state.enthalpy_j_kg)
    assert "conductivity unavailable" in " ".join(state.issues)
    assert "screening fallback" in state.transport_source
    limits = coolants.coolant_property_limits("Ethanol (100%)")
    assert limits.maximum_temperature_k == 650.0
    conductivity, viscosity = limits.transport_limits
    assert conductivity.maximum_temperature_k == 600.0
    assert conductivity.maximum_pressure_pa == 245e6
    assert isnan(viscosity.maximum_temperature_k)  # Not invented from EOS bounds.


def test_requested_refprop_missing_library_is_explicit_without_heos_substitution(monkeypatch):
    original = coolants._abstract_state
    def unavailable(name, *, saturation=False, backend="HEOS"):
        if backend == "REFPROP":
            raise ValueError("REFPROP library is not installed")
        return original(name, saturation=saturation, backend=backend)
    coolants.coolant_property_limits.cache_clear()
    monkeypatch.setattr(coolants, "_abstract_state", unavailable)
    state = coolants.coolant_state("H2O", 300.0, 25e5, backend="refprop")
    assert state.phase == "unknown"
    assert state.source == "screening"
    assert "REFPROP library is not installed" in " ".join(state.issues)


def test_rp1_does_not_claim_an_unavailable_nist_surrogate_provider():
    state = coolants.coolant_state("RP-1", 450.0, 100e5)
    assert state.phase == "supercritical_liquid"
    assert state.property_applicability == "correlated"
    assert "LPA fitted" in state.source and "engineering surrogate" in state.source
    assert "not the published NIST four-component" in " ".join(state.issues)
