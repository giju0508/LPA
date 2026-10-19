"""Check cell heat flux and wall temperature, not just the integrated Nu."""

from dataclasses import replace
from math import isfinite, log, pi, sqrt, tanh
from types import SimpleNamespace

import pytest
from scipy.integrate import quad

from lpa.thermal import solver
from lpa.thermal.coolants import CoolantState


def _analytic_local_stub(monkeypatch, *, gas_h=1000., wall_r=0., h_scale=100.):
    """Independent flat-plate h(s), with a fixed series wall/gas resistance."""
    calls = []

    def local(**kwargs):
        fraction = kwargs.get("entry_sample_fraction")
        assert fraction is not None and 0 < fraction < 1
        distance = kwargs["distance_from_inlet_m"] + fraction * kwargs["cell_length_m"]
        assert distance > 0  # No h(0) evaluation or artificial entry offset.
        calls.append(distance)
        coolant_h = h_scale / sqrt(distance)
        cold, hot = kwargs["coolant_bulk_state"].temperature_k, kwargs["effective_recovery_temperature_k"]
        flux = (hot - cold) / (1 / gas_h + wall_r + 1 / coolant_h)
        twc = cold + flux / coolant_h
        twg = twc + flux * wall_r
        return solver._StationSolution(
            Twg=twg, Twi=twg, Twc=twc, heat_flux=flux,
            gas_h=gas_h, coolant_h=coolant_h, iterations=7, converged=True,
            coolant_cp=3000., coolant_pressure_gradient_pa_m=25.,
            coolant_velocity_m_s=1., coolant_density_kg_m3=800.,
            coolant_phase="liquid", effective_cooling_area_ratio=1., fin_efficiency=1.,
            coolant_reynolds=1200., coolant_nusselt=coolant_h * .002 / .12,
            coolant_raw_coefficient_w_m2k=coolant_h, applicability="screening")

    monkeypatch.setattr(solver, "_solve_regen_station_local", local)
    return calls


def _analytic_kwargs(start=0., length=.001):
    return dict(coolant_bulk_state=SimpleNamespace(phase="liquid", temperature_k=300.),
                effective_recovery_temperature_k=1500.,
                distance_from_inlet_m=start, cell_length_m=length)


def _closed_flatplate_mean_flux(start, length, *, hot=1500., cold=300., gas_h=1000., wall_r=0., h_scale=100.):
    # Integral of ΔT/[R + sqrt(s)/H], where R=1/hg+Rwall.
    left, right = sqrt(start), sqrt(start + length)
    r_h = (1 / gas_h + wall_r) * h_scale
    integral = 2 * h_scale * (right - left - r_h * log((right + r_h) / (left + r_h)))
    return (hot - cold) * integral / length


@pytest.mark.parametrize("start", [0., .0001, .03])
@pytest.mark.parametrize("wall_r", [0., .0002])
def test_cell_mean_flux_matches_exact_conjugate_integral(monkeypatch, start, wall_r):
    _analytic_local_stub(monkeypatch, wall_r=wall_r)
    kwargs = _analytic_kwargs(start=start)
    actual = solver._solve_regen_station(**kwargs)
    expected = _closed_flatplate_mean_flux(start, .001, wall_r=wall_r)
    assert actual.heat_flux == pytest.approx(expected, rel=2e-12)
    # Constant hg makes the mean hot-wall relation independently exact.
    assert actual.Twg == pytest.approx(1500. - expected / 1000., rel=2e-12)
    assert actual.Twi - actual.Twc == pytest.approx(expected * wall_r, abs=1e-10)


def test_does_not_apply_wall_balance_to_arithmetic_mean_h(monkeypatch):
    _analytic_local_stub(monkeypatch)
    length = .001
    actual = solver._solve_regen_station(**_analytic_kwargs(length=length))
    arithmetic_h = 2 * 100. / sqrt(length)
    old_flux = (1500. - 300.) / (1 / 1000. + 1 / arithmetic_h)
    assert actual.heat_flux < old_flux
    assert actual.heat_flux == pytest.approx(_closed_flatplate_mean_flux(0., length), rel=1e-12)
    assert actual.Twg > 1500. - old_flux / 1000.


