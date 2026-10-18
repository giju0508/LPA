from __future__ import annotations

from math import pi

import pytest

from lpa.core import (
    AmbientConditions,
    AnalysisInput,
    EngineDefinition,
    NozzleExitCondition,
    RangeSpec,
    RocketCEAAdapter,
    SizeMode,
    SweepMode,
    ThermalAnalysisInput,
    ThrottleSettings,
    ThrustChamberInput,
    ThrustChamberSize,
    analyze_engine,
    build_thermodynamics,
    evaluate_performance,
    generate_contour,
    optimize_mixture_ratio,
    optimize_mixture_ratio_for_inputs,
    performance_at_ambient_pressure,
    run_ambient_sweep,
    run_throttle_sweep,
)


def test_fallback_nominal_sizing_is_self_consistent():
    result = evaluate_performance(AnalysisInput(), prefer_rocketcea=False)
    assert result.source == "ideal-gas-fallback"
    assert result.with_film.thrust_design_n == pytest.approx(1000.0)
    assert 1000 < result.delivered_cstar_m_s < 2500
    assert 1.1 < result.gamma < 1.35
    assert result.without_film.thrust_vacuum_n > result.without_film.thrust_sea_level_n
    assert result.oxidizer_mass_flow_kg_s + result.fuel_mass_flow_kg_s == pytest.approx(
        result.hot_gas_mass_flow_kg_s
    )


def test_fixed_throat_diameter_sets_hardware_area():
    chamber = ThrustChamberInput(
        size=ThrustChamberSize(
            mode=SizeMode.THROAT_DIAMETER,
            nominal_thrust_n=None,
            throat_diameter_mm=42.0,
        )
    )
    result = evaluate_performance(AnalysisInput(thrust_chamber=chamber), prefer_rocketcea=False)
    assert result.throat_diameter_mm == pytest.approx(42.0)
    assert result.throat_area_m2 == pytest.approx(pi * (0.042**2) / 4)


def test_ambient_exit_condition_is_ideally_expanded_in_fallback():
    chamber = ThrustChamberInput(
        exit_condition=NozzleExitCondition(
            mode="ambient_pressure", ambient_pressure_atm=0.35
        ),
        size=ThrustChamberSize(thrust_ambient_pressure_atm=0.35),
    )
    result = evaluate_performance(AnalysisInput(thrust_chamber=chamber), prefer_rocketcea=False)
    assert result.exit_pressure_bar == pytest.approx(0.35 * 1.01325, rel=2e-6)


def test_fixed_hardware_ambient_recalculation_matches_full_fallback_evaluation():
    inputs = AnalysisInput()
    baseline = evaluate_performance(
        inputs,
        film_mass_fraction=0.12,
        prefer_rocketcea=False,
    )
    ambient_pressure_atm = 0.25

    recalculated = performance_at_ambient_pressure(baseline, ambient_pressure_atm)
    fully_evaluated = evaluate_performance(
        inputs,
        ambient_pressure_atm=ambient_pressure_atm,
        fixed_throat_area_m2=baseline.throat_area_m2,
        fixed_expansion_ratio=baseline.expansion_ratio,
        film_mass_fraction=0.12,
        prefer_rocketcea=False,
    )

    assert recalculated.without_film.thrust_design_n == pytest.approx(
        fully_evaluated.without_film.thrust_design_n,
        rel=1.0e-12,
    )
    assert recalculated.with_film.thrust_design_n == pytest.approx(
        fully_evaluated.with_film.thrust_design_n,
        rel=1.0e-12,
    )
    assert recalculated.with_film.isp_design_s == pytest.approx(
        fully_evaluated.with_film.isp_design_s,
        rel=1.0e-12,
    )


def test_film_blc_exposes_corrected_and_uncorrected_performance():
    result = evaluate_performance(
        AnalysisInput(),
        film_mass_fraction=0.10,
        film_blc_recovery=0.45,
        prefer_rocketcea=False,
    )
    assert result.film_mass_flow_kg_s / result.total_mass_flow_kg_s == pytest.approx(0.10)
    assert result.with_film.thrust_design_n == pytest.approx(1000.0)
    assert result.with_film.thrust_vacuum_n > result.without_film.thrust_vacuum_n
    assert result.with_film.isp_vacuum_s < result.without_film.isp_vacuum_s


class _FakeCEA:
    def get_IvacCstrTc(self, **kwargs):
        return 325.0, 1810.0, 3500.0

    def get_exit_MolWt_gamma(self, **kwargs):
        return 21.0, 1.22

    def get_PcOvPe(self, **kwargs):
        return 45.0


