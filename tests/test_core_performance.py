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
        )
    )
    result = evaluate_performance(AnalysisInput(thrust_chamber=chamber), prefer_rocketcea=False)
    assert result.exit_pressure_bar == pytest.approx(0.35 * 1.01325, rel=2e-6)


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


def test_mixture_ratio_optimizer_maximizes_rocketcea_vacuum_isp():
    factory_calls = []

    class QuadraticCEA:
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
    assert optimum.vacuum_isp_s == pytest.approx(410.0, abs=1e-5)
    assert optimum.expansion_ratio == 18.0
    assert len(factory_calls) == 1


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
    assert optimum.warning is None


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
