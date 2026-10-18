from __future__ import annotations

from math import isfinite

import pytest

from lpa.core._numerics import solve_mach
from lpa.core.models import (
    AnalysisInput,
    EngineDefinition,
    EquilibriumFlow,
    NozzleExitCondition,
    ThrustChamberInput,
)
from lpa.core.performance import RocketCEAAdapter, evaluate_performance


def _chamber(mode: str) -> ThrustChamberInput:
    freeze_options = {
        "shifting": {},
        "frozen_pressure": {"freeze_pressure_ratio": 5.0},
        "frozen_area": {"freeze_area_ratio": 1.0},
    }[mode]
    return ThrustChamberInput(
        equilibrium=EquilibriumFlow(mode=mode, **freeze_options),
        exit_condition=NozzleExitCondition(
            mode="expansion_ratio", expansion_area_ratio=14.0, ambient_pressure_atm=None
        ),
    )


@pytest.mark.parametrize(
    ("mode", "frozen", "frozen_at_throat", "expected_throat_exponent"),
    (
        ("shifting", 0, 0, 1.14),
        ("frozen_pressure", 1, 0, 1.21),
        ("frozen_area", 1, 1, 1.23),
    ),
)
def test_cea_flow_properties_follow_freezing_model_and_reach_performance_result(
    mode: str, frozen: int, frozen_at_throat: int, expected_throat_exponent: float
) -> None:
    calls: list[tuple[str, dict[str, float | int]]] = []
    factory_calls: list[dict[str, object]] = []

    class FlowCEA:
        def get_IvacCstrTc(self, **_kwargs):
            return 330.0, 1810.0, 3500.0

        def getFrozen_IvacCstrTc(self, **_kwargs):
            return 320.0, 1810.0, 3500.0

        def get_PcOvPe(self, **_kwargs):
            return 50.0

        def get_exit_MolWt_gamma(self, **kwargs):
            calls.append(("exit", kwargs))
            if "frozen" not in kwargs:
                # The existing reported gamma remains independent of the new
                # flow-model-specific exponents used by nozzle construction.
                return 22.0, 1.22
            return 22.0, 1.23 if kwargs["eps"] == 1.0 else 1.19

        def get_Throat_MolWt_gamma(self, **kwargs):
            calls.append(("throat", kwargs))
            assert "frozenAtThroat" not in kwargs
            return 22.0, 1.21 if kwargs["frozen"] else 1.14

        def get_MachNumber(self, **kwargs):
            calls.append(("mach", kwargs))
            return 3.7

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return FlowCEA()

    inputs = AnalysisInput(thrust_chamber=_chamber(mode))
    result = evaluate_performance(inputs, cea_adapter=RocketCEAAdapter(factory))

    assert factory_calls[0]["fac_CR"] == inputs.thrust_chamber.contraction_area_ratio
    assert result.exit_mach == 3.7
    assert result.throat_isentropic_exponent == expected_throat_exponent
    assert result.exit_isentropic_exponent == 1.19
    assert result.gamma == 1.19
    assert result.nozzle_flow_source == "rocketcea"
    flow_flags = {"frozen": frozen, "frozenAtThroat": frozen_at_throat}
    for name, arguments in calls:
        if name == "mach" or (name == "exit" and "frozen" in arguments):
            assert {key: arguments[key] for key in flow_flags} == flow_flags
            assert arguments["Pc"] == inputs.engine.chamber_pressure_bar
            assert arguments["MR"] == inputs.engine.mixture_ratio
    if mode == "frozen_area":
        assert not any(name == "throat" for name, _ in calls)
        assert any(name == "exit" and arguments["eps"] == 1.0 for name, arguments in calls)
    else:
        assert ("throat", {
            "Pc": inputs.engine.chamber_pressure_bar,
            "MR": inputs.engine.mixture_ratio,
            "eps": 14.0,
            "frozen": frozen,
        }) in calls


def test_optional_cea_flow_getters_degrade_without_discarding_performance() -> None:
    class LegacyCEA:
        def get_IvacCstrTc(self, **_kwargs):
            return 330.0, 1810.0, 3500.0

        def getFrozen_IvacCstrTc(self, **_kwargs):
            return 320.0, 1810.0, 3500.0

        # This older adapter accepts no frozen/frozenAtThroat keywords.
        def get_exit_MolWt_gamma(self, Pc, MR, eps):
            return 22.0, 1.22

        def get_PcOvPe(self, **_kwargs):
            return 50.0

    class InvalidFlowCEA(LegacyCEA):
        def get_MachNumber(self, **_kwargs):
            return float("nan")

        def get_Throat_MolWt_gamma(self, **_kwargs):
            raise RuntimeError("auxiliary throat calculation is unavailable")

        def get_exit_MolWt_gamma(self, **kwargs):
            return (22.0, float("inf")) if "frozen" in kwargs else (22.0, 1.22)

    class PartialFlowCEA(InvalidFlowCEA):
        def get_MachNumber(self, **_kwargs):
            return 3.6

    for cea_class, expected_mach, expected_source in (
        (LegacyCEA, None, "constant_gamma_estimate"),
        (InvalidFlowCEA, None, "constant_gamma_estimate"),
        (PartialFlowCEA, 3.6, "rocketcea_with_constant_gamma_fallback"),
    ):
        result = evaluate_performance(
            AnalysisInput(thrust_chamber=_chamber("frozen_area")),
            cea_adapter=RocketCEAAdapter(lambda **_kwargs: cea_class()),
        )
        assert result.source == "rocketcea"
        assert result.ideal_cstar_m_s == 1810.0
        assert result.exit_mach == pytest.approx(expected_mach if expected_mach is not None else solve_mach(14.0, result.gamma, supersonic=True))
        assert result.throat_isentropic_exponent == result.gamma
        assert result.exit_isentropic_exponent == result.gamma
        assert any("screening gas properties" in warning for warning in result.warnings)
        assert result.nozzle_flow_source == expected_source

    fallback = evaluate_performance(AnalysisInput(), prefer_rocketcea=False)
    assert fallback.exit_mach is not None and fallback.exit_mach > 1.0
    assert fallback.throat_isentropic_exponent == fallback.gamma
    assert fallback.exit_isentropic_exponent == fallback.gamma
    assert fallback.nozzle_flow_source == "ideal_gas_constant_gamma"


@pytest.mark.parametrize("mode", ("shifting", "frozen_pressure", "frozen_area"))
def test_real_rocketcea_exposes_finite_nozzle_flow_properties(mode: str) -> None:
    adapter = RocketCEAAdapter()
    if not adapter.available:
        pytest.skip("compiled RocketCEA is unavailable")
    if mode == "frozen_pressure":
        with pytest.raises(ValueError, match="Frozen-at-chamber.*unsupported"):
            adapter.calculate(EngineDefinition(), _chamber(mode), 14.0)
        return
    state = adapter.calculate(EngineDefinition(), _chamber(mode), 14.0)
    assert state.nozzle_flow_source == "rocketcea"
    for value in (
        state.exit_mach,
        state.throat_isentropic_exponent,
        state.exit_isentropic_exponent,
    ):
        assert value is not None and isfinite(value) and value > 1.0