def test_total_heat_and_mean_wall_temperature_are_partition_invariant(monkeypatch):
    _analytic_local_stub(monkeypatch, wall_r=.0002)
    total_length = .03
    expected_flux = _closed_flatplate_mean_flux(0., total_length, wall_r=.0002)
    for count in (1, 12, 120):
        step = total_length / count
        values = [solver._solve_regen_station(**_analytic_kwargs(i * step, step)) for i in range(count)]
        mean_flux = sum(value.heat_flux for value in values) / count
        mean_wall = sum(value.Twg for value in values) / count
        assert mean_flux == pytest.approx(expected_flux, rel=2e-12)
        assert mean_wall == pytest.approx(1500. - expected_flux / 1000., rel=2e-12)


def test_inlet_samples_are_interior_and_effective_h_preserves_average_balance(monkeypatch):
    calls = _analytic_local_stub(monkeypatch, wall_r=.0002)
    actual = solver._solve_regen_station(**_analytic_kwargs())
    assert len(calls) > 1
    assert 0 < min(calls) < max(calls) < .001
    assert all(isfinite(value) for value in (actual.Twg, actual.Twc, actual.heat_flux))
    assert 300 < actual.wall_temperature_min_k < actual.Twg < actual.wall_temperature_max_k < 1500
    assert actual.coolant_h * (actual.Twc - 300.) == pytest.approx(actual.heat_flux)
    assert actual.gas_h * (1500. - actual.Twg) == pytest.approx(actual.heat_flux)
    assert actual.coolant_h < actual.coolant_raw_coefficient_w_m2k
    # Gauss samples define a sampled range, not a claim to include the s=0 limit.
    inlet_wall_limit = 300. + (1500. - 300.) / (.001 + .0002) * .0002
    assert actual.wall_temperature_min_k > inlet_wall_limit


@pytest.mark.parametrize("phase,with_entry", [("two_phase", True), ("liquid", False)])
def test_two_phase_or_legacy_calls_do_not_use_single_phase_entry_quadrature(monkeypatch, phase, with_entry):
    sentinel = object()
    seen = []

    def local(**kwargs):
        seen.append(kwargs)
        return sentinel

    monkeypatch.setattr(solver, "_solve_regen_station_local", local)
    kwargs = _analytic_kwargs()
    kwargs["coolant_bulk_state"].phase = phase
    if not with_entry:
        kwargs.pop("distance_from_inlet_m")
        kwargs.pop("cell_length_m")
    assert solver._solve_regen_station(**kwargs) is sentinel
    assert len(seen) == 1
    assert "entry_sample_fraction" not in seen[0]


def test_any_local_failure_and_warnings_survive_averaging(monkeypatch):
    calls = _analytic_local_stub(monkeypatch)
    original = solver._solve_regen_station_local

    def varied(**kwargs):
        result = original(**kwargs)
        first = len(calls) == 1
        return replace(result, converged=not first,
                       applicability="unsupported" if first else "screening",
                       physical_issues=("first local issue",) if first else ("later local issue",),
                       iterations=17 if first else 7)

    monkeypatch.setattr(solver, "_solve_regen_station_local", varied)
    actual = solver._solve_regen_station(**_analytic_kwargs())
    assert not actual.converged
    assert actual.applicability == "unsupported"
    assert actual.iterations == 17
    assert actual.physical_issues == ("first local issue", "later local issue")


