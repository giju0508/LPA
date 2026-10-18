"""TRAPP checks against the independent published TN1039 sample outputs.

The example densities are supplied rather than recalculated: LPA deliberately
uses a separate phase EOS. Modern pure ideal-gas Cp/critical data also differ
slightly from the 1981 component library, especially dilute-gas conductivity.
"""

from dataclasses import replace
from math import isfinite, nan

import CoolProp.CoolProp as CP
import pytest

from lpa.thermal.mixture_transport import TransportComponent, _coolprop_component, lng_ecs_transport


def transport(temperature, mass_density, components=("Methane",), fractions=(1.,)):
    molar_mass = sum(x * CP.PropsSI("M", fluid) for x, fluid in zip(fractions, components))
    return lng_ecs_transport(temperature_k=temperature, molar_density_mol_m3=mass_density / molar_mass,
                             components=components, mole_fractions=fractions)


@pytest.mark.parametrize("temperature,density,viscosity,conductivity", [
    (100., 439.219, 1482.3e-7, .21842),
    (120., 1.654, 48.2e-7, .01471),
    (120., 410.533, 971.3e-7, .17804),
    (140., 377.755, 673.5e-7, .14425),
    (190., 239.837, 239.7e-7, .07190),
])
def test_tn1039_table_a2_methane_published_si_examples(temperature, density, viscosity, conductivity):
    result = transport(temperature, density)
    assert result.viscosity_pa_s == pytest.approx(viscosity, rel=.001)
    # Ideal-gas Cp was updated from the report's polynomial to modern HEOS Cp0.
    assert result.conductivity_w_mk == pytest.approx(conductivity, rel=.015)
    assert result.reference_temperature_k == pytest.approx(temperature)


@pytest.mark.parametrize("fractions,temperature_f,density_lb_ft3,viscosity_lb_ft_h,conductivity_btu_ft_h_f", [
    ((.3, .1, .6), 400., 2.8122, .053292, .02700),
    ((.3, .1, .6), -100., 12.4563, .040324, .02040),
    ((.3, .1, .6), -300., 44.8939, .553857, .11165),
    ((.7, .05, .25), 77., .0523, .030090, .01912),
    ((.7, .05, .25), 77., 12.4219, .051985, .03323),
])
def test_tn1039_table_a3_mixture_published_imperial_examples(
        fractions, temperature_f, density_lb_ft3, viscosity_lb_ft_h, conductivity_btu_ft_h_f):
    # Exact physical unit conversions, independent of the implementation.
    temperature = (temperature_f - 32.0) * 5.0 / 9.0 + 273.15
    density = density_lb_ft3 * .45359237 / .3048 ** 3
    viscosity = viscosity_lb_ft_h * .45359237 / (.3048 * 3600.)
    conductivity = conductivity_btu_ft_h_f * 1055.05585262 / (.3048 * 3600. * (5.0 / 9.0))
    result = transport(temperature, density, ("Methane", "Propane", "Nitrogen"), fractions)
    assert result.viscosity_pa_s == pytest.approx(viscosity, rel=.01)
    assert result.conductivity_w_mk == pytest.approx(conductivity, rel=.025)


def test_lng_liquid_at_previous_native_nan_has_finite_positive_transport():
    components = ("Methane", "Ethane", "Propane", "n-Butane", "Nitrogen")
    fractions = (.94, .047, .008, .002, .003)
    phase = CP.AbstractState("HEOS", "&".join(components))
    phase.set_mole_fractions(fractions)
    phase.specify_phase(CP.iphase_liquid)
    phase.update(CP.PT_INPUTS, 25e5, 150.)
    # The old native log-mixing path evaluated propane at mixture rhomolar.
    assert not isfinite(phase.viscosity())
    result = lng_ecs_transport(temperature_k=150., molar_density_mol_m3=phase.rhomolar(),
                               components=components, mole_fractions=fractions)
    assert 5e-5 < result.viscosity_pa_s < 8e-5
    assert .12 < result.conductivity_w_mk < .16
    assert result.property_applicability == "correlated"
    assert result.validation_status == "screening"
    assert "Supplied phase density" in " ".join(result.issues)
    assert result.references


def test_phase_composition_and_component_order_are_respected():
    inputs = dict(temperature_k=180., molar_density_mol_m3=16000.)
    liquid = lng_ecs_transport(**inputs, components=("Methane", "Ethane"), mole_fractions=(.9, .1))
    reordered = lng_ecs_transport(**inputs, components=("Ethane", "Methane"), mole_fractions=(.1, .9))
    vapor = lng_ecs_transport(**inputs, components=("Methane", "Ethane"), mole_fractions=(.99, .01))
    assert reordered.viscosity_pa_s == pytest.approx(liquid.viscosity_pa_s, rel=1e-12)
    assert reordered.conductivity_w_mk == pytest.approx(liquid.conductivity_w_mk, rel=1e-12)
    assert vapor.viscosity_pa_s != pytest.approx(liquid.viscosity_pa_s, rel=.001)
    assert vapor.conductivity_w_mk != pytest.approx(liquid.conductivity_w_mk, rel=.001)


def test_custom_nonpolar_component_input_does_not_require_a_registered_transport_model():
    original = _coolprop_component("Methane", 150.)
    custom = replace(original, name="supplied nonpolar methane reference")
    assert isinstance(custom, TransportComponent)
    given = lng_ecs_transport(temperature_k=150., molar_density_mol_m3=15000.,
                              components=(custom,), mole_fractions=(1.,))
    native = lng_ecs_transport(temperature_k=150., molar_density_mol_m3=15000.,
                               components=("Methane",), mole_fractions=(1.,))
    assert given.viscosity_pa_s == native.viscosity_pa_s
    assert given.conductivity_w_mk == native.conductivity_w_mk


@pytest.mark.parametrize("changes", [
    {"temperature_k": nan}, {"molar_density_mol_m3": 0.},
    {"mole_fractions": (.8,)}, {"mole_fractions": (-1.,)},
    {"components": ("Ethanol",)}, {"components": ("Water",)},
    {"temperature_k": 10.}, {"temperature_k": 2000.},
    {"molar_density_mol_m3": 1.e12},
    {"components": ("Methane", "Nitrogen")},
])
def test_invalid_or_outside_declared_model_inputs_raise_instead_of_clamping(changes):
    inputs = dict(temperature_k=150., molar_density_mol_m3=15000.,
                  components=("Methane",), mole_fractions=(1.,))
    inputs.update(changes)
    with pytest.raises(ValueError):
        lng_ecs_transport(**inputs)
