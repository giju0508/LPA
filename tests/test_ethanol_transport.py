"""Experimental-source calibration checks and independent transport holdouts."""

import json
from math import isfinite, nan
from pathlib import Path

import CoolProp.CoolProp as CP
import numpy as np
import pytest

from lpa.thermal.ethanol_transport import (
    INDEPENDENT_HOLDOUT, M_ETHANOL, M_WATER, _pure_liquid_reference, ethanol_water_transport,
)


@pytest.fixture(scope="module")
def reference():
    return json.loads((Path(__file__).parent / "data/ethanol_water_transport_reference.json").read_text())


def errors_for(rows, property_name):
    errors = []
    for temperature, pressure, x, measured, _uncertainty in rows:
        result = ethanol_water_transport(temperature_k=temperature, pressure_pa=pressure,
                                          ethanol_mole_fraction=x, phase="liquid")
        predicted = getattr(result, property_name)
        errors.append(100.0 * (predicted / measured - 1.0))
    return np.abs(errors)


@pytest.mark.parametrize("dataset,property_name,aad_limit,maximum_limit", [
    ("gonzalez2007", "viscosity_pa_s", 1.1, 3.3),
    ("ono2016", "viscosity_pa_s", 1.5, 4.9),
    ("hoga2018", "viscosity_pa_s", 2.7, 6.8),
    ("cui2019", "conductivity_w_mk", .4, 2.6),
    ("zhou2013", "conductivity_w_mk", .7, 2.3),
])
def test_transport_matches_retained_experimental_points(reference, dataset, property_name, aad_limit, maximum_limit):
    key = "viscosity" if property_name == "viscosity_pa_s" else "conductivity"
    points = reference["datasets"][dataset][key]
    assert reference["columns"] == ["temperature_k", "pressure_pa", "x_ethanol_mole", "value_si", "expanded_uncertainty_si"]
    errors = errors_for(points, property_name)
    assert np.mean(errors) < aad_limit
    assert max(errors) < maximum_limit


@pytest.mark.parametrize("dataset,property_name,metadata_name", [
    ("hoga2018", "viscosity_pa_s", "viscosity_Hoga2018"),
    ("zhou2013", "conductivity_w_mk", "conductivity_Zhou2013"),
])
def test_independent_holdout_metadata_reproduces_source_comparisons(reference, dataset, property_name, metadata_name):
    key = "viscosity" if property_name == "viscosity_pa_s" else "conductivity"
    errors = errors_for(reference["datasets"][dataset][key], property_name)
    metadata = INDEPENDENT_HOLDOUT[metadata_name]
    assert len(errors) == metadata["points"]
    assert np.mean(errors) == pytest.approx(metadata["aad_percent"], abs=1e-7)
    assert max(errors) == pytest.approx(metadata["maximum_absolute_percent"], abs=1e-7)


def test_entire_withheld_pressure_level_remains_predictive(reference):
    withheld = [r for r in reference["datasets"]["ono2016"]["viscosity"] if r[1] == 30e6]
    assert len(withheld) == 21
    errors = errors_for(withheld, "viscosity_pa_s")
    assert np.mean(errors) < 1.5 and max(errors) < 4.9


def test_room_temperature_seventy_mass_percent_corrects_native_mixture_transport():
    x = (.7 / M_ETHANOL) / (.7 / M_ETHANOL + .3 / M_WATER)
    result = ethanol_water_transport(temperature_k=293.15, pressure_pa=25e5, ethanol_mole_fraction=x)
    assert .0021 < result.viscosity_pa_s < .0024
    assert .23 < result.conductivity_w_mk < .25
    assert result.property_applicability == "correlated"
    assert result.validation_status == "screening"
    assert result.evidence["viscosity_scope"] == "engineering prediction"
    assert result.evidence["conductivity_scope"] == "engineering prediction"
    assert result.evidence["source_grid_extent_is_validated_rectangle"] is False
    assert "unvalidated" in " ".join(result.issues)


@pytest.mark.parametrize("x,fluid", [(0., "Water"), (1., "Ethanol")])
def test_pure_limits_match_compressed_liquid_transport(x, fluid):
    result = ethanol_water_transport(temperature_k=300., pressure_pa=2e6, ethanol_mole_fraction=x)
    assert result.viscosity_pa_s == pytest.approx(CP.PropsSI("V", "T", 300., "P", 2e6, fluid), rel=1e-12)
    assert result.conductivity_w_mk == pytest.approx(CP.PropsSI("L", "T", 300., "P", 2e6, fluid), rel=1e-12)


def test_fractionated_hot_liquid_reference_is_explicit_and_critical_guarded():
    result = ethanol_water_transport(temperature_k=480., pressure_pa=1e6, ethanol_mole_fraction=.5)
    assert result.evidence["pure_saturated_liquid_reference_used"] is True
    assert result.viscosity_pa_s > 1e-5 and result.conductivity_w_mk > .1
    assert any("saturated-liquid reference" in note for note in result.issues)
    with pytest.raises(ValueError, match="critical"):
        _pure_liquid_reference(520., 10e6, "Ethanol")


def test_vapor_uses_phase_composition_and_reports_dense_gas_limit():
    ethanol_rich = ethanol_water_transport(temperature_k=480., pressure_pa=2e6,
        ethanol_mole_fraction=.8, phase="gas", phase_density_kg_m3=50.)
    water_rich = ethanol_water_transport(temperature_k=480., pressure_pa=2e6,
        ethanol_mole_fraction=.2, phase="gas", phase_density_kg_m3=50.)
    assert all(isfinite(v) and v > 0 for v in (ethanol_rich.viscosity_pa_s, ethanol_rich.conductivity_w_mk,
                                               water_rich.viscosity_pa_s, water_rich.conductivity_w_mk))
    assert ethanol_rich.viscosity_pa_s != pytest.approx(water_rich.viscosity_pa_s, rel=.001)
    assert ethanol_rich.conductivity_w_mk != pytest.approx(water_rich.conductivity_w_mk, rel=.001)
    assert ethanol_rich.evidence["dense_gas_correction"] is False
    assert ethanol_rich.evidence["viscosity_scope"] == "engineering prediction"
    assert any("High-pressure/nonideal" in note for note in ethanol_rich.issues)


@pytest.mark.parametrize("phase", ["supercritical_liquid", "supercritical_gas"])
def test_phase_qualified_supercritical_continuation_is_explicit(phase):
    result = ethanol_water_transport(temperature_k=450., pressure_pa=20e6,
                                      ethanol_mole_fraction=.5, phase=phase)
    assert result.phase == phase
    assert any("Supercritical" in note for note in result.issues)


@pytest.mark.parametrize("changes", [
    {"temperature_k": nan}, {"temperature_k": 250.}, {"temperature_k": 510.},
    {"pressure_pa": 0.}, {"pressure_pa": 41e6},
    {"ethanol_mole_fraction": -.1}, {"ethanol_mole_fraction": 1.1},
    {"phase": "unknown"}, {"phase": "two_phase"}, {"phase": "supercritical"},
    {"phase_density_kg_m3": -1.},
])
def test_invalid_or_unqualified_states_raise_instead_of_returning_clipped_properties(changes):
    inputs = dict(temperature_k=300., pressure_pa=2e6, ethanol_mole_fraction=.5)
    inputs.update(changes)
    with pytest.raises(ValueError):
        ethanol_water_transport(**inputs)
