"""Entry integration, physical limits, domain guards and transition continuity."""

from math import isfinite, sqrt

import pytest

from lpa.thermal.correlations import (
    developing_laminar_cell_nusselt,
    internal_flow_heat_transfer,
)


def _flow(reynolds=1200.0, prandtl=25.0, **kwargs):
    # Choose mass flow and cp to prescribe dimensionless Re/Pr independently.
    inputs = dict(
        mass_flow_kg_s=reynolds * 0.001 * 0.0001 / 0.002,
        total_flow_area_m2=0.0001,
        hydraulic_diameter_m=0.002,
        density_kg_m3=800.0,
        viscosity_pa_s=0.001,
        conductivity_w_mk=0.12,
        specific_heat_j_kgk=prandtl * 0.12 / 0.001,
        channel_aspect_ratio=0.5,
        distance_from_inlet_m=0.1,
        cell_length_m=0.001,
    )
    inputs.update(kwargs)
    return internal_flow_heat_transfer(**inputs)


def test_legacy_call_retains_fully_developed_square_reference():
    result = _flow(
        channel_aspect_ratio=1,
        distance_from_inlet_m=None,
        cell_length_m=None,
    )
    assert result.nusselt == pytest.approx(3.610224)
    assert result.friction_factor * result.reynolds == pytest.approx(56.9184)
    assert any("distance/cell length unavailable" in text for text in result.warnings)


@pytest.mark.parametrize("aspect", [None, 1.0, 0.5, 0.01])
@pytest.mark.parametrize("uniform_temperature", [False, True])
def test_first_cell_is_finite_and_has_flat_plate_integral_limit(aspect, uniform_temperature):
    reynolds, prandtl, diameter, length = 1200.0, 25.0, 0.002, 1e-12
    c0, c_inf = (0.564, 1.664) if uniform_temperature else (0.886, 1.909)
    f_pr = c0 / (1 + (c_inf * prandtl ** (1 / 6)) ** 4.5) ** (2 / 9)
    # The independent short-entry mean flat-plate limit has no duct shape term.
    asymptote = 2 * f_pr * sqrt(reynolds * prandtl * diameter / length)
    actual = developing_laminar_cell_nusselt(
        reynolds, prandtl, diameter, 0, length,
        channel_aspect_ratio=aspect, uniform_wall_temperature=uniform_temperature,
    )
    assert isfinite(actual)
    assert actual == pytest.approx(asymptote, rel=2e-6)


@pytest.mark.parametrize("reynolds", [1200.0, 3000.0, 15000.0])
def test_integrated_entry_enhancement_converges_without_mesh_size_growth(reynolds):
    length = 0.3
    one_cell = _flow(reynolds, distance_from_inlet_m=0, cell_length_m=length).nusselt
    averages = []
    for count in (12, 120, 700):
        step = length / count
        values = [
            _flow(reynolds, distance_from_inlet_m=i * step, cell_length_m=step)
            for i in range(count)
        ]
        assert all(isfinite(value.nusselt) and value.applicability == "screening" for value in values)
        averages.append(sum(value.nusselt for value in values) / count)
    # A cell result is an integral of LOCAL Nu; a mean-inlet Nu reused locally
    # would double count the entry effect and fail this partition check.
    assert averages == pytest.approx([one_cell] * 3, rel=2e-6)


def test_rectangular_reference_has_reciprocal_symmetry_and_develops_downstream():
    values = [
        developing_laminar_cell_nusselt(1200, 25, 0.002, start, 0.001, channel_aspect_ratio=0.5)
        for start in (0, 0.01, 0.1, 10, 1e9)
    ]
    assert all(a > b for a, b in zip(values, values[1:]))
    reciprocal = developing_laminar_cell_nusselt(1200, 25, 0.002, 0.1, 0.001, channel_aspect_ratio=2)
    assert reciprocal == pytest.approx(values[2])
    # Independently evaluated Eq.22 with epsilon^0.1 outside sqrt(pi).
    assert values[-1] == pytest.approx(4.52693275045675, rel=1e-8)


