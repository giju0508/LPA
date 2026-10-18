"""Reactant sensible enthalpy relative to the supplied CEA formation anchors.

CoolProp enthalpy has an arbitrary reference: only differences relative to the
matching pure reference states are added to CEA's chemical enthalpy. The LNG
blend uses one common temperature and the mixture EOS, retaining its mass and
elemental composition. Screening surrogates explicitly carry their provenance.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from math import isfinite

from .composition import aqueous_composition


# (formula, molecular weight kg/kmol, CEA h kJ/mol, reference T K, EOS fluid,
#  reference phase). Values match RocketCEA 1.2.3 input_cards.
PURE_STATES = {
    "LOX": ("O 2", 31.9988, -12.978768, 90.18, "Oxygen", "liquid"),
    "GOX": ("O 2", 31.9988, 0.0, 298.15, "Oxygen", "gas"),
    "N2O": ("N 2 O 1", 44.0128, 61.015272, 184.4, "NitrousOxide", "liquid"),
    "LCH4": ("C 1 H 4", 16.04246, -89.49576, 111.66, "Methane", "liquid"),
    "GCH4": ("C 1 H 4", 16.04246, -74.87268, 298.15, "Methane", "gas"),
    "LH2": ("H 2", 2.01588, -9.012336, 20.27, "Hydrogen", "liquid"),
    "GH2": ("H 2", 2.01588, 0.0, 298.15, "Hydrogen", "gas"),
    "Propane": ("C 3 H 8", 44.09562, -127.076448, 231.08, "Propane", "liquid"),
    "RP-1": ("C 1 H 1.9423", 13.968401862, -22.71912, 298.15, None, "liquid"),
    "Jet A-1": ("C 12 H 23", 167.31102, -303.2002544, 298.15, None, "liquid"),
}


def _reference_h(cp, fluid: str, temperature: float, phase: str) -> float:
    if phase == "liquid" and fluid not in {"Water", "Ethanol"}:
        return cp.PropsSI("Hmass", "T", temperature, "Q", 0, fluid)
    return cp.PropsSI("Hmass", "T", temperature, "P", 101325.0, fluid)


def _token(value: float) -> str:
    return f"{value:.12g}".replace(".", "p").replace("-", "m")


def _mixture_pt(state, cp, pressure: float, temperature: float) -> None:
    # Select the stable compressed-liquid branch only when the EOS bubble
    # pressure confirms it. An unconditional imposed liquid phase can return
    # metastable properties and is deliberately not used.
    liquid = False
    try:
        state.update(cp.QT_INPUTS, 0.0, temperature)
        liquid = pressure > state.p() * (1.0 + 1.e-6)
    except ValueError:
        pass
    if liquid:
        state.specify_phase(cp.iphase_liquid)
    try:
        state.update(cp.PT_INPUTS, pressure, temperature)
        if not isfinite(state.hmass()) or not isfinite(state.cpmass()) or state.cpmass() <= 0:
            raise ValueError("mixture EOS returned an invalid thermodynamic root")
        # Catch the known erroneous HEOS LNG root (~ -3 GJ/kg at 112 K).
        # This is a broad corruption guard, not a physical validity range.
        if abs(state.hmass()) > 5.e7:
            raise ValueError("mixture EOS enthalpy root is outside the reference scale; supply state unsupported")
    finally:
        state.unspecify_phase()


@lru_cache(maxsize=256)
def adjust_supply_spec(spec, temperature_k: float | None, pressure_bar: float | None):
    """Return an assigned-enthalpy CEA card and auditable state metadata."""
    aqueous = aqueous_composition(spec.display_name)
    lng = spec.display_name == "LNG"
    if temperature_k is None and pressure_bar is None and not lng:
        if spec.display_name == "LH2":
            return replace(spec, enthalpy_model="legacy liquid-H2 CEA NBP anchor; spin-state reference differs from normal-H2 EOS",
                warnings=("Legacy LH2 CEA liquid reference is retained; hydrogen spin conversion is unvalidated. Explicit supply T/P uses the normal-H2 EOS common gas reference.",))
        return spec
    if temperature_k is not None and (not isfinite(temperature_k) or temperature_k <= 0):
        raise ValueError("reactant supply temperature must be finite and positive")
    if pressure_bar is not None and (not isfinite(pressure_bar) or pressure_bar <= 0):
        raise ValueError("reactant supply pressure must be finite and positive")
    from CoolProp import CoolProp as cp

    pressure = (500000.0 if lng else 101325.0) if pressure_bar is None else pressure_bar * 100000.0
    warnings = []
    if lng:
        from .propellants import LNG_COMPONENTS, LNG_MASS_FRACTIONS
        temperature = 111.66 if temperature_k is None else temperature_k
        # A dissolved component does not have a separate pure-liquid state at
        # the common mixture T. Use the overall mixture h, referenced to the
        # original pure liquid anchors, and allocate that same J/kg increment
        # to the elemental cards. This preserves the blend's total enthalpy.
        fluids = ("Methane", "Ethane", "Propane", "n-Butane", "Nitrogen")
        state = cp.AbstractState("HEOS", "&".join(fluids))
        state.set_mole_fractions([row[1] for row in LNG_COMPONENTS])
        _mixture_pt(state, cp, pressure, temperature)
        if state.phase() == cp.iphase_twophase:
            raise ValueError("LNG supply is two-phase; specify a single-phase reactant state")
        reference = sum(
            LNG_MASS_FRACTIONS[row[0]] * _reference_h(cp, fluid, row[5], "liquid")
            for row, fluid in zip(LNG_COMPONENTS, fluids)
        )
        increment = state.hmass() - reference
        card = "".join(
            f"fuel {row[0]}(LNG) {row[3]} wt%={100 * LNG_MASS_FRACTIONS[row[0]]:.12g}\n"
            f" h,kj/mol={row[4] + increment * row[2] / 1.e6:.10g} t(k)={temperature:.12g}\n"
            for row in LNG_COMPONENTS
        )
        model = "CoolProp HEOS LNG mixture relative to pure liquid CEA anchors"
        warnings.append("LNG reactant enthalpy uses the representative mixture EOS; supplier composition and mixing accuracy require validation.")
        if pressure_bar is None:
            warnings.append("LNG uses a common 111.66 K / 5 bar reference state; specify actual supply temperature and pressure to include feed-state enthalpy.")
    elif aqueous:
        from .propellants import _AQUEOUS_DATA
        base, fraction = aqueous
        fraction = 1.0 if fraction is None else fraction
        temperature = 298.15 if temperature_k is None else temperature_k
        _, formula, hf = _AQUEOUS_DATA[base]
        molecular_weight = {"Ethanol": 46.06844, "IPA": 60.09502, "H2O2": 34.01468}[base]
        if base == "Ethanol":
            if fraction == 1.0:
                increment = cp.PropsSI("Hmass", "T", temperature, "P", pressure, "Ethanol") - _reference_h(cp, "Ethanol", 298.15, "liquid")
            else:
                state = cp.AbstractState("HEOS", "Ethanol&Water")
                state.set_mass_fractions([fraction, 1.0 - fraction])
                _mixture_pt(state, cp, pressure, temperature)
                if state.phase() == cp.iphase_twophase:
                    raise ValueError("aqueous ethanol supply is two-phase; specify a single-phase reactant state")
                increment = state.hmass() - (
                    fraction * _reference_h(cp, "Ethanol", 298.15, "liquid")
                    + (1.0 - fraction) * _reference_h(cp, "Water", 298.15, "liquid")
                )
                warnings.append("Ethanol/water reactant enthalpy includes the HEOS mixture increment; concentrated-solution accuracy is screening pending experiment.")
            model = "CoolProp HEOS relative enthalpy"
        else:
            if not 250.0 <= temperature <= 400.0:
                raise ValueError(f"{base} sensible-enthalpy screening model supports 250–400 K; an experimental reactant card is required outside this range")
            estimated_cp = fraction * ({"IPA": 2680.0, "H2O2": 2620.0}[base]) + (1.0 - fraction) * 4182.0
            increment = estimated_cp * (temperature - 298.15)
            model = "screening constant-cp sensible enthalpy; no excess mixing heat"
            warnings.append(f"{base}/water supply enthalpy is screening: no validated EOS or mixing heat; pressure enthalpy and chemical decomposition are excluded.")
        prefix = "oxid" if spec.kind == "oxidizer" else "fuel"
        card = (
            f"{prefix} {base}(solution) {formula} wt%={100 * fraction:.12g}\n"
            f" h,kj/mol={hf + increment * molecular_weight / 1.e6:.10g} t(k)={temperature:.12g}\n"
        )
        if fraction < 1.0:
            card += (
                f"{prefix} WATER(solution) H 2 O 1 wt%={100 * (1-fraction):.12g}\n"
                f" h,kj/mol={-285.830 + increment * 18.01528 / 1.e6:.10g} t(k)={temperature:.12g}\n"
            )
    else:
        formula, mw, hf, reference_temperature, fluid, phase = PURE_STATES[spec.display_name]
        temperature = reference_temperature if temperature_k is None else temperature_k
        if fluid is None:
            if not 250.0 <= temperature <= 600.0:
                raise ValueError("kerosene sensible-enthalpy surrogate supports 250–600 K; a measured reactant enthalpy is required")
            increment = 2050.0 * (temperature - reference_temperature)
            model = "screening kerosene sensible enthalpy"
            warnings.append("Kerosene supply enthalpy uses a constant-cp surrogate; fuel lot, pressure correction and thermal cracking are unvalidated.")
        else:
            actual_phase = cp.PhaseSI("T", temperature, "P", pressure, fluid)
            if actual_phase == "twophase":
                raise ValueError("reactant supply is two-phase; specify a single-phase state")
            increment = cp.PropsSI("Hmass", "T", temperature, "P", pressure, fluid) - _reference_h(cp, fluid, reference_temperature, phase)
            model = "CoolProp HEOS relative enthalpy"
            if spec.display_name in {"LH2", "GH2"}:
                # A liquid-H2 formation anchor combined with normal-H2's EOS
                # leaves a ~538 kJ/kg spin/reference offset at the same gas
                # T/P. Explicit states share the normal-H2 room-gas anchor,
                # matching the coolant EOS. Legacy blank LH2 stays separately
                # labeled; para/ortho conversion heat is not predicted.
                increment = cp.PropsSI("Hmass", "T", temperature, "P", pressure, "Hydrogen") - cp.PropsSI("Hmass", "T", 298.15, "P", 101325.0, "Hydrogen")
                hf = 0.0
                model = "normal-H2 HEOS relative to common 298.15 K gas CEA anchor"
                warnings.append("Explicit hydrogen supply uses normal-H2 EOS and a common room-gas enthalpy reference; para/ortho conversion heat and kinetics require separate validation.")
        prefix = "oxid" if spec.kind == "oxidizer" else "fuel"
        card = (
            f"{prefix} {spec.display_name}(supply) {formula} wt%=100\n"
            f" h,kj/mol={hf + increment * mw / 1.e6:.10g} t(k)={temperature:.12g}\n"
        )
    return replace(
        spec, cea_name=f"{spec.cea_name}_T{_token(temperature)}_P{_token(pressure / 1.e5)}",
        registration_card=card, supply_temperature_k=temperature,
        supply_pressure_bar=pressure / 1.e5, enthalpy_model=model, warnings=tuple(warnings),
    )
