"""Complete liquid/VLE/vapor marches exercise EOS, phase transport and energy."""
from math import isfinite

import pytest

from lpa.thermal import analyze_thermal
from lpa.thermal import coolants
from tests.test_release_thermal_fixes import cylinder, gas, regen, settings


@pytest.mark.parametrize("name,inlet_temperature,mass_flow,gas_temperature", [
    ("LNG",150.,.04,1500.),
    ("Ethanol (70%)",293.15,.02,2500.),
])
def test_full_channel_crosses_bubble_high_quality_and_dew_without_losing_energy(
        name,inlet_temperature,mass_flow,gas_temperature):
    segment=regen()
    segment["coolant"].update(coolant=name,inlet_temperature_k=inlet_temperature,
        inlet_pressure_bar=25.,mass_flow_kg_s=mass_flow)
    result=analyze_thermal(cylinder(),gas(gas_temperature),[segment],settings())
    assert result.metadata["wall_solution_complete"]
    assert all(isfinite(value) for value in result.Twg)
    assert {"liquid","two_phase","gas"} <= set(result.coolant_phase)
    two_phase=[i for i,phase in enumerate(result.coolant_phase) if phase=="two_phase"]
    quality=[result.coolant_vapor_quality[i] for i in two_phase]
    assert quality==sorted(quality) and .7 < max(quality) < 1
    for i in two_phase:
        assert result.coolant_wet_wall_assumed[i] is True
        assert result.coolant_temperature_glide_k[i] > 0
        assert 0 < result.coolant_boiling_mass_transfer_factor[i] <= 1
        assert 0 < result.coolant_boiling_convective_factor[i] <= 1
    balance=result.metadata["energy_balance_by_segment"]["water"]
    assert abs(balance["residual_w"]) < 1e-3
    assert result.coolant_outlet_phase["water"]=="gas"
    assert result.physical_validity!="valid"
    assert any("dryout" in issue and "NOT predicted" in issue for issue in result.physical_issues)
    assert not result.metadata["model_capabilities"]["critical_heat_flux"]
    assert not result.metadata["model_capabilities"]["dryout"]
    assert not any("subcooled boiling" in issue for issue in result.physical_issues
                   if "gas" in issue)


def test_aqueous_local_dew_pq_failure_is_recovered_on_same_equilibrium_qt_surface():
    # The native PQ solver fails at this real channel state; QT remains regular.
    state=coolants.coolant_state_from_quality("Ethanol (70%)",2497142.685327566,.5378516545638293)
    assert not any("unavailable" in issue for issue in state.mixture_boiling_property_issues)
    assert state.mixture_liquid_bubble_temperature_k == pytest.approx(state.temperature_k,abs=1e-4)
    assert state.mixture_liquid_dew_temperature_k > state.temperature_k


def test_mixture_transport_failure_does_not_silently_reuse_native_finite_values(monkeypatch):
    import lpa.thermal.mixture_transport as transport
    def unavailable(**kwargs):
        raise ValueError("test provider failure")
    monkeypatch.setattr(transport,"lng_ecs_transport",unavailable)
    single=coolants.coolant_state("LNG",150.,25e5)
    assert single.property_applicability=="unsupported"
    two_phase=coolants.coolant_state_from_quality("LNG",25e5,.2)
    assert two_phase.property_applicability=="unsupported"
    assert two_phase.saturated_liquid.transport_applicability=="unsupported"


def test_mixture_and_global_disable_controls_stop_the_first_two_phase_wall():
    segment=regen()
    segment["coolant"].update(coolant="LNG",inlet_temperature_k=150.,
        inlet_pressure_bar=25.,mass_flow_kg_s=.04)
    for options in ({"mixture_boiling_model":"disabled"},{"two_phase_model":"disabled"}):
        result=analyze_thermal(cylinder(),gas(1500.),[segment],settings(**options))
        first=result.coolant_flow_regime.index("unsupported_two_phase")
        assert result.coolant_phase[first]=="two_phase"
        assert all(not isfinite(value) for value in result.Twg[first:])
        assert result.physical_validity=="unsupported"
