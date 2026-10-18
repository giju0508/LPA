"""Separate reacting nozzle states from frozen Bartz reference properties."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from lpa.core.analysis import analyze_engine
from lpa.core.models import (
    AmbientConditions, AnalysisInput, EngineDefinition, EquilibriumFlow,
    NozzleExitCondition, ThrustChamberInput, ThrustChamberSize,
)
from lpa.core.performance import RocketCEAAdapter, UNIVERSAL_GAS_CONSTANT
from lpa.core.rocketcea_runtime import rocketcea_import_environment
from lpa.thermal.correlations import (
    adiabatic_wall_temperature, bartz_heat_transfer_coefficient,
)


@pytest.fixture
def cea_adapter():
    adapter = RocketCEAAdapter()
    if not adapter.available:
        pytest.skip("compiled RocketCEA is unavailable")
    return adapter


def _inputs():
    return AnalysisInput(
        engine=EngineDefinition(
            oxidizer="GOX", fuel="GCH4", chamber_pressure_bar=10, mixture_ratio=2.6,
        ),
        thrust_chamber=ThrustChamberInput(
            contraction_area_ratio=4, reaction_efficiency_percent=100,
            size=ThrustChamberSize(mode="throat_diameter", throat_diameter_mm=31.79),
            exit_condition=NozzleExitCondition(mode="expansion_ratio", expansion_area_ratio=4),
            ambient=AmbientConditions(enabled=True, fixed_pressure_atm=0),
        ),
    )


def test_frozen_chamber_reference_matches_independent_public_getters(cea_adapter):
    inputs = _inputs()
    reference = cea_adapter.bartz_reference_properties(inputs.engine, inputs.thrust_chamber)
    # Infinite-area public getters expose the zero-velocity chamber state,
    # independently of the adapter's FAC injector-array extraction.
    with rocketcea_import_environment():
        from rocketcea.cea_obj_w_units import CEA_Obj
        oracle = CEA_Obj(oxName="GOX", fuelName="GCH4", pressure_units="bar",
                         specific_heat_units="J/kg-K")
        cp_it, mu, _conductivity, pr = oracle.get_Chamber_Transport(
            Pc=10, MR=2.6, eps=4, frozen=1,
        )
        molecular_weight, _reacting_exponent = oracle.get_Chamber_MolWt_gamma(Pc=10, MR=2.6, eps=4)
    # The unit wrapper uses IT calories; the underlying CEA arrays use
    # thermochemical calories. Keep the same conversion used for axial data.
    cp_thermochemical = cp_it * 4184.0 / 4186.8
    gas_constant = UNIVERSAL_GAS_CONSTANT / molecular_weight
    assert reference["specific_heat_j_kgk"] == pytest.approx(cp_thermochemical, rel=2e-6)
    assert reference["viscosity_pa_s"] == pytest.approx(mu * 1e-4, rel=2e-6)
    assert reference["prandtl"] == pytest.approx(pr, rel=2e-6)
    assert reference["gamma"] == pytest.approx(cp_thermochemical / (cp_thermochemical - gas_constant), rel=2e-6)


def test_flow_freezing_does_not_choose_bartz_transport_or_replace_axial_cp(cea_adapter):
    inputs = _inputs()
    shifting = analyze_engine(inputs, cea_adapter=cea_adapter, require_rocketcea=True)
    frozen_inputs = replace(inputs, thrust_chamber=replace(
        inputs.thrust_chamber, equilibrium=EquilibriumFlow(mode="frozen_area", freeze_area_ratio=1),
    ))
    frozen = analyze_engine(frozen_inputs, cea_adapter=cea_adapter, require_rocketcea=True)
    for name in ("specific_heat_j_kgk", "viscosity_pa_s", "prandtl", "gamma"):
        field = f"bartz_reference_{name}"
        assert getattr(shifting.thermodynamics, field) == pytest.approx(getattr(frozen.thermodynamics, field), rel=1e-12)
    gas = shifting.thermodynamics
    assert gas.bartz_reference_source == "rocketcea-chamber-stagnation-frozen-transport"
    assert gas.specific_heat_j_kgk[0] > 2 * gas.bartz_reference_specific_heat_j_kgk
    assert gas.gamma[0] < gas.bartz_reference_gamma
    assert frozen.thermodynamics.specific_heat_j_kgk[-1] != pytest.approx(gas.specific_heat_j_kgk[-1], rel=0.05)
    # The service passes the original thermodynamics object, so these scalar
    # references must survive mesh preparation independently of axial arrays.
    from lpa.thermal.solver import ThermalSolverSettings, _build_mesh, _prepare_gas
    mesh = _build_mesh(shifting.contour, 120)
    prepared = _prepare_gas(shifting, shifting.contour, mesh, ThermalSolverSettings())
    assert prepared.reference_specific_heat_j_kgk == gas.bartz_reference_specific_heat_j_kgk
    assert prepared.reference_prandtl == gas.bartz_reference_prandtl
    assert prepared.reference_gamma == gas.bartz_reference_gamma
    assert prepared.reference_viscosity_pa_s == gas.bartz_reference_viscosity_pa_s
    throat = mesh.throat_index
    assert prepared.recovery_temperature_k[throat] == pytest.approx(adiabatic_wall_temperature(
        shifting.performance.combustion_temperature_k, prepared.mach[throat],
        gas.bartz_reference_gamma, gas.bartz_reference_prandtl,
    ))


def test_missing_reference_preserves_valid_local_cea_flow(cea_adapter, monkeypatch):
    def unavailable(*_args):
        raise RuntimeError("transport reference disabled for test")
    monkeypatch.setattr(cea_adapter, "bartz_reference_properties", unavailable)
    result = analyze_engine(_inputs(), cea_adapter=cea_adapter, require_rocketcea=True)
    assert result.thermodynamics.source == "rocketcea-local-stations-and-transport"
    assert result.thermodynamics.bartz_reference_specific_heat_j_kgk is None
    assert result.thermodynamics.bartz_reference_source == "unavailable"
    assert any("Bartz chamber frozen transport unavailable" in item for item in result.warnings)


@pytest.mark.parametrize("station_index", [0, 1, 2])
def test_frozen_bartz_reference_agrees_with_captured_rpa_fixed_wall(station_index):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "rpa_bartz_fixed_wall_4_0_13.json").read_text(encoding="utf-8"))
    config, reference = fixture["configuration"], fixture["gas_reference"]
    station = fixture["stations"][station_index]
    cp, pr = reference["frozen_specific_heat_j_kgk"], reference["frozen_prandtl"]
    gamma = cp / (cp - reference["gas_constant_j_kgk"])
    coefficient = bartz_heat_transfer_coefficient(
        chamber_pressure_pa=config["chamber_pressure_pa"],
        characteristic_velocity_m_s=reference["characteristic_velocity_m_s"],
        throat_diameter_m=config["throat_diameter_m"],
        throat_radius_of_curvature_m=config["upstream_throat_radius_ratio"] * config["throat_diameter_m"] / 2,
        area_ratio=station["area_ratio"], wall_temperature_k=config["fixed_wall_temperature_k"],
        stagnation_temperature_k=reference["stagnation_temperature_k"], mach=station["mach"],
        viscosity_pa_s=reference["viscosity_pa_s"], specific_heat_j_kgk=cp, prandtl=pr, gamma=gamma,
    )
    recovery = adiabatic_wall_temperature(reference["stagnation_temperature_k"], station["mach"], gamma, pr)
    heat_flux = coefficient * (recovery - config["fixed_wall_temperature_k"])
    assert coefficient == pytest.approx(station["heat_transfer_coefficient_w_m2k"], rel=fixture["acceptance"]["relative_h_difference_max"])
    assert heat_flux == pytest.approx(station["convective_heat_flux_w_m2"], rel=fixture["acceptance"]["relative_q_difference_max"])
