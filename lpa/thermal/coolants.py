"""Compact coolant property estimates for preliminary regenerative analysis.

The UI coolant definition intentionally contains only identity, inlet pressure,
temperature, and mass-flow fraction.  These values provide a deterministic
screening calculation when a dedicated property package is unavailable.  A
caller can override every property through ``settings.coolant_properties`` or
through equivalently named fields on a dictionary coolant definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite


@dataclass(frozen=True, slots=True)
class CoolantState:
    density_kg_m3: float
    specific_heat_j_kgk: float
    conductivity_w_mk: float
    viscosity_pa_s: float

    @property
    def prandtl(self) -> float:
        return self.specific_heat_j_kgk * self.viscosity_pa_s / self.conductivity_w_mk


@dataclass(frozen=True, slots=True)
class CoolantPropertyModel:
    name: str
    reference_temperature_k: float
    density_kg_m3: float
    specific_heat_j_kgk: float
    conductivity_w_mk: float
    viscosity_pa_s: float
    volumetric_expansion_per_k: float = 7.0e-4
    cp_slope_per_k: float = 2.0e-4
    conductivity_slope_per_k: float = -2.0e-4
    viscosity_decay_per_k: float = 1.0e-2
    notes: str = ""

    def at_temperature(self, temperature_k: float) -> CoolantState:
        temperature_k = float(temperature_k)
        if not isfinite(temperature_k) or temperature_k <= 0:
            raise ValueError("coolant temperature must be finite and positive")
        delta = temperature_k - self.reference_temperature_k
        density_factor = max(0.20, 1.0 - self.volumetric_expansion_per_k * delta)
        cp_factor = max(0.50, 1.0 + self.cp_slope_per_k * delta)
        conductivity_factor = max(0.35, 1.0 + self.conductivity_slope_per_k * delta)
        viscosity_factor = min(8.0, max(0.08, exp(-self.viscosity_decay_per_k * delta)))
        return CoolantState(
            density_kg_m3=self.density_kg_m3 * density_factor,
            specific_heat_j_kgk=self.specific_heat_j_kgk * cp_factor,
            conductivity_w_mk=self.conductivity_w_mk * conductivity_factor,
            viscosity_pa_s=self.viscosity_pa_s * viscosity_factor,
        )


# Representative compressed-liquid values near the listed reference
# temperatures.  Gas entries are explicitly marked and are necessarily more
# pressure-sensitive; projects should supply pressure-dependent overrides.
COOLANT_MODELS: dict[str, CoolantPropertyModel] = {
    "H2O": CoolantPropertyModel(
        "H2O", 293.15, 998.0, 4182.0, 0.598, 1.00e-3,
        notes="Liquid water near 1 bar and 20 C.",
    ),
    "LOX": CoolantPropertyModel(
        "LOX", 90.0, 1141.0, 1690.0, 0.151, 1.95e-4,
        volumetric_expansion_per_k=3.5e-3,
        viscosity_decay_per_k=2.0e-2,
        notes="Subcooled liquid oxygen screening values.",
    ),
    "GOX": CoolantPropertyModel(
        "GOX", 300.0, 25.0, 950.0, 0.030, 2.1e-5,
        volumetric_expansion_per_k=3.3e-3,
        viscosity_decay_per_k=-1.5e-3,
        notes="Representative high-pressure gaseous oxygen; override density at operating pressure.",
    ),
    "N2O": CoolantPropertyModel(
        "N2O", 285.0, 790.0, 1800.0, 0.105, 2.7e-4,
        volumetric_expansion_per_k=3.0e-3,
        notes="Compressed liquid nitrous oxide screening values.",
    ),
    "RP-1": CoolantPropertyModel(
        "RP-1", 293.15, 810.0, 2050.0, 0.135, 1.65e-3,
        notes="Representative rocket kerosene values.",
    ),
    "Jet A-1": CoolantPropertyModel(
        "Jet A-1", 293.15, 800.0, 2050.0, 0.130, 1.50e-3,
        notes="Representative aviation kerosene values.",
    ),
    "LCH4": CoolantPropertyModel(
        "LCH4", 111.0, 423.0, 3480.0, 0.190, 1.18e-4,
        volumetric_expansion_per_k=3.0e-3,
        viscosity_decay_per_k=1.8e-2,
        notes="Saturated/subcooled liquid methane screening values.",
    ),
    "GCH4": CoolantPropertyModel(
        "GCH4", 300.0, 20.0, 2300.0, 0.050, 1.15e-5,
        volumetric_expansion_per_k=3.3e-3,
        viscosity_decay_per_k=-1.8e-3,
        notes="Representative high-pressure methane gas; density override recommended.",
    ),
    "LH2": CoolantPropertyModel(
        "LH2", 21.0, 71.0, 9700.0, 0.105, 1.30e-5,
        volumetric_expansion_per_k=1.5e-2,
        viscosity_decay_per_k=2.0e-2,
        notes="Subcooled liquid hydrogen screening values.",
    ),
    "GH2": CoolantPropertyModel(
        "GH2", 300.0, 8.0, 14300.0, 0.180, 8.9e-6,
        volumetric_expansion_per_k=3.3e-3,
        viscosity_decay_per_k=-2.0e-3,
        notes="Representative high-pressure hydrogen gas; density override recommended.",
    ),
    "Propane": CoolantPropertyModel(
        "Propane", 250.0, 540.0, 2500.0, 0.120, 2.0e-4,
        volumetric_expansion_per_k=2.7e-3,
        notes="Compressed liquid propane screening values.",
    ),
    "Ethanol (70%)": CoolantPropertyModel(
        "Ethanol (70%)", 293.15, 860.0, 3300.0, 0.300, 2.4e-3,
        notes="70 percent ethanol-water mixture by mass, screening values.",
    ),
    "Ethanol (80%)": CoolantPropertyModel(
        "Ethanol (80%)", 293.15, 835.0, 3000.0, 0.250, 2.0e-3,
        notes="80 percent ethanol-water mixture by mass, screening values.",
    ),
    "Ethanol (90%)": CoolantPropertyModel(
        "Ethanol (90%)", 293.15, 810.0, 2700.0, 0.205, 1.6e-3,
        notes="90 percent ethanol-water mixture by mass, screening values.",
    ),
    "Ethanol (100%)": CoolantPropertyModel(
        "Ethanol (100%)", 293.15, 789.0, 2440.0, 0.171, 1.20e-3,
        notes="Anhydrous ethanol near 20 C.",
    ),
    "H2O2 (70%)": CoolantPropertyModel(
        "H2O2 (70%)", 293.15, 1290.0, 3000.0, 0.500, 1.35e-3,
        notes="70 percent hydrogen-peroxide solution screening values.",
    ),
    "H2O2 (80%)": CoolantPropertyModel(
        "H2O2 (80%)", 293.15, 1340.0, 2850.0, 0.525, 1.30e-3,
        notes="80 percent hydrogen-peroxide solution screening values.",
    ),
    "H2O2 (90%)": CoolantPropertyModel(
        "H2O2 (90%)", 293.15, 1390.0, 2720.0, 0.550, 1.25e-3,
        notes="90 percent hydrogen-peroxide solution screening values.",
    ),
    "H2O2 (100%)": CoolantPropertyModel(
        "H2O2 (100%)", 293.15, 1450.0, 2620.0, 0.580, 1.20e-3,
        notes="Anhydrous hydrogen peroxide screening values.",
    ),
}


_ALIASES = {
    "water": "H2O",
    "h2o": "H2O",
    "lox": "LOX",
    "gox": "GOX",
    "n2o": "N2O",
    "rp1": "RP-1",
    "jeta1": "Jet A-1",
    "lch4": "LCH4",
    "gch4": "GCH4",
    "lh2": "LH2",
    "gh2": "GH2",
    "propane": "Propane",
    "ethanol70": "Ethanol (70%)",
    "ethanol80": "Ethanol (80%)",
    "ethanol90": "Ethanol (90%)",
    "ethanol100": "Ethanol (100%)",
    "h2o270": "H2O2 (70%)",
    "h2o280": "H2O2 (80%)",
    "h2o290": "H2O2 (90%)",
    "h2o2100": "H2O2 (100%)",
}


def _normalise_name(value: object) -> str:
    value = getattr(value, "value", value)
    return "".join(character for character in str(value).casefold() if character.isalnum())


def get_coolant_model(name: object) -> CoolantPropertyModel:
    key = _ALIASES.get(_normalise_name(name))
    if key is None:
        options = ", ".join(COOLANT_MODELS)
        raise KeyError(f"unknown coolant {name!r}; choose one of: {options}")
    return COOLANT_MODELS[key]