def _independent_local_muzychka(distance, reynolds, prandtl, diameter, aspect):
    # Primary Table1 UWF/Eq.45, deliberately independent of production helpers.
    ratio = (1 + aspect) / (2 * sqrt(aspect))
    z = distance / (reynolds * prandtl * diameter * ratio**2)
    f_re = 12 / (sqrt(aspect) * (1 + aspect) * (1 - 192 * aspect / pi**5 * tanh(pi / (2 * aspect))))
    flat = .886 / (1 + (1.909 * prandtl**(1/6))**4.5)**(2/9) / sqrt(z)
    fully = 3.86 * f_re / (8 * sqrt(pi) * aspect**.1)
    graetz = ((.501 * (f_re / z)**(1/3))**5 + fully**5)**.2
    exponent = 2.27 + 1.65 * prandtl**(1/3)
    return (flat**exponent + graetz**exponent)**(1/exponent) / ratio


@pytest.mark.parametrize("start", [0., .02])
def test_actual_constant_property_wall_matches_independent_adaptive_integral(monkeypatch, start):
    # Real local wall solver: no synthetic local-station replacement. Fix only
    # gas h to isolate nonlinear coolant+rib+radial-conduction integration.
    radius, thickness, conductivity = .02, .0007, 300.
    width, height, channels = .002, .002, 20
    gas_h, hot, cold, length = 1000., 1000., 300., .001
    mass_flow, viscosity, fluid_k, cp, density = .048, .001, .12, 3000., 800.
    mesh = solver._build_mesh(dict(x_m=(0., .025, .05), radius_m=(radius,)*3, throat_index=1), 3)
    wall = solver._Wall(thickness, conductivity, None, 0., 1.)
    segment = dict(width_mode="channel_width", widths_mm=width*1000,
                   channel_height_mm=height*1000, channel_count=channels)
    bulk = CoolantState(density, cp, fluid_k, viscosity, temperature_k=cold,
                        pressure_pa=2e6, phase="liquid")
    monkeypatch.setattr(solver, "_gas_coefficient", lambda *args, **kwargs: gas_h)
    actual = solver._solve_regen_station(
        index=1, segment=segment, identifier="independent_constant_property",
        wall=wall, coolant_definition="unused_injected_state", coolant_temperature_k=cold,
        coolant_pressure_pa=2e6, coolant_mass_flow_kg_s=mass_flow,
        effective_recovery_temperature_k=hot, segment_range=(0., .05), mesh=mesh,
        gas=SimpleNamespace(temperature_k=(hot,)*3),
        settings=solver.ThermalSolverSettings(gas_emissivity=0., relative_tolerance=1e-11),
        coolant_bulk_state=bulk, distance_from_inlet_m=start, cell_length_m=length)
    diameter = 2 * width * height / (width + height)
    reynolds = mass_flow * diameter / (width * height * channels * viscosity)
    prandtl = cp * viscosity / fluid_k
    pitch = 2 * pi * (radius + thickness) / channels
    rib = pitch - width
    wall_r = radius * log(1 + thickness / radius) / conductivity

    def local_fields(u):
        distance = start + length*u*u
        h = _independent_local_muzychka(distance, reynolds, prandtl, diameter, min(width/height, height/width)) * fluid_k / diameter
        mh = sqrt(2*h/(conductivity*rib))*height
        fin_efficiency = tanh(mh)/mh
        area_ratio = (width + 2*height*fin_efficiency)/pitch*(radius+thickness)/radius
        cold_h = h * area_ratio
        flux = (hot - cold) / (1/gas_h + wall_r + 1/cold_h)
        return flux, hot - flux/gas_h, cold + flux/cold_h

    expected = [quad(lambda u: 2*u*local_fields(u)[i], 0., 1., epsabs=1e-7, epsrel=1e-11)[0] for i in range(3)]
    assert actual.converged
    assert actual.heat_flux == pytest.approx(expected[0], rel=2e-8)
    assert actual.Twg == pytest.approx(expected[1], rel=2e-8)
    assert actual.Twc == pytest.approx(expected[2], rel=2e-8)
    assert actual.coolant_h * (actual.Twc - cold) == pytest.approx(actual.heat_flux, rel=1e-12)
