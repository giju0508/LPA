"""Single-call orchestration for the UI and command-line entry point."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .contour import ContourResult, generate_contour
from .models import AnalysisInput, Resolution, validate_inputs
from .performance import PerformanceResult, RocketCEAAdapter, evaluate_performance
from .sweeps import (
    PerformanceSweep,
    run_ambient_sweep,
    run_standard_atmosphere_sweep,
    run_throttle_sweep,
)
from .thermodynamics import AxialThermodynamics, build_thermodynamics
from .serialization import analysis_input_from_dict


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    inputs: AnalysisInput
    performance: PerformanceResult
    contour: ContourResult
    thermodynamics: AxialThermodynamics
    throttle_sweep: PerformanceSweep
    ambient_sweep: PerformanceSweep
    altitude_sweep: PerformanceSweep
    warnings: tuple[str, ...]

    @property
    def section_count(self) -> int:
        return self.contour.section_count


def analyze_engine(
    inputs: AnalysisInput | Mapping[str, Any],
    *,
    prefer_rocketcea: bool = True,
    require_rocketcea: bool = False,
    cea_adapter: RocketCEAAdapter | None = None,
) -> AnalysisResult:
    """Run sizing, contour, thermo table and enabled sweeps in dependency order."""

    if not isinstance(inputs, AnalysisInput):
        inputs = analysis_input_from_dict(inputs)
    if cea_adapter is None and (prefer_rocketcea or require_rocketcea):
        cea_adapter = RocketCEAAdapter()
    performance = evaluate_performance(
        inputs,
        prefer_rocketcea=prefer_rocketcea,
        require_rocketcea=require_rocketcea,
        cea_adapter=cea_adapter,
    )
    resolution = inputs.thermal.resolution if inputs.thermal.enabled else Resolution.MEDIUM
    contour = generate_contour(
        inputs.thrust_chamber,
        performance.throat_diameter_mm,
        performance.expansion_ratio,
        resolution,
        exit_mach=performance.exit_mach,
        throat_isentropic_exponent=performance.throat_isentropic_exponent,
        exit_isentropic_exponent=performance.exit_isentropic_exponent,
        nozzle_flow_source=performance.nozzle_flow_source,
    )
    thermodynamics = build_thermodynamics(contour, performance, inputs=inputs, cea_adapter=cea_adapter)
    throttle_sweep = run_throttle_sweep(
        inputs,
        performance,
        prefer_rocketcea=prefer_rocketcea,
        require_rocketcea=require_rocketcea,
        cea_adapter=cea_adapter,
    )
    ambient_sweep = run_ambient_sweep(
        inputs,
        performance,
        prefer_rocketcea=prefer_rocketcea,
        require_rocketcea=require_rocketcea,
        cea_adapter=cea_adapter,
    )
    altitude_sweep = run_standard_atmosphere_sweep(
        inputs,
        performance,
        prefer_rocketcea=prefer_rocketcea,
        require_rocketcea=require_rocketcea,
        cea_adapter=cea_adapter,
    )
    warnings = list(validate_inputs(inputs))
    warnings.extend(performance.warnings)
    warnings.extend(thermodynamics.warnings)
    for sweep in (throttle_sweep, ambient_sweep, altitude_sweep):
        for point in sweep.points:
            warnings.extend(f"{sweep.variable}={point.value:g} {sweep.unit}: {warning}" for warning in point.result.warnings if warning not in performance.warnings)
    rao_warning = contour.metadata.get("rao_angle_warning")
    if isinstance(rao_warning, str):
        warnings.append(rao_warning)
    geometry_warning = contour.metadata.get("convergent_geometry_warning")
    if isinstance(geometry_warning, str):
        warnings.append(geometry_warning)
    if inputs.thermal.enabled:
        warnings.extend(
            inputs.thermal.overlap_warnings(
                contour.length_m * 1000.0,
                contour.x_m[contour.chamber_end_index] * 1000.0,
            )
        )
    return AnalysisResult(
        inputs=inputs,
        performance=performance,
        contour=contour,
        thermodynamics=thermodynamics,
        throttle_sweep=throttle_sweep,
        ambient_sweep=ambient_sweep,
        altitude_sweep=altitude_sweep,
        warnings=tuple(dict.fromkeys(warnings)),
    )
