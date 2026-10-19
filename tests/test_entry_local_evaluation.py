"""Independent local Eq.45 checks for conjugate entrance integration."""

from math import isfinite, pi, sqrt, tanh

import numpy as np
import pytest

from lpa.thermal.correlations import (
    developing_laminar_cell_nusselt,
    developing_laminar_local_nusselt,
    internal_flow_heat_transfer,
)


def _flow(reynolds=1200.0, **kwargs):
    inputs = dict(
        mass_flow_kg_s=reynolds * .001 * .0001 / .002,
        total_flow_area_m2=.0001, hydraulic_diameter_m=.002,
        density_kg_m3=800., viscosity_pa_s=.001,
        conductivity_w_mk=.12, specific_heat_j_kgk=25 * .12 / .001,
        channel_aspect_ratio=.5, distance_from_inlet_m=.01, cell_length_m=.002,
    )
    inputs.update(kwargs)
    return internal_flow_heat_transfer(**inputs)


@pytest.mark.parametrize("uniform_temperature", [False, True])
def test_local_eq45_matches_independent_published_parameters(uniform_temperature):
    # Muzychka-Yovanovich 2004 Eq.21, Eq.45/46, LOCAL Table1 coefficients.
    reynolds, prandtl, diameter, distance, aspect = 1200., 25., .002, .012, .5
    ratio = (1 + aspect) / (2 * sqrt(aspect))
    z = distance / (reynolds * prandtl * diameter * ratio**2)
    friction_re = 12 / (sqrt(aspect) * (1 + aspect) * (
        1 - 192 * aspect / pi**5 * tanh(pi / (2 * aspect))))
    c1, c3, c0, c_inf = (3.24, .409, .564, 1.664) if uniform_temperature else (3.86, .501, .886, 1.909)
    flat_plate = c0 / (1 + (c_inf * prandtl**(1/6))**4.5)**(2/9) / sqrt(z)
    fully_developed = c1 * friction_re / (8 * sqrt(pi) * aspect**.1)
    graetz = ((c3 * (friction_re / z)**(1/3))**5 + fully_developed**5)**.2
    exponent = 2.27 + 1.65 * prandtl**(1/3)
    expected = (flat_plate**exponent + graetz**exponent)**(1/exponent) / ratio
    actual = developing_laminar_local_nusselt(
        reynolds, prandtl, diameter, distance,
        channel_aspect_ratio=aspect, uniform_wall_temperature=uniform_temperature)
    assert actual == pytest.approx(expected, rel=1e-13)


@pytest.mark.parametrize("reynolds", [1200., 3000., 15000.])
@pytest.mark.parametrize("start", [0., .03, .3])
def test_sampled_coefficients_integrate_to_existing_cell_average(reynolds, start):
    # Independent higher-order rule and CUBIC substitution: the turbulent
    # s**(-2/3) singularity cancels exactly, and laminar leaves an integrable
    # smooth u**(1/2) term. Never evaluate the singular inlet itself.
    nodes, weights = np.polynomial.legendre.leggauss(96)
    nodes, weights = (nodes + 1) / 2, weights / 2
    mean = _flow(reynolds, distance_from_inlet_m=start).nusselt
    sampled = sum(float(3 * u*u * weight) * _flow(
        reynolds, distance_from_inlet_m=start,
        entry_sample_fraction=float(u**3)).nusselt for u, weight in zip(nodes, weights))
    assert sampled == pytest.approx(mean, rel=2e-6)


def test_local_sampling_uses_actual_fraction_without_restarting_entry():
    flow = _flow(entry_sample_fraction=.25)
    expected = developing_laminar_local_nusselt(
        1200., 25., .002, .01 + .25 * .002, channel_aspect_ratio=.5)
    assert flow.nusselt == pytest.approx(expected)
    assert flow.coefficient_w_m2k == pytest.approx(expected * .12 / .002)
    assert "local combined-entry" in flow.nusselt_model
    assert isfinite(flow.coefficient_w_m2k)


def test_turbulent_sampling_uses_local_derivative_of_mean_entry_factor():
    developed = _flow(15000., distance_from_inlet_m=None, cell_length_m=None)
    local = _flow(15000., entry_sample_fraction=.25)
    expected_factor = 1 + (.002 / (.01 + .25 * .002))**(2/3) / 3
    assert local.nusselt / developed.nusselt == pytest.approx(expected_factor)
    assert "local thermal-entry" in local.nusselt_model
    db_mean = _flow(15000., correlation="dittus_boelter")
    db_sample = _flow(15000., correlation="dittus_boelter", entry_sample_fraction=.25)
    assert db_sample.nusselt == db_mean.nusselt


@pytest.mark.parametrize("fraction", [0., -1., 1., 1.01, float("nan"), float("inf")])
def test_local_sample_fraction_rejects_endpoints_and_nonfinite(fraction):
    with pytest.raises(ValueError):
        _flow(entry_sample_fraction=fraction)


def test_local_sampling_requires_cell_coordinates_and_positive_local_distance():
    with pytest.raises(ValueError, match="requires inlet distance"):
        _flow(entry_sample_fraction=.5, distance_from_inlet_m=None, cell_length_m=None)
    with pytest.raises(ValueError, match="distance from heated inlet"):
        developing_laminar_local_nusselt(1200, 25, .002, 0)


def test_local_reference_preserves_true_domain_guards():
    with pytest.raises(ValueError, match="Pr >= 0.1"):
        developing_laminar_local_nusselt(1200, .09, .002, .01)
    with pytest.raises(ValueError, match="aspect ratio >= 0.01"):
        developing_laminar_local_nusselt(1200, 25, .002, .01, channel_aspect_ratio=.009)
    diagnostic = _flow(specific_heat_j_kgk=.09 * .12 / .001, entry_sample_fraction=.5)
    assert diagnostic.applicability == "unsupported"
    assert diagnostic.nusselt > 0


def test_nonlinear_conjugate_average_differs_from_balance_at_average_h():
    # Independent exact flat-plate model h(s)=C/sqrt(s), fixed gas-side/solid
    # resistance R. Integrating Nu is not sufficient to integrate heat pickup.
    from math import log
    resistance, coefficient, length = .2, 1., 1.
    average_h = 2 * coefficient / sqrt(length)
    average_conductance = 2 * coefficient / length * (
        sqrt(length) - resistance * coefficient * log(
            1 + sqrt(length) / (resistance * coefficient)))
    balance_of_average_h = 1 / (resistance + 1 / average_h)
    assert average_conductance < balance_of_average_h
    nodes, weights = np.polynomial.legendre.leggauss(96)
    nodes, weights = (nodes + 1) / 2, weights / 2
    integrated = sum(2 * u * weight / (resistance + sqrt(length * u*u) / coefficient)
                     for u, weight in zip(nodes, weights))
    assert integrated == pytest.approx(average_conductance, rel=1e-13)
