from __future__ import annotations

from dataclasses import replace
import math
import re

import pytest

from lpa.analysis import _normalised_segment
from lpa.core import (
    AnalysisInput, CoolantDefinition, EngineDefinition, Fuel, Oxidizer,
    RocketCEAAdapter, ThrustChamberInput, ThrustChamberSize, NozzleExitCondition,
    analysis_input_from_dict, analysis_input_to_dict, evaluate_performance,
    optimize_mixture_ratio,
)
from lpa.core.composition import engine_selection
from lpa.core.propellants import (
    FUELS, OXIDIZERS, LNG_COMPONENTS, LNG_MASS_FRACTIONS,
    fallback_chemistry, registration_cards, rocketcea_names,
)
from lpa.thermal.coolants import get_coolant_model
from lpa.ui.input_views import default_segment


@pytest.mark.parametrize("fraction", [0.01, 0.70, 0.73125, 0.99, 1.0])
@pytest.mark.parametrize("fuel", [Fuel.ETHANOL, Fuel.IPA])
def test_mass_composition_round_trip_and_card_weights(fraction, fuel):
    engine = EngineDefinition(
        oxidizer=Oxidizer.H2O2, oxidizer_mass_fraction=fraction,
        fuel=fuel, fuel_mass_fraction=fraction,
    )
    restored = analysis_input_from_dict(analysis_input_to_dict(AnalysisInput(engine=engine)))
    assert restored.engine == engine
    for _, _, card in registration_cards(engine.oxidizer, engine.fuel, fraction, fraction):
        weights = [float(value) for value in re.findall(r"wt%=([\d.eE+\-]+)", card)]
        assert weights[0] == pytest.approx(fraction * 100)
        assert sum(weights) == pytest.approx(100)
        assert ("WATER" in card) == (fraction < 1.0)
        if fraction < 1.0:
            assert weights[1] == pytest.approx(100.0 * (1.0 - fraction))


@pytest.mark.parametrize("value", [0, -0.1, 1.01, math.nan, math.inf, "bad"])
@pytest.mark.parametrize("kind", ["oxidizer", "fuel"])
def test_invalid_mass_fractions_rejected(value, kind):
    with pytest.raises(ValueError):
        EngineDefinition(oxidizer="H2O2", fuel="IPA", **{f"{kind}_mass_fraction": value})


def test_legacy_names_keep_mass_composition_and_conflicts_are_rejected():
    engine = EngineDefinition(oxidizer=Oxidizer.H2O2_80, fuel=Fuel.ETHANOL_70)
    assert engine.oxidizer is Oxidizer.H2O2
    assert engine.oxidizer_mass_fraction == 0.8
    assert engine.fuel is Fuel.ETHANOL
    assert engine.fuel_mass_fraction == 0.7
    assert engine_selection({"fuel": "Ethanol 90%", "fuel_mass_fraction_pct": 70}, "fuel") == ("Ethanol", 0.9)
    with pytest.raises(ValueError, match="disagree"):
        EngineDefinition(fuel=Fuel.ETHANOL_70, fuel_mass_fraction=0.8)
    with pytest.raises(ValueError, match="not supported"):
        EngineDefinition(fuel=Fuel.LNG, fuel_mass_fraction=0.7)


def test_concentrations_have_separate_cea_cache_identities():
    names = [rocketcea_names(Oxidizer.H2O2, Fuel.IPA, fraction, fraction) for fraction in (0.7, 0.73125, 0.8, 1.0)]
    assert len({name[0] for name in names}) == len(names)
    assert len({name[1] for name in names}) == len(names)


def test_all_propellants_have_coolant_properties_and_consistent_phase_cards():
    assert OXIDIZERS[Oxidizer.N2O].cea_name == "N2O_nbp"
    assert FUELS[Fuel.PROPANE].phase == "liquid"
    for value in list(Oxidizer) + list(Fuel):
        state = get_coolant_model(value).at_temperature(293.15)
        assert all(math.isfinite(number) and number > 0 for number in (
            state.density_kg_m3, state.specific_heat_j_kgk, state.conductivity_w_mk, state.viscosity_pa_s,
        ))
    ipa_card = FUELS[Fuel.IPA].registration_card
    assert "-318.20000000" in ipa_card  # NIST liquid, not RocketCEA's gas value.


