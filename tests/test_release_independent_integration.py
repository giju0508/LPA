"""Independent thermodynamic-cycle, mass-ledger and restriction oracles."""
from math import pi, sqrt
import re
from types import SimpleNamespace

import pytest

from lpa.analysis import AnalysisService, _film_orifice_results, _normalised_segment
from lpa.core.models import Fuel, Oxidizer
from lpa.core.propellants import propellant_specs
from lpa.ui.input_views import default_segment


def molar_enthalpy(spec):
    return float(re.search(r"h,kj/mol=([^ ]+)", spec.registration_card)[1])


@pytest.mark.parametrize("temperature,pressure", [(25.0, 30.0), (90.0, 50.0), (300.0, 30.0)])
def test_explicit_hydrogen_same_state_has_one_chemical_enthalpy(temperature, pressure):
    values = []
    for fuel in (Fuel.LH2, Fuel.GH2):
        spec = propellant_specs(Oxidizer.LOX, fuel,
                                fuel_temperature_k=temperature, fuel_pressure_bar=pressure)[1]
        values.append(molar_enthalpy(spec))
        assert any("spin" in warning.casefold() or "para/ortho" in warning.casefold() for warning in spec.warnings)
    assert values[0] == pytest.approx(values[1], abs=1e-9)


def test_legacy_hydrogen_reference_is_preserved_and_not_confused_with_eos_state():
    legacy = propellant_specs(Oxidizer.LOX, Fuel.LH2)[1]
    assert legacy.cea_name == "LH2"
    assert legacy.registration_card is None
    explicit = propellant_specs(Oxidizer.LOX, Fuel.LH2,
                               fuel_temperature_k=20.27, fuel_pressure_bar=30)[1]
    assert explicit.cea_name != legacy.cea_name
    assert explicit.warnings
    assert "common" in explicit.enthalpy_model.casefold() and "anchor" in explicit.enthalpy_model.casefold()


@pytest.mark.parametrize("fraction", [0.3, 0.7, 0.9])
def test_solution_card_energy_difference_equals_independent_mixture_eos(fraction):
    from CoolProp import CoolProp as cp
    state = cp.AbstractState("HEOS", "Ethanol&Water")
    state.set_mass_fractions([fraction, 1.0 - fraction])
    expected = []
    observed = []
    for temperature in (298.15, 350.0):
        state.update(cp.PT_INPUTS, 3e6, temperature)
        expected.append(state.hmass())
        spec = propellant_specs(Oxidizer.LOX, Fuel.ETHANOL,
                                fuel_mass_fraction=fraction,
                                fuel_temperature_k=temperature, fuel_pressure_bar=30)[1]
        h_values = [float(value) for value in re.findall(r"h,kj/mol=([^ ]+)", spec.registration_card)]
        weights = [float(value) / 100 for value in re.findall(r"wt%=([^\s]+)", spec.registration_card)]
        # kJ/mol -> J/kg uses the independently specified chemical MW.
        observed.append(sum(w * h * 1e6 / mw for w, h, mw in zip(weights, h_values, (46.06844, 18.01528))))
    assert observed[1] - observed[0] == pytest.approx(expected[1] - expected[0], rel=2e-8)


def test_supply_cache_identity_keeps_pressure_and_composition_separate():
    entries = []
    for fraction, temperature, pressure in ((0.7, 300, 30), (0.8, 300, 30), (0.7, 350, 30), (0.7, 300, 40)):
        entries.append(propellant_specs(Oxidizer.LOX, Fuel.ETHANOL, fuel_mass_fraction=fraction,
                                       fuel_temperature_k=temperature, fuel_pressure_bar=pressure)[1])
    assert len({entry.cea_name for entry in entries}) == 4
    repeated = propellant_specs(Oxidizer.LOX, Fuel.ETHANOL, fuel_mass_fraction=.7,
                                fuel_temperature_k=300, fuel_pressure_bar=30)[1]
    assert repeated == entries[0]


