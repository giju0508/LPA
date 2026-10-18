"""Mixture resistance limits and safeguards, not hardware validation."""

from math import expm1, isfinite, isnan, nextafter
from types import SimpleNamespace

import pytest

from lpa.thermal.two_phase import (
    TwoPhaseApplicabilityError,
    mixture_saturated_boiling,
)


def _state(quality=0.2, glide=20.0, slope=1e-4):
    def phase(rho, cp, k, mu, enthalpy, mw):
        return SimpleNamespace(
            density_kg_m3=rho, specific_heat_j_kgk=cp,
            conductivity_w_mk=k, viscosity_pa_s=mu,
            enthalpy_j_kg=enthalpy, molar_mass_kg_mol=mw, issues=(),
        )
    return SimpleNamespace(
        mixture_component_names=("Methane", "Ethane"),
        pressure_pa=1e6, critical_pressure_pa=5e6, temperature_k=300.0,
        vapor_quality_mass_fraction=quality,
        mixture_liquid_bubble_temperature_k=300.0,
        mixture_liquid_dew_temperature_k=300.0+glide,
        equilibrium_temperature_enthalpy_derivative_k_kg_j=slope,
        saturated_liquid=phase(600, 2000, .1, 1e-4, 0, .030),
        saturated_vapor=phase(30, 1500, .02, 1e-5, 3e5, .020),
        surface_tension_n_m=float("nan"),
    )


def _boil(state=None, **kwargs):
    inputs = dict(
        state=_state() if state is None else state,
        mass_flow_kg_s=.05, total_flow_area_m2=1e-4,
        hydraulic_diameter_m=.004, wall_temperature_k=310,
        wall_heat_flux_w_m2=1e5,
    )
    inputs.update(kwargs)
    return mixture_saturated_boiling(**inputs)


def test_zero_glide_and_sensible_resistance_recover_original_gw87():
    state = _state(glide=0, slope=0)
    actual = _boil(state)
    g, d, x = 500, .004, .2
    re_l = g*(1-x)*d/state.saturated_liquid.viscosity_pa_s
    pr_l = 2.0
    h_l = .023*re_l**.8*pr_l**.4*.1/d
    bo = 1e5/(g*3e5)
    expected = h_l*(1+3000*bo**.86+1.12*(x/(1-x))**.75*(600/30)**.41)
    assert actual.coefficient_w_m2k == pytest.approx(expected, rel=1e-13)
    assert actual.mass_transfer_correction_factor == 1
    assert actual.convective_correction_factor == 1
    assert actual.applicability == "screening"


def test_glide_and_sensible_heating_suppress_distinct_heat_transfer_terms():
    ideal = _boil(_state(glide=0, slope=0))
    nucleate = _boil(_state(glide=20, slope=0))
    both = _boil(_state(glide=20, slope=1e-4))
    assert 0 < both.coefficient_w_m2k < nucleate.coefficient_w_m2k < ideal.coefficient_w_m2k
    assert nucleate.convective_coefficient_w_m2k == ideal.convective_coefficient_w_m2k
    assert both.nucleate_coefficient_w_m2k == nucleate.nucleate_coefficient_w_m2k
    assert 0 < both.mass_transfer_correction_factor < 1
    assert 0 < both.convective_correction_factor < 1
    assert both.sensible_vapor_heat_fraction == pytest.approx(.03)


def test_infinite_mass_transfer_limit_removes_nucleate_suppression():
    reference = _boil(_state(glide=0))
    actual = _boil(mass_transfer_coefficient_m_s=1e100)
    assert actual.coefficient_w_m2k == pytest.approx(reference.coefficient_w_m2k, rel=1e-12)


def test_cooper_reference_uses_g_per_mol_not_state_kg_per_mol():
    # Cooper/ht published water example: at 4.3 K superheat, h=1558.143544.
    # This is a numerical unit check with synthetic mixture identities, not a
    # claim that a water mixture is a validated GW87 test fluid.
    state = _state()
    state.pressure_pa=101325
    state.critical_pressure_pa=22048321
    state.saturated_liquid.molar_mass_kg_mol=.01802
    state.saturated_vapor.molar_mass_kg_mol=.01802
    known_h = 1558.1435442153575
    q = known_h*4.3
    actual = _boil(state, wall_heat_flux_w_m2=q)
    suppression = -expm1(-q/(600*3e5*3e-4))
    recovered_pool_h = (1/actual.mass_transfer_correction_factor-1)*q/(20*suppression)
    assert recovered_pool_h == pytest.approx(known_h, rel=1e-12)


