from __future__ import annotations

import pytest

from lpa.core import (
    ATM_PA,
    AmbientConditions,
    AnalysisInput,
    RangeSpec,
    SweepMode,
    ThrustChamberInput,
    altitude_for_pressure,
    evaluate_performance,
    run_standard_atmosphere_sweep,
    standard_atmosphere,
)


def test_standard_atmosphere_matches_sea_level_and_11_km_layer_boundary() -> None:
    sea_level = standard_atmosphere(0.0)
    assert sea_level.temperature_k == pytest.approx(288.15, abs=1.0e-10)
    assert sea_level.pressure_pa == pytest.approx(101_325.0, abs=1.0e-8)
    assert sea_level.density_kg_m3 == pytest.approx(1.225, rel=2.0e-6)

    boundary = altitude_for_pressure(22_632.06)
    assert boundary is not None
    assert boundary.geopotential_altitude_m == pytest.approx(11_000.0, abs=0.02)
    assert boundary.temperature_k == pytest.approx(216.65, abs=0.01)


@pytest.mark.parametrize("altitude_m", [-5_000.0, 0.0, 5_000.0, 20_000.0, 50_000.0, 85_000.0])
def test_standard_atmosphere_pressure_inverse_round_trip(altitude_m: float) -> None:
    original = standard_atmosphere(altitude_m)
    restored = altitude_for_pressure(original.pressure_pa)
    assert restored is not None
    assert restored.geometric_altitude_m == pytest.approx(altitude_m, abs=1.0e-5)


def test_standard_altitude_sweep_uses_uniform_altitude_and_fixed_hardware() -> None:
    chamber = ThrustChamberInput(
        ambient=AmbientConditions(
            True,
            SweepMode.RANGE,
            range=RangeSpec(0.05, 1.0, 5),
        )
    )
    inputs = AnalysisInput(thrust_chamber=chamber)
    baseline = evaluate_performance(inputs, prefer_rocketcea=False)
    sweep = run_standard_atmosphere_sweep(inputs, baseline, prefer_rocketcea=False)

    assert len(sweep.points) == 5
    intervals = [sweep.values[index + 1] - sweep.values[index] for index in range(4)]
    assert intervals == pytest.approx([intervals[0]] * 4)
    assert sweep.values[0] == pytest.approx(0.0, abs=1.0e-9)
    assert sweep.points[0].result.design_ambient_pressure_atm == pytest.approx(1.0)
    assert sweep.points[-1].result.design_ambient_pressure_atm == pytest.approx(0.05)
    assert all(point.result.throat_area_m2 == baseline.throat_area_m2 for point in sweep.points)
    assert all(point.result.expansion_ratio == baseline.expansion_ratio for point in sweep.points)


def test_vacuum_pressure_is_not_reported_as_a_finite_standard_altitude() -> None:
    assert altitude_for_pressure(0.0) is None
    assert altitude_for_pressure(2.0 * ATM_PA) is None


@pytest.mark.parametrize("pressure_atm", [0.0, 2.0])
def test_fixed_pressure_outside_model_does_not_create_clipped_altitude(
    pressure_atm: float,
) -> None:
    chamber = ThrustChamberInput(
        ambient=AmbientConditions(True, SweepMode.FIXED, fixed_pressure_atm=pressure_atm)
    )
    inputs = AnalysisInput(thrust_chamber=chamber)
    baseline = evaluate_performance(inputs, prefer_rocketcea=False)

    sweep = run_standard_atmosphere_sweep(inputs, baseline, prefer_rocketcea=False)

    assert sweep.points == ()


def test_pressure_range_is_intersected_with_standard_atmosphere_bounds() -> None:
    chamber = ThrustChamberInput(
        ambient=AmbientConditions(
            True,
            SweepMode.RANGE,
            range=RangeSpec(0.0, 1.0, 4),
        )
    )
    inputs = AnalysisInput(thrust_chamber=chamber)
    baseline = evaluate_performance(inputs, prefer_rocketcea=False)

    sweep = run_standard_atmosphere_sweep(inputs, baseline, prefer_rocketcea=False)

    assert len(sweep.points) == 4
    assert sweep.values[0] == pytest.approx(0.0, abs=1.0e-9)
    assert 85.9 < sweep.values[-1] < 86.1
    assert all(point.result.design_ambient_pressure_atm > 0.0 for point in sweep.points)
