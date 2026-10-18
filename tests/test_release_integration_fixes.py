"""Public integration checks independent of solver implementation loops."""
from __future__ import annotations

from math import isclose, sqrt, pi
import re
from types import SimpleNamespace

import pytest

from lpa.analysis import _core_project, _film_orifice_results, _normalised_segment, _float, _int
from lpa.analysis import AnalysisService
from lpa.core import EngineDefinition, Fuel, Oxidizer, RangeSpec
from lpa.core.propellants import propellant_specs
from lpa.core.serialization import analysis_input_from_dict, analysis_input_to_dict
from lpa.core.models import AnalysisInput
from lpa.ui.input_views import default_segment


@pytest.mark.parametrize("value", ["banana", "nan", "inf", float("nan"), float("inf")])
def test_active_normalization_never_substitutes_bad_number(value):
    with pytest.raises(ValueError):
        _float(value, 1.5)


@pytest.mark.parametrize("value", [60.9, True, "nan", "inf"])
def test_integer_normalization_never_truncates(value):
    with pytest.raises(ValueError):
        _int(value)
    with pytest.raises(ValueError):
        RangeSpec(1, 2, value)


def test_engine_regen_flow_matches_hot_propellant_stream_with_external_film():
    regen = default_segment("Regen", 1)
    regen["coolant_source_mode"] = "Engine fuel"
    film = default_segment("Film", 2)
    film.update(coolant="H2O", relative_mass_flow_pct="30")
    coolant = _normalised_segment(regen, {"fuel": "RP-1", "mixture_ratio": "2.5"}, [regen, film])["coolant"]
    assert coolant["relative_mass_flow_percent"] == pytest.approx(20.0)


def test_inactive_film_orifice_inputs_do_not_block_thermal_analysis():
    film = default_segment("Film", 1)
    film.update(orifice_enabled=False, discharge_coefficient="bad", orifice_count="60.9")
    segment = _normalised_segment(film)
    assert segment["discharge_coefficient"] == .6
    assert segment["orifice_count"] == 30
    film["orifice_enabled"] = True
    with pytest.raises(ValueError):
        _normalised_segment(film)


def _orifice_fixture(coolant="H2O", supply_p=30.0, gas_p=20.0, temperature=300.0):
    regen = default_segment("Regen", 1)
    regen.update(id="regen", coolant=coolant, coolant_source_mode="Custom coolant", coolant_inlet_pressure_bar="50")
    film = default_segment("Film", 2)
    film.update(id="film", temperature_source_id="regen", temperature_mode="Temperature from Regen segment",
                orifice_enabled=True, position_mode="Injector Face", relative_mass_flow_pct="3",
                discharge_coefficient="0.6", orifice_count="30")
    project = {"engine": {}, "thermal": {"segments": [regen, film]}}
    core = SimpleNamespace(contour=SimpleNamespace(x_m=(0, .1), chamber_end_index=0),
        performance=SimpleNamespace(chamber_pressure_bar=gas_p, total_mass_flow_kg_s=1.0))
    thermal = SimpleNamespace(x_m=(0, .1), Tc_K=(temperature, temperature), active_segment_id=("regen", "regen"),
        coolant_outlet_temperature_k={"regen": temperature}, coolant_outlet_pressure_bar={"regen": supply_p})
    return project, core, thermal


def test_orifice_uses_outlet_loss_and_matches_independent_liquid_equation():
    from CoolProp.CoolProp import PropsSI
    project, core, thermal = _orifice_fixture()
    rows, warnings = _film_orifice_results(project, core, thermal)
    assert warnings == []
    row = rows[0]
    rho = PropsSI("Dmass", "T", 300, "P", 3e6, "Water")
    area = .03 / (.6 * sqrt(2 * rho * 1e6))
    assert row["pressure_drop_bar"] == pytest.approx(10)
    assert row["diameter_mm"] == pytest.approx(sqrt(4 * area / (pi * 30)) * 1000)
    assert row["physical_validity"] == "valid"


@pytest.mark.parametrize("outlet_available", [True, False])
def test_film_orifice_rejects_incomplete_regen_before_outlet_or_nearest_fallback(outlet_available):
    project, core, thermal = _orifice_fixture()
    thermal.metadata = {"regen_segment_completion": {"regen": {
        "solved_wall_stations": 1, "requested_wall_stations": 2, "wall_march_completed": False}}}
    thermal.coolant_pressure_bar = (30., 30.)
    if not outlet_available:
        thermal.coolant_outlet_temperature_k = {}
        thermal.coolant_outlet_pressure_bar = {}
    rows, warnings = _film_orifice_results(project, core, thermal)
    assert rows == []
    assert len(warnings) == 1
    assert "did not complete its coolant march" in warnings[0]
    assert "partial state" in warnings[0]


