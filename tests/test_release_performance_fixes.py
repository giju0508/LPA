"""Independent invariants and real-CEA checks for the release physics fixes."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from math import atan, cos, degrees, isfinite, isnan, pi, radians, sqrt, tan

import pytest

from lpa.core._numerics import area_mach_ratio, expansion_ratio_for_pressure, solve_mach
from lpa.core.analysis import analyze_engine
from lpa.core.contour import generate_contour
from lpa.core.models import (
    AmbientConditions, AnalysisInput, ChamberLength, EngineDefinition, EquilibriumFlow,
    NozzleExitCondition, NozzleGeometry, RangeSpec, ThrottleSettings,
    ThrustChamberInput, ThrustChamberSize,
)
from lpa.core.performance import (
    ATM_PA, RocketCEAAdapter, _estimated_nozzle_efficiency,
    evaluate_performance, performance_at_ambient_pressure,
)
from lpa.core.thermodynamics import build_thermodynamics


def hardware(expansion=5.0, **options):
    return ThrustChamberInput(
        exit_condition=NozzleExitCondition(mode="expansion_ratio", expansion_area_ratio=expansion),
        size=ThrustChamberSize(mode="throat_diameter", throat_diameter_mm=20.0), **options,
    )


def test_separation_is_unavailable_and_cannot_size_a_nominal_engine():
    inputs = AnalysisInput(thrust_chamber=hardware(40.0))
    result = evaluate_performance(inputs, prefer_rocketcea=False)
    assert result.design_nozzle_regime == "unsupported_separated"
    assert isnan(result.without_film.isp_sea_level_s)
    assert isfinite(result.without_film.isp_vacuum_s)
    assert any("outside its validity" in warning for warning in result.warnings)
    nominal = replace(inputs.thrust_chamber, size=ThrustChamberSize())
    with pytest.raises(ValueError, match="sizing requires attached supersonic flow"):
        evaluate_performance(replace(inputs, thrust_chamber=nominal), prefer_rocketcea=False)


def test_high_back_pressure_never_fabricates_positive_thrust():
    result = evaluate_performance(AnalysisInput(thrust_chamber=hardware()), prefer_rocketcea=False)
    varied = performance_at_ambient_pressure(result, 50.0)
    assert varied.design_nozzle_regime == "unsupported_choking_or_internal_shock"
    assert isnan(varied.with_film.thrust_design_n)


@pytest.mark.parametrize("fraction", [0.0, 0.1, 0.2, 0.7])
def test_film_preserves_fixed_hardware_external_pressure_force(fraction):
    result = evaluate_performance(AnalysisInput(thrust_chamber=hardware()),
                                  ambient_pressure_atm=0, film_mass_fraction=fraction, prefer_rocketcea=False)
    raised = performance_at_ambient_pressure(result, 0.1)
    expected_loss = result.throat_area_m2 * result.expansion_ratio * (0.1 * ATM_PA)
    assert result.with_film.thrust_design_n - raised.with_film.thrust_design_n == pytest.approx(expected_loss, rel=1e-12)


@pytest.mark.parametrize("angle", [15.0, 30.0, 40.0, 44.0])
def test_estimated_cone_momentum_obeys_nasa_divergence_bound(angle):
    chamber = hardware(nozzle=NozzleGeometry(conical_half_angle_deg=angle))
    geometric_bound = (1.0 + cos(radians(angle))) / 2.0
    assert sqrt(_estimated_nozzle_efficiency(chamber)) == pytest.approx(0.985 * geometric_bound)
    assert sqrt(_estimated_nozzle_efficiency(chamber)) < geometric_bound


@pytest.mark.parametrize("efficiency", [100, 98, 50, 25])
def test_fallback_reaction_closure_obeys_continuity(efficiency):
    inputs = AnalysisInput(thrust_chamber=hardware(reaction_efficiency_percent=efficiency))
    result = evaluate_performance(inputs, prefer_rocketcea=False)
    contour = generate_contour(inputs.thrust_chamber, result.throat_diameter_mm, result.expansion_ratio)
    gas = build_thermodynamics(contour, result)
    for station in gas.stations.values():
        assert station.density_kg_m3 * station.mach * station.sonic_velocity_m_s == pytest.approx(station.mass_flux_kg_m2_s, rel=1e-12)


def test_direct_length_reports_ellipse_endpoint_curvature_and_angle():
    chamber = hardware(length=ChamberLength(mode="direct", chamber_length_mm=410, cylindrical_length_mm=250))
    result = generate_contour(chamber, 20, 5)
    scale = 160.0 / result.metadata["natural_convergent_length_mm"]
    assert result.metadata["convergent_arc_form"] == "elliptical"
    assert result.metadata["actual_contraction_angle_deg"] == pytest.approx(degrees(atan(tan(radians(30)) / scale)))
    assert result.metadata["R1_mm"] == pytest.approx(15.0 * scale**2)
    assert result.metadata["requested_R1_mm"] == 15.0
    assert "elliptical" in result.metadata["convergent_geometry_warning"]


@pytest.mark.parametrize("epsilon,radius", [(1.0001, 0.382), (1.01, 5.0), (1.1, 5.0)])
def test_cone_rejects_exit_inside_the_throat_circle(epsilon, radius):
    with pytest.raises(ValueError, match="inside the throat blend"):
        generate_contour(hardware(nozzle=NozzleGeometry(throat_radius_ratio=radius)), 20, epsilon)


@pytest.mark.parametrize("gamma", [1.05, 1.2, 1.4, 1.67])
@pytest.mark.parametrize("supersonic", [False, True])
def test_area_mach_extreme_finite_ratio_is_actually_bracketed(gamma, supersonic):
    for area in [1.0001, 1000.0, 1e30, 1e100]:
        mach = solve_mach(area, gamma, supersonic=supersonic)
        assert area_mach_ratio(mach, gamma) == pytest.approx(area, rel=2e-12)


@pytest.mark.parametrize("area,gamma", [(float("nan"), 1.2), (float("inf"), 1.2), (5, 1), (5, float("nan"))])
def test_area_mach_rejects_invalid_inputs(area, gamma):
    with pytest.raises(ValueError):
        solve_mach(area, gamma, supersonic=True)


def test_exit_pressure_must_admit_a_supersonic_branch():
    with pytest.raises(ValueError, match="supersonic"):
        expansion_ratio_for_pressure(1e5, 9e4, 1.2)


@pytest.fixture
def actual_cea():
    adapter = RocketCEAAdapter()
    if not adapter.available:
        pytest.skip("compiled RocketCEA is unavailable")
    return adapter


@pytest.mark.parametrize("mode,criterion", [("shifting", None), ("frozen_area", 1.0)])
def test_real_local_cea_states_match_independent_public_getters(actual_cea, mode, criterion):
    engine = EngineDefinition(oxidizer="LOX", fuel="LH2", chamber_pressure_bar=100, mixture_ratio=6)
    flow = EquilibriumFlow(mode=mode, freeze_area_ratio=criterion)
    chamber = hardware(40, equilibrium=flow, reaction_efficiency_percent=100,
                       ambient=AmbientConditions(enabled=True, fixed_pressure_atm=0))
    result = analyze_engine(AnalysisInput(engine, chamber), cea_adapter=actual_cea, require_rocketcea=True)
    gas = result.thermodynamics
    assert gas.source == "rocketcea-local-stations-and-transport"
    cea = actual_cea._make_cea(engine, chamber.contraction_area_ratio)
    flags = dict(frozen=int(mode != "shifting"), frozenAtThroat=int(mode == "frozen_area"))
    temperatures = cea.get_Temperatures(Pc=100, MR=6, eps=40, **flags)
    assert gas.stations["injector"].temperature_k == pytest.approx(temperatures[0], rel=2e-5)
    assert gas.stations["nozzle_exit"].temperature_k == pytest.approx(temperatures[-1], rel=5e-5)
    assert gas.stations["nozzle_exit"].pressure_pa == pytest.approx(result.performance.exit_pressure_bar * 1e5, rel=5e-5)
    cp, viscosity, _conductivity, prandtl = cea.get_Exit_Transport(Pc=100, MR=6, eps=40, **flags)
    # RocketCEA's unit wrapper uses IT calorie conversion, whereas the CEA
    # arrays are thermochemical calories. The 0.067% difference is documented.
    assert gas.stations["nozzle_exit"].specific_heat_j_kgk == pytest.approx(cp * 1000, rel=1e-3)
    assert gas.stations["nozzle_exit"].viscosity_pa_s == pytest.approx(viscosity * 1e-4, rel=5e-5)
    assert gas.stations["nozzle_exit"].prandtl == pytest.approx(prandtl, rel=5e-5)
    for station in gas.stations.values():
        assert station.density_kg_m3 * station.mach * station.sonic_velocity_m_s == pytest.approx(station.mass_flux_kg_m2_s, rel=1e-4)
    assert result.performance.ideal_cstar_m_s > result.performance.cea_cstar_m_s
    assert "injector" in result.performance.pressure_reference
    assert all(0 <= value <= 1 for value in gas.h2o_mole_fraction)


def test_frozen_pressure_criterion_is_not_silently_used_with_invalid_fac(actual_cea):
    chamber = hardware(equilibrium=EquilibriumFlow(mode="frozen_pressure", freeze_pressure_ratio=10))
    with pytest.raises(ValueError, match="Frozen-at-chamber.*unsupported"):
        evaluate_performance(AnalysisInput(thrust_chamber=chamber), cea_adapter=actual_cea)


def test_throat_freezing_exit_pressure_and_legacy_criterion_are_explicit(actual_cea):
    engine = EngineDefinition(oxidizer="LOX", fuel="LH2", chamber_pressure_bar=100, mixture_ratio=6)
    chamber = replace(hardware(equilibrium=EquilibriumFlow(mode="frozen_area", freeze_area_ratio=1)),
                      contraction_area_ratio=6.25,
                      exit_condition=NozzleExitCondition(mode="ambient_pressure", ambient_pressure_atm=0.1))
    actual = evaluate_performance(AnalysisInput(engine, chamber), cea_adapter=actual_cea, require_rocketcea=True)
    assert actual.exit_pressure_bar == pytest.approx(0.1 * 1.01325, rel=1e-4)
    assert not any("criterion" in warning for warning in actual.warnings)
    legacy = replace(chamber, equilibrium=EquilibriumFlow(mode="frozen_area", freeze_area_ratio=5))
    approximated = evaluate_performance(AnalysisInput(engine, legacy), cea_adapter=actual_cea, require_rocketcea=True)
    assert any("criterion 5 is unsupported" in warning for warning in approximated.warnings)


def test_sweep_cannot_bypass_required_cea_and_exposes_fallback_warnings():
    class PressureCEA:
        def get_IvacCstrTc(self, Pc, **_kwargs):
            if Pc < 15:
                raise RuntimeError("low-pressure CEA failure")
            return 325, 1810, 3500
        def get_exit_MolWt_gamma(self, **_kwargs):
            return 21, 1.22
        def get_PcOvPe(self, **_kwargs):
            return 5
    chamber = hardware(throttle=ThrottleSettings(enabled=True, fixed_percent=50))
    adapter = RocketCEAAdapter(lambda **_kwargs: PressureCEA())
    inputs = AnalysisInput(thrust_chamber=chamber)
    with pytest.raises(RuntimeError, match="low-pressure CEA failure"):
        analyze_engine(inputs, cea_adapter=adapter, require_rocketcea=True)
    result = analyze_engine(inputs, cea_adapter=adapter)
    assert result.throttle_sweep.points[0].result.source == "ideal-gas-fallback"
    assert any("throttle=50" in warning and "low-pressure" in warning for warning in result.warnings)


def test_no_cea_context_cannot_claim_local_gas_transport():
    result = evaluate_performance(AnalysisInput(), prefer_rocketcea=False)
    contour = generate_contour(ThrustChamberInput(), result.throat_diameter_mm, result.expansion_ratio)
    gas = build_thermodynamics(contour, replace(result, source="rocketcea"))
    assert gas.source == "constant-gas-screening-with-air-transport"
    assert any("not local CEA" in warning for warning in gas.warnings)


def test_nonideal_reaction_closure_does_not_claim_recomputed_cea_transport(actual_cea):
    chamber = hardware(5, reaction_efficiency_percent=50,
                       ambient=AmbientConditions(enabled=True, fixed_pressure_atm=0))
    result = analyze_engine(AnalysisInput(thrust_chamber=chamber),
                            cea_adapter=actual_cea, require_rocketcea=True)
    assert any("not re-equilibrated" in warning for warning in result.thermodynamics.warnings)
    from lpa.thermal.solver import _build_mesh, _prepare_gas
    from lpa.thermal import ThermalSolverSettings
    mesh = _build_mesh(result.contour, 120)
    thermal_gas = _prepare_gas(result, result.contour, mesh, ThermalSolverSettings())
    assert any("not re-equilibrated" in issue for issue in thermal_gas.property_issues)


def test_concurrent_cea_queries_keep_their_own_species_and_stations(actual_cea):
    engines = (
        EngineDefinition(oxidizer="LOX", fuel="LH2", chamber_pressure_bar=100, mixture_ratio=6),
        EngineDefinition(oxidizer="LOX", fuel="RP-1", chamber_pressure_bar=60, mixture_ratio=2.5),
    )
    chamber = hardware(40)
    reference = [actual_cea.axial_station_states(engine, chamber, (4, 1, 40), 1) for engine in engines]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(actual_cea.axial_station_states, engines[i % 2], chamber, (4, 1, 40), 1) for i in range(8)]
        for i, future in enumerate(futures):
            observed = future.result()
            for actual, expected in zip(observed, reference[i % 2]):
                assert actual["temperature_k"] == pytest.approx(expected["temperature_k"], rel=1e-9)
                assert actual["h2o_mole_fraction"] == pytest.approx(expected["h2o_mole_fraction"], rel=1e-9)
                assert actual["co2_mole_fraction"] == pytest.approx(expected["co2_mole_fraction"], rel=1e-9)
