"""Independent real-CEA oracles for the theoretical-vacuum-Isp O/F objective.

Saved baselines were obtained by a separate 101-point scan + SciPy bounded
search on 2026-10-11 (RocketCEA 1.2.3), before the production objective change:
tmp/of_objective_review_20261011/cea_comparison_results.json. These constants
do not depend on that temporary artifact being present in a fresh checkout.
The independent evaluator calls the real units-wrapper getters directly;
it never calls the production vacuum_isp_evaluator or optimization helper.
"""
from __future__ import annotations

from dataclasses import replace
from importlib.metadata import version
import copy
from types import SimpleNamespace

import pytest

from lpa.core import (
    AmbientConditions, AnalysisInput, EngineDefinition, EquilibriumFlow,
    EquilibriumMode, FilmSegment, NozzleEfficiency, NozzleExitCondition,
    RocketCEAAdapter, ThermalAnalysisInput, ThrustChamberInput,
    ThrustChamberSize, optimize_mixture_ratio, optimize_mixture_ratio_for_inputs,
)
from lpa.core.performance import UnsupportedFlowError
from lpa.core.propellants import registration_cards, rocketcea_names


# fuel, mass fraction, Pc[injector,bar], O/F bounds, epsilon, mode, MR*, Ivac*
BASELINES = [
    ("RP-1", 1., 20., (.5, 4.), 5., "shifting", 2.358144742366127, 303.6963681632592),
    ("RP-1", 1., 20., (.5, 4.), 40., "shifting", 2.6641622751230667, 355.23754532361914),
    ("RP-1", 1., 20., (.5, 4.), 5., "throat_frozen", 2.1954898232969375, 295.61654663434786),
    ("RP-1", 1., 20., (.5, 4.), 40., "throat_frozen", 2.260503717363329, 333.99831662328086),
    ("Ethanol", .7, 20., (.3, 3.), 5., "shifting", 1.3134208817800324, 278.71864135201787),
    ("Ethanol", .7, 20., (.3, 3.), 40., "shifting", 1.4222078492061143, 327.53234783085276),
    ("Ethanol", .7, 20., (.3, 3.), 5., "throat_frozen", 1.23088855500226, 272.78326963250186),
    ("Ethanol", .7, 20., (.3, 3.), 40., "throat_frozen", 1.2479737749071549, 312.13814649343186),
    ("LH2", 1., 100., (2., 8.), 40., "shifting", 4.758734705209451, 455.2174517188928),
    ("LH2", 1., 100., (2., 8.), 40., "throat_frozen", 4.08310860687268, 451.44293993819275),
]


@pytest.fixture(scope="module")
def real_backend():
    # The adapter initializes the safe Windows native work-file directory.
    # Only the independent CEA constructor below evaluates the oracle.
    adapter = RocketCEAAdapter()
    if not adapter.available:
        pytest.skip(f"real RocketCEA unavailable: {adapter.unavailable_reason}")
    assert version("rocketcea") == "1.2.3", "saved oracle is pinned to the supported RocketCEA database"
    pytest.importorskip("scipy.optimize")
    return adapter


def independent_cea(engine):
    from rocketcea.cea_obj import add_new_fuel, add_new_oxidizer
    from rocketcea.cea_obj_w_units import CEA_Obj

    arguments = dict(
        oxidizer_temperature_k=engine.oxidizer_temperature_k,
        fuel_temperature_k=engine.fuel_temperature_k,
        oxidizer_pressure_bar=engine.oxidizer_pressure_bar,
        fuel_pressure_bar=engine.fuel_pressure_bar,
    )
    for kind, name, card in registration_cards(
        engine.oxidizer, engine.fuel, engine.oxidizer_mass_fraction,
        engine.fuel_mass_fraction, **arguments,
    ):
        (add_new_oxidizer if kind == "oxidizer" else add_new_fuel)(name, card)
    oxidizer, fuel = rocketcea_names(
        engine.oxidizer, engine.fuel, engine.oxidizer_mass_fraction,
        engine.fuel_mass_fraction, **arguments,
    )
    return CEA_Obj(oxName=oxidizer, fuelName=fuel, fac_CR=6.25,
                   pressure_units="bar", cstar_units="m/s", temperature_units="K")


