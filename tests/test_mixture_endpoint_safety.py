"""Independent regressions for vanished-phase and terminal-flow guard issues."""

from dataclasses import replace
from math import isfinite

import pytest

from lpa.thermal import analyze_thermal, coolants
import lpa.thermal.solver as solver
from tests.test_release_thermal_fixes import cylinder, gas, regen, settings


@pytest.mark.parametrize("missing_numbers", [False, True])
def test_dew_endpoint_ignores_transport_of_the_disappeared_liquid(monkeypatch, missing_numbers):
    original = coolants._extract_phase
    def absent_liquid_transport(name, state, *, vapor, backend):
        phase = original(name, state, vapor=vapor, backend=backend)
        if vapor:
            return phase
        updates = dict(transport_applicability="unsupported", issues=(
            "absent liquid viscosity unavailable; test provider failure",))
        if missing_numbers:
            updates.update(viscosity_pa_s=float("nan"), conductivity_w_mk=float("nan"),
                           specific_heat_j_kgk=float("nan"),enthalpy_j_kg=float("nan"),
                           density_kg_m3=float("nan"))
        return replace(phase, **updates)
    monkeypatch.setattr(coolants, "_extract_phase", absent_liquid_transport)
    state = coolants.coolant_state_from_quality("LNG", 25e5, 1.0)
    vapor = state.saturated_vapor
    assert state.phase == "gas"
    assert state.property_applicability == state.transport_applicability == "correlated"
    assert vapor is not None and vapor.transport_applicability == "correlated"
    assert state.viscosity_pa_s == pytest.approx(vapor.viscosity_pa_s)
    assert state.conductivity_w_mk == pytest.approx(vapor.conductivity_w_mk)
    assert isfinite(state.viscosity_pa_s) and isfinite(state.conductivity_w_mk)
    assert isfinite(state.equilibrium_energy_residual_j_kg)
    assert abs(state.equilibrium_energy_residual_j_kg)<1e-4
    assert not any("absent liquid" in issue for issue in state.issues)


def test_present_liquid_transport_failure_is_still_unsupported(monkeypatch):
    original = coolants._extract_phase
    def failed_liquid_transport(name, state, *, vapor, backend):
        phase = original(name, state, vapor=vapor, backend=backend)
        return phase if vapor else replace(phase, transport_applicability="unsupported")
    monkeypatch.setattr(coolants, "_extract_phase", failed_liquid_transport)
    state = coolants.coolant_state_from_quality("LNG", 25e5, .99)
    assert state.phase == "two_phase"
    assert state.property_applicability == "unsupported"


@pytest.mark.parametrize("terminal_sound_speed, supported", [(10.0, False), (100000.0, True)])
def test_final_gas_outlet_mach_is_checked_after_the_last_wall_station(
        monkeypatch, terminal_sound_speed, supported):
    # This narrow segment solves one wall cell. Inject a finite terminal gas
    # flash so only the final state crosses the Mach check, not the wall state.
    segment = regen(start=.00998, end=.01002)
    original = solver._advance_coolant_state
    def terminal_flash(*args, **kwargs):
        state = original(*args, **kwargs)
        return replace(state, phase="gas", density_kg_m3=1.0,
                       speed_of_sound_m_s=terminal_sound_speed)
    monkeypatch.setattr(solver, "_advance_coolant_state", terminal_flash)
    result = analyze_thermal(cylinder(), gas(), [segment], settings())
    last = result.metadata["coolant_property_metadata"]["water"]["last_state"]
    assert result.coolant_outlet_phase["water"] == "gas"
    assert last["flow_supported"] is supported
    assert (last["mach_number"] < .3) is supported
    completion = result.metadata["regen_segment_completion"]["water"]
    assert completion["solved_wall_stations"] == completion["requested_wall_stations"] == 1
    assert completion["wall_march_completed"] is supported
    warning = any("outlet coolant Mach >= 0.3" in issue for issue in result.physical_issues)
    assert warning is not supported
    if not supported:
        assert result.physical_validity == "unsupported"
