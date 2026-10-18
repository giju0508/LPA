"""CEA reactant states and explicitly approximate fallback chemistry.

References and limitations: docs/PROPELLANT_AUDIT.md. Aqueous fractions and
O/F refer to the mass of the complete supplied streams, including water.
"""

from __future__ import annotations

from dataclasses import dataclass

from .composition import aqueous_composition, mass_fraction, solution_name
from .models import Coolant, Fuel, Oxidizer


@dataclass(frozen=True, slots=True)
class PropellantSpec:
    display_name: str
    cea_name: str
    phase: str
    kind: str
    water_mass_fraction: float = 0.0
    registration_card: str | None = None
    supply_temperature_k: float | None = None
    supply_pressure_bar: float | None = None
    enthalpy_model: str = "standard CEA reactant reference"
    warnings: tuple[str, ...] = ()


# Match the pure RocketCEA liquid cards at the 100% endpoint. IPA needs its
# own card: RocketCEA 1.2.3's Isopropanol enthalpy is for GAS (-272.516 kJ/mol).
_AQUEOUS_DATA = {
    "H2O2": ("oxidizer", "H 2 O 2", -187.77792),
    "Ethanol": ("fuel", "C 2 H 6 O 1", -277.69108),
    "IPA": ("fuel", "C 3 H 8 O 1", -318.2),
}


def _aqueous_spec(base: str, fraction: float) -> PropellantSpec:
    fraction = mass_fraction(fraction)
    kind, formula, enthalpy = _AQUEOUS_DATA[base]
    percent = 100.0 * fraction
    # A composition-specific name prevents RocketCEA's global cache from
    # reusing a different concentration. Preserve fractional percentages.
    token = f"{percent:.12g}".replace(".", "p").replace("-", "m")
    name = f"LPA_{base.upper()}_{token}"
    prefix = "oxid" if kind == "oxidizer" else "fuel"
    card = (
        f"{prefix} {base}(L) {formula} wt%={percent:.12g}\n"
        f" h,kj/mol={enthalpy:.8f} t(k)=298.15\n"
    )
    if fraction < 1.0:
        card += (
            f"{prefix} WATER(L) H 2 O 1 wt%={100.0 - percent:.12g}\n"
            " h,kj/mol=-285.830 t(k)=298.15\n"
        )
    return PropellantSpec(solution_name(base, fraction), name, "liquid", kind, 1.0 - fraction, card)


# Wärtsilä's typical commercial natural gas composition (volume = mole basis).
# Butane isomer is unspecified in the source; n-butane is the surrogate.
# (species, mole fraction, molecular weight, elements, liquid h [kJ/mol], T [K])
# Liquid reference states: RocketCEA input_cards / NASA CEA thermo.inp.
# This is an ideal reactant blend, not a cryogenic mixture equation of state.
LNG_COMPONENTS = (
    ("CH4", 0.940, 16.04246, "C 1 H 4", -89.49576, 111.66),
    ("C2H6", 0.047, 30.06904, "C 2 H 6", -103.750648, 184.56),
    ("C3H8", 0.008, 44.09562, "C 3 H 8", -127.076448, 231.08),
    ("nC4H10", 0.002, 58.12220, "C 4 H 10", -150.664, 272.638),
    ("N2", 0.003, 28.01340, "N 2", -12.107, 77.352),
)
LNG_MOLECULAR_WEIGHT = sum(row[1] * row[2] for row in LNG_COMPONENTS)
LNG_MASS_FRACTIONS = {row[0]: row[1] * row[2] / LNG_MOLECULAR_WEIGHT for row in LNG_COMPONENTS}
LNG_DESCRIPTION = "Typical LNG: CH4 94%, C2H6 4.7%, C3H8 0.8%, C4H10 0.2%, N2 0.3% (mol)"


def _lng_card() -> str:
    return "".join(
        f"fuel {name}(L) {elements} wt%={100.0 * LNG_MASS_FRACTIONS[name]:.12g}\n"
        f" h,kj/mol={enthalpy:.8f} t(k)={temperature:g}\n"
        for name, _, _, elements, enthalpy, temperature in LNG_COMPONENTS
    )