def independent_state(cea, engine, mr, epsilon, mode):
    arguments = dict(Pc=engine.chamber_pressure_bar, MR=float(mr), eps=float(epsilon))
    if mode is EquilibriumMode.SHIFTING:
        return tuple(float(value) for value in cea.get_IvacCstrTc(**arguments))
    return tuple(float(value) for value in cea.getFrozen_IvacCstrTc(**arguments, frozenAtThroat=1))


def scipy_maximum(objective, bounds):
    from scipy.optimize import minimize_scalar

    # Independent search: no production coarse grid, golden-section routine,
    # alpha conversion, evaluator, or reporting formula is reused.
    solved = minimize_scalar(lambda mr: -float(objective(float(mr))), method="bounded",
                             bounds=bounds, options={"xatol": 1e-9, "maxiter": 100})
    assert solved.success
    return float(solved.x), -float(solved.fun)


@pytest.mark.parametrize("fuel,fraction,pc,bounds,epsilon,flow,expected_mr,expected_isp", BASELINES)
def test_real_vacuum_optimizer_matches_saved_and_independent_cea_maximum(
    real_backend, fuel, fraction, pc, bounds, epsilon, flow, expected_mr, expected_isp,
):
    engine = EngineDefinition(fuel=fuel, fuel_mass_fraction=fraction, chamber_pressure_bar=pc)
    mode = EquilibriumMode.SHIFTING if flow == "shifting" else EquilibriumMode.FROZEN_AREA
    cea = independent_cea(engine)
    objective = lambda mr: independent_state(cea, engine, mr, epsilon, mode)[0]
    independent_mr, independent_isp = scipy_maximum(objective, bounds)
    optimum = optimize_mixture_ratio(engine, contraction_area_ratio=6.25, expansion_ratio=epsilon,
                                     equilibrium_mode=mode, bounds=bounds, cea_adapter=real_backend)
    assert optimum.source == "rocketcea"
    assert optimum.objective == "maximum theoretical vacuum specific impulse"
    assert optimum.mixture_ratio == pytest.approx(expected_mr, abs=5e-5)
    assert optimum.mixture_ratio == pytest.approx(independent_mr, abs=5e-5)
    assert optimum.vacuum_isp_s == pytest.approx(expected_isp, abs=2e-5)
    assert optimum.vacuum_isp_s == pytest.approx(independent_isp, abs=2e-5)
    actual_state = independent_state(cea, engine, optimum.mixture_ratio, epsilon, mode)
    assert optimum.vacuum_isp_s == pytest.approx(actual_state[0], abs=1e-8)
    assert optimum.ideal_cstar_m_s == pytest.approx(actual_state[1], abs=1e-8)
    for neighbour in (optimum.mixture_ratio-.005, optimum.mixture_ratio+.005):
        assert objective(optimum.mixture_ratio) > objective(neighbour)


def test_fixed_cr_objective_ignores_delivered_losses_film_and_design_ambient(real_backend):
    engine = EngineDefinition(fuel="Ethanol", fuel_mass_fraction=.7)
    chamber = ThrustChamberInput(
        contraction_area_ratio=6.25,
        exit_condition=NozzleExitCondition(mode="expansion_ratio", expansion_area_ratio=5., ambient_pressure_atm=None),
        reaction_efficiency_percent=100.,
        nozzle_efficiency=NozzleEfficiency(mode="direct", value_percent=100.),
        ambient=AmbientConditions(enabled=True, fixed_pressure_atm=1.),
        size=ThrustChamberSize(mode="throat_diameter", nominal_thrust_n=None, throat_diameter_mm=30.),
    )
    inputs = AnalysisInput(engine=engine, thrust_chamber=chamber)
    changed = replace(inputs,
        thrust_chamber=replace(chamber, reaction_efficiency_percent=72.,
            nozzle_efficiency=NozzleEfficiency(mode="direct", value_percent=64.),
            ambient=AmbientConditions(enabled=True, fixed_pressure_atm=.02)),
        thermal=ThermalAnalysisInput(enabled=True, segments=[
            FilmSegment("film", "H2O", 300., 30., injector_face=True)]))
    baseline = optimize_mixture_ratio_for_inputs(inputs, bounds=(.3, 3.), cea_adapter=real_backend)
    varied = optimize_mixture_ratio_for_inputs(changed, bounds=(.3, 3.), cea_adapter=real_backend)
    assert varied.source == baseline.source == "rocketcea"
    assert varied.mixture_ratio == baseline.mixture_ratio
    assert varied.vacuum_isp_s == baseline.vacuum_isp_s
    assert varied.mixture_ratio == pytest.approx(1.3134208817800324, abs=5e-5)