@pytest.mark.parametrize("completion", [{}, {"other": {"wall_march_completed": False}},
                                         {"regen": {"wall_march_completed": True}}])
def test_film_orifice_preserves_legacy_or_completed_source(completion):
    project, core, thermal = _orifice_fixture()
    thermal.metadata = {"regen_segment_completion": completion}
    rows, warnings = _film_orifice_results(project, core, thermal)
    assert len(rows) == 1
    assert warnings == []


def test_orifice_blocks_reverse_pressure_and_flashing():
    for fixture in (_orifice_fixture(supply_p=15), _orifice_fixture(supply_p=30, gas_p=1, temperature=450)):
        rows, warnings = _film_orifice_results(*fixture)
        assert rows == [] and warnings


def test_gas_orifice_choking_ignores_further_downstream_pressure_reduction():
    sizes = []
    for pressure in (1.0, 5.0):
        rows, warnings = _film_orifice_results(*_orifice_fixture("GH2", 30, pressure))
        assert rows[0]["choked"]
        assert rows[0]["physical_validity"] == "screening"
        assert warnings
        sizes.append(rows[0]["diameter_mm"])
    assert sizes[0] == pytest.approx(sizes[1])


def test_supply_state_round_trip_and_invalid_feed_pressure():
    engine = EngineDefinition(fuel_temperature_k=350, fuel_pressure_bar=35)
    restored = analysis_input_from_dict(analysis_input_to_dict(AnalysisInput(engine=engine)))
    assert restored.engine == engine
    with pytest.raises(ValueError, match="supply pressure"):
        EngineDefinition(fuel_pressure_bar=5)


def test_supply_card_delta_uses_eos_relative_enthalpy_not_arbitrary_datum():
    from CoolProp.CoolProp import PropsSI
    spec = propellant_specs(Oxidizer.LOX, Fuel.LCH4, fuel_temperature_k=93.24, fuel_pressure_bar=30)[1]
    actual = float(re.search(r"h,kj/mol=([^ ]+)", spec.registration_card)[1])
    delta = PropsSI("Hmass", "T", 93.24, "P", 3e6, "Methane") - PropsSI("Hmass", "T", 111.66, "Q", 0, "Methane")
    assert actual == pytest.approx(-89.49576 + delta * 16.04246 / 1e6, abs=1e-8)


def test_lng_card_has_one_common_state_and_preserves_composition():
    spec = propellant_specs(Oxidizer.LOX, Fuel.LNG, fuel_pressure_bar=30)[1]
    assert set(re.findall(r"t\(k\)=([\d.]+)", spec.registration_card)) == {"111.66"}
    assert sum(float(x) for x in re.findall(r"wt%=([\d.]+)", spec.registration_card)) == pytest.approx(100)
    assert "mixture" in spec.enthalpy_model


def test_regen_reactant_feedback_matches_independent_fixed_point():
    # Independent steady response T_out=300+0.1*T_in has T*=1000/3 K.
    service = AnalysisService()
    def solve(project):
        inlet = float(project["engine"].get("fuel_temperature_k", 300))
        return {"warnings": [], "thermal": {"physical_validity": "valid", "converged":True,
            "coolant_outlet_temperature_k": {"r": 300 + .1 * inlet},
            "coolant_outlet_pressure_bar": {"r": 32.0}}, "reactant_t": inlet}
    service._analyze_once = solve
    project = {"engine": {"fuel_temperature_k":300}, "thermal":{
        "regen_feed_feedback_enabled":True,"segments":[{"id":"r","type":"Regen","coolant_source_mode":"Engine fuel"}]}}
    result = service.analyze(project)
    assert result["regen_feed_feedback"]["converged"]
    assert abs(result["reactant_t"] - 1000/3) < .06
    assert result["input_project"] == project


def test_regen_reactant_feedback_rejects_unsupported_phase():
    service=AnalysisService()
    service._analyze_once=lambda project: {"warnings":[],"thermal":{"physical_validity":"unsupported", "converged":True}}
    result=service.analyze({"thermal":{"regen_feed_feedback_enabled":True}})
    assert not result["regen_feed_feedback"]["converged"]
    assert result["thermal"]["physical_validity"]=="unsupported"
    assert result["warnings"]
