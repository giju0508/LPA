"""Independent RP-1 evidence checks, thermodynamic closure and range rejection."""
from math import isfinite

import CoolProp.CoolProp as CP
import pytest

from lpa.thermal.rp1_surrogate import (
    _conductivity, register_trans_decalin, rp1_surrogate_estimate,
    rp1_surrogate_from_enthalpy, surrogate_bubble_temperature,
)
from lpa.thermal.rp1_properties import CONDUCTIVITY_DATA


@pytest.mark.parametrize("temperature",[293.,400.,600.])
def test_public_constituent_eos_saturation_has_equal_gibbs_energy(temperature):
    # Catches the almost-vacuum QT solution produced by inaccurate initial
    # ancillaries, which can otherwise have a plausible liquid density.
    state=CP.AbstractState("HEOS",register_trans_decalin())
    state.update(CP.QT_INPUTS,0.,temperature)
    hl=state.saturated_liquid_keyed_output(CP.iHmolar)
    hv=state.saturated_vapor_keyed_output(CP.iHmolar)
    sl=state.saturated_liquid_keyed_output(CP.iSmolar)
    sv=state.saturated_vapor_keyed_output(CP.iSmolar)
    assert state.p()>1.
    assert hl-temperature*sl==pytest.approx(hv-temperature*sv,abs=2e-4)


@pytest.mark.parametrize("temperature,pressure,density",[
    # Outcalt et al. (2009), Table 2; none of these were in the 12-point fit.
    (270.,5e6,824.8),(270.,20e6,833.2),
    (330.,3e6,780.4),(390.,15e6,749.5),(430.,30e6,738.2),(450.,4e6,692.),
])
def test_density_holdouts_are_independent_of_fitted_temperatures_and_pressures(temperature,pressure,density):
    state=rp1_surrogate_estimate(temperature,pressure)
    assert state["density_kg_m3"]==pytest.approx(density,rel=.008)


@pytest.mark.parametrize("temperature,pressure,cp",[
    # Independent approximate graph readings, not claims of exact source-table
    # values: Fuel2011 Fig2. Low-resolution readings carry several percent
    # uncertainty; a predictive surrogate's agreement is checked to 8%.
    (535.32,20e6,2890.),(576.63,20e6,3080.),(633.84,20e6,3290.),
    (535.32,40e6,2860.),(576.63,40e6,3000.),(633.84,40e6,3130.),
])
def test_independent_high_temperature_heat_capacity_graph_checks(temperature,pressure,cp):
    state=rp1_surrogate_estimate(temperature,pressure)
    assert state["specific_heat_j_kgk"]==pytest.approx(cp,rel=.08)


def test_corrected_conductivity_high_temperature_holdout_was_not_used_in_fit():
    data=[(t,p,k) for _,t,p,k in CONDUCTIVITY_DATA if 550<=t<630 and p<=50]
    errors=[abs(_conductivity(t,p*1e6)/k-1.) for t,p,k in data]
    assert len(data)==50
    assert sum(errors)/len(errors)<.025
    assert max(errors)<.04


@pytest.mark.parametrize("temperature,pressure,viscosity_mpa_s",[
    # Official high-resolution Fuel2019 Fig3a filled-circle centers, independently
    # read; approximate T +/-2 K, viscosity +/-0.003 mPa s, not raw table values.
    (530.,10e6,.1905),(530.,20e6,.2107),
    (630.,10e6,.1231),(630.3,20e6,.1407),
])
def test_independent_high_temperature_viscosity_graph_holdouts(temperature,pressure,viscosity_mpa_s):
    state=rp1_surrogate_estimate(temperature,pressure)
    assert state["viscosity_pa_s"]*1e3==pytest.approx(viscosity_mpa_s,rel=.10)


@pytest.mark.parametrize("temperature",[293.,400.,600.,649.9])
def test_pressure_enthalpy_round_trip_and_heat_capacity_energy_identity(temperature):
    state=rp1_surrogate_estimate(temperature,2e6)
    inverse=rp1_surrogate_from_enthalpy(state["enthalpy_j_kg"],2e6,temperature_hint_k=300.)
    assert inverse["temperature_k"]==pytest.approx(temperature,abs=1e-7)
    assert inverse["enthalpy_j_kg"]==pytest.approx(state["enthalpy_j_kg"],abs=1e-4)
    if temperature<649.9:
        plus=rp1_surrogate_estimate(temperature+.001,2e6)
        minus=rp1_surrogate_estimate(temperature-.001,2e6)
        assert (plus["enthalpy_j_kg"]-minus["enthalpy_j_kg"])/.002 == pytest.approx(
            state["specific_heat_j_kgk"],rel=1e-7)
    assert all(isfinite(state[k]) and state[k]>0 for k in (
        "density_kg_m3","specific_heat_j_kgk","conductivity_w_mk","viscosity_pa_s"))


def test_surrogate_rejects_boiling_decomposition_and_out_of_range_enthalpy():
    assert surrogate_bubble_temperature(2e6)==pytest.approx(657.29338,abs=.002)
    for t,p in [(650.,2e6),(269.,2e6),(500.,.1e6),(300.,51e6)]:
        with pytest.raises(ValueError):rp1_surrogate_estimate(t,p)
    with pytest.raises(ValueError):rp1_surrogate_from_enthalpy(1e9,2e6)