OXIDIZERS: dict[Oxidizer, PropellantSpec] = {
    Oxidizer.LOX: PropellantSpec("LOX", "LOX", "liquid", "oxidizer"),
    Oxidizer.GOX: PropellantSpec("GOX", "GOX", "gas", "oxidizer"),
    Oxidizer.H2O2: _aqueous_spec("H2O2", 1.0),
    # The bare N2O card describes 298 K gas; this selection is liquid.
    Oxidizer.N2O: PropellantSpec("N2O", "N2O_nbp", "liquid", "oxidizer"),
}
FUELS: dict[Fuel, PropellantSpec] = {
    Fuel.ETHANOL: _aqueous_spec("Ethanol", 1.0),
    Fuel.IPA: _aqueous_spec("IPA", 1.0),
    Fuel.LNG: PropellantSpec("LNG", "LPA_LNG_TYPICAL", "liquid", "fuel", registration_card=_lng_card()),
    Fuel.RP1: PropellantSpec("RP-1", "RP1", "liquid", "fuel"),
    Fuel.JET_A1: PropellantSpec("Jet A-1", "JetA", "liquid", "fuel"),
    Fuel.LCH4: PropellantSpec("LCH4", "CH4", "liquid", "fuel"),
    Fuel.GCH4: PropellantSpec("GCH4", "GCH4", "gas", "fuel"),
    Fuel.LH2: PropellantSpec("LH2", "LH2", "liquid", "fuel"),
    Fuel.GH2: PropellantSpec("GH2", "GH2", "gas", "fuel"),
    Fuel.PROPANE: PropellantSpec("Propane", "C3H8", "liquid", "fuel"),
}
# Old public enum members remain readable; the engine model migrates them.
for _member in Oxidizer:
    if _member not in OXIDIZERS:
        _base, _fraction = aqueous_composition(_member)
        OXIDIZERS[_member] = _aqueous_spec(_base, _fraction)
for _member in Fuel:
    if _member not in FUELS:
        _base, _fraction = aqueous_composition(_member)
        FUELS[_member] = _aqueous_spec(_base, _fraction)

COOLANT_CEA_NAMES: dict[Coolant, str] = {
    **{Coolant[item.name]: spec.cea_name for item, spec in OXIDIZERS.items() if item.name in Coolant.__members__},
    **{Coolant[item.name]: spec.cea_name for item, spec in FUELS.items() if item.name in Coolant.__members__},
    Coolant.WATER: "H2O",
}


def propellant_specs(
    oxidizer: Oxidizer, fuel: Fuel,
    oxidizer_mass_fraction: float | None = None,
    fuel_mass_fraction: float | None = None,
    oxidizer_temperature_k: float | None = None,
    fuel_temperature_k: float | None = None,
    oxidizer_pressure_bar: float | None = None,
    fuel_pressure_bar: float | None = None,
) -> tuple[PropellantSpec, PropellantSpec]:
    specs = []
    for value, fraction, catalog in (
        (oxidizer, oxidizer_mass_fraction, OXIDIZERS), (fuel, fuel_mass_fraction, FUELS),
    ):
        aqueous = aqueous_composition(value)
        if aqueous:
            base, legacy = aqueous
            specs.append(_aqueous_spec(base, fraction if fraction is not None else (legacy if legacy is not None else 1.0)))
        else:
            specs.append(catalog[value])
    from .reactant_states import adjust_supply_spec
    return (
        adjust_supply_spec(specs[0], oxidizer_temperature_k, oxidizer_pressure_bar),
        adjust_supply_spec(specs[1], fuel_temperature_k, fuel_pressure_bar),
    )


def rocketcea_names(
    oxidizer: Oxidizer, fuel: Fuel,
    oxidizer_mass_fraction: float | None = None, fuel_mass_fraction: float | None = None,
    oxidizer_temperature_k: float | None = None, fuel_temperature_k: float | None = None,
    oxidizer_pressure_bar: float | None = None, fuel_pressure_bar: float | None = None,
) -> tuple[str, str]:
    ox, fu = propellant_specs(oxidizer, fuel, oxidizer_mass_fraction, fuel_mass_fraction,
                            oxidizer_temperature_k, fuel_temperature_k, oxidizer_pressure_bar, fuel_pressure_bar)
    return ox.cea_name, fu.cea_name


