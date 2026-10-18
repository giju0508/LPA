"""Liquid rocket performance calculation with an optional RocketCEA backend."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import wraps
from math import cos, isfinite, nan, pi, radians, sqrt
from typing import Callable
from threading import RLock

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
    propellant_specs,
    registration_cards,
    rocketcea_names,
)
from .rocketcea_runtime import configure_rocketcea_process_directory, rocketcea_import_environment


G0 = 9.80665
ATM_PA = 101_325.0
BAR_PA = 100_000.0
UNIVERSAL_GAS_CONSTANT = 8_314.462618
_CEA_LOCK = RLock()


def _serialized_cea(function):
    """CEA output arrays and registration caches are process-global."""
    @wraps(function)
    def serialized(*args, **kwargs):
        with _CEA_LOCK:
            return function(*args, **kwargs)
    return serialized


class UnsupportedFlowError(ValueError):
    """A requested flow model cannot produce a verified physical state."""


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
    throat_isentropic_exponent: float | None = None
    exit_isentropic_exponent: float | None = None
    nozzle_flow_source: str = "constant_gamma_estimate"
    cea_cstar_m_s: float | None = None
    pressure_reference: str = "injector-face pressure"

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
    exit_mach: float | None = None
    throat_isentropic_exponent: float | None = None
    exit_isentropic_exponent: float | None = None
    nozzle_flow_source: str = "constant_gamma_estimate"
    design_nozzle_regime: str = "attached"
    sea_level_nozzle_regime: str = "attached"
    cea_cstar_m_s: float | None = None
    pressure_reference: str = "injector-face pressure"

    @property
    def mass_flow_kg_s(self) -> float:
        return self.total_mass_flow_kg_s


@dataclass(frozen=True, slots=True)
class MixtureRatioOptimum:
    """Maximum theoretical vacuum Isp for the configured nozzle flow.

    ``ideal_cstar_m_s`` is optional metadata at that optimum, in RocketCEA's
    CEA infinite-combustor pressure convention, not the optimized quantity.
    """

    mixture_ratio: float
    vacuum_isp_s: float
    expansion_ratio: float
    source: str
    warning: str | None = None
    stoichiometric_mixture_ratio: float | None = None
    oxidizer_excess_coefficient: float | None = None
    objective: str = "maximum theoretical vacuum specific impulse"
    ideal_cstar_m_s: float | None = None


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
                    from rocketcea import cea_obj as cea_module
                    from rocketcea.cea_obj import add_new_fuel, add_new_oxidizer
                    from rocketcea.cea_obj_w_units import CEA_Obj
                    configure_rocketcea_process_directory(cea_module)

                self._factory = CEA_Obj
                self._add_fuel = add_new_fuel
                self._add_oxidizer = add_new_oxidizer
            except (ImportError, OSError) as error:
                self.unavailable_reason = str(error)

    @property
    def available(self) -> bool:
        return self._factory is not None

    def _register(self, engine: EngineDefinition) -> None:
        for kind, name, card in registration_cards(
            engine.oxidizer, engine.fuel, engine.oxidizer_mass_fraction, engine.fuel_mass_fraction,
            oxidizer_temperature_k=getattr(engine, "oxidizer_temperature_k", None),
            fuel_temperature_k=getattr(engine, "fuel_temperature_k", None),
            oxidizer_pressure_bar=getattr(engine, "oxidizer_pressure_bar", None),
            fuel_pressure_bar=getattr(engine, "fuel_pressure_bar", None),
        ):
            function = self._add_oxidizer if kind == "oxidizer" else self._add_fuel
            if function is not None:
                function(name, card)

    @_serialized_cea
    def _make_cea(self, engine: EngineDefinition, contraction_area_ratio: float) -> object:
        if self._factory is None:
            raise RuntimeError(self.unavailable_reason or "RocketCEA is unavailable")
        self._register(engine)
        oxidizer_name, fuel_name = rocketcea_names(
            engine.oxidizer, engine.fuel, engine.oxidizer_mass_fraction, engine.fuel_mass_fraction,
            oxidizer_temperature_k=getattr(engine, "oxidizer_temperature_k", None),
            fuel_temperature_k=getattr(engine, "fuel_temperature_k", None),
            oxidizer_pressure_bar=getattr(engine, "oxidizer_pressure_bar", None),
            fuel_pressure_bar=getattr(engine, "fuel_pressure_bar", None),
        )
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

    @staticmethod
    def _resolve_expansion_ratio_with_cea(
        cea: object,
        engine: EngineDefinition,
        *,
        ambient_pressure_atm: float,
        equilibrium_mode: EquilibriumMode,
        mixture_ratio: float,
    ) -> float:
        if ambient_pressure_atm < 0.0:
            raise ValueError("ambient pressure must be non-negative")
        if ambient_pressure_atm == 0.0:
            # A finite nozzle cannot reach zero exit pressure.  Match LPA's
            # pressure-to-area solver practical upper bound.
            return 250.0
        method = getattr(cea, "get_eps_at_PcOvPe", None)
        if not callable(method):
            raise RuntimeError("RocketCEA cannot resolve area ratio from exit pressure")
        pressure_ratio = (
            engine.chamber_pressure_bar * BAR_PA
            / (ambient_pressure_atm * ATM_PA)
        )
        frozen = int(equilibrium_mode is not EquilibriumMode.SHIFTING)
        frozen_at_throat = int(equilibrium_mode is EquilibriumMode.FROZEN_AREA)
        value = float(
            method(
                Pc=engine.chamber_pressure_bar,
                MR=mixture_ratio,
                PcOvPe=pressure_ratio,
                frozen=frozen,
                frozenAtThroat=frozen_at_throat,
            )
        )
        if not isfinite(value) or value <= 1.0:
            raise ValueError(f"invalid expansion area ratio {value!r}")
        return value

    @_serialized_cea
    def expansion_ratio_for_exit_pressure(
        self,
        engine: EngineDefinition,
        *,
        contraction_area_ratio: float,
        ambient_pressure_atm: float,
        equilibrium_mode: EquilibriumMode,
        mixture_ratio: float | None = None,
    ) -> float:
        """Resolve ``Ae/At`` from ``Pe`` with the same CEA model used by analysis."""

        cea = self._make_cea(engine, contraction_area_ratio)
        return self._resolve_expansion_ratio_with_cea(
            cea,
            engine,
            ambient_pressure_atm=ambient_pressure_atm,
            equilibrium_mode=equilibrium_mode,
            mixture_ratio=(engine.mixture_ratio if mixture_ratio is None else mixture_ratio),
        )

    @_serialized_cea
    def cstar_evaluator(
        self,
        engine: EngineDefinition,
        *,
        contraction_area_ratio: float,
        expansion_ratio: float | None,
        ambient_pressure_atm: float | None = None,
        equilibrium_mode: EquilibriumMode,
    ) -> Callable[[float], float]:
        """Optimize chamber C*, independent of nozzle exit and freezing mode.

        Nozzle settings are used only for Isp/expansion metadata at the optimum.
        RocketCEA get_Cstar returns SI m/s using the configured unit wrapper.
        """

        cea = self._make_cea(engine, contraction_area_ratio)
        nozzle_states: dict[float, tuple[float, float, float]] = {}

        @_serialized_cea
        def resolve_expansion_ratio(mixture_ratio: float) -> float:
            if expansion_ratio is not None:
                return float(expansion_ratio)
            if ambient_pressure_atm is None or ambient_pressure_atm < 0.0:
                raise ValueError("ambient pressure is required when expansion ratio is omitted")
            return self._resolve_expansion_ratio_with_cea(
                cea,
                engine,
                ambient_pressure_atm=ambient_pressure_atm,
                equilibrium_mode=equilibrium_mode,
                mixture_ratio=mixture_ratio,
            )

        @_serialized_cea
        def vacuum_isp(mixture_ratio: float) -> float:
            if equilibrium_mode is EquilibriumMode.FROZEN_PRESSURE and getattr(cea, "cea_obj", None) is not None:
                raise UnsupportedFlowError("Frozen-at-chamber with finite-area combustor is unsupported by this RocketCEA adapter (FAC nfz=1 gives an unverified combustion-end state). Use shifting equilibrium or frozen at throat.")
            key = float(mixture_ratio)
            if key in nozzle_states:
                return nozzle_states[key][0]
            candidate_expansion_ratio = resolve_expansion_ratio(mixture_ratio)
            arguments = {
                "Pc": engine.chamber_pressure_bar,
                "MR": mixture_ratio,
                "eps": candidate_expansion_ratio,
            }
            if equilibrium_mode is EquilibriumMode.SHIFTING:
                state = cea.get_IvacCstrTc(**arguments)  # type: ignore[attr-defined]
            else:
                frozen_method = getattr(cea, "getFrozen_IvacCstrTc", None)
                if frozen_method is None:
                    raise RuntimeError("RocketCEA wrapper does not support the requested frozen nozzle flow")
                state = frozen_method(
                    **arguments,
                    frozenAtThroat=int(equilibrium_mode is EquilibriumMode.FROZEN_AREA),
                )
            nozzle_states[key] = (float(state[0]), float(state[1]), candidate_expansion_ratio)
            return nozzle_states[key][0]

        def nozzle_cstar(mixture_ratio: float) -> float:
            vacuum_isp(mixture_ratio)
            return nozzle_states[float(mixture_ratio)][1]

        def nozzle_expansion(mixture_ratio: float) -> float:
            vacuum_isp(mixture_ratio)
            return nozzle_states[float(mixture_ratio)][2]

        @_serialized_cea
        def evaluate(mixture_ratio: float) -> float:
            return float(cea.get_Cstar(Pc=engine.chamber_pressure_bar, MR=mixture_ratio))  # type: ignore[attr-defined]

        # RPA defines its search variable as oxidizer excess coefficient,
        # alpha=(O/F)/(O/F)_stoich.  RocketCEA exposes the same stoichiometric
        # conversion.  Keep it on the evaluator so one reusable CEA object
        # serves both the conversion and every objective evaluation.
        stoichiometric_ratio: float | None = None
        ratio_method = getattr(cea, "getMRforER", None)
        if callable(ratio_method):
            try:
                candidate = float(ratio_method(ERphi=1.0))
                if isfinite(candidate) and candidate > 0.0:
                    stoichiometric_ratio = candidate
            # Stoichiometric conversion is optional metadata.  A third-party
            # wrapper error here must not discard an otherwise valid CEA C*
            # evaluator and force the entire optimization onto the fallback.
            except Exception:
                pass
        setattr(evaluate, "stoichiometric_mixture_ratio", stoichiometric_ratio)
        setattr(evaluate, "expansion_ratio_for_mixture_ratio", resolve_expansion_ratio)
        setattr(evaluate, "vacuum_isp_for_mixture_ratio", vacuum_isp)
        setattr(evaluate, "nozzle_cstar_for_mixture_ratio", nozzle_cstar)
        setattr(evaluate, "nozzle_expansion_for_mixture_ratio", nozzle_expansion)
        return evaluate

    def vacuum_isp_evaluator(
        self,
        engine: EngineDefinition,
        *,
        contraction_area_ratio: float,
        expansion_ratio: float | None,
        ambient_pressure_atm: float | None = None,
        equilibrium_mode: EquilibriumMode,
    ) -> Callable[[float], float]:
        """Theoretical vacuum Isp, with exit conditions solved for each O/F.

        Fixed exit pressure defines a different expansion ratio at each O/F.
        The objective is always vacuum Isp; no delivered losses or film are
        applied. ``cstar_evaluator`` retains its previous raw-C* contract for
        embedding callers, while the application optimizer uses this method.
        """
        chamber_evaluator = self.cstar_evaluator(
            engine, contraction_area_ratio=contraction_area_ratio,
            expansion_ratio=expansion_ratio, ambient_pressure_atm=ambient_pressure_atm,
            equilibrium_mode=equilibrium_mode,
        )
        evaluate = getattr(chamber_evaluator, "vacuum_isp_for_mixture_ratio")
        setattr(evaluate, "stoichiometric_mixture_ratio", getattr(chamber_evaluator, "stoichiometric_mixture_ratio"))
        setattr(evaluate, "expansion_ratio_for_mixture_ratio", getattr(chamber_evaluator, "nozzle_expansion_for_mixture_ratio"))
        setattr(evaluate, "cstar_for_mixture_ratio", getattr(chamber_evaluator, "nozzle_cstar_for_mixture_ratio"))
        return evaluate

    @_serialized_cea
    def calculate(
        self,
        engine: EngineDefinition,
        chamber: ThrustChamberInput,
        expansion_ratio: float,
    ) -> ThermochemicalState:
        if self._factory is None:
            raise RuntimeError(self.unavailable_reason or "RocketCEA is unavailable")
        cea = self._make_cea(engine, chamber.contraction_area_ratio)
        if chamber.equilibrium.mode is EquilibriumMode.FROZEN_PRESSURE and getattr(cea, "cea_obj", None) is not None:
            # RocketCEA 1.2.3 emits FAC nfz=1 (injector), rather than nfz=2
            # (combustion end). The resulting frozen FAC run can yield a sonic
            # or supersonic combustor and omit every requested subar station.
            raise UnsupportedFlowError("Frozen-at-chamber with finite-area combustor is unsupported by this RocketCEA adapter (FAC nfz=1 gives an unverified combustion-end state). Use shifting equilibrium or frozen at throat.")
        arguments = {
            "Pc": engine.chamber_pressure_bar,
            "MR": engine.mixture_ratio,
            "eps": expansion_ratio,
        }
        frozen = int(chamber.equilibrium.mode is not EquilibriumMode.SHIFTING)
        frozen_at_throat = int(chamber.equilibrium.mode is EquilibriumMode.FROZEN_AREA)
        selected_arguments = {**arguments, "frozen": frozen, "frozenAtThroat": frozen_at_throat}
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

        fallback = _engine_fallback_chemistry(engine)
        molecular_weight, gamma = fallback.molecular_weight_kg_kmol, fallback.gamma
        auxiliary_warnings: list[str] = []
        gamma_method = getattr(cea, "get_exit_MolWt_gamma", None)
        if gamma_method is not None:
            try:
                candidate_mw, candidate_gamma = gamma_method(**selected_arguments)
                if not isfinite(candidate_mw) or not isfinite(candidate_gamma) or candidate_mw <= 0.0 or candidate_gamma <= 1.0:
                    raise ValueError("invalid selected-model exit molecular weight or exponent")
                molecular_weight, gamma = candidate_mw, candidate_gamma
            except (TypeError, ValueError, RuntimeError):
                auxiliary_warnings.append("Selected-model exit MW/isentropic exponent unavailable; screening gas properties are used.")

        exit_pressure_bar: float
        pressure_method = getattr(cea, "get_PcOvPe", None)
        if pressure_method is not None:
            pressure_ratio = float(pressure_method(**selected_arguments))
            exit_pressure_bar = engine.chamber_pressure_bar / pressure_ratio
            raw = getattr(cea, "cea_obj", None)
            if raw is not None:
                # Pcout/Pexit in RocketCEA's FAC frozen-chamber getter can use
                # the wrong combustion-end normalization. CEA's actual static
                # exit pressure is available immediately after this query.
                with rocketcea_import_environment():
                    from rocketcea.cea_obj import py_cea
                exit_pressure_bar = float(py_cea.prtout.ppp[raw.i_exit])
        else:
            exit_mach_guess = solve_mach(expansion_ratio, float(gamma), supersonic=True)
            exit_pressure_bar = engine.chamber_pressure_bar / (
                1.0 + 0.5 * (float(gamma) - 1.0) * exit_mach_guess**2
            ) ** (float(gamma) / (float(gamma) - 1.0))

        # Geometry uses station exponents from the same selected flow model.
        # RocketCEA's *_MolWt_gamma getters return CEA GAMMAs: the isentropic
        # exponent used in a^2 = GAMMAs * R * T, not equilibrium Cp/Cv.
        # See rocketcea/cea_obj.py and py_cea.f (GAMMAs/SON VEL calculations).
        frozen = int(chamber.equilibrium.mode is not EquilibriumMode.SHIFTING)
        frozen_at_throat = int(chamber.equilibrium.mode is EquilibriumMode.FROZEN_AREA)
        flow_arguments = {
            **arguments,
            "frozen": frozen,
            "frozenAtThroat": frozen_at_throat,
        }

        def optional_flow_value(
            name: str, keywords: dict[str, float | int], *, molwt_pair: bool = False
        ) -> float | None:
            method = getattr(cea, name, None)
            if not callable(method):
                return None
            try:
                returned = method(**keywords)
                value = float(returned[1] if molwt_pair else returned)
            except Exception:
                # These getters are optional for older/custom CEA adapters.
                # An unavailable auxiliary property must not discard otherwise
                # successful performance and force all results onto fallback.
                return None
            return value if isfinite(value) and value > 1.0 else None

        actual_mach = optional_flow_value("get_MachNumber", flow_arguments)
        actual_exit_exponent = optional_flow_value(
            "get_exit_MolWt_gamma", flow_arguments, molwt_pair=True
        )
        if frozen_at_throat:
            # The throat getter has no frozenAtThroat argument: frozen=1 there
            # freezes composition in the chamber.  Evaluate the sonic exit
            # station with throat freezing to obtain the exponent immediately
            # after composition freezes at the throat.
            actual_throat_exponent = optional_flow_value(
                "get_exit_MolWt_gamma",
                {**flow_arguments, "eps": 1.0},
                molwt_pair=True,
            )
        else:
            actual_throat_exponent = optional_flow_value(
                "get_Throat_MolWt_gamma",
                {**arguments, "frozen": frozen},
                molwt_pair=True,
            )

        exit_mach = (
            actual_mach
            if actual_mach is not None
            else solve_mach(expansion_ratio, float(gamma), supersonic=True)
        )
        throat_exponent = (
            actual_throat_exponent if actual_throat_exponent is not None else float(gamma)
        )
        exit_exponent = (
            actual_exit_exponent if actual_exit_exponent is not None else float(gamma)
        )
        actual_properties = (actual_mach, actual_throat_exponent, actual_exit_exponent)
        if all(value is not None for value in actual_properties):
            nozzle_flow_source = "rocketcea"
        elif any(value is not None for value in actual_properties):
            nozzle_flow_source = "rocketcea_with_constant_gamma_fallback"
        else:
            nozzle_flow_source = "constant_gamma_estimate"
        raw_cstar = float(cstar)
        raw = getattr(cea, "cea_obj", None)
        if raw is not None:
            # CEA's FAC C* is referenced to Pinf, while the input p is Pinj.
            # App[1] is Pinj/Pinf; normalize C* so Pc*At/C* obeys continuity.
            with rocketcea_import_environment():
                from rocketcea.cea_obj import py_cea
            # Restore the selected exit query: optional throat queries may
            # have overwritten the shared FORTRAN output arrays.
            raw.setupCards(Pc=engine.chamber_pressure_bar, pc_units="bar", MR=engine.mixture_ratio,
                           eps=expansion_ratio, frozen=frozen, frozenAtThroat=frozen_at_throat)
            cstar = raw_cstar * float(py_cea.rockt.app[raw.i_chm])
            temperature = float(py_cea.prtout.ttt[raw.i_injface])
        if any(not isfinite(value) or value <= 0.0 for value in (float(cstar), float(isp_vac), float(temperature), exit_pressure_bar)):
            raise ValueError("RocketCEA returned invalid performance/pressure data")
        return ThermochemicalState(
            source="rocketcea",
            ideal_cstar_m_s=float(cstar),
            ideal_vacuum_isp_s=float(isp_vac),
            combustion_temperature_k=float(temperature),
            gamma=float(gamma),
            molecular_weight_kg_kmol=float(molecular_weight),
            exit_pressure_bar=exit_pressure_bar,
            exit_mach=exit_mach,
            throat_isentropic_exponent=throat_exponent,
            exit_isentropic_exponent=exit_exponent,
            nozzle_flow_source=nozzle_flow_source,
            warnings=freezing_model_warnings(chamber) + tuple(auxiliary_warnings),
            cea_cstar_m_s=raw_cstar if raw is not None else None,
        )

    @_serialized_cea
    def bartz_reference_properties(
        self, engine: EngineDefinition, chamber: ThrustChamberInput,
    ) -> dict[str, float]:
        """Frozen-composition transport at the chamber stagnation reference.

        This is a heat-transfer reference, independent of the selected nozzle
        equilibrium/frozen flow. CEA's equilibrium Cp includes reaction heat;
        it must not replace frozen Cp in the conventional Bartz transport
        factor. The injector-face state is the zero-velocity FAC reference.
        ``gamma`` is frozen Cp/Cv, rather than the reacting-flow GAMMAs.
        """
        cea = self._make_cea(engine, chamber.contraction_area_ratio)
        raw = getattr(cea, "cea_obj", None)
        if raw is None or not callable(getattr(raw, "setupCards", None)):
            raise RuntimeError("CEA chamber frozen transport interface is unavailable")
        with rocketcea_import_environment():
            from rocketcea.cea_obj import py_cea
        raw.setupCards(
            Pc=engine.chamber_pressure_bar, pc_units="bar", MR=engine.mixture_ratio,
            eps=1.0, frozen=0, frozenAtThroat=0, show_transport=1,
        )
        index = raw.i_injface
        cp = float(py_cea.trpts.cpfro[index]) * 4184.0
        gas_constant = UNIVERSAL_GAS_CONSTANT * float(py_cea.prtout.totn[index])
        if not isfinite(cp) or not isfinite(gas_constant) or cp <= gas_constant or gas_constant <= 0:
            raise RuntimeError("CEA returned invalid chamber frozen Cp/Cv")
        result = {
            "specific_heat_j_kgk": cp,
            "viscosity_pa_s": float(py_cea.trpts.vis[index]) * 1e-4,
            "prandtl": float(py_cea.trpts.prfro[index]),
            "gamma": cp / (cp - gas_constant),
        }
        if any(not isfinite(value) or value <= 0 for value in result.values()):
            raise RuntimeError("CEA returned invalid chamber frozen transport")
        return result

    @_serialized_cea
    def axial_station_states(
        self, engine: EngineDefinition, chamber: ThrustChamberInput,
        area_ratios: tuple[float, ...], throat_index: int,
    ) -> tuple[dict[str, float], ...]:
        """Query CEA subar/supar stations in batches, with actual gas transport.

        RocketCEA's public scalar getters expose only chamber/throat/exit.
        Its pinned 1.2.3 setupCards interface supports subar/supar lists; the
        immediately copied FORTRAN output arrays retain all those stations.
        Never retain references to the mutable FORTRAN arrays between queries.
        Pressure is bar, h/s are normalized by R*, transport Cp is cal/(g K),
        viscosity is millipoise. These conversions match RocketCEA's getters.
        """
        cea = self._make_cea(engine, chamber.contraction_area_ratio)
        raw = getattr(cea, "cea_obj", None)
        if raw is None or not callable(getattr(raw, "setupCards", None)):
            raise RuntimeError("CEA axial station interface is unavailable")
        with rocketcea_import_environment():
            from rocketcea.cea_obj import py_cea
        frozen = int(chamber.equilibrium.mode is not EquilibriumMode.SHIFTING)
        at_throat = int(chamber.equilibrium.mode is EquilibriumMode.FROZEN_AREA)
        output: list[dict[str, float] | None] = [None] * len(area_ratios)

        def extract(index: int, use_frozen_transport: bool) -> dict[str, float]:
            mw = float(1.0 / py_cea.prtout.totn[index])
            temperature = float(py_cea.prtout.ttt[index])
            pressure = float(py_cea.prtout.ppp[index]) * BAR_PA
            gamma = float(py_cea.prtout.gammas[index])
            cp_array = py_cea.trpts.cpfro if use_frozen_transport else py_cea.trpts.cpeql
            pr_array = py_cea.trpts.prfro if use_frozen_transport else py_cea.trpts.preql
            result = {
                "pressure_pa": pressure, "temperature_k": temperature,
                "enthalpy_j_kg": float(py_cea.prtout.hsum[index]) * 8314.51,
                "entropy_j_kgk": float(py_cea.prtout.ssum[index]) * 8314.51,
                "specific_heat_j_kgk": float(cp_array[index]) * 4184.0,
                "gamma": gamma, "gas_constant_j_kgk": UNIVERSAL_GAS_CONSTANT / mw,
                "density_kg_m3": pressure / ((UNIVERSAL_GAS_CONSTANT / mw) * temperature),
                "sonic_velocity_m_s": float(py_cea.rockt.sonvel[index]),
                "mach": float(py_cea.rockt.vmoc[index]),
                "viscosity_pa_s": float(py_cea.trpts.vis[index]) * 1e-4,
                "prandtl": float(pr_array[index]),
            }
            composition_index = (raw.i_thrt if at_throat else raw.i_injface) if use_frozen_transport else index
            for species_name, output_name in (("H2O", "h2o_mole_fraction"), ("CO2", "co2_mole_fraction")):
                fraction = 0.0
                for species_index in range(int(py_cea.indx.ngc)):
                    name = py_cea.cdata.prod[species_index].decode("utf-8").strip().lstrip("*")
                    if name == species_name:
                        fraction = float(py_cea.comp.en[species_index - 1, composition_index] / py_cea.prtout.totn[composition_index])
                        break
                result[output_name] = max(0.0, min(1.0, fraction))
            if any(not isfinite(value) for value in result.values()) or any(result[name] <= 0 for name in ("pressure_pa", "temperature_k", "specific_heat_j_kgk", "density_kg_m3", "sonic_velocity_m_s", "viscosity_pa_s", "prandtl")):
                raise RuntimeError("CEA returned invalid axial thermodynamic/transport data")
            return result

        # A constant-area combustor is represented by the combustion-end state;
        # this model does not resolve the injector's heat-release zone.
        raw.setupCards(Pc=engine.chamber_pressure_bar, pc_units="bar", MR=engine.mixture_ratio,
                       eps=1.0, frozen=frozen, frozenAtThroat=at_throat, show_transport=1)
        chamber_row = extract(raw.i_chm, bool(frozen and not at_throat))
        throat_row = extract(raw.i_thrt, bool(frozen))
        for position, area_ratio in enumerate(area_ratios):
            if position == throat_index:
                output[position] = throat_row.copy()
            elif position < throat_index and abs(area_ratio / chamber.contraction_area_ratio - 1.0) < 1e-8:
                output[position] = chamber_row.copy()

        for supersonic in (False, True):
            indices = [i for i, row in enumerate(output) if row is None and (i > throat_index) == supersonic]
            # This wheel has eight output slots and overwrites earlier pages
            # on longer queries. Discover capacity and reserve the sonic exit.
            batch_size = max(1, len(py_cea.rockt.aeat) - raw.i_thrt - 2)
            for start in range(0, len(indices), batch_size):
                batch = indices[start:start + batch_size]
                ratios = [area_ratios[i] for i in batch]
                options = {"eps": ratios} if supersonic else {"subar": ratios, "eps": 1.0}
                raw.setupCards(Pc=engine.chamber_pressure_bar, pc_units="bar", MR=engine.mixture_ratio,
                               frozen=frozen, frozenAtThroat=at_throat, show_transport=1, **options)
                first = raw.i_thrt + 1
                for offset, target in enumerate(batch):
                    observed_area = float(py_cea.rockt.aeat[first + offset])
                    if abs(observed_area / area_ratios[target] - 1.0) > 2e-5:
                        raise RuntimeError(f"CEA omitted or reordered axial station {target}: requested A/At={area_ratios[target]:.9g}, observed {observed_area:.9g}, batch offset={offset}")
                    output[target] = extract(first + offset, bool(frozen and (not at_throat or supersonic)))
        return tuple(row for row in output if row is not None)


def freezing_model_warnings(chamber: ThrustChamberInput) -> tuple[str, ...]:
    mode = chamber.equilibrium.mode
    if mode is EquilibriumMode.SHIFTING:
        return ()
    if mode is EquilibriumMode.FROZEN_AREA and chamber.equilibrium.freeze_area_ratio == 1.0:
        return ()
    requested = (chamber.equilibrium.freeze_pressure_ratio if mode is EquilibriumMode.FROZEN_PRESSURE
                 else chamber.equilibrium.freeze_area_ratio)
    applied = "chamber" if mode is EquilibriumMode.FROZEN_PRESSURE else "throat (A/At=1)"
    return (f"Frozen flow uses composition frozen in the {applied}. Requested freezing criterion {requested:g} is unsupported by RocketCEA and is not applied; arbitrary freezing positions require a different solver.",)


def _engine_fallback_chemistry(engine: EngineDefinition, mixture_ratio: float | None = None):
    return fallback_chemistry(
        engine.oxidizer, engine.fuel,
        engine.mixture_ratio if mixture_ratio is None else mixture_ratio,
        engine.oxidizer_mass_fraction, engine.fuel_mass_fraction,
    )


def _engine_propellant_specs(engine: EngineDefinition):
    return propellant_specs(
        engine.oxidizer, engine.fuel, engine.oxidizer_mass_fraction, engine.fuel_mass_fraction,
        oxidizer_temperature_k=getattr(engine, "oxidizer_temperature_k", None),
        fuel_temperature_k=getattr(engine, "fuel_temperature_k", None),
        oxidizer_pressure_bar=getattr(engine, "oxidizer_pressure_bar", None),
        fuel_pressure_bar=getattr(engine, "fuel_pressure_bar", None),
    )


def _fallback_state(
    engine: EngineDefinition,
    chamber: ThrustChamberInput,
    expansion_ratio: float,
    warning: str | None = None,
) -> ThermochemicalState:
    chemistry = _engine_fallback_chemistry(engine)
    gamma = chemistry.gamma
    gas_constant = UNIVERSAL_GAS_CONSTANT / chemistry.molecular_weight_kg_kmol
    # A constant-composition perfect gas has no shifting-versus-frozen
    # chemistry. Do not manufacture a frozen loss with an arbitrary factor.
    temperature = chemistry.flame_temperature_k
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
        or "RocketCEA is not installed; unvalidated ideal-gas screening estimates are shown",
    ) + freezing_model_warnings(chamber) + (("Constant-gas fallback cannot model equilibrium composition changes or a freezing location; no invented frozen-performance correction is applied.",) if chamber.equilibrium.mode is not EquilibriumMode.SHIFTING else ())
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
        throat_isentropic_exponent=gamma,
        exit_isentropic_exponent=gamma,
        nozzle_flow_source="ideal_gas_constant_gamma",
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
    """Find O/F maximizing theoretical vacuum Isp for the configured nozzle.

    Each candidate uses the supplied reactant states, finite contraction ratio
    and shifting/frozen flow model. With assigned Pe, its Ae/At is solved anew
    at every O/F; vacuum Isp remains the objective even when Pe is specified.
    Delivered efficiencies and film losses are excluded. O/F includes water.
    """

    _engine_propellant_specs(engine)
    lower, upper = (float(bounds[0]), float(bounds[1]))
    if not (isfinite(lower) and isfinite(upper) and 0 < lower < upper):
        raise ValueError("mixture-ratio bounds must be finite, positive, and increasing")
    if not isfinite(contraction_area_ratio) or contraction_area_ratio <= 1.0:
        raise ValueError("contraction area ratio must be greater than 1")
    if isinstance(equilibrium_mode, EquilibriumMode):
        mode = equilibrium_mode
    else:
        mode = EquilibriumMode(str(equilibrium_mode))

    configured_expansion_ratio = expansion_ratio
    if configured_expansion_ratio is None:
        if ambient_pressure_atm is None or not isfinite(ambient_pressure_atm):
            raise ValueError("ambient pressure is required when expansion ratio is omitted")
        if ambient_pressure_atm < 0:
            raise ValueError("ambient pressure must be non-negative")
    else:
        configured_expansion_ratio = float(configured_expansion_ratio)
    if configured_expansion_ratio is not None and (
        not isfinite(configured_expansion_ratio) or configured_expansion_ratio <= 1.0
    ):
        raise ValueError("expansion ratio must be finite and greater than 1")

    def fallback_expansion_ratio(mixture_ratio: float) -> float:
        if configured_expansion_ratio is not None:
            return configured_expansion_ratio
        chemistry = _engine_fallback_chemistry(engine, mixture_ratio)
        return expansion_ratio_for_pressure(
            engine.chamber_pressure_bar * BAR_PA,
            float(ambient_pressure_atm) * ATM_PA,
            chemistry.gamma,
        )

    # The constant-gas chamber is only a fallback calculation context. Do not
    # pre-screen CEA's pressure-defined nozzle using an unrelated fallback
    # gamma or the initial (possibly nonoptimal) O/F. Each candidate resolves
    # its actual area ratio in its own backend below.
    reference_expansion_ratio = configured_expansion_ratio if configured_expansion_ratio is not None else 4.0

    flow = EquilibriumFlow(
        mode=mode,
        freeze_pressure_ratio=10.0 if mode is EquilibriumMode.FROZEN_PRESSURE else None,
        freeze_area_ratio=1.0 if mode is EquilibriumMode.FROZEN_AREA else None,
    )
    reference_chamber = ThrustChamberInput(
        contraction_area_ratio=contraction_area_ratio,
        exit_condition=NozzleExitCondition(
            mode=ExitConditionMode.EXPANSION_RATIO,
            expansion_area_ratio=reference_expansion_ratio,
            ambient_pressure_atm=None,
        ),
        equilibrium=EquilibriumFlow(),
    )

    def fallback_objective(mixture_ratio: float) -> float:
        candidate = replace(engine, mixture_ratio=mixture_ratio)
        candidate_expansion_ratio = fallback_expansion_ratio(mixture_ratio)
        return _fallback_state(
            candidate,
            reference_chamber,
            candidate_expansion_ratio,
        ).ideal_vacuum_isp_s

    errors: list[str] = []

    def maximize(
        evaluator: Callable[[float], float],
        stoichiometric_ratio: float | None = None,
    ) -> tuple[float, float, bool]:
        cache: dict[float, float] = {}

        def safe_value(mixture_ratio: float) -> float:
            key = round(float(mixture_ratio), 12)
            if key in cache:
                return cache[key]
            try:
                value = float(evaluator(float(mixture_ratio)))
                if not isfinite(value) or value <= 0.0:
                    raise ValueError(f"invalid vacuum specific impulse {value!r}")
            except UnsupportedFlowError:
                raise
            except Exception as error:  # RocketCEA exposes several wrapper errors.
                if len(errors) < 3:
                    errors.append(str(error))
                value = float("-inf")
            cache[key] = value
            return value

        use_alpha = (
            stoichiometric_ratio is not None
            and isfinite(stoichiometric_ratio)
            and stoichiometric_ratio > 0.0
        )
        scale = float(stoichiometric_ratio) if use_alpha else 1.0
        coordinate_lower = lower / scale
        coordinate_upper = upper / scale

        def mixture_ratio(coordinate: float) -> float:
            return coordinate * scale

        sample_count = 49
        samples = [
            coordinate_lower
            + (coordinate_upper - coordinate_lower) * index / (sample_count - 1)
            for index in range(sample_count)
        ]
        values = [safe_value(mixture_ratio(item)) for item in samples]
        valid_indices = [index for index, value in enumerate(values) if isfinite(value)]
        if not valid_indices:
                raise RuntimeError(errors[0] if errors else "vacuum specific impulse could not be evaluated")
        best_index = max(valid_indices, key=lambda index: values[index])
        left = samples[max(0, best_index - 1)]
        right = samples[min(sample_count - 1, best_index + 1)]

        # Golden-section maximization inside the best coarse interval.
        inverse_phi = (sqrt(5.0) - 1.0) / 2.0
        x1 = right - inverse_phi * (right - left)
        x2 = left + inverse_phi * (right - left)
        f1, f2 = safe_value(mixture_ratio(x1)), safe_value(mixture_ratio(x2))
        for _ in range(30):
            if f1 < f2:
                left, x1, f1 = x1, x2, f2
                x2 = left + inverse_phi * (right - left)
                f2 = safe_value(mixture_ratio(x2))
            else:
                right, x2, f2 = x2, x1, f1
                x1 = right - inverse_phi * (right - left)
                f1 = safe_value(mixture_ratio(x1))

        candidates = [(ratio, value) for ratio, value in cache.items() if isfinite(value)]
        optimum_ratio, optimum_value = max(candidates, key=lambda item: item[1])
        bound_tolerance = max(1.0e-9, (upper - lower) * 1.0e-7)
        at_bound = (
            abs(optimum_ratio - lower) <= bound_tolerance
            or abs(optimum_ratio - upper) <= bound_tolerance
        )
        return optimum_ratio, optimum_value, at_bound

    adapter = cea_adapter
    if adapter is None and prefer_rocketcea:
        adapter = RocketCEAAdapter()
    warning: str | None = None
    source = "ideal-gas-fallback"
    stoichiometric_ratio: float | None = None
    expansion_resolver: Callable[[float], float] | None = None
    cstar_resolver: Callable[[float], float] | None = None
    if prefer_rocketcea and adapter is not None and adapter.available:
        try:
            cea_objective = adapter.vacuum_isp_evaluator(
                engine,
                contraction_area_ratio=contraction_area_ratio,
                expansion_ratio=configured_expansion_ratio,
                ambient_pressure_atm=ambient_pressure_atm,
                equilibrium_mode=mode,
            )
            stoichiometric_ratio = getattr(
                cea_objective,
                "stoichiometric_mixture_ratio",
                None,
            )
            expansion_resolver = getattr(
                cea_objective,
                "expansion_ratio_for_mixture_ratio",
                None,
            )
            cstar_resolver = getattr(cea_objective, "cstar_for_mixture_ratio", None)
            ratio, isp, at_bound = maximize(cea_objective, stoichiometric_ratio)
            source = "rocketcea"
        except UnsupportedFlowError:
            raise
        except Exception as error:
            errors.clear()
            ratio, isp, at_bound = maximize(fallback_objective)
            stoichiometric_ratio = None
            warning = f"RocketCEA vacuum-Isp O/F optimization failed ({error}); unvalidated ideal-gas screening optimum is used"
    else:
        ratio, isp, at_bound = maximize(fallback_objective)
        if prefer_rocketcea:
            detail = adapter.unavailable_reason if adapter is not None else "RocketCEA is unavailable"
            warning = f"{detail}; unvalidated ideal-gas vacuum-Isp screening optimum is used"
    objective = "maximum theoretical vacuum specific impulse"
    if source != "rocketcea":
        objective = "maximum ideal-gas vacuum specific impulse (unvalidated screening)"
        note = "Ideal-gas O/F screening cannot model equilibrium/frozen chemistry or supply-state enthalpy; its optimum is not a validated CEA/RPA result."
        warning = f"{warning}; {note}" if warning else note
    elif errors:
        warning = f"Some O/F candidates could not be evaluated ({errors[0]}); the maximum compares only evaluable candidates."
    if configured_expansion_ratio is None and ambient_pressure_atm == 0:
        note = "A zero assigned exit pressure has no finite nozzle area; the finite-area limit of this backend is used for vacuum-Isp screening."
        warning = f"{warning}; {note}" if warning else note
    if at_bound:
        bound_note = f"optimum reached the configured O/F bound [{lower:g}, {upper:g}]"
        warning = f"{warning}; {bound_note}" if warning else bound_note
    cstar: float | None = None
    if source == "rocketcea":
        try:
            optimum_expansion_ratio = float(expansion_resolver(ratio)) if callable(expansion_resolver) else float(configured_expansion_ratio)
        except Exception as error:
            # A valid objective survives failure of optional report metadata.
            optimum_expansion_ratio = float("nan")
            note = f"Vacuum Isp optimized, but exit-area metadata could not be evaluated ({error})"
            warning = f"{warning}; {note}" if warning else note
        if callable(cstar_resolver):
            try:
                cstar = float(cstar_resolver(ratio))
                if not isfinite(cstar) or cstar <= 0:
                    raise ValueError(f"invalid C* metadata {cstar!r}")
            except Exception as error:
                cstar = None
                note = f"Vacuum Isp optimized, but reference C* metadata is unavailable ({error})"
                warning = f"{warning}; {note}" if warning else note
    else:
        optimum_expansion_ratio = fallback_expansion_ratio(ratio)
        cstar = _fallback_state(
            replace(engine, mixture_ratio=ratio), replace(reference_chamber, equilibrium=flow),
            optimum_expansion_ratio,
        ).ideal_cstar_m_s
    return MixtureRatioOptimum(
        mixture_ratio=ratio,
        vacuum_isp_s=isp,
        expansion_ratio=optimum_expansion_ratio,
        source=source,
        objective=objective,
        ideal_cstar_m_s=cstar,
        warning=warning,
        stoichiometric_mixture_ratio=stoichiometric_ratio,
        oxidizer_excess_coefficient=(
            ratio / stoichiometric_ratio
            if stoichiometric_ratio is not None and stoichiometric_ratio > 0.0
            else None
        ),
    )


def _estimated_nozzle_efficiency(chamber: ThrustChamberInput) -> float:
    if chamber.nozzle.contour_type is NozzleContourType.CONICAL:
        divergence = 0.5 * (1.0 + cos(radians(chamber.nozzle.conical_half_angle_deg)))
        # Efficiency is a kinetic-energy ratio; divergence is a momentum ratio.
        return (0.985 * divergence) ** 2
    length_fraction = chamber.nozzle.bell_length_percent / 100.0
    return max(0.94, min(0.995, 0.982 + 0.015 * (length_fraction - 0.7)))


def nozzle_regime(chamber_pressure_pa: float, exit_pressure_pa: float, ambient_pa: float,
                  gamma: float) -> str:
    """Validity screen for attached supersonic flow, not a separation solution.

    The Kalt/Badal incipient-separation criterion is also used by RocketCEA.
    It cannot establish bell-nozzle side loads or the separated thrust.
    """
    if ambient_pa == 0.0:
        return "attached_vacuum"
    sonic_pressure = chamber_pressure_pa / ((gamma + 1.0) / 2.0) ** (gamma / (gamma - 1.0))
    if ambient_pa >= sonic_pressure:
        return "unsupported_choking_or_internal_shock"
    incipient_pressure = (2.0 / 3.0) * (chamber_pressure_pa / ambient_pa) ** (-0.2) * ambient_pa
    if exit_pressure_pa <= incipient_pressure:
        return "unsupported_separated"
    return "attached_underexpanded" if exit_pressure_pa >= ambient_pa else "attached_overexpanded"


def _regime_warning(label: str, regime: str) -> tuple[str, ...]:
    if not regime.startswith("unsupported"):
        return ()
    return (f"{label} performance unavailable: {regime.replace('_', ' ')}. The attached supersonic model is outside its validity range; NaN denotes unavailable performance, not zero thrust.",)


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
    gamma: float = 1.2,
) -> DeliveredPerformance:
    pe_pc = exit_pressure_pa / chamber_pressure_pa
    momentum_cf = ideal_vacuum_cf - pe_pc * expansion_ratio
    delivered_momentum_cf = max(0.0, momentum_cf) * sqrt(nozzle_efficiency)

    def cf(ambient_pa: float) -> float:
        if nozzle_regime(chamber_pressure_pa, exit_pressure_pa, ambient_pa, gamma).startswith("unsupported"):
            return nan
        pressure_cf = (exit_pressure_pa - ambient_pa) / chamber_pressure_pa * expansion_ratio
        coefficient = delivered_momentum_cf * thrust_multiplier + pressure_cf
        return coefficient if coefficient > 0.0 else nan

    cf_design = cf(design_ambient_pressure_atm * ATM_PA)
    cf_sea = cf(ATM_PA)
    cf_optimum = cf(exit_pressure_pa)
    cf_vacuum = cf(0.0)

    def pair(coefficient: float) -> tuple[float, float]:
        base_thrust = chamber_pressure_pa * throat_area_m2 * coefficient
        thrust = base_thrust
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


def performance_at_ambient_pressure(
    baseline: PerformanceResult,
    ambient_pressure_atm: float,
) -> PerformanceResult:
    """Re-evaluate fixed hardware at a new back pressure without rerunning CEA."""

    ambient = float(ambient_pressure_atm)
    if not isfinite(ambient) or ambient < 0.0:
        raise ValueError("ambient pressure must be finite and non-negative")
    pc_pa = baseline.chamber_pressure_bar * BAR_PA
    pe_pa = baseline.exit_pressure_bar * BAR_PA
    pressure_cf = pe_pa / pc_pa * baseline.expansion_ratio
    delivered_vacuum_cf = baseline.without_film.thrust_vacuum_n / (
        pc_pa * baseline.throat_area_m2
    )
    delivered_momentum_cf = max(0.0, delivered_vacuum_cf - pressure_cf)
    ideal_momentum_cf = delivered_momentum_cf / sqrt(baseline.nozzle_efficiency)
    ideal_vacuum_cf = ideal_momentum_cf + pressure_cf
    film_multiplier = 1.0 + baseline.film_blc_recovery * baseline.film_mass_flow_kg_s / baseline.hot_gas_mass_flow_kg_s
    without_film = _metric_set(
        baseline.throat_area_m2,
        pc_pa,
        baseline.hot_gas_mass_flow_kg_s,
        baseline.hot_gas_mass_flow_kg_s,
        baseline.expansion_ratio,
        pe_pa,
        ideal_vacuum_cf,
        baseline.delivered_cstar_m_s,
        baseline.nozzle_efficiency,
        ambient,
        gamma=baseline.throat_isentropic_exponent or baseline.gamma,
    )
    with_film = _metric_set(
        baseline.throat_area_m2,
        pc_pa,
        baseline.hot_gas_mass_flow_kg_s,
        baseline.total_mass_flow_kg_s,
        baseline.expansion_ratio,
        pe_pa,
        ideal_vacuum_cf,
        baseline.delivered_cstar_m_s,
        baseline.nozzle_efficiency,
        ambient,
        thrust_multiplier=film_multiplier,
        gamma=baseline.throat_isentropic_exponent or baseline.gamma,
    )
    regime = nozzle_regime(pc_pa, pe_pa, ambient * ATM_PA, baseline.throat_isentropic_exponent or baseline.gamma)
    return replace(
        baseline,
        design_ambient_pressure_atm=ambient,
        without_film=without_film,
        with_film=with_film,
        design_nozzle_regime=regime,
        warnings=tuple(dict.fromkeys(tuple(w for w in baseline.warnings if not w.startswith("Design ambient performance unavailable:")) + _regime_warning("Design ambient", regime))),
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
    # Supply-state validation is an input check, not a CEA failure. It must
    # not be swallowed by the optional numerical-backend fallback below.
    supply_specs = _engine_propellant_specs(engine)
    supply_warnings = tuple(warning for spec in supply_specs for warning in spec.warnings)

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
            resolved = chamber.resolved_contraction_area_ratio(result.throat_diameter_mm)
            if abs(resolved / ratio - 1.0) > 1e-6:
                raise RuntimeError("Direct chamber-diameter/nominal-thrust sizing did not converge to a consistent contraction ratio")
            return replace(
                result,
                contraction_area_ratio=resolved,
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
    if ambient_pressure_atm is None or not isfinite(ambient_pressure_atm) or ambient_pressure_atm < 0:
        raise ValueError("ambient pressure must be finite and non-negative")
    if not 0 <= film_blc_recovery <= 1:
        raise ValueError("film BLC recovery must be between 0 and 1")
    if film_mass_fraction is None:
        film_mass_fraction = inputs.thermal.film_mass_fraction
    if not 0 <= film_mass_fraction < 1:
        raise ValueError("film mass fraction must be in [0, 1)")

    fallback = _engine_fallback_chemistry(engine)
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
    if expansion_ratio is None or not isfinite(expansion_ratio) or expansion_ratio <= 1:
        raise ValueError("expansion ratio must be finite and greater than 1")

    adapter = cea_adapter
    if adapter is None and (prefer_rocketcea or require_rocketcea):
        adapter = RocketCEAAdapter()
    state: ThermochemicalState
    if (prefer_rocketcea or require_rocketcea) and adapter is not None and adapter.available:
        try:
            resolved_with_cea = False
            if (
                fixed_expansion_ratio is None
                and chamber.exit_condition.mode is ExitConditionMode.AMBIENT_PRESSURE
            ):
                try:
                    expansion_ratio = adapter.expansion_ratio_for_exit_pressure(
                        engine,
                        contraction_area_ratio=chamber.contraction_area_ratio,
                        ambient_pressure_atm=float(
                            chamber.exit_condition.ambient_pressure_atm
                        ),
                        equilibrium_mode=chamber.equilibrium.mode,
                    )
                    resolved_with_cea = True
                except Exception:
                    # Compatibility path for older/custom CEA wrappers that do
                    # not expose get_eps_at_PcOvPe: retain the gamma iteration.
                    pass
            state = adapter.calculate(engine, chamber, expansion_ratio)
            if (
                fixed_expansion_ratio is None
                and chamber.exit_condition.mode is ExitConditionMode.AMBIENT_PRESSURE
                and not resolved_with_cea
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
            if isinstance(error, UnsupportedFlowError):
                raise
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
            f"{detail}; unvalidated ideal-gas screening estimates are shown",
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
    regime_gamma = state.throat_isentropic_exponent or state.gamma

    def design_cf(atmospheres: float) -> float:
        regime = nozzle_regime(pc_pa, pe_pa, atmospheres * ATM_PA, regime_gamma)
        if regime.startswith("unsupported"):
            raise ValueError(f"nominal-thrust sizing requires attached supersonic flow; {regime}. Choose another sizing ambient/expansion ratio or specify throat hardware.")
        value = delivered_momentum_cf * film_thrust_multiplier + (pe_pa - atmospheres * ATM_PA) / pc_pa * expansion_ratio
        if not isfinite(value) or value <= 0.0:
            raise ValueError("nominal-thrust sizing has no positive valid thrust coefficient")
        return value

    film_thrust_multiplier = 1.0 + film_blc_recovery * film_mass_fraction / max(
        1e-12, 1.0 - film_mass_fraction
    )
    if fixed_throat_area_m2 is not None:
        if not isfinite(fixed_throat_area_m2) or fixed_throat_area_m2 <= 0:
            raise ValueError("fixed throat area must be positive")
        throat_area = fixed_throat_area_m2
    elif chamber.size.mode is SizeMode.THROAT_DIAMETER:
        diameter_m = chamber.size.throat_diameter_mm / 1000.0
        throat_area = pi * diameter_m**2 / 4.0
    else:
        sizing_cf = design_cf(chamber.size.thrust_ambient_pressure_atm)
        throat_area = chamber.size.nominal_thrust_n / (
            pc_pa * sizing_cf
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
        gamma=regime_gamma,
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
        gamma=regime_gamma,
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
        combustion_temperature_k=state.combustion_temperature_k * reaction_efficiency**2,
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
        warnings=tuple(dict.fromkeys(state.warnings + supply_warnings
            + _regime_warning("Design ambient", nozzle_regime(pc_pa, pe_pa, ambient_pressure_atm * ATM_PA, regime_gamma))
            + _regime_warning("Sea level", nozzle_regime(pc_pa, pe_pa, ATM_PA, regime_gamma))
            + (("Reaction efficiency is C* efficiency. Gas temperatures use an eta(C*) squared calorically-perfect screening closure; this does not recalculate imperfect-combustion chemistry.",) if reaction_efficiency != 1.0 else ()))),
        exit_mach=state.exit_mach,
        throat_isentropic_exponent=state.throat_isentropic_exponent,
        exit_isentropic_exponent=state.exit_isentropic_exponent,
        nozzle_flow_source=state.nozzle_flow_source,
        design_nozzle_regime=nozzle_regime(pc_pa, pe_pa, ambient_pressure_atm * ATM_PA, regime_gamma),
        sea_level_nozzle_regime=nozzle_regime(pc_pa, pe_pa, ATM_PA, regime_gamma),
        cea_cstar_m_s=state.cea_cstar_m_s,
        pressure_reference=state.pressure_reference,
    )


def optimize_mixture_ratio_for_inputs(
    inputs: AnalysisInput,
    *,
    bounds: tuple[float, float] = (0.10, 30.0),
    prefer_rocketcea: bool = True,
    cea_adapter: RocketCEAAdapter | None = None,
) -> MixtureRatioOptimum:
    """Optimize O/F while resolving a direct-``Dc`` sizing dependency.

    With nominal-thrust sizing, ``Dc`` and ``Ac/At`` are coupled through the
    throat area.  Repeating the O/F search at the newly resolved ``Ac/At``
    prevents a hidden, inactive area-ratio field from influencing the result.
    """

    engine = inputs.engine
    chamber = inputs.thrust_chamber
    if chamber.exit_condition.mode is ExitConditionMode.EXPANSION_RATIO:
        expansion_ratio = chamber.exit_condition.expansion_area_ratio
        ambient_pressure_atm = None
    else:
        expansion_ratio = None
        ambient_pressure_atm = chamber.exit_condition.ambient_pressure_atm

    coupled_dc_sizing = (
        chamber.contraction_mode is ContractionDefinitionMode.CHAMBER_DIAMETER
        and chamber.size.mode is SizeMode.NOMINAL_THRUST
    )
    if chamber.contraction_mode is ContractionDefinitionMode.CHAMBER_DIAMETER:
        if chamber.size.mode is SizeMode.THROAT_DIAMETER:
            contraction_ratio = chamber.resolved_contraction_area_ratio(
                float(chamber.size.throat_diameter_mm)
            )
        else:
            contraction_ratio = (
                float(chamber.contraction_area_ratio)
                if isfinite(chamber.contraction_area_ratio)
                and chamber.contraction_area_ratio > 1.0
                else 4.0
            )
    else:
        contraction_ratio = chamber.contraction_area_ratio

    adapter = cea_adapter
    if adapter is None and prefer_rocketcea:
        adapter = RocketCEAAdapter()

    optimum: MixtureRatioOptimum | None = None
    for _iteration in range(8 if coupled_dc_sizing else 1):
        optimum = optimize_mixture_ratio(
            engine,
            contraction_area_ratio=contraction_ratio,
            expansion_ratio=expansion_ratio,
            ambient_pressure_atm=ambient_pressure_atm,
            equilibrium_mode=chamber.equilibrium.mode,
            bounds=bounds,
            prefer_rocketcea=prefer_rocketcea,
            cea_adapter=adapter,
        )
        if not coupled_dc_sizing:
            return optimum

        candidate_inputs = replace(
            inputs,
            engine=replace(engine, mixture_ratio=optimum.mixture_ratio),
        )
        sized = evaluate_performance(
            candidate_inputs,
            prefer_rocketcea=prefer_rocketcea,
            cea_adapter=adapter,
        )
        resolved_ratio = sized.contraction_area_ratio
        if abs(resolved_ratio / contraction_ratio - 1.0) <= 1.0e-6:
            return optimum
        contraction_ratio = resolved_ratio

    # Re-evaluate once at the latest coupled ratio so the returned objective
    # never belongs to the preceding iterate.
    final_optimum = optimize_mixture_ratio(
        engine,
        contraction_area_ratio=contraction_ratio,
        expansion_ratio=expansion_ratio,
        ambient_pressure_atm=ambient_pressure_atm,
        equilibrium_mode=chamber.equilibrium.mode,
        bounds=bounds,
        prefer_rocketcea=prefer_rocketcea,
        cea_adapter=adapter,
    )
    final_sized = evaluate_performance(
        replace(inputs, engine=replace(engine, mixture_ratio=final_optimum.mixture_ratio)),
        prefer_rocketcea=prefer_rocketcea, cea_adapter=adapter,
    )
    if abs(final_sized.contraction_area_ratio / contraction_ratio - 1.0) > 1e-6:
        note = "Automatic O/F/direct chamber-diameter coupling reached its iteration limit without convergence"
        return replace(final_optimum, warning=f"{final_optimum.warning}; {note}" if final_optimum.warning else note)
    return final_optimum
