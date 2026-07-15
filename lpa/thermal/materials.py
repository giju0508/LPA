"""Temperature-dependent wall material data used by the thermal solver.

The tables are deliberately embedded so a frozen, single-file LPA executable
does not need a network connection.  Values are engineering data, not design
allowables.  Additive-manufactured alloys are especially sensitive to build
orientation and heat treatment; the source/condition metadata is therefore
kept with every table and exposed to the GUI.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from math import isfinite
from typing import Iterable


@dataclass(frozen=True, slots=True)
class MaterialReference:
    """Human-readable provenance for a material-property table."""

    title: str
    authors_or_organization: str
    year: int
    identifier: str
    url: str
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ThermalMaterial:
    """Piecewise-linear thermal-conductivity curve in SI units."""

    name: str
    temperatures_k: tuple[float, ...]
    conductivity_w_mk: tuple[float, ...]
    reference: MaterialReference
    manufacturing_condition: str

    def __post_init__(self) -> None:
        if len(self.temperatures_k) != len(self.conductivity_w_mk):
            raise ValueError("temperature and conductivity tables must have equal length")
        if len(self.temperatures_k) < 2:
            raise ValueError("a material table needs at least two points")
        if any(b <= a for a, b in zip(self.temperatures_k, self.temperatures_k[1:])):
            raise ValueError("material temperatures must be strictly increasing")
        if any(value <= 0 or not isfinite(value) for value in self.conductivity_w_mk):
            raise ValueError("thermal conductivity values must be finite and positive")

    @property
    def valid_temperature_range_k(self) -> tuple[float, float]:
        return self.temperatures_k[0], self.temperatures_k[-1]

    def conductivity(self, temperature_k: float, *, extrapolate: bool = False) -> float:
        """Return linearly interpolated conductivity.

        The default clamps to the measured/table range.  Extrapolation is
        opt-in because unconstrained high-temperature extrapolation is unsafe.
        """

        temperature_k = float(temperature_k)
        if not isfinite(temperature_k) or temperature_k <= 0:
            raise ValueError("temperature must be finite and positive")
        temperatures = self.temperatures_k
        values = self.conductivity_w_mk
        if temperature_k <= temperatures[0]:
            if not extrapolate:
                return values[0]
            left = 0
        elif temperature_k >= temperatures[-1]:
            if not extrapolate:
                return values[-1]
            left = len(temperatures) - 2
        else:
            left = bisect_right(temperatures, temperature_k) - 1
        fraction = (temperature_k - temperatures[left]) / (
            temperatures[left + 1] - temperatures[left]
        )
        return values[left] + fraction * (values[left + 1] - values[left])


def _k_from_celsius(values: Iterable[float]) -> tuple[float, ...]:
    return tuple(float(value) + 273.15 for value in values)


def _k_from_fahrenheit(values: Iterable[float]) -> tuple[float, ...]:
    return tuple((float(value) - 32.0) * 5.0 / 9.0 + 273.15 for value in values)


_CUCRZR_REFERENCE = MaterialReference(
    title=(
        "Effect of heat treatment on the microstructure and properties of "
        "CuCrZr prepared by laser powder bed fusion"
    ),
    authors_or_organization="X. Chen et al., Materials Characterization",
    year=2024,
    identifier="doi:10.1016/j.matchar.2024.114103",
    url="https://doi.org/10.1016/j.matchar.2024.114103",
    notes=(
        "The paper reports 314.3 +/- 5.3 W/(m K) after direct aging.  The "
        "embedded elevated-temperature curve is a rounded screening curve "
        "consistent with the reported LPBF electrical/thermal trend; verify "
        "the actual build and heat lot for detailed design."
    ),
)

_ALSI10MG_REFERENCE = MaterialReference(
    title=(
        "Thermophysical Properties of Laser Powder Bed Fused Ti-6Al-4V and "
        "AlSi10Mg Alloys Made with Varying Laser Parameters"
    ),
    authors_or_organization="S. Akwaboa et al., Materials",
    year=2023,
    identifier="doi:10.3390/ma16144920",
    url="https://doi.org/10.3390/ma16144920",
    notes=(
        "Figure 2f reports temperature-dependent L-PBF data. LPA uses the "
        "100 W, 0.2 m/s series; the 118.2 and 172.0 W/(m K) endpoints are "
        "reported by the authors and intermediate markers are rounded from "
        "the figure. Build parameters and porosity must be matched for design."
    ),
)

_IN625_REFERENCE = MaterialReference(
    title="INCONEL alloy 625 technical bulletin, Table 3",
    authors_or_organization="Special Metals Corporation",
    year=2013,
    identifier="SMC-063",
    url=(
        "https://www.specialmetals.com/documents/technical-bulletins/"
        "inconel/inconel-alloy-625.pdf"
    ),
    notes="Annealed 2100 F for one hour; measured by Battelle Memorial Institute.",
)

_IN718_REFERENCE = MaterialReference(
    title="INCONEL alloy 718 technical bulletin, Table 5",
    authors_or_organization="Special Metals Corporation",
    year=2007,
    identifier="SMC-045",
    url=(
        "https://www.specialmetals.com/documents/technical-bulletins/"
        "inconel/inconel-alloy-718.pdf"
    ),
    notes=(
        "Annealed and aged condition. Conductivity is calculated from the "
        "manufacturer's resistivity measurements."
    ),
)

_C103_REFERENCE = MaterialReference(
    title="C-103 Niobium Alloy, Alloy Digest Cb-25",
    authors_or_organization="ASM International",
    year=2000,
    identifier="doi:10.31399/asm.ad.cb0025",
    url="https://doi.org/10.31399/asm.ad.cb0025",
    notes=(
        "Rounded engineering values for Nb-10Hf-1Ti are used. Published "
        "C-103 data vary with product form and temperature history; verify "
        "the supplier heat for life or margin assessment."
    ),
)

_TI64_REFERENCE = MaterialReference(
    title="Prediction of Space Shuttle TPS panel heating, Table II",
    authors_or_organization="NASA",
    year=1989,
    identifier="NASA-TM-101660",
    url="https://ntrs.nasa.gov/citations/19900002976",
    notes="Table II temperature-dependent data for a Ti-6Al-4V panel.",
)


MATERIALS: dict[str, ThermalMaterial] = {
    "CuCrZr": ThermalMaterial(
        name="CuCrZr",
        temperatures_k=_k_from_celsius((20, 100, 200, 300, 400, 500, 600, 700)),
        conductivity_w_mk=(314.3, 318.0, 323.0, 328.0, 333.0, 337.0, 341.0, 344.0),
        reference=_CUCRZR_REFERENCE,
        manufacturing_condition="LPBF, direct aged at 450 C",
    ),
    "IN625": ThermalMaterial(
        name="IN625",
        temperatures_k=_k_from_celsius((-18, 21, 38, 93, 204, 316, 427, 538, 649, 760, 871, 982)),
        conductivity_w_mk=(9.2, 9.8, 10.1, 10.8, 12.5, 14.1, 15.7, 17.5, 19.0, 20.8, 22.8, 25.2),
        reference=_IN625_REFERENCE,
        manufacturing_condition="Wrought, annealed at 1149 C for one hour",
    ),
    "IN718": ThermalMaterial(
        name="IN718",
        temperatures_k=_k_from_fahrenheit((70, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000)),
        conductivity_w_mk=(11.39, 12.55, 14.42, 16.15, 17.88, 19.61, 21.35, 23.22, 24.95, 26.83, 28.70),
        reference=_IN718_REFERENCE,
        manufacturing_condition="Wrought, solution annealed and aged",
    ),
    "AlSi10Mg": ThermalMaterial(
        name="AlSi10Mg",
        temperatures_k=_k_from_celsius((100, 200, 300, 400)),
        conductivity_w_mk=(118.2, 144.0, 165.0, 172.0),
        reference=_ALSI10MG_REFERENCE,
        manufacturing_condition="LPBF, as-built, 100 W and 0.2 m/s scan speed",
    ),
    "C103": ThermalMaterial(
        name="C103",
        temperatures_k=_k_from_celsius((20, 200, 400, 600, 800, 1000, 1200, 1400, 1600)),
        conductivity_w_mk=(37.0, 39.0, 41.5, 44.0, 47.0, 50.5, 54.0, 58.0, 62.0),
        reference=_C103_REFERENCE,
        manufacturing_condition="Wrought Nb-10Hf-1Ti engineering curve",
    ),
    "Ti64": ThermalMaterial(
        name="Ti64",
        temperatures_k=(300.0, 311.0, 350.0, 400.0, 450.0, 500.0, 550.0, 589.0, 600.0, 650.0, 700.0, 750.0, 800.0, 850.0, 900.0, 950.0, 1000.0, 1100.0),
        conductivity_w_mk=(7.27, 7.39, 7.70, 8.22, 8.83, 9.40, 10.02, 10.59, 10.70, 11.16, 11.77, 12.37, 12.98, 13.53, 14.19, 14.75, 15.30, 15.92),
        reference=_TI64_REFERENCE,
        manufacturing_condition="Conventional Ti-6Al-4V panel",
    ),
}


_ALIASES = {
    "cucrzr": "CuCrZr",
    "cucr1zr": "CuCrZr",
    "in625": "IN625",
    "inconel625": "IN625",
    "in718": "IN718",
    "inconel718": "IN718",
    "alsi10mg": "AlSi10Mg",
    "c103": "C103",
    "nbc103": "C103",
    "ti64": "Ti64",
    "ti6al4v": "Ti64",
}


def _normalise_name(name: object) -> str:
    value = getattr(name, "value", name)
    return "".join(character for character in str(value).casefold() if character.isalnum())


def get_material(name: object) -> ThermalMaterial:
    """Look up a material using UI enum values or common aliases."""

    key = _ALIASES.get(_normalise_name(name))
    if key is None:
        options = ", ".join(MATERIALS)
        raise KeyError(f"unknown thermal material {name!r}; choose one of: {options}")
    return MATERIALS[key]


def thermal_conductivity(name: object, temperature_k: float) -> float:
    """Convenience wrapper used by the wall solver."""

    return get_material(name).conductivity(temperature_k)


def material_reference_metadata() -> dict[str, dict[str, object]]:
    """Return serialisable property provenance for reports/project exports."""

    return {
        name: {
            "title": material.reference.title,
            "authors_or_organization": material.reference.authors_or_organization,
            "year": material.reference.year,
            "identifier": material.reference.identifier,
            "url": material.reference.url,
            "notes": material.reference.notes,
            "manufacturing_condition": material.manufacturing_condition,
            "valid_temperature_range_k": material.valid_temperature_range_k,
        }
        for name, material in MATERIALS.items()
    }