def registration_cards(
    oxidizer: Oxidizer, fuel: Fuel,
    oxidizer_mass_fraction: float | None = None, fuel_mass_fraction: float | None = None,
    oxidizer_temperature_k: float | None = None, fuel_temperature_k: float | None = None,
    oxidizer_pressure_bar: float | None = None, fuel_pressure_bar: float | None = None,
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (spec.kind, spec.cea_name, spec.registration_card)
        for spec in propellant_specs(oxidizer, fuel, oxidizer_mass_fraction, fuel_mass_fraction,
                                     oxidizer_temperature_k, fuel_temperature_k, oxidizer_pressure_bar, fuel_pressure_bar)
        if spec.registration_card
    )


@dataclass(frozen=True, slots=True)
class FallbackChemistry:
    optimum_mixture_ratio: float
    flame_temperature_k: float
    gamma: float
    molecular_weight_kg_kmol: float


_FUEL_CHEMISTRY = {
    Fuel.ETHANOL: (1.90, 3450.0, 22.0), Fuel.IPA: (2.15, 3500.0, 22.5),
    Fuel.RP1: (2.65, 3650.0, 23.0), Fuel.JET_A1: (2.60, 3600.0, 23.5),
    Fuel.LCH4: (3.45, 3550.0, 20.5), Fuel.GCH4: (3.45, 3580.0, 20.5),
    Fuel.LNG: (3.35, 3550.0, 21.0),
    Fuel.LH2: (5.50, 3500.0, 14.5), Fuel.GH2: (5.50, 3530.0, 14.5),
    Fuel.PROPANE: (3.05, 3600.0, 22.0),
}


def fallback_chemistry(
    oxidizer: Oxidizer, fuel: Fuel, mixture_ratio: float,
    oxidizer_mass_fraction: float | None = None, fuel_mass_fraction: float | None = None,
) -> FallbackChemistry:
    """Smooth screening estimates, never a substitute for chemical equilibrium.

    Oxygen-equivalent mass scales O/F: H2O2 releases 16/34 kg O2 per kg,
    N2O supplies 16/44. Water dilutes the complete fuel/oxidizer mass streams.
    """
    ox_spec, fuel_spec = propellant_specs(oxidizer, fuel, oxidizer_mass_fraction, fuel_mass_fraction)
    aqueous_fuel = aqueous_composition(fuel)
    base_fuel = Fuel(aqueous_fuel[0]) if aqueous_fuel else fuel
    base_mr, base_temperature, base_mw = _FUEL_CHEMISTRY[base_fuel]
    fuel_fraction = 1.0 - fuel_spec.water_mass_fraction
    ox_fraction = 1.0 - ox_spec.water_mass_fraction
    if aqueous_composition(oxidizer):
        oxygen_fraction = (15.9994 / 34.01468) * ox_fraction
        temperature_factor, mw_add = 0.96 * ox_fraction, 1.0 + 8.0 * (1.0 - ox_fraction)
    elif oxidizer == Oxidizer.N2O:
        oxygen_fraction = 15.9994 / 44.0128
        temperature_factor, mw_add = 0.90, 2.0
    else:
        oxygen_fraction = 1.0
        temperature_factor, mw_add = (1.005 if oxidizer == Oxidizer.GOX else 1.0), 0.0
    optimum = base_mr * fuel_fraction / oxygen_fraction
    ratio = mixture_ratio / max(optimum, 1e-12)
    off_optimum = min(0.60, 0.16 * abs(ratio - 1.0) ** 1.25)
    temperature = 298.15 + (base_temperature - 298.15) * temperature_factor * fuel_fraction * (1.0 - off_optimum)
    molecular_weight = base_mw + mw_add + 5.0 * (1.0 - fuel_fraction) + min(4.0, 1.5 * abs(ratio - 1.0))
    gamma = max(1.12, min(1.28, 1.235 - 0.0032 * (molecular_weight - 18.0)))
    return FallbackChemistry(optimum, temperature, gamma, molecular_weight)