def restriction_fixture(gas_pressure, temperature=300):
    regen = default_segment("Regen", 1)
    regen.update(id="r", coolant="GH2", coolant_source_mode="Custom coolant")
    film = default_segment("Film", 2)
    film.update(id="f", temperature_source_id="r", temperature_mode="Temperature from Regen segment",
                orifice_enabled=True, position_mode="Specified location", position_mm="50",
                relative_mass_flow_pct="3", discharge_coefficient="0.6", orifice_count="30")
    project = {"engine": {}, "thermal": {"segments": [regen, film]}}
    core = SimpleNamespace(contour=SimpleNamespace(x_m=(0, .1), chamber_end_index=0),
        performance=SimpleNamespace(chamber_pressure_bar=20, total_mass_flow_kg_s=1.0),
        thermodynamics=SimpleNamespace(x_m=(0, .1), pressure_pa=(gas_pressure * 1e5, gas_pressure * 1e5)))
    thermal = SimpleNamespace(x_m=(0, .1), Tc_K=(temperature, temperature), active_segment_id=("r", "r"),
        coolant_outlet_temperature_k={"r": temperature}, coolant_outlet_pressure_bar={"r": 30})
    return project, core, thermal


@pytest.mark.parametrize("back_pressure", [1.0, 5.0])
def test_gas_orifice_matches_independent_sonic_mass_flow_equation(back_pressure):
    from CoolProp import CoolProp as cp
    rows, warnings = _film_orifice_results(*restriction_fixture(back_pressure))
    assert rows and warnings
    specific_heat = cp.PropsSI("Cpmass", "T", 300, "P", 3e6, "Hydrogen")
    cv = cp.PropsSI("Cvmass", "T", 300, "P", 3e6, "Hydrogen")
    gamma = specific_heat / cv
    gas_constant = cp.PropsSI("gas_constant", "Hydrogen") / cp.PropsSI("molar_mass", "Hydrogen")
    sonic_flux = 3e6 * sqrt(gamma / (gas_constant * 300)) * (2 / (gamma + 1)) ** ((gamma + 1) / (2 * (gamma - 1)))
    expected_area = .03 / (.6 * sonic_flux)
    assert rows[0]["gas_pressure_bar"] == back_pressure
    assert rows[0]["choked"]
    assert rows[0]["total_area_mm2"] == pytest.approx(expected_area * 1e6, rel=1e-12)
    assert rows[0]["diameter_mm"] == pytest.approx(sqrt(4 * expected_area / (pi * 30)) * 1e3, rel=1e-12)


def test_engine_source_normalization_obeys_external_film_mass_ledger():
    film = default_segment("Film", 1)
    film.update(relative_mass_flow_pct="20", coolant="H2O")
    regens = []
    for source in ("Engine oxidizer", "Engine fuel"):
        regen = default_segment("Regen", len(regens) + 2)
        regen.update(coolant_source_mode=source)
        regens.append(regen)
    engine = {"mixture_ratio": "2.5", "oxidizer": "LOX", "fuel": "RP-1"}
    fractions = [_normalised_segment(regen, engine, [film, *regens])["coolant"]["relative_mass_flow_percent"] / 100 for regen in regens]
    assert sum(fractions) + .2 == pytest.approx(1)
    assert fractions[0] / fractions[1] == pytest.approx(2.5)


@pytest.mark.parametrize("inner_coupling", [True, False])
def test_feedback_does_not_certify_unconverged_inner_thermal_solution(inner_coupling):
    service = AnalysisService()
    service._analyze_once = lambda project: {"warnings": [], "thermal": {
        "physical_validity": "screening", "converged": False,
        "metadata": {"coupled_converged": inner_coupling},
        "coolant_outlet_temperature_k": {"r": 333.0},
        "coolant_outlet_pressure_bar": {"r": 32.0}}}
    project = {"engine": {"fuel_temperature_k": 333, "fuel_pressure_bar": 32},
               "thermal": {"regen_feed_feedback_enabled": True,
                           "segments": [{"id": "r", "type": "Regen", "coolant_source_mode": "Engine fuel"}]}}
    result = service.analyze(project)
    assert not result["regen_feed_feedback"]["converged"]
    assert result["warnings"]
    assert result["thermal"]["metadata"]["physical_validity"] == result["thermal"]["physical_validity"]
    assert result["thermal"]["metadata"]["physical_issues"] == result["thermal"]["physical_issues"]