def test_lng_is_a_commercial_mixture_with_mole_to_mass_conversion():
    assert sum(row[1] for row in LNG_COMPONENTS) == pytest.approx(1.0)
    assert sum(LNG_MASS_FRACTIONS.values()) == pytest.approx(1.0)
    assert 0.88 < LNG_MASS_FRACTIONS["CH4"] < 0.90
    assert LNG_MASS_FRACTIONS["CH4"] != 0.94
    weights = [float(x) for x in re.findall(r"wt%=([\d.eE+\-]+)", FUELS[Fuel.LNG].registration_card)]
    assert sum(weights) == pytest.approx(100)
    assert len(weights) == 5
    assert FUELS[Fuel.LNG].cea_name != FUELS[Fuel.LCH4].cea_name


@pytest.mark.parametrize("base", ["H2O2", "Ethanol", "IPA"])
@pytest.mark.parametrize("percentage", [25, 73.125, 99, 100])
def test_cooling_keeps_actual_engine_composition_through_regen_and_film(base, percentage):
    kind = "oxidizer" if base == "H2O2" else "fuel"
    engine = {kind: base, f"{kind}_mass_fraction_pct": percentage, "mixture_ratio": 1.3}
    root = default_segment("Regen", 1)
    root.update(id="root", coolant_source_mode=f"Engine {kind}")
    linked = default_segment("Regen", 2)
    linked.update(id="linked", coolant_source_mode="Receive from Regen segment", coolant_source_id="root")
    film = default_segment("Film", 3)
    film.update(temperature_mode="Temperature from Regen segment", temperature_source_id="linked")
    segments = [root, linked, film]
    coolant = _normalised_segment(root, engine, segments)["coolant"]
    film_name = _normalised_segment(film, engine, segments)["coolant"]
    expected = f"{base} ({percentage:g}%)"
    assert coolant["coolant"] == film_name == expected
    validated = CoolantDefinition(**coolant)
    model = get_coolant_model(validated.coolant)
    assert model.name == expected
    assert model.density_kg_m3 > 0
    if percentage < 100:
        assert model.specific_heat_j_kgk > get_coolant_model(f"{base} (100%)").specific_heat_j_kgk


def test_fallback_oxygen_mass_and_dilution_trends():
    pure = fallback_chemistry(Oxidizer.LOX, Fuel.ETHANOL, 1.9)
    diluted_fuel = fallback_chemistry(Oxidizer.LOX, Fuel.ETHANOL, 1.3, 1, 0.7)
    peroxide = fallback_chemistry(Oxidizer.H2O2, Fuel.ETHANOL, 4, 1, 1)
    dilute_peroxide = fallback_chemistry(Oxidizer.H2O2, Fuel.ETHANOL, 6, 0.7, 1)
    nitrous = fallback_chemistry(Oxidizer.N2O, Fuel.ETHANOL, 5)
    assert diluted_fuel.optimum_mixture_ratio == pytest.approx(0.7 * pure.optimum_mixture_ratio)
    assert diluted_fuel.flame_temperature_k < pure.flame_temperature_k
    assert dilute_peroxide.optimum_mixture_ratio > peroxide.optimum_mixture_ratio > pure.optimum_mixture_ratio
    assert nitrous.optimum_mixture_ratio > pure.optimum_mixture_ratio


@pytest.fixture(scope="module")
def real_cea(tmp_path_factory):
    pytest.importorskip("rocketcea")
    adapter = RocketCEAAdapter()
    assert adapter.available, adapter.unavailable_reason
    from rocketcea import cea_obj
    previous = cea_obj.ROCKETCEA_DATA_DIR
    cea_obj.ROCKETCEA_DATA_DIR = str(tmp_path_factory.mktemp("propellant_cea"))
    try:
        yield adapter
    finally:
        cea_obj.ROCKETCEA_DATA_DIR = previous