def test_rocketcea_adapter_interface_is_used_when_available():
    factory_arguments = []

    def factory(**kwargs):
        factory_arguments.append(kwargs)
        return _FakeCEA()

    chamber = ThrustChamberInput(
        exit_condition=NozzleExitCondition(
            mode="expansion_ratio", expansion_area_ratio=10.0, ambient_pressure_atm=None
        )
    )
    result = evaluate_performance(
        AnalysisInput(thrust_chamber=chamber),
        cea_adapter=RocketCEAAdapter(factory),
    )
    assert result.source == "rocketcea"
    assert result.ideal_cstar_m_s == 1810.0
    assert result.gamma == 1.22
    assert factory_arguments[0]["pressure_units"] == "bar"
    assert factory_arguments[0]["cstar_units"] == "m/s"


def test_rocketcea_failure_falls_back_or_can_be_required():
    class BrokenCEA:
        def get_IvacCstrTc(self, **kwargs):
            raise RuntimeError("solver failed")

    adapter = RocketCEAAdapter(lambda **kwargs: BrokenCEA())
    result = evaluate_performance(AnalysisInput(), cea_adapter=adapter)
    assert result.source == "ideal-gas-fallback"
    assert "solver failed" in result.warnings[0]
    with pytest.raises(RuntimeError, match="RocketCEA calculation failed"):
        evaluate_performance(
            AnalysisInput(), cea_adapter=adapter, require_rocketcea=True
        )


def test_mixture_ratio_optimizer_maximizes_vacuum_isp_when_cstar_peak_differs():
    factory_calls = []

    class QuadraticCEA:
        def get_Cstar(self, **kwargs):
            assert set(kwargs) == {"Pc", "MR"}
            return 1800.0 - 35.0 * (kwargs["MR"] - 2.3) ** 2

        def getMRforER(self, **kwargs):
            assert kwargs == {"ERphi": 1.0}
            return 4.0

        def get_IvacCstrTc(self, **kwargs):
            mixture_ratio = kwargs["MR"]
            return 410.0 - 7.5 * (mixture_ratio - 3.4) ** 2, 1800.0, 3500.0

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return QuadraticCEA()

    optimum = optimize_mixture_ratio(
        EngineDefinition(chamber_pressure_bar=35.0, oxidizer="LOX", fuel="RP-1"),
        expansion_ratio=18.0,
        bounds=(1.0, 6.0),
        cea_adapter=RocketCEAAdapter(factory),
    )

    assert optimum.source == "rocketcea"
    assert optimum.mixture_ratio == pytest.approx(3.4, abs=2e-4)
    assert optimum.ideal_cstar_m_s == pytest.approx(1800.0, abs=1e-5)
    assert optimum.vacuum_isp_s == pytest.approx(410.0, abs=1e-5)
    assert optimum.expansion_ratio == 18.0
    assert optimum.stoichiometric_mixture_ratio == 4.0
    assert optimum.oxidizer_excess_coefficient == pytest.approx(0.85, abs=5e-5)
    assert optimum.objective == "maximum theoretical vacuum specific impulse"
    assert len(factory_calls) == 1


def test_stoichiometric_lookup_failure_keeps_rocketcea_optimizer_available():
    class WorkingCEA:
        def get_Cstar(self, **kwargs):
            return 1750.0 - 30.0 * (kwargs["MR"] - 2.6) ** 2

        def getMRforER(self, **_kwargs):
            raise LookupError("stoichiometric metadata unavailable")

        def get_IvacCstrTc(self, **kwargs):
            mixture_ratio = kwargs["MR"]
            return 400.0 - 5.0 * (mixture_ratio - 2.6) ** 2, 1750.0, 3400.0

    optimum = optimize_mixture_ratio(
        EngineDefinition(chamber_pressure_bar=25.0, oxidizer="LOX", fuel="RP-1"),
        expansion_ratio=12.0,
        bounds=(1.0, 4.0),
        cea_adapter=RocketCEAAdapter(lambda **_kwargs: WorkingCEA()),
    )

    assert optimum.source == "rocketcea"
    assert optimum.mixture_ratio == pytest.approx(2.6, abs=2e-4)
    assert optimum.stoichiometric_mixture_ratio is None
    assert optimum.oxidizer_excess_coefficient is None