@pytest.mark.parametrize("mode", [EquilibriumMode.SHIFTING, EquilibriumMode.FROZEN_AREA])
def test_assigned_exit_pressure_resolves_area_at_each_candidate_against_cea(real_backend, mode):
    engine = EngineDefinition(fuel="Ethanol", fuel_mass_fraction=.7)
    cea = independent_cea(engine)
    exit_ambient_atm = .3
    frozen = int(mode is EquilibriumMode.FROZEN_AREA)
    def area(mr):
        return float(cea.get_eps_at_PcOvPe(Pc=20., MR=float(mr), PcOvPe=20./(1.01325*exit_ambient_atm),
                                           frozen=frozen, frozenAtThroat=frozen))
    def objective(mr):
        return independent_state(cea, engine, mr, area(mr), mode)[0]
    assert abs(area(1.1)-area(1.8)) > .1
    independent_mr, independent_isp = scipy_maximum(objective, (.3, 3.))
    optimum = optimize_mixture_ratio(engine, contraction_area_ratio=6.25, expansion_ratio=None,
                                     ambient_pressure_atm=exit_ambient_atm, equilibrium_mode=mode,
                                     bounds=(.3, 3.), cea_adapter=real_backend)
    assert optimum.source == "rocketcea"
    # Assigned-Pe CEA iteration adds a small non-smooth roundtrip residual.
    # On 1.2.3 the flat frozen peak can move 8.5e-5 in MR while its Isp changes
    # only 3.2e-7 s. Direct native assigned-Pe verification follows below.
    assert optimum.mixture_ratio == pytest.approx(independent_mr, abs=2e-4)
    assert optimum.vacuum_isp_s == pytest.approx(independent_isp, abs=3e-5)
    assert optimum.expansion_ratio == pytest.approx(area(optimum.mixture_ratio), rel=1e-9)
    for neighbour in (optimum.mixture_ratio-.005, optimum.mixture_ratio+.005):
        assert objective(optimum.mixture_ratio) > objective(neighbour)
    pressure_ratio = float(cea.get_PcOvPe(Pc=20., MR=optimum.mixture_ratio, eps=optimum.expansion_ratio,
                                         frozen=frozen, frozenAtThroat=frozen))
    assert 20./pressure_ratio == pytest.approx(1.01325*exit_ambient_atm, rel=5e-5)
    from rocketcea import py_cea
    def direct_native_assigned_pe(mr):
        raw = cea.cea_obj
        raw.setupCards(Pc=20., pc_units="bar", MR=float(mr), eps=None,
                       PcOvPe=20./(1.01325*exit_ambient_atm), frozen=frozen,
                       frozenAtThroat=frozen)
        return float(py_cea.rockt.vaci[raw.i_exit])
    native_mr, native_isp = scipy_maximum(direct_native_assigned_pe, (.3, 3.))
    assert optimum.mixture_ratio == pytest.approx(native_mr, abs=2e-4)
    # CEA's direct assigned-Pe and eps forward run differ up to 0.00062 s;
    # this tolerance is measured native-solver resolution, not an ideal-Isp loss.
    assert optimum.vacuum_isp_s == pytest.approx(native_isp, abs=1e-3)