@pytest.mark.parametrize("oxidizer", [Oxidizer.LOX, Oxidizer.GOX, Oxidizer.H2O2, Oxidizer.N2O])
@pytest.mark.parametrize("fuel", [Fuel.ETHANOL, Fuel.IPA, Fuel.RP1, Fuel.JET_A1, Fuel.LCH4, Fuel.LNG, Fuel.GCH4, Fuel.LH2, Fuel.GH2, Fuel.PROPANE])
def test_every_engine_propellant_pair_runs_in_actual_cea(real_cea, oxidizer, fuel):
    engine = EngineDefinition(
        oxidizer=oxidizer, fuel=fuel,
        oxidizer_mass_fraction=0.85 if oxidizer == Oxidizer.H2O2 else 1.0,
        fuel_mass_fraction=0.73125 if fuel in {Fuel.ETHANOL, Fuel.IPA} else 1.0,
    )
    # This covers chemistry, not unsupported separated-flow sea-level sizing.
    chamber = ThrustChamberInput(
        exit_condition=NozzleExitCondition("expansion_ratio", 8.0, None),
        size=ThrustChamberSize(thrust_ambient_pressure_atm=0.0),
    )
    result = evaluate_performance(AnalysisInput(engine, chamber), cea_adapter=real_cea, require_rocketcea=True)
    assert result.source == "rocketcea"
    assert 100 < result.ideal_cstar_m_s < 4000
    assert 300 < result.combustion_temperature_k < 5000


def test_real_vacuum_isp_optimum_depends_on_exit_and_responds_to_dilution(real_cea):
    engine = EngineDefinition(fuel=Fuel.ETHANOL, fuel_mass_fraction=0.7, mixture_ratio=1.3)
    small = optimize_mixture_ratio(engine, contraction_area_ratio=6.25, expansion_ratio=5, cea_adapter=real_cea)
    large = optimize_mixture_ratio(engine, contraction_area_ratio=6.25, expansion_ratio=50, cea_adapter=real_cea)
    ambient = optimize_mixture_ratio(engine, contraction_area_ratio=6.25, expansion_ratio=None, ambient_pressure_atm=1, cea_adapter=real_cea)
    assert small.source == large.source == ambient.source == "rocketcea"
    assert small.warning is None
    assert large.mixture_ratio > small.mixture_ratio + 0.1
    assert abs(small.mixture_ratio - ambient.mixture_ratio) > 0.001
    assert small.objective == "maximum theoretical vacuum specific impulse"
    cea = real_cea._make_cea(engine, 6.25)
    assert small.ideal_cstar_m_s == pytest.approx(cea.get_Cstar(Pc=20, MR=small.mixture_ratio))
    for optimum, fixed_exit in ((small, 5), (large, 50), (ambient, None)):
        for delta in (-0.05, -0.01, 0.01, 0.05):
            candidate_mr = optimum.mixture_ratio + delta
            epsilon = fixed_exit if fixed_exit is not None else cea.get_eps_at_PcOvPe(
                Pc=20, MR=candidate_mr, PcOvPe=20 / 1.01325,
            )
            assert cea.get_Isp(Pc=20, MR=candidate_mr, eps=epsilon) < optimum.vacuum_isp_s
    pure = optimize_mixture_ratio(replace(engine, fuel_mass_fraction=1), contraction_area_ratio=6.25,
                                  expansion_ratio=5, cea_adapter=real_cea)
    assert pure.mixture_ratio > small.mixture_ratio
    assert pure.ideal_cstar_m_s > small.ideal_cstar_m_s
    assert pure.vacuum_isp_s > small.vacuum_isp_s


def test_real_cea_100_percent_endpoints_match_pure_liquid_cards(real_cea):
    from rocketcea.cea_obj_w_units import CEA_Obj
    for oxidizer, fuel, ox_name, fuel_name in (
        (Oxidizer.LOX, Fuel.ETHANOL, "LOX", "Ethanol"),
        (Oxidizer.H2O2, Fuel.RP1, "H2O2", "RP1"),
    ):
        engine = EngineDefinition(oxidizer=oxidizer, fuel=fuel)
        actual = real_cea._make_cea(engine, 6.25)
        reference = CEA_Obj(oxName=ox_name, fuelName=fuel_name, fac_CR=6.25, pressure_units="bar", cstar_units="m/s")
        assert actual.get_Cstar(Pc=20, MR=2) == pytest.approx(reference.get_Cstar(Pc=20, MR=2), rel=1e-6)