def test_optimizer_does_not_report_nearby_interior_optimum_as_bound():
    class NearBoundCEA:
        def get_Cstar(self, **kwargs):
            return 1700.0 - 20.0 * (kwargs["MR"] - 1.01) ** 2

        def get_IvacCstrTc(self, **kwargs):
            mixture_ratio = kwargs["MR"]
            return 390.0 - 20.0 * (mixture_ratio - 1.01) ** 2, 1700.0, 3300.0

    optimum = optimize_mixture_ratio(
        EngineDefinition(chamber_pressure_bar=20.0, oxidizer="LOX", fuel="RP-1"),
        expansion_ratio=10.0,
        bounds=(1.0, 4.0),
        cea_adapter=RocketCEAAdapter(lambda **_kwargs: NearBoundCEA()),
    )

    assert optimum.mixture_ratio == pytest.approx(1.01, abs=2e-4)
    assert optimum.warning is None


def test_ambient_exit_analysis_uses_rocketcea_pressure_to_area_solution():
    resolved_epsilons: list[float] = []

    class PressureExitCEA:
        def get_eps_at_PcOvPe(self, **kwargs):
            assert kwargs["PcOvPe"] == pytest.approx(30.0 / (0.4 * 1.01325))
            return 12.345

        def get_IvacCstrTc(self, **kwargs):
            resolved_epsilons.append(kwargs["eps"])
            return 330.0, 1800.0, 3500.0

        def get_exit_MolWt_gamma(self, **_kwargs):
            return 22.0, 1.21

        def get_PcOvPe(self, **_kwargs):
            return 30.0 / (0.4 * 1.01325)

    chamber = ThrustChamberInput(
        exit_condition=NozzleExitCondition(
            mode="ambient_pressure",
            ambient_pressure_atm=0.4,
        )
    )
    inputs = AnalysisInput(
        engine=EngineDefinition(chamber_pressure_bar=30.0),
        thrust_chamber=chamber,
    )

    result = evaluate_performance(
        inputs,
        cea_adapter=RocketCEAAdapter(lambda **_kwargs: PressureExitCEA()),
    )

    assert result.source == "rocketcea"
    assert result.expansion_ratio == pytest.approx(12.345)
    assert resolved_epsilons == [pytest.approx(12.345)]
    assert result.exit_pressure_bar == pytest.approx(0.4 * 1.01325)


def test_direct_dc_nominal_thrust_optimizer_resolves_coupled_area_ratio():
    class CoupledCEA:
        def __init__(self, contraction_ratio: float):
            self.contraction_ratio = contraction_ratio

        def get_Cstar(self, **kwargs):
            target = 2.2 + 0.03 * self.contraction_ratio
            return 1800.0 - 30.0 * (kwargs["MR"] - target) ** 2

        def get_IvacCstrTc(self, **kwargs):
            target = 2.2 + 0.03 * self.contraction_ratio
            mixture_ratio = kwargs["MR"]
            return 350.0 - 3.0 * (mixture_ratio - target) ** 2, 1800.0, 3450.0

        def get_exit_MolWt_gamma(self, **_kwargs):
            return 22.0, 1.21

        def get_PcOvPe(self, **_kwargs):
            return 50.0

    def optimize_from_hidden_ratio(hidden_ratio: float):
        chamber = ThrustChamberInput(
            contraction_mode="chamber_diameter",
            contraction_area_ratio=hidden_ratio,
            chamber_diameter_mm=60.0,
            exit_condition=NozzleExitCondition(
                mode="expansion_ratio",
                expansion_area_ratio=12.0,
                ambient_pressure_atm=None,
            ),
            size=ThrustChamberSize(
                mode=SizeMode.NOMINAL_THRUST,
                nominal_thrust_n=1000.0,
                thrust_ambient_pressure_atm=1.0,
                throat_diameter_mm=None,
            ),
        )
        adapter = RocketCEAAdapter(
            lambda **kwargs: CoupledCEA(float(kwargs["fac_CR"]))
        )
        return optimize_mixture_ratio_for_inputs(
            AnalysisInput(thrust_chamber=chamber),
            bounds=(1.0, 4.0),
            cea_adapter=adapter,
        )

    from_low_guess = optimize_from_hidden_ratio(2.0)
    from_high_guess = optimize_from_hidden_ratio(12.0)

    assert from_low_guess.source == "rocketcea"
    assert from_low_guess.mixture_ratio == pytest.approx(
        from_high_guess.mixture_ratio,
        abs=2.0e-4,
    )


def test_mixture_ratio_optimizer_has_bounded_fallback():
    optimum = optimize_mixture_ratio(
        EngineDefinition(oxidizer="LOX", fuel="LH2"),
        expansion_ratio=40.0,
        bounds=(0.5, 10.0),
        prefer_rocketcea=False,
    )

    assert optimum.source == "ideal-gas-fallback"
    assert 0.5 < optimum.mixture_ratio < 10.0
    assert optimum.vacuum_isp_s > 0.0
    assert optimum.warning is not None
    assert "unvalidated" in optimum.objective
    assert "not a validated CEA/RPA result" in optimum.warning


