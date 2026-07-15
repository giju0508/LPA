"""Public calculation API for LGJ Propulsion Analysis."""

from .analysis import AnalysisResult, analyze_engine
from .contour import ContourResult, generate_contour
from .models import (
    AmbientConditions,
    AnalysisInput,
    ChamberLength,
    ChannelTriplet,
    ChannelWidthMode,
    ContractionDefinitionMode,
    Coolant,
    CoolantDefinition,
    EfficiencyMode,
    EngineDefinition,
    EquilibriumFlow,
    EquilibriumMode,
    ExitConditionMode,
    FilmSegment,
    Fuel,
    LengthMode,
    NozzleContourType,
    NozzleEfficiency,
    NozzleExitCondition,
    NozzleGeometry,
    Oxidizer,
    RadiationMaterial,
    RadiationSegment,
    RangeSpec,
    RegenMaterial,
    RegenSegment,
    Resolution,
    SegmentRange,
    SizeMode,
    SweepMode,
    ThermalAnalysisInput,
    ThermalBarrierCoating,
    ThrottleSettings,
    ThrustChamberInput,
    ThrustChamberSize,
    validate_inputs,
)
from .performance import (
    ATM_PA,
    BAR_PA,
    G0,
    DeliveredPerformance,
    MixtureRatioOptimum,
    PerformanceResult,
    RocketCEAAdapter,
    ThermochemicalState,
    evaluate_performance,
    optimize_mixture_ratio,
)
from .propellants import (
    COOLANT_CEA_NAMES,
    FUELS,
    OXIDIZERS,
    FallbackChemistry,
    PropellantSpec,
    fallback_chemistry,
    registration_cards,
    rocketcea_names,
)
from .sweeps import (
    PerformanceSweep,
    SweepPoint,
    run_ambient_sweep,
    run_throttle_sweep,
)
from .serialization import analysis_input_from_dict, analysis_input_to_dict
from .thermodynamics import (
    AxialThermodynamics,
    ThermodynamicStation,
    build_thermodynamics,
)

__all__ = [name for name in globals() if not name.startswith("_")]
