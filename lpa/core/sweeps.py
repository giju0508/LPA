"""Throttle and ambient-pressure performance sweeps on fixed hardware."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .atmosphere import (
    MAX_MODEL_PRESSURE_PA,
    MIN_MODEL_PRESSURE_PA,
    altitude_for_pressure,
    standard_atmosphere,
)
from .models import AnalysisInput, SweepMode
from .performance import (
    ATM_PA,
    PerformanceResult,
    RocketCEAAdapter,
    evaluate_performance,
    performance_at_ambient_pressure,
)


@dataclass(frozen=True, slots=True)
class SweepPoint:
    value: float
    result: PerformanceResult


@dataclass(frozen=True, slots=True)
class PerformanceSweep:
    variable: str
    unit: str
    points: tuple[SweepPoint, ...]

    @property
    def values(self) -> tuple[float, ...]:
        return tuple(point.value for point in self.points)


def _throttle_values(inputs: AnalysisInput) -> tuple[float, ...]:
    settings = inputs.thrust_chamber.throttle
    if not settings.enabled:
        return ()
    if settings.mode is SweepMode.FIXED:
        return (settings.fixed_percent,)
    return settings.range.values()  # type: ignore[union-attr]


def _ambient_values(inputs: AnalysisInput) -> tuple[float, ...]:
    settings = inputs.thrust_chamber.ambient
    if not settings.enabled:
        return ()
    if settings.mode is SweepMode.FIXED:
        return (settings.fixed_pressure_atm,)
    return settings.range.values()  # type: ignore[union-attr]


def run_throttle_sweep(
    inputs: AnalysisInput,
    baseline: PerformanceResult | None = None,
    *,
    prefer_rocketcea: bool = True,
    require_rocketcea: bool = False,
    cea_adapter: RocketCEAAdapter | None = None,
) -> PerformanceSweep:
    """Vary chamber pressure with throttle while holding nozzle hardware fixed."""

    values = _throttle_values(inputs)
    if not values:
        return PerformanceSweep("throttle", "%", ())
    baseline = baseline or evaluate_performance(
        inputs, prefer_rocketcea=prefer_rocketcea, require_rocketcea=require_rocketcea, cea_adapter=cea_adapter
    )
    points: list[SweepPoint] = []
    for throttle_percent in values:
        engine = replace(
            inputs.engine,
            chamber_pressure_bar=inputs.engine.chamber_pressure_bar * throttle_percent / 100.0,
        )
        varied = AnalysisInput(engine, inputs.thrust_chamber, inputs.thermal)
        result = evaluate_performance(
            varied,
            ambient_pressure_atm=baseline.design_ambient_pressure_atm,
            fixed_throat_area_m2=baseline.throat_area_m2,
            fixed_expansion_ratio=baseline.expansion_ratio,
            prefer_rocketcea=prefer_rocketcea,
            require_rocketcea=require_rocketcea,
            cea_adapter=cea_adapter,
        )
        points.append(SweepPoint(throttle_percent, result))
    return PerformanceSweep("throttle", "%", tuple(points))


def run_ambient_sweep(
    inputs: AnalysisInput,
    baseline: PerformanceResult | None = None,
    *,
    prefer_rocketcea: bool = True,
    require_rocketcea: bool = False,
    cea_adapter: RocketCEAAdapter | None = None,
) -> PerformanceSweep:
    """Vary back pressure while holding chamber state and nozzle hardware fixed."""

    values = _ambient_values(inputs)
    if not values:
        return PerformanceSweep("ambient_pressure", "atm", ())
    baseline = baseline or evaluate_performance(
        inputs, prefer_rocketcea=prefer_rocketcea, require_rocketcea=require_rocketcea, cea_adapter=cea_adapter
    )
    points = tuple(
        SweepPoint(pressure_atm, performance_at_ambient_pressure(baseline, pressure_atm))
        for pressure_atm in values
    )
    return PerformanceSweep("ambient_pressure", "atm", points)


def run_standard_atmosphere_sweep(
    inputs: AnalysisInput,
    baseline: PerformanceResult | None = None,
    *,
    prefer_rocketcea: bool = True,
    require_rocketcea: bool = False,
    cea_adapter: RocketCEAAdapter | None = None,
) -> PerformanceSweep:
    """Evaluate fixed hardware on an evenly spaced standard-altitude grid."""

    settings = inputs.thrust_chamber.ambient
    if not settings.enabled:
        return PerformanceSweep("geometric_altitude", "km", ())
    baseline = baseline or evaluate_performance(
        inputs, prefer_rocketcea=prefer_rocketcea, require_rocketcea=require_rocketcea, cea_adapter=cea_adapter
    )
    if settings.mode is SweepMode.FIXED:
        state = altitude_for_pressure(settings.fixed_pressure_atm * ATM_PA)
        if state is None:
            return PerformanceSweep("geometric_altitude", "km", ())
        altitudes_km = (state.geometric_altitude_m / 1000.0,)
    else:
        pressure1 = settings.range.minimum * ATM_PA  # type: ignore[union-attr]
        pressure2 = settings.range.maximum * ATM_PA  # type: ignore[union-attr]
        requested_low, requested_high = sorted((pressure1, pressure2))
        valid_low = max(requested_low, MIN_MODEL_PRESSURE_PA)
        valid_high = min(requested_high, MAX_MODEL_PRESSURE_PA)
        if valid_low > valid_high:
            return PerformanceSweep("geometric_altitude", "km", ())
        high_altitude = altitude_for_pressure(valid_low)
        low_altitude = altitude_for_pressure(valid_high)
        if high_altitude is None or low_altitude is None:  # Defensive bounds check.
            return PerformanceSweep("geometric_altitude", "km", ())
        altitude1 = low_altitude.geometric_altitude_m / 1000.0
        altitude2 = high_altitude.geometric_altitude_m / 1000.0
        lower, upper = sorted((altitude1, altitude2))
        points = settings.range.points  # type: ignore[union-attr]
        if points == 1 or abs(upper - lower) < 1.0e-12:
            altitudes_km = (lower,)
        else:
            altitudes_km = tuple(
                lower + (upper - lower) * index / (points - 1)
                for index in range(points)
            )
    sweep_points = tuple(
        SweepPoint(
            altitude_km,
            performance_at_ambient_pressure(
                baseline,
                standard_atmosphere(altitude_km * 1000.0).pressure_pa / ATM_PA,
            ),
        )
        for altitude_km in altitudes_km
    )
    return PerformanceSweep("geometric_altitude", "km", sweep_points)
