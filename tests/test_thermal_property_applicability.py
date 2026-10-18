"""Integration checks for property stops, entry distances and truthful diagnostics."""
from dataclasses import replace
from math import isfinite

import pytest

from lpa.thermal import analyze_thermal
from lpa.thermal.coolants import get_coolant_model
from lpa.thermal import solver
from tests.test_release_thermal_fixes import cylinder, gas, regen, settings


class PropertyOverride:
    def __init__(self, **changes):
        self.changes = changes

    def at_state(self, temperature, pressure):
        return replace(get_coolant_model("H2O").at_state(temperature, pressure), **self.changes)

    def at_enthalpy(self, enthalpy, pressure):
        return replace(get_coolant_model("H2O").at_enthalpy(enthalpy, pressure), **self.changes)


def test_unsupported_inlet_has_zero_wall_stations_and_no_false_complete_outlet():
    provider = PropertyOverride(property_applicability="unsupported", issues=("transport unavailable",))
    result = analyze_thermal(cylinder(), gas(), [regen()], settings(coolant_properties={"water": provider}))
    assert all(not isfinite(value) for value in result.Twg)
    assert result.metadata["unsolved_station_count"] == result.section_count
    assert result.metadata["solved_wall_station_count"] == 0
    assert result.converged is False
    assert not result.metadata["wall_solution_complete"]
    assert not result.metadata["regen_segment_completion"]["water"]["wall_march_completed"]
    assert result.coolant_flow_regime[0] == "unsupported_properties"
    assert result.station_applicability[0] == "unsupported"


def test_unknown_phase_is_diagnostic_not_an_asserted_single_phase_regime():
    provider = PropertyOverride(phase="unknown", property_applicability="screening", issues=())
    result = analyze_thermal(cylinder(), gas(), [regen()], settings(coolant_properties={"water": provider}))
    assert result.metadata["wall_solution_complete"]
    assert set(result.coolant_flow_regime) == {"unknown_phase_screening"}
    assert set(result.station_applicability) == {"unsupported"}
    assert all(isfinite(value) and value > 0 for value in result.coolant_reynolds)
    assert all(isfinite(value) and value > 0 for value in result.coolant_nusselt)
    assert all(isfinite(value) and value > 0 for value in result.coolant_raw_coefficient_w_m2k)
    exported = result.as_dict()
    assert len(exported["station_applicability"]) == result.section_count
    assert result.physical_validity == "unsupported"


def test_material_outside_data_range_is_not_only_a_screening_notice():
    segment = regen()
    segment.pop("wall_conductivity_w_mk")
    segment["material"] = "AlSi10Mg"
    result = analyze_thermal(cylinder(), gas(), [segment], settings())
    assert min(result.Twc) < 373.15
    assert result.physical_validity == "unsupported"
    assert result.metadata["unsupported_station_count"] > 0
    assert any("diagnostic only" in issue for issue in result.physical_issues)


def test_entrance_distance_follows_flow_and_continues_across_equal_link(monkeypatch):
    original = solver._solve_regen_station
    calls = []

    def observe(**kwargs):
        calls.append((kwargs["identifier"], kwargs["distance_from_inlet_m"], kwargs["cell_length_m"]))
        return original(**kwargs)

    monkeypatch.setattr(solver, "_solve_regen_station", observe)
    first = regen("first", 0, .025)
    second = regen("second", .025, .05)
    second["inherit_coolant_from"] = "first"
    result = analyze_thermal(cylinder(), gas(), [first, second], settings())
    # No films: one pass. Cell pieces on the common station sum to one cell.
    distances = [distance for _, distance, _ in calls]
    assert distances[0] == 0
    assert all(right > left for left, right in zip(distances, distances[1:]))
    assert sum(length for _, _, length in calls) == pytest.approx(.05)
    second_start = next(distance for identifier, distance, _ in calls if identifier == "second")
    assert second_start == pytest.approx(.025)
    metadata = result.metadata["regen_segment_completion"]
    assert metadata["second"]["heated_distance_at_outlet_m"] == pytest.approx(.05)
    assert "continued" in metadata["second"]["thermal_entrance_basis"]


def test_counterflow_entry_distance_starts_at_nozzle_exit(monkeypatch):
    original = solver._solve_regen_station
    calls = []

    def observe(**kwargs):
        calls.append((kwargs["index"], kwargs["distance_from_inlet_m"], kwargs["cell_length_m"]))
        return original(**kwargs)

    monkeypatch.setattr(solver, "_solve_regen_station", observe)
    segment = regen()
    segment["coflow"] = False
    result = analyze_thermal(cylinder(), gas(), [segment], settings())
    assert calls[0][0] == result.section_count - 1
    assert calls[0][1] == 0
    assert calls[-1][0] == 0
    assert sum(length for _, _, length in calls) == pytest.approx(.05)


def test_incomplete_circuit_cannot_supply_a_linked_film_temperature():
    provider = PropertyOverride(property_applicability="unsupported", issues=("transport unavailable",))
    film = {"type":"film", "segment_id":"film", "coolant":"H2O", "injection_location_mm":0,
            "relative_mass_flow_percent":3, "inherit_temperature_from_regen":"water"}
    result = analyze_thermal(cylinder(), gas(), [regen(), film], settings(coolant_properties={"water":provider}))
    assert "film" in result.metadata["inactive_segment_ids"]
    assert max(result.film_effectiveness) == 0
    assert any("complete usable outlet" in warning for warning in result.warnings)


def test_compressible_coolant_warning_is_also_recorded_at_each_station():
    segment = regen()
    segment["coolant"].update(coolant="GH2", inlet_temperature_k=300., inlet_pressure_bar=100.)
    result = analyze_thermal(cylinder(), gas(), [segment], settings())
    assert any("Mach >= 0.3" in issue for issue in result.physical_issues)
    assert result.metadata["unsupported_station_count"] > 0
    assert "unsupported" in result.station_applicability
