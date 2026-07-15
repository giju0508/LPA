from __future__ import annotations

import pytest

from lpa.core import (
    AnalysisInput,
    ContractionDefinitionMode,
    NozzleExitCondition,
    RocketCEAAdapter,
    SizeMode,
    ThrustChamberInput,
    ThrustChamberSize,
    analysis_input_from_dict,
    analysis_input_to_dict,
    evaluate_performance,
    generate_contour,
)


def _direct_dc_chamber(
    chamber_diameter_mm: float = 60.0,
    throat_diameter_mm: float = 20.0,
) -> ThrustChamberInput:
    return ThrustChamberInput(
        contraction_mode=ContractionDefinitionMode.CHAMBER_DIAMETER,
        chamber_diameter_mm=chamber_diameter_mm,
        size=ThrustChamberSize(
            mode=SizeMode.THROAT_DIAMETER,
            nominal_thrust_n=None,
            throat_diameter_mm=throat_diameter_mm,
        ),
        exit_condition=NozzleExitCondition(
            mode="expansion_ratio",
            expansion_area_ratio=8.0,
            ambient_pressure_atm=None,
        ),
    )


def test_direct_dc_resolves_exact_area_ratio_and_contour_diameter() -> None:
    chamber = _direct_dc_chamber()
    result = evaluate_performance(
        AnalysisInput(thrust_chamber=chamber), prefer_rocketcea=False
    )
    contour = generate_contour(
        chamber,
        result.throat_diameter_mm,
        result.expansion_ratio,
        "low",
    )

    assert result.contraction_area_ratio == pytest.approx(9.0)
    assert contour.metadata["contraction_area_ratio"] == pytest.approx(9.0)
    assert contour.metadata["chamber_diameter_mm"] == pytest.approx(60.0)
    assert contour.radius_mm[0] == pytest.approx(30.0)


def test_direct_dc_ratio_is_passed_to_rocketcea_finite_area_combustor() -> None:
    factory_arguments: list[dict[str, object]] = []

    class FakeCEA:
        def get_IvacCstrTc(self, **_kwargs: object) -> tuple[float, float, float]:
            return 320.0, 1800.0, 3450.0

        def get_exit_MolWt_gamma(self, **_kwargs: object) -> tuple[float, float]:
            return 22.0, 1.22

        def get_PcOvPe(self, **_kwargs: object) -> float:
            return 40.0

    def factory(**kwargs: object) -> FakeCEA:
        factory_arguments.append(kwargs)
        return FakeCEA()

    result = evaluate_performance(
        AnalysisInput(thrust_chamber=_direct_dc_chamber()),
        cea_adapter=RocketCEAAdapter(factory),
    )

    assert result.contraction_area_ratio == pytest.approx(9.0)
    assert factory_arguments[-1]["fac_CR"] == pytest.approx(9.0)


def test_direct_dc_nominal_thrust_sizing_closes_area_ratio_loop() -> None:
    chamber = ThrustChamberInput(
        contraction_mode="chamber_diameter",
        chamber_diameter_mm=60.0,
    )
    result = evaluate_performance(
        AnalysisInput(thrust_chamber=chamber), prefer_rocketcea=False
    )

    assert result.contraction_area_ratio == pytest.approx(
        (60.0 / result.throat_diameter_mm) ** 2
    )


def test_direct_dc_rejects_a_chamber_no_larger_than_fixed_throat() -> None:
    with pytest.raises(ValueError, match="greater than throat diameter"):
        evaluate_performance(
            AnalysisInput(thrust_chamber=_direct_dc_chamber(20.0, 20.0)),
            prefer_rocketcea=False,
        )


def test_direct_dc_core_serialization_round_trip_preserves_definition() -> None:
    inputs = AnalysisInput(thrust_chamber=_direct_dc_chamber(55.0, 22.0))
    payload = analysis_input_to_dict(inputs)
    restored = analysis_input_from_dict(payload)

    assert payload["thrust_chamber"]["contraction_mode"] == "chamber_diameter"
    assert payload["thrust_chamber"]["chamber_diameter_mm"] == pytest.approx(55.0)
    assert restored.thrust_chamber.contraction_mode is ContractionDefinitionMode.CHAMBER_DIAMETER
    assert restored.thrust_chamber.chamber_diameter_mm == pytest.approx(55.0)