@pytest.mark.parametrize("quality", [0, 1e-12, .7, .9, .999, nextafter(1.0, 0.0)])
def test_full_wet_wall_quality_path_is_finite_without_an_invented_dryout(quality):
    actual = _boil(_state(quality))
    assert all(isfinite(value) and value > 0 for value in (
        actual.coefficient_w_m2k, actual.pressure_gradient_pa_m,
        actual.homogeneous_density_kg_m3, actual.velocity_m_s,
    ))
    assert actual.wet_wall_assumed
    assert isnan(actual.critical_heat_flux_w_m2)
    assert isnan(actual.dryout_vapor_quality)
    assert actual.regime == "mixture_wet_wall_assumption"
    assert "NOT predicted" in " ".join(actual.warnings)
    if quality > .99:
        assert actual.applicability == "unsupported"
        assert any("model discontinuity" in warning for warning in actual.warnings)


def test_mass_flux_not_total_channel_area_controls_both_correlations():
    reference = _boil()
    many_channels = _boil(mass_flow_kg_s=.15, total_flow_area_m2=3e-4)
    assert many_channels.coefficient_w_m2k == pytest.approx(reference.coefficient_w_m2k)
    assert many_channels.pressure_gradient_pa_m == pytest.approx(reference.pressure_gradient_pa_m)


@pytest.mark.parametrize("change", [
    dict(vapor_quality_mass_fraction=-.1),
    dict(vapor_quality_mass_fraction=1),
    dict(mixture_liquid_bubble_temperature_k=299),
    dict(mixture_liquid_dew_temperature_k=299),
    dict(equilibrium_temperature_enthalpy_derivative_k_kg_j=-1e-5),
    dict(equilibrium_temperature_enthalpy_derivative_k_kg_j=float("nan")),
    dict(critical_pressure_pa=1e6),
    dict(mixture_component_names=()),
])
def test_invalid_equilibrium_inputs_raise_instead_of_being_clipped(change):
    state = _state()
    state.__dict__.update(change)
    with pytest.raises(TwoPhaseApplicabilityError):
        _boil(state)


@pytest.mark.parametrize("change", [
    dict(wall_temperature_k=300),
    dict(wall_heat_flux_w_m2=0),
    dict(wall_heat_flux_w_m2=float("nan")),
    dict(mass_transfer_coefficient_m_s=0),
    dict(model="disabled"),
])
def test_no_cold_wall_flux_or_mass_transfer_parameter_fallback(change):
    with pytest.raises(TwoPhaseApplicabilityError):
        _boil(**change)


def test_phase_transport_fallback_is_rejected_but_unrelated_bulk_diagnostic_is_not():
    state = _state()
    state.saturated_liquid.issues=("saturated liquid viscosity unavailable; screening property used",)
    with pytest.raises(TwoPhaseApplicabilityError, match="fallback"):
        _boil(state)
    state.saturated_liquid.issues=("saturated liquid cp unavailable; screening property used",)
    with pytest.raises(TwoPhaseApplicabilityError, match="fallback"):
        _boil(state)
    state.saturated_liquid.issues=("saturated liquid speed of sound unavailable",)
    assert isfinite(_boil(state).coefficient_w_m2k)
    state.saturated_liquid.transport_applicability="unsupported"
    with pytest.raises(TwoPhaseApplicabilityError, match="unsupported"):
        _boil(state)
    state.saturated_liquid.transport_applicability="correlated"
    state.saturated_liquid.issues=("correlated transport requires validation; no screening fallback used",)
    assert isfinite(_boil(state).coefficient_w_m2k)
    state.saturated_vapor.viscosity_pa_s=float("nan")
    with pytest.raises(TwoPhaseApplicabilityError):
        _boil(state)


def test_aqueous_composition_and_parameter_extrapolation_are_never_validated():
    state = _state()
    state.mixture_component_names=("Water", "Ethanol")
    result = _boil(state, mass_flow_kg_s=.2)
    assert isfinite(result.coefficient_w_m2k)
    assert result.applicability == "unsupported"
    assert any("Marangoni" in warning for warning in result.warnings)
    assert any("G outside" in warning for warning in result.warnings)


def test_current_liquid_composition_glide_changes_the_local_prediction():
    first, enriched = _state(glide=5), _state(glide=30)
    # Overall fluid identity/quality stay fixed: local-liquid enrichment data
    # must influence the result rather than silently reusing a fixed glide.
    assert _boil(first).coefficient_w_m2k > _boil(enriched).coefficient_w_m2k