@pytest.mark.parametrize("uniform_temperature, expected", [(False, 4.364), (True, 3.66)])
def test_circular_fully_developed_limit_agrees_with_classical_values(uniform_temperature, expected):
    actual = developing_laminar_cell_nusselt(
        1200, 25, 0.002, 1e9, 1,
        uniform_wall_temperature=uniform_temperature,
    )
    # Rounded coefficients 3.86/3.24 in the source make this approximate.
    assert actual == pytest.approx(expected, rel=0.003)


@pytest.mark.parametrize("endpoint", [2300.0, 4000.0])
@pytest.mark.parametrize("start", [0.0, 0.1])
def test_nusselt_and_darcy_factor_are_continuous_at_regime_endpoints(endpoint, start):
    below = _flow(endpoint - 1e-6, distance_from_inlet_m=start)
    at = _flow(endpoint, distance_from_inlet_m=start)
    above = _flow(endpoint + 1e-6, distance_from_inlet_m=start)
    assert below.nusselt == pytest.approx(at.nusselt, rel=1e-7)
    assert above.nusselt == pytest.approx(at.nusselt, rel=1e-7)
    assert below.friction_factor == pytest.approx(at.friction_factor, rel=1e-7)
    assert above.friction_factor == pytest.approx(at.friction_factor, rel=1e-7)


def test_transition_uses_fixed_physical_endpoints_and_reports_uncertainty():
    lower, middle, upper = [_flow(reynolds) for reynolds in (2300, 3150, 4000)]
    assert middle.nusselt == pytest.approx((lower.nusselt + upper.nusselt) / 2)
    assert middle.friction_factor == pytest.approx((lower.friction_factor + upper.friction_factor) / 2)
    assert middle.flow_regime == "transition"
    assert middle.applicability == "screening"
    assert any("Re=2300..4000" in text for text in middle.warnings)


def test_small_first_cell_endpoint_inversion_is_model_uncertainty_not_domain_failure():
    result = _flow(3000, distance_from_inlet_m=0, cell_length_m=1e-5)
    assert result.applicability == "screening"
    assert any("non-monotone" in text for text in result.warnings)


@pytest.mark.parametrize("overrides", [dict(prandtl=0.09), dict(channel_aspect_ratio=0.009)])
def test_actual_laminar_domain_violation_is_unsupported(overrides):
    result = _flow(**overrides)
    assert result.applicability == "unsupported"
    assert any("diagnostic fallback" in text for text in result.warnings)


def test_turbulent_first_cell_matches_length_mean_and_approaches_fd_downstream():
    finite = _flow(15000, distance_from_inlet_m=0, cell_length_m=0.03)
    developed = _flow(15000, distance_from_inlet_m=None, cell_length_m=None)
    assert finite.nusselt / developed.nusselt == pytest.approx(1 + (0.002 / 0.03) ** (2 / 3))
    far = _flow(15000, distance_from_inlet_m=1e9)
    assert far.nusselt == pytest.approx(developed.nusselt, rel=1e-7)


def test_conjugate_boundary_is_screening_and_uwt_option_changes_reference():
    conjugate = _flow()
    temperature = _flow(thermal_boundary_condition="uniform_wall_temperature")
    assert conjugate.applicability == "screening"
    assert any("conjugate/one-sided" in text for text in conjugate.warnings)
    assert 0 < temperature.nusselt < conjugate.nusselt


@pytest.mark.parametrize("overrides", [
    dict(distance_from_inlet_m=-0.1),
    dict(distance_from_inlet_m=None),
    dict(cell_length_m=0),
    dict(thermal_boundary_condition="unknown"),
])
def test_invalid_entry_coordinates_raise(overrides):
    with pytest.raises(ValueError):
        _flow(**overrides)
