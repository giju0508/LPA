"""Liquid rocket performance calculation with an optional RocketCEA backend."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import cos, isfinite, pi, radians, sqrt
from typing import Callable

from ._numerics import expansion_ratio_for_pressure, solve_mach
from .models import (
    AnalysisInput,
    ContractionDefinitionMode,
    EfficiencyMode,
    EngineDefinition,
    EquilibriumFlow,
    EquilibriumMode,
    ExitConditionMode,
    NozzleExitCondition,
    NozzleContourType,
    SizeMode,
    ThrustChamberInput,
)
from .propellants import (
    fallback_chemistry,
    registration_cards,
    rocketcea_names,
)
from .rocketcea_runtime import rocketcea_import_environment


G0 = 9.80665
ATM_PA = 101_325.0
BAR_PA = 100_000.0
UNIVERSAL_GAS_CONSTANT = 8_314.462618


@dataclass(frozen=True, slots=True)
class ThermochemicalState:
    source: str
    ideal_cstar_m_s: float
    ideal_vacuum_isp_s: float
    combustion_temperature_k: float
    gamma: float
    molecular_weight_kg_kmol: float
    exit_pressure_bar: float
    exit_mach: float
    warnings: tuple[str, ...] = ()

    @property
    def gas_constant_j_kgk(self) -> float:
        return UNIVERSAL_GAS_CONSTANT / self.molecular_weight_kg_kmol

    @property
    def ideal_vacuum_cf(self) -> float:
        return self.ideal_vacuum_isp_s * G0 / self.ideal_cstar_m_s


@dataclass(frozen=True, slots=True)
class DeliveredPerformance:
    thrust_design_n: float
    thrust_sea_level_n: float
    thrust_optimum_n: float
    thrust_vacuum_n: float
    isp_design_s: float
    isp_sea_level_s: float
    isp_optimum_s: float
    isp_vacuum_s: float


@dataclass(frozen=True, slots=True)
class PerformanceResult:
    source: str
    chamber_pressure_bar: float
    mixture_ratio: float
    contraction_area_ratio: float
    expansion_ratio: float
    exit_pressure_bar: float
    design_ambient_pressure_atm: float
    throat_area_m2: float
    throat_diameter_mm: float
    exit_diameter_mm: float
    ideal_cstar_m_s: float
    delivered_cstar_m_s: float
    combustion_temperature_k: float
    gamma: float
    molecular_weight_kg_kmol: float
    gas_constant_j_kgk: float
    nozzle_efficiency: float
    reaction_efficiency: float
    hot_gas_mass_flow_kg_s: float
    oxidizer_mass_flow_kg_s: float
    fuel_mass_flow_kg_s: float
    film_mass_flow_kg_s: float
    total_mass_flow_kg_s: float
    without_film: DeliveredPerformance
    with_film: DeliveredPerformance
    film_blc_recovery: float
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def mass_flow_kg_s(self) -> float:
        return self.total_mass_flow_kg_s


@dataclass(frozen=True, slots=True)
class MixtureRatioOptimum:
    """Maximum-vacuum-Isp O/F result at one reference nozzle condition."""

    mixture_ratio: float
    vacuum_isp_s: float
    expansion_ratio: float
    source: str
    warning: str | None = None


class RocketCEAAdapter:
    """Thin adapter around RocketCEA with SI/bar unit configuration.

    A custom ``cea_factory`` can be supplied by tests or embedding applications.
    Normal operation discovers RocketCEA lazily, allowing LPA to start and edit
    projects even when the optional compiled dependency is not installed.
    """

    def __init__(self, cea_factory: Callable[..., object] | None = None) -> None:
        self._factory = cea_factory
        self._add_fuel: Callable[..., object] | None = None
        self._add_oxidizer: Callable[..., object] | None = None
        self.unavailable_reason: str | None = None
        if cea_factory is None:
            try:
                with rocketcea_import_environment():
                    from rocketcea.cea_obj import add_new_fuel, add_new_oxidizer
                    from rocketcea.cea_obj_w_units import CEA_Obj

                self._factory = CEA_Obj
                self._add_fuel = add_new_fuel
                self._add_oxidizer = add_new_oxidizer
            except (ImportError, OSError) as error:
                self.unavailable_reason = str(error)

    @property
    def available(self) -> bool:
        return self._factory is not None

    def _register(self, engine: EngineDefinition) -> None:
        for kind, name, card in registration_cards(engine.oxidizer, engine.fuel):
            function = self._add_oxidizer if kind == "oxidizer" else self._add_fuel
            if function is not None:
                function(name, card)

    def _make_cea(self, engine: EngineDefinition, contraction_area_ratio: float) -> object:
        if self._factory is None:
            raise RuntimeError(self.unavailable_reason or "RocketCEA is unavailable")
        self._register(engine)
        oxidizer_name, fuel_name = rocketcea_names(engine.oxidizer, engine.fuel)
        return self._factory(
            oxName=oxidizer_name,
            fuelName=fuel_name,
            fac_CR=contraction_area_ratio,
            pressure_units="bar",
            cstar_units="m/s",
            temperature_units="K",
            isp_units="sec",
            sonic_velocity_units="m/s",
            enthalpy_units="kJ/kg",
            density_units="kg/m^3",
            specific_heat_units="kJ/kg-K",
            viscosity_units="millipoise",
            thermal_cond_units="W/cm-degC",
        )

    def vacuum_isp_evaluator(
        self,
        engine: EngineDefinition,
        *,
        contraction_area_ratio: float,
        expansion_ratio: float,
        equilibrium_mode: EquilibriumMode,
    ) -> Callable[[float], float]:
        """Build one reusable CEA object for a bounded O/F optimization."""

        cea = self._make_cea(engine, contraction_area_ratio)

        def evaluate(mixture_ratio: float) -> float:
            arguments = {
                "Pc": engine.chamber_pressure_bar,
                "MR": mixture_ratio,
                "eps": expansion_ratio,
            }
            if equilibrium_mode is EquilibriumMode.SHIFTING:
                value = cea.get_IvacCstrTc(**arguments)[0]  # type: ignore[attr-defined]
            else:
                frozen_method = getattr(cea, "getFrozen_IvacCstrTc", None)
                if frozen_method is None:
                    value = cea.get_IvacCstrTc(**arguments)[0]  # type: ignore[attr-defined]
                else:
                    value = frozen_method(
                        **arguments,
                        frozenAtThroat=int(equilibrium_mode is EquilibriumMode.FROZEN_AREA),
                    )[0]
            return float(value)

        return evaluate

    def calculate(
        self,
        engine: EngineDefinition,
        chamber: ThrustChamberInput,
        expansion_ratio: float,
    ) -> ThermochemicalState:
        if self._factory is None:
            raise RuntimeError(self.unavailable_reason or "RocketCEA is unavailable")
        cea = self._make_cea(engine, chamber.contraction_area_ratio)
        arguments = {
            "Pc": engine.chamber_pressure_bar,
            "MR": engine.mixture_ratio,
            "eps": expansion_ratio,
        }
        if chamber.equilibrium.mode is EquilibriumMode.SHIFTING:
            isp_vac, cstar, temperature = cea.get_IvacCstrTc(**arguments)  # type: ignore[attr-defined]
        else:
            frozen_at_throat = int(chamber.equilibrium.mode is EquilibriumMode.FROZEN_AREA)
            frozen_method = getattr(cea, "getFrozen_IvacCstrTc", None)
            if frozen_method is None:
                isp_vac, cstar, temperature = cea.get_IvacCstrTc(**arguments)  # type: ignore[attr-defined]
            else:
                isp_vac, cstar, temperature = frozen_method(
                    **arguments, frozenAtThroat=frozen_at_throat
                )

        fallback = fallback_chemistry(engine.oxidizer, engine.fuel, engine.mixture_ratio)
        molecular_weight, gamma = fallback.molecular_weight_kg_kmol, fallback.gamma
        gamma_method = getattr(cea, "get_exit_MolWt_gamma", None)
        if gamma_method is not None:
            try:
                molecular_weight, gamma = gamma_method(**arguments)
            except (TypeError, ValueError, RuntimeError):
                pass

        exit_pressure_bar: float
        pressure_method = getattr(cea, "get_PcOvPe", None)
        if pressure_method is not None:
            pressure_ratio = float(pressure_method(**arguments))
            exit_pressure_bar = engine.chamber_pressure_bar / pressure_ratio
        else:
            exit_mach_guess = solve_mach(expansion_ratio, float(gamma), supersonic=True)
            exit_pressure_bar = engine.chamber_pressure_bar / (
                1.0 + 0.5 * (float(gamma) - 1.0) * exit_mach_guess**2
            ) ** (float(gamma) / (float(gamma) - 1.0))
        exit_mach = solve_mach(expansion_ratio, float(gamma), supersonic=True)
        return ThermochemicalState(
            source="rocketcea",
            ideal_cstar_m_s=float(cstar),
            ideal_vacuum_isp_s=float(isp_vac),
            combustion_temperature_k=float(temperature),
            gamma=float(gamma),
            molecular_weight_kg_kmol=float(molecular_weight),
            exit_pressure_bar=exit_pressure_bar,
            exit_mach=exit_mach,
        )


def _fallback_state(
    engine: EngineDefinition,
    chamber: ThrustChamberInput,
    expansion_ratio: float,
    warning: str | None = None,
) -> ThermochemicalState:
    chemistry = fallback_chemistry(engine.oxidizer, engine.fuel, engine.mixture_ratio)
    gamma = chemistry.gamma
    gas_constant = UNIVERSAL_GAS_CONSTANT / chemistry.molecular_weight_kg_kmol
    flow_factor = {
        EquilibriumMode.SHIFTING: 1.0,
        EquilibriumMode.FROZEN_PRESSURE: 0.985,
        EquilibriumMode.FROZEN_AREA: 0.975,
    }[chamber.equilibrium.mode]
    temperature = chemistry.flame_temperature_k * flow_factor
    cstar = sqrt(gas_constant * temperature / gamma) * (
        (gamma + 1.0) / 2.0
    ) ** ((gamma + 1.0) / (2.0 * (gamma - 1.0)))
    exit_mach = solve_mach(expansion_ratio, gamma, supersonic=True)
    pressure_ratio = (
        1.0 + 0.5 * (gamma - 1.0) * exit_mach**2
    ) ** (gamma / (gamma - 1.0))
    exit_pressure_bar = engine.chamber_pressure_bar / pressure_ratio
    pe_pc = 1.0 / pressure_ratio
    momentum_cf = sqrt(
        (2.0 * gamma**2 / (gamma - 1.0))
        * (2.0 / (gamma + 1.0)) ** ((gamma + 1.0) / (gamma - 1.0))
        * (1.0 - pe_pc ** ((gamma - 1.0) / gamma))
    )
    vacuum_cf = momentum_cf + pe_pc * expansion_ratio
    warnings = (
        warning
        or "RocketCEA is not installed; conservative ideal-gas fallback estimates are shown",
    )
    return ThermochemicalState(
        source="ideal-gas-fallback",
        ideal_cstar_m_s=cstar,
        ideal_vacuum_isp_s=vacuum_cf * cstar / G0,
        combustion_temperature_k=temperature,
        gamma=gamma,
        molecular_weight_kg_kmol=chemistry.molecular_weight_kg_kmol,
        exit_pressure_bar=exit_pressure_bar,
        exit_mach=exit_mach,
        warnings=warnings,
    )


def optimize_mixture_ratio(
    engine: EngineDefinition,
    *,
    contraction_area_ratio: float = 4.0,
    expansion_ratio: float | None = 40.0,
    ambient_pressure_atm: float | None = None,
    equilibrium_mode: EquilibriumMode | str = EquilibriumMode.SHIFTING,
    bounds: tuple[float, float] = (0.10, 30.0),
    prefer_rocketcea: bool = True,
    cea_adapter: RocketCEAAdapter | None = None,
) -> MixtureRatioOptimum:
    """Find the O/F that maximizes ideal vacuum specific impulse.

    The nozzle area ratio is held fixed while O/F is varied.  If an ambient
    pressure is supplied instead of an area ratio, a reference area ratio is
    first calculated at the fallback chemistry optimum.  A broad bounded scan
    followed by golden-section refinement avoids depending on a derivative
    from the Fortran solver.  When RocketCEA is unavailable or cannot evaluate
    the selected propellants, the same search is performed on LPA's explicitly
    marked engineering fallback model.
    """

    lower, upper = (float(bounds[0]), float(bounds[1]))
    if not (isfinite(lower) and isfinite(upper) and 0 < lower < upper):
        raise ValueError("mixture-ratio bounds must be finite, positive, and increasing")
    if not isfinite(contraction_area_ratio) or contraction_area_ratio <= 1.0:
        raise ValueError("contraction area ratio must be greater than 1")
    if isinstance(equilibrium_mode, EquilibriumMode):
        mode = equilibrium_mode
    else:
        mode = EquilibriumMode(str(equilibrium_mode))

    if expansion_ratio is None:
        if ambient_pressure_atm is None or not isfinite(ambient_pressure_atm):
            raise ValueError("ambient pressure is required when expansion ratio is omitted")
        if ambient_pressure_atm < 0:
            raise ValueError("ambient pressure must be non-negative")
        seed = fallback_chemistry(engine.oxidizer, engine.fuel, engine.mixture_ratio)
        reference = fallback_chemistry(
            engine.oxidizer, engine.fuel, seed.optimum_mixture_ratio
        )
        expansion_ratio = expansion_ratio_for_pressure(
            engine.chamber_pressure_bar * BAR_PA,
            ambient_pressure_atm * ATM_PA,
            reference.gamma,
        )
    expansion_ratio = float(expansion_ratio)
    if not isfinite(expansion_ratio) or expansion_ratio <= 1.0:
        raise ValueError("expansion ratio must be finite and greater than 1")

    flow = EquilibriumFlow(
        mode=mode,
        freeze_pressure_ratio=10.0 if mode is EquilibriumMode.FROZEN_PRESSURE else None,
        freeze_area_ratio=1.0 if mode is EquilibriumMode.FROZEN_AREA else None,
    )
    reference_chamber = ThrustChamberInput(
        contraction_area_ratio=contraction_area_ratio,
        exit_condition=NozzleExitCondition(
            mode=ExitConditionMode.EXPANSION_RATIO,
            expansion_area_ratio=expansion_ratio,
            ambient_pressure_atm=None,
        ),
        equilibrium=flow,
    )

    def fallback_objective(mixture_ratio: float) -> float:
        candidate = replace(engine, mixture_ratio=mixture_ratio)
        return _fallback_state(candidate, reference_chamber, expansion_ratio).ideal_vacuum_isp_s

    errors: list[str] = []

    def maximize(evaluator: Callable[[float], float]) -> tuple[float, float, bool]:
        cache: dict[float, float] = {}

        def safe_value(mixture_ratio: float) -> float:
            key = round(float(mixture_ratio), 12)
            if key in cache:
                return cache[key]
            try:
                value = float(evaluator(float(mixture_ratio)))
                if not isfinite(value) or value <= 0.0:
                    raise ValueError(f"invalid specific impulse {value!r}")
            except Exception as error:  # RocketCEA exposes several wrapper errors.
                if len(errors) < 3:
                    errors.append(str(error))
                value = float("-inf")
            cache[key] = value
            return value

        sample_count = 49
        samples = [lower + (upper - lower) * index / (sample_count - 1) for index in range(sample_count)]
        values = [safe_value(item) for item in samples]
        valid_indices = [index for index, value in enumerate(values) if isfinite(value)]
        if not valid_indices:
            raise RuntimeError(errors[0] if errors else "specific impulse could not be evaluated")
        best_index = max(valid_indices, key=lambda index: values[index])
        at_bound = best_index in (0, sample_count - 1)
        left = samples[max(0, best_index - 1)]
        right = samples[min(sample_count - 1, best_index + 1)]

        # Golden-section maximization inside the best coarse interval.
        inverse_phi = (sqrt(5.0) - 1.0) / 2.0
        x1 = right - inverse_phi * (right - left)
        x2 = left + inverse_phi * (right - left)
        f1, f2 = safe_value(x1), safe_value(x2)
        for _ in range(30):
            if f1 < f2:
                left, x1, f1 = x1, x2, f2
                x2 = left + inverse_phi * (right - left)
                f2 = safe_value(x2)
            else:
                right, x2, f2 = x2, x1, f1
                x1 = right - inverse_phi * (right - left)
                f1 = safe_value(x1)

        candidates = [(ratio, value) for ratio, value in cache.items() if isfinite(value)]
        optimum_ratio, optimum_isp = max(candidates, key=lambda item: item[1])
        return optimum_ratio, optimum_isp, at_bound

    adapter = cea_adapter
    if adapter is None and prefer_rocketcea:
        adapter = RocketCEAAdapter()
    warning: str | None = None
    source = "ideal-gas-fallback"
    if prefer_rocketcea and adapter is not None and adapter.available:
        try:
            cea_objective = adapter.vacuum_isp_evaluator(
                engine,
                contraction_area_ratio=contraction_area_ratio,
                expansion_ratio=expansion_ratio,
                equilibrium_mode=mode,
            )
            ratio, isp, at_bound = maximize(cea_objective)
            source = "rocketcea"
        except Exception as error:
            errors.clear()
            ratio, isp, at_bound = maximize(fallback_objective)
            warning = f"RocketCEA O/F optimization failed ({error}); engineering fallback optimum is used"
    else:
        ratio, isp, at_bound = maximize(fallback_objective)
        if prefer_rocketcea:
            detail = adapter.unavailable_reason if adapter is not None else "RocketCEA is unavailable"
            warning = f"{detail}; engineering fallback optimum is used"
    if at_bound:
        bound_note = f"optimum reached the configured O/F bound [{lower:g}, {upper:g}]"
        warning = f"{warning}; {bound_note}" if warning else bound_note
    return MixtureRatioOptimum(
        mixture_ratio=ratio,
        vacuum_isp_s=isp,
        expansion_ratio=expansion_ratio,
        source=source,
        warning=warning,
    )


def _estimated_nozzle_efficiency(chamber: ThrustChamberInput) -> float:
    if chamber.nozzle.contour_type is NozzleContourType.CONICAL:
        divergence = 0.5 * (1.0 + cos(radians(chamber.nozzle.conical_half_angle_deg)))
        return max(0.85, min(0.995, 0.985 * divergence))
    length_fraction = chamber.nozzle.bell_length_percent / 100.0
    return max(0.94, min(0.995, 0.982 + 0.015 * (length_fraction - 0.7)))


def _metric_set(
    throat_area_m2: float,
    chamber_pressure_pa: float,
    hot_mass_flow: float,
    total_mass_flow: float,
    expansion_ratio: float,
    exit_pressure_pa: float,
    ideal_vacuum_cf: float,
    delivered_cstar: float,
    nozzle_efficiency: float,
    design_ambient_pressure_atm: float,
    thrust_multiplier: float = 1.0,
) -> DeliveredPerformance:
    pe_pc = exit_pressure_pa / chamber_pressure_pa
    momentum_cf = ideal_vacuum_cf - pe_pc * expansion_ratio
    delivered_momentum_cf = max(0.0, momentum_cf) * sqrt(nozzle_efficiency)

    def cf(ambient_pa: float) -> float:
        pressure_cf = (exit_pressure_pa - ambient_pa) / chamber_pressure_pa * expansion_ratio
        return max(0.02, delivered_momentum_cf + pressure_cf)

    cf_design = cf(design_ambient_pressure_atm * ATM_PA)
    cf_sea = cf(ATM_PA)
    cf_optimum = cf(exit_pressure_pa)
    cf_vacuum = cf(0.0)

    def pair(coefficient: float) -> tuple[float, float]:
        base_thrust = chamber_pressure_pa * throat_area_m2 * coefficient
        thrust = base_thrust * thrust_multiplier
        isp = thrust / (max(total_mass_flow, 1e-12) * G0)
        return thrust, isp

    thrust_design, isp_design = pair(cf_design)
    thrust_sea, isp_sea = pair(cf_sea)
    thrust_optimum, isp_optimum = pair(cf_optimum)
    thrust_vacuum, isp_vacuum = pair(cf_vacuum)
    return DeliveredPerformance(
        thrust_design_n=thrust_design,
        thrust_sea_level_n=thrust_sea,
        thrust_optimum_n=thrust_optimum,
        thrust_vacuum_n=thrust_vacuum,
        isp_design_s=isp_design,
        isp_sea_level_s=isp_sea,
        isp_optimum_s=isp_optimum,
        isp_vacuum_s=isp_vacuum,
    )


def evaluate_performance(
    inputs: AnalysisInput,
    *,
    ambient_pressure_atm: float | None = None,
    fixed_throat_area_m2: float | None = None,
    fixed_expansion_ratio: float | None = None,
    film_mass_fraction: float | None = None,
    film_blc_recovery: float = 0.45,
    prefer_rocketcea: bool = True,
    require_rocketcea: bool = False,
    cea_adapter: RocketCEAAdapter | None = None,
    _contraction_area_ratio_override: float | None = None,
) -> PerformanceResult:
    """Evaluate delivered sea-level, optimum and vacuum performance.

    Film coolant is treated as a boundary-layer coolant (BLC).  The uncorrected
    result ignores its mass and momentum.  The corrected result adds total film
    mass and recovers ``film_blc_recovery`` of its ideal axial momentum, exposing
    both values so reports do not hide the assumption.
    """

    engine, chamber = inputs.engine, inputs.thrust_chamber

    # A direct chamber diameter and nominal-thrust sizing form a small coupled
    # problem: CEA's finite-area combustor model needs Ac/At, while At follows
    # from delivered performance.  Resolve that loop here so every downstream
    # consumer receives one self-consistent ratio.  Fixed throat hardware is
    # determinate immediately and needs no iteration.
    if (
        chamber.contraction_mode is ContractionDefinitionMode.CHAMBER_DIAMETER
        and _contraction_area_ratio_override is None
    ):
        known_throat_diameter_mm: float | None = None
        if fixed_throat_area_m2 is not None:
            if fixed_throat_area_m2 <= 0:
                raise ValueError("fixed throat area must be positive")
            known_throat_diameter_mm = sqrt(4.0 * fixed_throat_area_m2 / pi) * 1000.0
        elif chamber.size.mode is SizeMode.THROAT_DIAMETER:
            known_throat_diameter_mm = float(chamber.size.throat_diameter_mm)  # type: ignore[arg-type]

        if known_throat_diameter_mm is not None:
            _contraction_area_ratio_override = chamber.resolved_contraction_area_ratio(
                known_throat_diameter_mm
            )
        else:
            ratio = (
                float(chamber.contraction_area_ratio)
                if isfinite(chamber.contraction_area_ratio)
                and chamber.contraction_area_ratio > 1.0
                else 4.0
            )
            iteration_adapter = cea_adapter
            if iteration_adapter is None and (prefer_rocketcea or require_rocketcea):
                iteration_adapter = RocketCEAAdapter()
            result: PerformanceResult | None = None
            for _iteration in range(12):
                result = evaluate_performance(
                    inputs,
                    ambient_pressure_atm=ambient_pressure_atm,
                    fixed_throat_area_m2=fixed_throat_area_m2,
                    fixed_expansion_ratio=fixed_expansion_ratio,
                    film_mass_fraction=film_mass_fraction,
                    film_blc_recovery=film_blc_recovery,
                    prefer_rocketcea=prefer_rocketcea,
                    require_rocketcea=require_rocketcea,
                    cea_adapter=iteration_adapter,
                    _contraction_area_ratio_override=ratio,
                )
                resolved = chamber.resolved_contraction_area_ratio(
                    result.throat_diameter_mm
                )
                if abs(resolved / ratio - 1.0) <= 1.0e-7:
                    return replace(result, contraction_area_ratio=resolved)
                ratio = resolved
            # Re-evaluate at the latest ratio rather than returning a result
            # from the preceding iterate.
            result = evaluate_performance(
                inputs,
                ambient_pressure_atm=ambient_pressure_atm,
                fixed_throat_area_m2=fixed_throat_area_m2,
                fixed_expansion_ratio=fixed_expansion_ratio,
                film_mass_fraction=film_mass_fraction,
                film_blc_recovery=film_blc_recovery,
                prefer_rocketcea=prefer_rocketcea,
                require_rocketcea=require_rocketcea,
                cea_adapter=iteration_adapter,
                _contraction_area_ratio_override=ratio,
            )
            return replace(
                result,
                contraction_area_ratio=chamber.resolved_contraction_area_ratio(
                    result.throat_diameter_mm
                ),
            )

    if _contraction_area_ratio_override is not None:
        if not isfinite(_contraction_area_ratio_override) or _contraction_area_ratio_override <= 1.0:
            raise ValueError("resolved contraction area ratio must be greater than 1")
        chamber = replace(
            chamber,
            contraction_area_ratio=float(_contraction_area_ratio_override),
        )
    if ambient_pressure_atm is None:
        if chamber.ambient.enabled and chamber.ambient.mode.value == "fixed":
            ambient_pressure_atm = chamber.ambient.fixed_pressure_atm
        elif chamber.exit_condition.mode is ExitConditionMode.AMBIENT_PRESSURE:
            ambient_pressure_atm = chamber.exit_condition.ambient_pressure_atm
        else:
            ambient_pressure_atm = chamber.size.thrust_ambient_pressure_atm
    if ambient_pressure_atm is None or ambient_pressure_atm < 0:
        raise ValueError("ambient pressure must be non-negative")
    if not 0 <= film_blc_recovery <= 1:
        raise ValueError("film BLC recovery must be between 0 and 1")
    if film_mass_fraction is None:
        film_mass_fraction = inputs.thermal.film_mass_fraction
    if not 0 <= film_mass_fraction < 1:
        raise ValueError("film mass fraction must be in [0, 1)")

    fallback = fallback_chemistry(engine.oxidizer, engine.fuel, engine.mixture_ratio)
    if fixed_expansion_ratio is not None:
        expansion_ratio = fixed_expansion_ratio
    elif chamber.exit_condition.mode is ExitConditionMode.EXPANSION_RATIO:
        expansion_ratio = chamber.exit_condition.expansion_area_ratio
    else:
        requested_exit_pa = chamber.exit_condition.ambient_pressure_atm * ATM_PA
        expansion_ratio = expansion_ratio_for_pressure(
            engine.chamber_pressure_bar * BAR_PA,
            requested_exit_pa,
            fallback.gamma,
        )
    if expansion_ratio is None or expansion_ratio <= 1:
        raise ValueError("expansion ratio must be greater than 1")

    adapter = cea_adapter
    if adapter is None and (prefer_rocketcea or require_rocketcea):
        adapter = RocketCEAAdapter()
    state: ThermochemicalState
    if prefer_rocketcea and adapter is not None and adapter.available:
        try:
            state = adapter.calculate(engine, chamber, expansion_ratio)
            if (
                fixed_expansion_ratio is None
                and chamber.exit_condition.mode is ExitConditionMode.AMBIENT_PRESSURE
            ):
                refined_ratio = expansion_ratio_for_pressure(
                    engine.chamber_pressure_bar * BAR_PA,
                    chamber.exit_condition.ambient_pressure_atm * ATM_PA,
                    state.gamma,
                )
                if abs(refined_ratio / expansion_ratio - 1.0) > 1e-3:
                    expansion_ratio = refined_ratio
                    state = adapter.calculate(engine, chamber, expansion_ratio)
        except Exception as error:  # RocketCEA raises several Fortran wrapper errors.
            if require_rocketcea:
                raise RuntimeError(f"RocketCEA calculation failed: {error}") from error
            state = _fallback_state(
                engine,
                chamber,
                expansion_ratio,
                f"RocketCEA failed ({error}); ideal-gas fallback estimates are shown",
            )
    elif require_rocketcea:
        raise RuntimeError(
            (adapter.unavailable_reason if adapter is not None else None)
            or "RocketCEA is unavailable"
        )
    else:
        detail = (
            adapter.unavailable_reason
            if prefer_rocketcea and adapter is not None
            else "RocketCEA use was disabled"
        )
        state = _fallback_state(
            engine,
            chamber,
            expansion_ratio,
            f"{detail}; conservative ideal-gas fallback estimates are shown",
        )

    reaction_efficiency = chamber.reaction_efficiency_percent / 100.0
    delivered_cstar = state.ideal_cstar_m_s * reaction_efficiency
    if chamber.nozzle_efficiency.mode is EfficiencyMode.DIRECT:
        nozzle_efficiency = chamber.nozzle_efficiency.value_percent / 100.0
    else:
        nozzle_efficiency = _estimated_nozzle_efficiency(chamber)

    pc_pa = engine.chamber_pressure_bar * BAR_PA
    pe_pa = state.exit_pressure_bar * BAR_PA
    ideal_vacuum_cf = state.ideal_vacuum_cf
    pe_pc = pe_pa / pc_pa
    momentum_cf = max(0.0, ideal_vacuum_cf - pe_pc * expansion_ratio)
    delivered_momentum_cf = momentum_cf * sqrt(nozzle_efficiency)

    def design_cf(atmospheres: float) -> float:
        return max(
            0.02,
            delivered_momentum_cf
            + (pe_pa - atmospheres * ATM_PA) / pc_pa * expansion_ratio,
        )

    film_thrust_multiplier = 1.0 + film_blc_recovery * film_mass_fraction / max(
        1e-12, 1.0 - film_mass_fraction
    )
    if fixed_throat_area_m2 is not None:
        if fixed_throat_area_m2 <= 0:
            raise ValueError("fixed throat area must be positive")
        throat_area = fixed_throat_area_m2
    elif chamber.size.mode is SizeMode.THROAT_DIAMETER:
        diameter_m = chamber.size.throat_diameter_mm / 1000.0
        throat_area = pi * diameter_m**2 / 4.0
    else:
        sizing_cf = design_cf(chamber.size.thrust_ambient_pressure_atm)
        throat_area = chamber.size.nominal_thrust_n / (
            pc_pa * sizing_cf * film_thrust_multiplier
        )

    throat_diameter_mm = sqrt(4.0 * throat_area / pi) * 1000.0
    exit_diameter_mm = throat_diameter_mm * sqrt(expansion_ratio)
    hot_mass_flow = pc_pa * throat_area / delivered_cstar
    total_mass_flow = hot_mass_flow / (1.0 - film_mass_fraction)
    film_mass_flow = total_mass_flow - hot_mass_flow
    oxidizer_mass_flow = hot_mass_flow * engine.mixture_ratio / (1.0 + engine.mixture_ratio)
    fuel_mass_flow = hot_mass_flow / (1.0 + engine.mixture_ratio)

    without_film = _metric_set(
        throat_area,
        pc_pa,
        hot_mass_flow,
        hot_mass_flow,
        expansion_ratio,
        pe_pa,
        ideal_vacuum_cf,
        delivered_cstar,
        nozzle_efficiency,
        ambient_pressure_atm,
    )
    with_film = _metric_set(
        throat_area,
        pc_pa,
        hot_mass_flow,
        total_mass_flow,
        expansion_ratio,
        pe_pa,
        ideal_vacuum_cf,
        delivered_cstar,
        nozzle_efficiency,
        ambient_pressure_atm,
        thrust_multiplier=film_thrust_multiplier,
    )
    return PerformanceResult(
        source=state.source,
        chamber_pressure_bar=engine.chamber_pressure_bar,
        mixture_ratio=engine.mixture_ratio,
        contraction_area_ratio=chamber.contraction_area_ratio,
        expansion_ratio=expansion_ratio,
        exit_pressure_bar=state.exit_pressure_bar,
        design_ambient_pressure_atm=ambient_pressure_atm,
        throat_area_m2=throat_area,
        throat_diameter_mm=throat_diameter_mm,
        exit_diameter_mm=exit_diameter_mm,
        ideal_cstar_m_s=state.ideal_cstar_m_s,
        delivered_cstar_m_s=delivered_cstar,
        combustion_temperature_k=state.combustion_temperature_k * reaction_efficiency,
        gamma=state.gamma,
        molecular_weight_kg_kmol=state.molecular_weight_kg_kmol,
        gas_constant_j_kgk=state.gas_constant_j_kgk,
        nozzle_efficiency=nozzle_efficiency,
        reaction_efficiency=reaction_efficiency,
        hot_gas_mass_flow_kg_s=hot_mass_flow,
        oxidizer_mass_flow_kg_s=oxidizer_mass_flow,
        fuel_mass_flow_kg_s=fuel_mass_flow,
        film_mass_flow_kg_s=film_mass_flow,
        total_mass_flow_kg_s=total_mass_flow,
        without_film=without_film,
        with_film=with_film,
        film_blc_recovery=film_blc_recovery,
        warnings=state.warnings,
    )
