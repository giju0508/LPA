"""Property evidence, bounded interpolation and explicit fallback regressions."""
from math import isfinite, isnan

import pytest

from lpa.thermal import coolants
from lpa.thermal import rp1_properties as rp1


@pytest.mark.parametrize("temperature,measured_nu", [
    (243.29, 7.667), (253.15, 5.369), (273.15, 3.093),
    (293.15, 2.040), (313.15, 1.475), (323.15, 1.282), (333.15, 1.126),
])
def test_nist_rp1_equation_reproduces_original_atmospheric_measurements(temperature, measured_nu):
    # The report gives a maximum fit residual of approximately 1.1%.
    assert rp1.rp1_kinematic_viscosity(temperature)*1e6 == pytest.approx(measured_nu, rel=.012)


def test_rp1_interpolation_preserves_actual_nist_measurements():
    assert len(rp1.CONDUCTIVITY_DATA) == 465
    assert len(rp1.VISCOSITY_PRODUCT_DATA) == 30
    for _, temperature, pressure_mpa, conductivity in rp1.CONDUCTIVITY_DATA[::23]:
        assert rp1.rp1_conductivity(temperature, pressure_mpa*1e6) == pytest.approx(conductivity, rel=1e-10)
    for pressure_mpa, temperature, product in rp1.VISCOSITY_PRODUCT_DATA:
        assert rp1.rp1_viscosity_density_product(temperature, pressure_mpa*1e6) == pytest.approx(product, rel=1e-10)


def test_rp1_domain_is_a_property_specific_hull_not_an_enclosing_rectangle():
    assert isnan(rp1.rp1_kinematic_viscosity(333.16))
    assert isnan(rp1.rp1_viscosity_density_product(450.0, 20e5))
    # Both coordinates are within the individual min/max values, but this
    # cold/high-pressure combination is outside the sampled convex hull.
    assert isnan(rp1.rp1_viscosity_density_product(250.0, 60e6))
    assert isnan(rp1.rp1_conductivity(300.0, 20e5))


def test_rp1_engineering_surrogate_exceeds_old_fit_without_claiming_original_nist_accuracy():
    cold = coolants.coolant_state("RP-1", 293.0, 20e5)
    warm = coolants.coolant_state("RP-1", 589.0, 20e5)
    unsupported = coolants.coolant_state("RP-1", 650.0, 20e5)
    assert cold.phase == warm.phase == "liquid"
    assert unsupported.phase == "unknown"
    assert cold.property_applicability == warm.property_applicability == "correlated"
    assert isfinite(warm.viscosity_pa_s) and warm.viscosity_pa_s < cold.viscosity_pa_s
    assert unsupported.property_applicability == "unsupported"
    assert isnan(unsupported.viscosity_pa_s)
    assert "two-component engineering surrogate" in cold.issues[0]
    assert any("1949" in ref for ref in cold.property_references)
    evidence = {item["property_name"]: item for item in warm.property_evidence}
    assert evidence["conductivity_w_mk"]["applicability"] == "correlated"
    assert evidence["density_kg_m3"]["applicability"] == "correlated"
    assert evidence["viscosity_pa_s"]["maximum_temperature_inclusive"] is False
    atmospheric = coolants.coolant_state("RP-1", 293.15, 83000.0)
    assert .0015 < atmospheric.viscosity_pa_s < .002
    assert atmospheric.property_applicability == "correlated"


def test_rp1_ph_inversion_recomputes_pressure_dependent_transport():
    target = coolants.coolant_state("RP-1", 320.0, 20e5)
    inverse = coolants.coolant_state_from_enthalpy(
        "RP-1", target.enthalpy_j_kg, 30e5, temperature_hint_k=293.0,
    )
    expected = coolants.coolant_state("RP-1", inverse.temperature_k, 30e5)
    assert inverse.enthalpy_j_kg == pytest.approx(target.enthalpy_j_kg, abs=1e-4)
    assert inverse.conductivity_w_mk == pytest.approx(expected.conductivity_w_mk, rel=1e-10)
    assert inverse.viscosity_pa_s == pytest.approx(expected.viscosity_pa_s, rel=1e-10)
    assert inverse.conductivity_w_mk != pytest.approx(target.conductivity_w_mk, rel=1e-4)


def test_eos_health_separates_transport_fallback_from_thermodynamics():
    water = coolants.coolant_state("H2O", 300.0, 25e5)
    assert water.property_applicability == "eos"
    no_transport = coolants.coolant_state("N2O", 285.0, 20e5)
    assert no_transport.thermodynamic_applicability == "eos"
    assert no_transport.transport_applicability == "screening"
    assert no_transport.property_applicability == "unsupported"
    hot_ethanol = coolants.coolant_state("Ethanol (100%)", 620.0, 100e5)
    assert hot_ethanol.thermodynamic_applicability == "eos"
    assert hot_ethanol.transport_applicability == "screening"
    assert hot_ethanol.property_applicability == "unsupported"
    evidence = {item["property_name"]: item for item in hot_ethanol.property_evidence}
    assert evidence["conductivity_w_mk"]["applicability"] == "screening"
    assert evidence["viscosity_pa_s"]["applicability"] == "eos"
    assert "screening fallback" in hot_ethanol.transport_source
    failed = coolants.coolant_state("LCH4", 150.0, 1001e6)
    assert failed.property_applicability == failed.thermodynamic_applicability == "unsupported"


def test_two_phase_bulk_diagnostic_does_not_hide_valid_saturated_transport():
    state = coolants.coolant_state_from_quality("LCH4", 20e5, .5)
    assert state.property_applicability == state.transport_applicability == "eos"
    assert state.saturated_liquid is not None and state.saturated_vapor is not None
    assert all(isfinite(s.conductivity_w_mk) and isfinite(s.viscosity_pa_s)
               for s in (state.saturated_liquid, state.saturated_vapor))


@pytest.mark.parametrize("name", ["IPA (100%)", "H2O2 (90%)", "Jet A-1"])
def test_legacy_screening_fluids_make_no_invented_domain_claim(name):
    state = coolants.coolant_state(name, 650.0, 20e5)
    assert state.phase == "unknown" and state.property_applicability == "unsupported"
    assert state.thermodynamic_applicability == "unsupported"
    assert state.transport_applicability == "screening"
    assert "clamp active" in " ".join(state.issues)
    assert state.property_limits is None
    assert all(item["temperature_range_k"] is None and item["pressure_range_pa"] is None
               for item in state.property_evidence)
    explicit_screening = coolants.get_coolant_model(name).at_temperature(650.0)
    assert explicit_screening.property_applicability == "screening"


def test_extreme_screening_viscosity_cannot_overflow_the_exponential():
    state = coolants.get_coolant_model("GOX").at_temperature(1e6)
    assert isfinite(state.viscosity_pa_s)
    assert "clamp active" in " ".join(state.issues)


def test_custom_model_with_rp1_name_keeps_explicit_user_properties():
    model = coolants.CoolantPropertyModel("RP-1", 293.15, 900, 2500, .2, .003)
    assert model.at_temperature(293.15).viscosity_pa_s == .003
