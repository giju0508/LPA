"""Throttle and ambient-pressure performance sweeps on fixed hardware."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .models import AnalysisInput, SweepMode
from .performance import PerformanceResult, RocketCEAAdapter, evaluate_performance


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
    cea_adapter: RocketCEAAdapter | None = None,
) -> PerformanceSweep:
    """Vary chamber pressure with throttle while holding nozzle hardware fixed."""

    values = _throttle_values(inputs)
    if not values:
        return PerformanceSweep("throttle", "%", ())
    baseline = baseline or evaluate_performance(
        inputs, prefer_rocketcea=prefer_rocketcea, cea_adapter=cea_adapter
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
            cea_adapter=cea_adapter,
        )
        points.append(SweepPoint(throttle_percent, result))
    return PerformanceSweep("throttle", "%", tuple(points))


def run_ambient_sweep(
    inputs: AnalysisInput,
    baseline: PerformanceResult | None = None,
    *,
    prefer_rocketcea: bool = True,
    cea_adapter: RocketCEAAdapter | None = None,
) -> PerformanceSweep:
    """Vary back pressure while holding chamber state and nozzle hardware fixed."""

    values = _ambient_values(inputs)
    if not values:
        return PerformanceSweep("ambient_pressure", "atm", ())
    baseline = baseline or evaluate_performance(
        inputs, prefer_rocketcea=prefer_rocketcea, cea_adapter=cea_adapter
    )
    points = tuple(
        SweepPoint(
            pressure_atm,
            evaluate_performance(
                inputs,
                ambient_pressure_atm=pressure_atm,
                fixed_throat_area_m2=baseline.throat_area_m2,
                fixed_expansion_ratio=baseline.expansion_ratio,
                prefer_rocketcea=prefer_rocketcea,
                cea_adapter=cea_adapter,
            ),
        )
        for pressure_atm in values
    )
    return PerformanceSweep("ambient_pressure", "atm", points)