def test_vacuum_isp_optimizer_resolves_pressure_exit_at_every_candidate():
    evaluated: list[tuple[float, float]] = []
    resolved: list[float] = []

    class AmbientCEA:
        def get_Cstar(self, **kwargs):
            return 1750.0 - 30.0 * (kwargs["MR"] - 2.25) ** 2

        def getMRforER(self, **_kwargs):
            return 3.0

        def get_eps_at_PcOvPe(self, **kwargs):
            assert kwargs["PcOvPe"] == pytest.approx(30 / (0.4 * 1.01325))
            assert kwargs["frozen"] == kwargs["frozenAtThroat"] == 0
            resolved.append(kwargs["MR"])
            return 4.0 + kwargs["MR"]

        def get_IvacCstrTc(self, **kwargs):
            evaluated.append((kwargs["MR"], kwargs["eps"]))
            # The location of the peak depends on the candidate's exit area.
            return 390.0 - 4.0 * (kwargs["MR"] - (2.0 + 0.1 * kwargs["eps"])) ** 2, 1750.0, 3400.0

    optimum = optimize_mixture_ratio(
        EngineDefinition(chamber_pressure_bar=30.0, oxidizer="LOX", fuel="RP-1"),
        expansion_ratio=None,
        ambient_pressure_atm=0.4,
        bounds=(1.0, 4.0),
        cea_adapter=RocketCEAAdapter(lambda **_kwargs: AmbientCEA()),
    )

    assert optimum.mixture_ratio == pytest.approx(8 / 3, abs=2e-4)
    assert optimum.expansion_ratio == pytest.approx(20 / 3, abs=2e-4)
    assert len(evaluated) >= 49
    assert resolved == [ratio for ratio, _ in evaluated]
    assert all(expansion == pytest.approx(4.0 + ratio) for ratio, expansion in evaluated)


def test_raw_cstar_evaluator_keeps_its_embedding_contract():
    from lpa.core.models import EquilibriumMode

    class CEA:
        def get_Cstar(self, Pc, MR):
            return 1600 + MR
        def get_IvacCstrTc(self, **_kwargs):
            raise AssertionError("raw C* calls must not require nozzle evaluation")

    evaluator = RocketCEAAdapter(lambda **_kwargs: CEA()).cstar_evaluator(
        EngineDefinition(), contraction_area_ratio=4, expansion_ratio=20,
        equilibrium_mode=EquilibriumMode.SHIFTING)
    assert evaluator(2.3) == 1602.3


@pytest.mark.parametrize("expansion,expected", [(5, 2.1), (40, 2.8)])
def test_vacuum_isp_objective_can_change_with_exit_area(expansion, expected):
    class CEA:
        def get_IvacCstrTc(self, Pc, MR, eps):
            target = 2.0 + eps / 50.0
            return 350 - (MR - target)**2, 1700, 3200

    optimum = optimize_mixture_ratio(EngineDefinition(), expansion_ratio=expansion,
        bounds=(1, 4), cea_adapter=RocketCEAAdapter(lambda **_kwargs: CEA()))
    assert optimum.source == "rocketcea"
    assert optimum.mixture_ratio == pytest.approx(expected, abs=2e-4)


def test_vacuum_isp_optimizer_uses_requested_throat_freeze_for_every_candidate():
    calls = []
    class CEA:
        def get_IvacCstrTc(self, **_kwargs):
            raise AssertionError("the shifting model must not substitute for frozen flow")
        def get_eps_at_PcOvPe(self, **kwargs):
            assert kwargs["frozen"] == kwargs["frozenAtThroat"] == 1
            assert kwargs["PcOvPe"] == pytest.approx(20 / 1.01325)
            return 4 + kwargs["MR"]
        def getFrozen_IvacCstrTc(self, Pc, MR, eps, frozenAtThroat):
            assert frozenAtThroat == 1
            calls.append((MR, eps))
            return 340 - 4*(MR - 2.7)**2, 1650, 3300

    optimum = optimize_mixture_ratio(EngineDefinition(), equilibrium_mode="freezing_at_area_ratio",
        expansion_ratio=None, ambient_pressure_atm=1, bounds=(1, 4),
        cea_adapter=RocketCEAAdapter(lambda **_kwargs: CEA()))
    assert optimum.source == "rocketcea"
    assert optimum.mixture_ratio == pytest.approx(2.7, abs=2e-4)
    assert len(calls) >= 49
    assert all(eps == 4 + mr for mr, eps in calls)