def test_supply_temperature_pressure_and_dilution_use_same_actual_cea_maximum(real_backend):
    base = EngineDefinition(fuel="Ethanol", fuel_mass_fraction=.7)
    variants = [base, replace(base, fuel_mass_fraction=.9),
                replace(base, fuel_temperature_k=350., fuel_pressure_bar=30.),
                replace(base, fuel_temperature_k=350., fuel_pressure_bar=80.)]
    results = []
    for engine in variants:
        cea = independent_cea(engine)
        objective = lambda mr: independent_state(cea, engine, mr, 40., EquilibriumMode.SHIFTING)[0]
        expected_mr, expected_isp = scipy_maximum(objective, (.3, 3.))
        optimum = optimize_mixture_ratio(engine, contraction_area_ratio=6.25, expansion_ratio=40.,
                                         bounds=(.3, 3.), cea_adapter=real_backend)
        assert optimum.source == "rocketcea"
        assert optimum.mixture_ratio == pytest.approx(expected_mr, abs=8e-5)
        assert optimum.vacuum_isp_s == pytest.approx(expected_isp, abs=3e-5)
        actual = independent_state(cea, engine, optimum.mixture_ratio, 40., EquilibriumMode.SHIFTING)
        assert optimum.ideal_cstar_m_s == pytest.approx(actual[1], abs=1e-8)
        assert optimum.vacuum_isp_s == pytest.approx(actual[0], abs=1e-8)
        results.append(optimum)
    assert abs(results[0].mixture_ratio-results[1].mixture_ratio) > .05
    assert abs(results[0].mixture_ratio-results[2].mixture_ratio) > .001
    assert abs(results[2].vacuum_isp_s-results[3].vacuum_isp_s) > 1e-7


def test_unsupported_fac_chamber_freezing_is_rejected_without_silent_fallback(real_backend):
    engine = EngineDefinition(fuel="Ethanol", fuel_mass_fraction=.7)
    with pytest.raises(UnsupportedFlowError, match="Frozen-at-chamber"):
        optimize_mixture_ratio(engine, contraction_area_ratio=6.25, expansion_ratio=40.,
                               equilibrium_mode=EquilibriumMode.FROZEN_PRESSURE, cea_adapter=real_backend)
    chamber = ThrustChamberInput(
        contraction_area_ratio=6.25,
        equilibrium=EquilibriumFlow(mode=EquilibriumMode.FROZEN_PRESSURE, freeze_pressure_ratio=10.),
    )
    with pytest.raises(UnsupportedFlowError, match="Frozen-at-chamber"):
        optimize_mixture_ratio_for_inputs(AnalysisInput(engine=engine, thrust_chamber=chamber),
                                          cea_adapter=real_backend)


def integration_project(stored_mr):
    from lpa.ui.input_views import default_segment
    regen = default_segment("Regen", 1)
    regen.update(id="fuel-regen", coolant_source_mode="Engine fuel", coolant_inlet_pressure_bar="45")
    film = default_segment("Film", 2)
    film.update(id="water-film", coolant="H2O", relative_mass_flow_pct="30")
    return {
        "engine": {"engine_name": "independent automatic OF oracle", "chamber_pressure_bar": "20",
                   "oxidizer": "LOX", "fuel": "Ethanol", "fuel_mass_fraction_pct": "70",
                   "mixture_ratio": stored_mr, "mixture_ratio_auto": True},
        "thrust_chamber": {"contraction_area_ratio": "6.25", "exit_condition_mode": "Expansion area ratio",
                           "exit_condition_value": "40", "flow_model": "Shifting equilibrium",
                           "reaction_efficiency_pct": "100", "nozzle_efficiency_mode": "Direct",
                           "nozzle_efficiency_pct": "100", "sizing_mode": "Throat diameter",
                           "throat_diameter_mm": "30", "characteristic_length_mm": "1000",
                           "contraction_angle_deg": "30", "r2_ratio": ".5", "r1_rt": "1.5",
                           "nozzle_type": "Conical", "nozzle_half_angle_deg": "15", "rn_rt": ".382"},
        "thermal": {"thermal_enabled": True, "thermal_resolution": "Low", "segments": [regen, film]},
    }