@pytest.mark.parametrize("all_invalid", [False, True])
def test_nonfinite_vacuum_isp_candidates_cannot_win(all_invalid):
    class CEA:
        def get_IvacCstrTc(self, Pc, MR, eps):
            value = float("nan") if all_invalid or MR < 1.8 else 350 - (MR - 2.7)**2
            return value, 1700, 3200

    optimum = optimize_mixture_ratio(EngineDefinition(), bounds=(1, 4),
        cea_adapter=RocketCEAAdapter(lambda **_kwargs: CEA()))
    if all_invalid:
        assert optimum.source == "ideal-gas-fallback"
        assert "invalid vacuum specific impulse" in optimum.warning
        assert "unvalidated" in optimum.objective
    else:
        assert optimum.source == "rocketcea"
        assert optimum.mixture_ratio == pytest.approx(2.7, abs=2e-4)


def test_invalid_cstar_metadata_does_not_discard_valid_isp_optimum():
    class CEA:
        def get_IvacCstrTc(self, Pc, MR, eps):
            return 350 - (MR - 2.7)**2, float("nan"), 3200

    optimum = optimize_mixture_ratio(EngineDefinition(), bounds=(1, 4),
        cea_adapter=RocketCEAAdapter(lambda **_kwargs: CEA()))
    assert optimum.source == "rocketcea"
    assert optimum.mixture_ratio == pytest.approx(2.7, abs=2e-4)
    assert optimum.ideal_cstar_m_s is None
    assert "reference C* metadata" in optimum.warning


def test_thermodynamic_station_table_and_axial_arrays_are_complete():
    performance = evaluate_performance(AnalysisInput(), prefer_rocketcea=False)
    contour = generate_contour(
        AnalysisInput().thrust_chamber,
        performance.throat_diameter_mm,
        performance.expansion_ratio,
        120,
    )
    thermo = build_thermodynamics(contour, performance)
    assert set(thermo.stations) == {
        "injector",
        "nozzle_inlet",
        "nozzle_throat",
        "nozzle_exit",
    }
    assert thermo.section_count == 120
    assert thermo.stations["nozzle_throat"].mach == 1.0
    assert thermo.stations["nozzle_exit"].mach > 1.0
    assert thermo.pressure_pa[-1] < thermo.pressure_pa[0]
    assert len(thermo.plot_variables) == 13
    for flux, area in zip(thermo.mass_flux_kg_m2_s, contour.area_m2):
        assert flux * area == pytest.approx(performance.hot_gas_mass_flow_kg_s)


def test_throttle_and_ambient_sweeps_hold_hardware_fixed():
    chamber = ThrustChamberInput(
        exit_condition=NozzleExitCondition(
            mode="expansion_ratio", expansion_area_ratio=6.0, ambient_pressure_atm=None
        ),
        size=ThrustChamberSize(
            mode="nominal_thrust",
            nominal_thrust_n=1000.0,
            thrust_ambient_pressure_atm=0.0,
        ),
        throttle=ThrottleSettings(
            True, SweepMode.RANGE, range=RangeSpec(50.0, 100.0, 3)
        ),
        ambient=AmbientConditions(
            True, SweepMode.RANGE, range=RangeSpec(0.0, 1.0, 3)
        ),
    )
    inputs = AnalysisInput(thrust_chamber=chamber)
    baseline = evaluate_performance(inputs, prefer_rocketcea=False)
    throttled = run_throttle_sweep(inputs, baseline, prefer_rocketcea=False)
    ambient = run_ambient_sweep(inputs, baseline, prefer_rocketcea=False)
    assert throttled.values == (50.0, 75.0, 100.0)
    assert all(
        point.result.throat_area_m2 == baseline.throat_area_m2 for point in throttled.points
    )
    thrusts = [point.result.without_film.thrust_design_n for point in throttled.points]
    assert thrusts == sorted(thrusts)
    ambient_thrusts = [point.result.without_film.thrust_design_n for point in ambient.points]
    assert ambient_thrusts == sorted(ambient_thrusts, reverse=True)


def test_high_level_dict_adapter_honors_resolution_and_reports_count():
    result = analyze_engine(
        {
            "engine": {"name": "Dictionary engine"},
            "thermal": {"enabled": True, "resolution": "low", "segments": []},
        },
        prefer_rocketcea=False,
    )
    assert result.inputs.engine.name == "Dictionary engine"
    assert result.section_count == 120
    assert result.contour.metadata["actual_section_count"] == 120
    assert result.thermodynamics.section_count == 120