def capture_thermal_streams(monkeypatch):
    import lpa.analysis as integration
    import lpa.thermal as thermal_module
    calls, cores = [], []
    actual_analyze_engine = integration.analyze_engine
    def capture_core(*args, **kwargs):
        result = actual_analyze_engine(*args, **kwargs)
        cores.append(result)
        return result
    def capture_thermal(contour, gas, segments, **kwargs):
        calls.append((gas["performance"], segments))
        data = {"x_m": [], "radius_m": [], "Twg_K": [], "Tc_K": [], "warnings": [],
                "physical_validity": "screening", "physical_issues": [], "converged": True,
                "coolant_outlet_temperature_k": {"fuel-regen": 350.},
                "coolant_outlet_pressure_bar": {"fuel-regen": 30.},
                "metadata": {"coupled_converged": True}}
        return SimpleNamespace(as_dict=lambda: copy.deepcopy(data), x_m=(), Tc_K=(), active_segment_id=(),
                               coolant_outlet_temperature_k=data["coolant_outlet_temperature_k"],
                               coolant_outlet_pressure_bar=data["coolant_outlet_pressure_bar"])
    monkeypatch.setattr(integration, "analyze_engine", capture_core)
    monkeypatch.setattr(thermal_module, "analyze_thermal", capture_thermal)
    return calls, cores


@pytest.mark.parametrize("stored_mr", ["1.234799", "inactive-invalid-O/F"])
def test_service_keeps_auto_input_snapshot_and_uses_selected_of_for_all_streams(real_backend, monkeypatch, stored_mr):
    from lpa.analysis import AnalysisService
    calls, cores = capture_thermal_streams(monkeypatch)
    project = integration_project(stored_mr)
    before = copy.deepcopy(project)
    result = AnalysisService().analyze(project)
    assert project == before
    assert result["input_project"] == before
    assert result["input_project"]["engine"]["mixture_ratio_auto"] is True
    optimum = result["mixture_ratio_optimization"]
    assert optimum["enabled"] and optimum["source"] == "rocketcea"
    assert optimum["mixture_ratio"] == pytest.approx(1.4222078492061143, abs=5e-5)
    perf, segments = calls[0]
    assert perf.mixture_ratio == optimum["mixture_ratio"]
    assert cores[0].inputs.engine.mixture_ratio == perf.mixture_ratio
    normalized = segments[0]["coolant"]["relative_mass_flow_percent"] / 100.
    assert normalized * perf.total_mass_flow_kg_s == pytest.approx(perf.fuel_mass_flow_kg_s, rel=1e-12)
    core_fraction = cores[0].inputs.thermal.segments[0].coolant.relative_mass_flow_percent / 100.
    assert core_fraction * perf.total_mass_flow_kg_s == pytest.approx(perf.fuel_mass_flow_kg_s, rel=1e-12)
    assert perf.oxidizer_mass_flow_kg_s/perf.fuel_mass_flow_kg_s == pytest.approx(optimum["mixture_ratio"], rel=1e-12)


def test_feedback_reoptimizes_updated_supply_state_without_changing_saved_auto_snapshot(real_backend, monkeypatch):
    from lpa.analysis import AnalysisService
    calls, _ = capture_thermal_streams(monkeypatch)
    project = integration_project("inactive-invalid-O/F")
    project["thermal"]["regen_feed_feedback_enabled"] = True
    before = copy.deepcopy(project)
    result = AnalysisService().analyze(project)
    assert project == before
    assert result["input_project"] == before
    assert result["regen_feed_feedback"]["converged"]
    assert len(calls) == 2
    assert abs(calls[1][0].mixture_ratio-calls[0][0].mixture_ratio) > .001
    supplied = EngineDefinition(fuel="Ethanol", fuel_mass_fraction=.7,
                                fuel_temperature_k=350., fuel_pressure_bar=30.)
    cea = independent_cea(supplied)
    objective = lambda mr: independent_state(cea, supplied, mr, 40., EquilibriumMode.SHIFTING)[0]
    expected_mr, expected_isp = scipy_maximum(objective, (.3, 3.))
    optimum = result["mixture_ratio_optimization"]
    assert optimum["mixture_ratio"] == pytest.approx(expected_mr, abs=8e-5)
    assert optimum["vacuum_isp_s"] == pytest.approx(expected_isp, abs=3e-5)
    for perf, segments in calls:
        fuel_fraction = segments[0]["coolant"]["relative_mass_flow_percent"] / 100.
        assert fuel_fraction*perf.total_mass_flow_kg_s == pytest.approx(perf.fuel_mass_flow_kg_s, rel=1e-12)
