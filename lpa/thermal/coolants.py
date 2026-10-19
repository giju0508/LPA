"""Compact coolant property estimates for preliminary regenerative analysis.

The UI coolant definition intentionally contains only identity, inlet pressure,
temperature, and mass-flow fraction.  These values provide a deterministic
screening calculation when a dedicated property package is unavailable.  A
caller can override every property through ``settings.coolant_properties`` or
through equivalently named fields on a dictionary coolant definition.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import exp, floor, isfinite, log, nan
from functools import lru_cache
from threading import local

from ..core.composition import aqueous_composition, solution_name


@dataclass(frozen=True, slots=True)
class CoolantPhaseState:
    """One equilibrium phase, without an invented two-phase bulk transport law."""

    density_kg_m3: float
    specific_heat_j_kgk: float
    conductivity_w_mk: float
    viscosity_pa_s: float
    temperature_k: float
    pressure_pa: float
    enthalpy_j_kg: float
    molar_mass_kg_mol: float
    phase: str
    source: str
    speed_of_sound_m_s: float = nan
    specific_heat_cv_j_kgk: float = nan
    issues: tuple[str, ...] = ()
    component_names: tuple[str, ...] = ()
    mole_fractions: tuple[float, ...] = ()
    transport_source: str = "native provider"
    transport_applicability: str = "eos"
    property_references: tuple[str, ...] = ()
    property_evidence: tuple[dict[str, object], ...] = ()

    @property
    def prandtl(self) -> float:
        return self.specific_heat_j_kgk * self.viscosity_pa_s / self.conductivity_w_mk


@dataclass(frozen=True, slots=True)
class CoolantTransportLimits:
    property_name: str
    minimum_temperature_k: float = nan
    maximum_temperature_k: float = nan
    maximum_pressure_pa: float = nan
    references: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoolantPropertyLimits:
    name: str
    backend: str
    minimum_temperature_k: float
    maximum_temperature_k: float
    maximum_pressure_pa: float
    thermodynamic_source: str
    transport_source: str
    references: tuple[str, ...]
    notes: tuple[str, ...] = ()
    transport_limits: tuple[CoolantTransportLimits, ...] = ()


@dataclass(frozen=True, slots=True)
class CoolantState:
    density_kg_m3: float
    specific_heat_j_kgk: float
    conductivity_w_mk: float
    viscosity_pa_s: float
    temperature_k: float = nan
    pressure_pa: float = nan
    enthalpy_j_kg: float = nan
    phase: str = "unknown"
    source: str = "screening"
    saturation_temperature_k: float = nan
    saturation_pressure_pa: float = nan
    critical_temperature_k: float = nan
    critical_pressure_pa: float = nan
    pseudocritical_temperature_k: float = nan
    speed_of_sound_m_s: float = nan
    specific_heat_cv_j_kgk: float = nan
    gas_constant_j_kgk: float = nan
    issues: tuple[str, ...] = ()
    vapor_quality_mass_fraction: float = nan
    saturated_liquid: CoolantPhaseState | None = None
    saturated_vapor: CoolantPhaseState | None = None
    surface_tension_n_m: float = nan
    thermodynamic_source: str = "screening"
    transport_source: str = "screening"
    property_limits: CoolantPropertyLimits | None = None
    equilibrium_energy_residual_j_kg: float = nan
    property_applicability: str = "screening"
    thermodynamic_applicability: str = "screening"
    transport_applicability: str = "screening"
    property_notes: tuple[str, ...] = ()
    property_references: tuple[str, ...] = ()
    property_evidence: tuple[dict[str, object], ...] = ()
    mixture_component_names: tuple[str, ...] = ()
    mixture_overall_mole_fractions: tuple[float, ...] = ()
    mixture_liquid_bubble_temperature_k: float = nan
    mixture_liquid_dew_temperature_k: float = nan
    equilibrium_temperature_enthalpy_derivative_k_kg_j: float = nan
    bubble_temperature_k: float = nan
    dew_temperature_k: float = nan
    mixture_boiling_property_issues: tuple[str, ...] = ()

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
        if self is COOLANT_MODELS.get("RP-1"):
            return _rp1_state(temperature_k, 83000.0)
        delta = temperature_k - self.reference_temperature_k
        density_factor = max(0.20, 1.0 - self.volumetric_expansion_per_k * delta)
        cp_factor = max(0.50, 1.0 + self.cp_slope_per_k * delta)
        conductivity_factor = max(0.35, 1.0 + self.conductivity_slope_per_k * delta)
        # Bound the exponent before evaluation as well as the legacy estimate.
        # These are screening safeguards, never validated fluid-domain limits.
        viscosity_raw = exp(max(-700.0, min(700.0, -self.viscosity_decay_per_k * delta)))
        viscosity_factor = min(8.0, max(0.08, viscosity_raw))
        issues = ["pressure-independent screening coolant properties"]
        if density_factor == .2 or cp_factor == .5 or conductivity_factor == .35 or viscosity_factor != viscosity_raw:
            issues.append("legacy screening property clamp active; no validated thermophysical range is established")
        return CoolantState(
            density_kg_m3=self.density_kg_m3 * density_factor,
            specific_heat_j_kgk=self.specific_heat_j_kgk * cp_factor,
            conductivity_w_mk=self.conductivity_w_mk * conductivity_factor,
            viscosity_pa_s=self.viscosity_pa_s * viscosity_factor,
            temperature_k=temperature_k,
            enthalpy_j_kg=self.screening_enthalpy(temperature_k),
            issues=tuple(issues),
            property_notes=("reference estimates have no independently established pressure, phase, or temperature validity range",),
        )

    def screening_enthalpy(self, temperature_k: float) -> float:
        """Integral of the documented screening cp, with a consistent datum."""
        delta = float(temperature_k) - self.reference_temperature_k
        slope = self.cp_slope_per_k
        if slope and 1.0 + slope * delta < 0.5:
            crossing = -0.5 / slope
            return self.specific_heat_j_kgk * (
                crossing + 0.5 * slope * crossing**2 + 0.5 * (delta - crossing)
            )
        return self.specific_heat_j_kgk * (delta + 0.5 * slope * delta**2)

    def at_state(self, temperature_k: float, pressure_pa: float, *, backend: str = "HEOS") -> CoolantState:
        return coolant_state(self.name, temperature_k, pressure_pa, backend=backend)

    def at_enthalpy(self, enthalpy_j_kg: float, pressure_pa: float, *, backend: str = "HEOS") -> CoolantState:
        return coolant_state_from_enthalpy(self.name, enthalpy_j_kg, pressure_pa, backend=backend)

    def screening_at_enthalpy(self, enthalpy_j_kg: float, pressure_pa: float) -> CoolantState:
        temperature=self.reference_temperature_k
        for _ in range(40):
            state=self.at_temperature(temperature)
            residual=state.enthalpy_j_kg-enthalpy_j_kg
            if abs(residual)<max(1.0,abs(enthalpy_j_kg))*1e-10:
                if self is COOLANT_MODELS.get("RP-1"):
                    return _rp1_state(temperature, pressure_pa)
                return replace(state,pressure_pa=pressure_pa)
            temperature=max(1.0,temperature-residual/state.specific_heat_j_kgk)
        raise ValueError("custom screening enthalpy inversion failed")


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
    "LNG": CoolantPropertyModel(
        "LNG", 111.66, 450.0, 3400.0, 0.185, 1.3e-4,
        volumetric_expansion_per_k=3.0e-3,
        viscosity_decay_per_k=1.8e-2,
        notes="Typical commercial LNG (Wartsila); density 450 kg/m3. Other properties are liquid-mixture screening estimates.",
    ),
    "IPA (100%)": CoolantPropertyModel(
        "IPA (100%)", 293.15, 785.0, 2680.0, 0.135, 2.04e-3,
        notes="Liquid isopropanol near 20 C; aqueous mixtures use ideal screening mixing rules.",
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
    "lng": "LNG",
    "ipa": "IPA (100%)",
    "ipa100": "IPA (100%)",
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
    aqueous = aqueous_composition(name)
    if aqueous:
        base, fraction = aqueous
        fraction = 1.0 if fraction is None else fraction
        canonical = solution_name(base, fraction)
        if canonical in COOLANT_MODELS:
            return COOLANT_MODELS[canonical]
        water = COOLANT_MODELS["H2O"]
        # Preserve existing screening anchors for peroxide and ethanol.
        # Below 70%, and for IPA, use ideal-volume density, mass-based cp,
        # linear conductivity and logarithmic viscosity screening estimates.
        if base in {"H2O2", "Ethanol"} and fraction >= 0.70:
            anchors = (0.70, 0.80, 0.90, 1.0)
            lower = max(value for value in anchors if value <= fraction)
            upper = min(value for value in anchors if value >= fraction)
            left = COOLANT_MODELS[solution_name(base, lower)]
            right = COOLANT_MODELS[solution_name(base, upper)]
            weight = (fraction - lower) / (upper - lower)
            density = left.density_kg_m3 + weight * (right.density_kg_m3 - left.density_kg_m3)
        else:
            left = water
            right = COOLANT_MODELS[solution_name(base, 0.70 if base != "IPA" else 1.0)]
            weight = fraction / (0.70 if base != "IPA" else 1.0)
            density = 1.0 / ((1.0 - weight) / left.density_kg_m3 + weight / right.density_kg_m3)
        return replace(
            right, name=canonical, density_kg_m3=density,
            specific_heat_j_kgk=(1.0 - weight) * left.specific_heat_j_kgk + weight * right.specific_heat_j_kgk,
            conductivity_w_mk=(1.0 - weight) * left.conductivity_w_mk + weight * right.conductivity_w_mk,
            viscosity_pa_s=exp((1.0 - weight) * log(left.viscosity_pa_s) + weight * log(right.viscosity_pa_s)),
            notes="Aqueous mass-fraction interpolation; screening only, no excess mixing or phase-change model.",
        )
    key = _ALIASES.get(_normalise_name(name))
    if key is None:
        options = ", ".join(COOLANT_MODELS)
        raise KeyError(f"unknown coolant {name!r}; choose one of: {options}")
    return COOLANT_MODELS[key]


def _rp1_state(temperature_k: float, pressure_pa: float) -> CoolantState:
    try:
        from .rp1_surrogate import rp1_surrogate_estimate
        return CoolantState(**rp1_surrogate_estimate(temperature_k,pressure_pa))
    except (ValueError,ImportError,OSError) as error:
        reason=str(error)
    # Retain earlier measurements as diagnostics only after the conditional
    # surrogate refuses a state. Their finite values cannot authorize a march.
    from .rp1_properties import NIST_RP1_REFERENCE, rp1_estimate
    values=rp1_estimate(temperature_k,pressure_pa)
    values.update(phase="unknown",property_applicability="unsupported",
                  issues=(*values.get("issues",()),f"RP-1 engineering surrogate unavailable: {reason}"))
    return CoolantState(
        temperature_k=temperature_k, pressure_pa=pressure_pa,
        thermodynamic_source="unsupported RP-1 state; legacy diagnostics only",
        thermodynamic_applicability="unsupported",transport_applicability="unsupported",
        property_notes=(
            "Conditional RP-1 engineering surrogate rejected this state; no usable phase/transport solution.",
            "Interpolation hulls are property-specific and do not certify liquid-phase stability.",
            "The original NIST RP-1 sample was atypical; fuel lot differences remain unresolved.",
        ),
        property_references=(NIST_RP1_REFERENCE,), **values,
    )


_EOS_FLUIDS = {
    "H2O": "Water", "LOX": "Oxygen", "GOX": "Oxygen",
    "LCH4": "Methane", "GCH4": "Methane", "LH2": "Hydrogen",
    "GH2": "Hydrogen", "N2O": "NitrousOxide", "Propane": "Propane",
    "Ethanol (100%)": "Ethanol",
}
_EOS_LOCAL = local()


def _eos_definition(name: str) -> tuple[str, tuple[float, ...], bool] | None:
    if name in _EOS_FLUIDS:
        return _EOS_FLUIDS[name], (), False
    aqueous = aqueous_composition(name)
    if aqueous and aqueous[0] == "Ethanol":
        fraction = 1.0 if aqueous[1] is None else aqueous[1]
        if fraction == 1.0:
            return "Ethanol", (), False
        return "Ethanol&Water", (fraction, 1.0-fraction), False
    if name == "LNG":
        from ..core.propellants import LNG_COMPONENTS
        return (
            "Methane&Ethane&Propane&n-Butane&Nitrogen",
            tuple(row[1] for row in LNG_COMPONENTS), True,
        )
    return None


def _backend_name(backend: str) -> str:
    value = str(backend).upper()
    if value in {"COOLPROP", "HEOS"}:
        return "HEOS"
    if value == "REFPROP":
        return value
    raise ValueError("coolant backend must be HEOS/coolprop or REFPROP")


def _abstract_state(name: str, *, saturation: bool | str = False, backend: str = "HEOS") -> object:
    import CoolProp
    backend = _backend_name(backend)
    definition = _eos_definition(name)
    if definition is None:
        raise ValueError(f"no validated equation of state for {name}")
    cache = getattr(_EOS_LOCAL, "states", None)
    if cache is None:
        cache = _EOS_LOCAL.states = {}
    key = (name, backend, saturation)
    if key not in cache:
        fluid, fractions, mole_basis = definition
        state = CoolProp.AbstractState(backend, fluid)
        if fractions:
            (state.set_mole_fractions if mole_basis else state.set_mass_fractions)(fractions)
        cache[key] = state
    return cache[key]


@lru_cache(maxsize=128)
def coolant_property_limits(name: object, *, backend: str = "HEOS") -> CoolantPropertyLimits:
    """EOS bounds are distinct from the validity of each transport correlation.

    These limits do not assert that every mixture, phase, or transport property
    has been experimentally validated throughout the bounding rectangle.
    REFPROP requires a separately installed licensed library and fluid files.
    """
    canonical = get_coolant_model(name).name
    backend = _backend_name(backend)
    state = _abstract_state(canonical, backend=backend, saturation="limits")
    definition = _eos_definition(canonical)
    assert definition is not None
    fluid, fractions, _ = definition
    maximum = float(state.Tmax())
    maximum_pressure = float(state.pmax())
    notes = ["EOS limits do not imply validation of viscosity or thermal conductivity."]
    # CoolProp permits extrapolation of IAPWS-95 to 2000 K. The IAPWS release
    # validates the stable fluid region only through 1273 K and 1000 MPa.
    if fluid == "Water":
        maximum = min(maximum, 1273.0)
        notes.append("IAPWS-95 stable-fluid validity cap: 1273 K; melting boundary still applies.")
    if fractions:
        notes.append("Mixture limits also depend on composition and phase-envelope convergence.")
        # CoolProp exposes composition-weighted mixture Tmax/pmax; that can
        # exceed a constituent EOS limit (Et70 advertises Tmax about 1356 K
        # despite pure ethanol's 650 K limit). Do not authorize that extrapolation.
        import CoolProp
        for component in fluid.split("&"):
            constituent = CoolProp.AbstractState(backend, component)
            maximum = min(maximum, float(constituent.Tmax()))
            maximum_pressure = min(maximum_pressure, float(constituent.pmax()))
        notes.append("Upper bounds conservatively include every constituent EOS limit; mixture freezing is not modelled.")
    if fluid == "Ethanol":
        notes.append("Ethanol conductivity correlation: triple point to 600 K, up to 245 MPa.")
    references = (
        "https://coolprop.org/fluid_properties/Mixtures.html",
        "https://coolprop.org/coolprop/REFPROP.html",
    ) if fractions else (f"https://coolprop.org/fluid_properties/fluids/{fluid}.html",)
    if fluid == "Water":
        references += ("https://iapws.org/technical-guidance/release/IAPWS-95",)
    if canonical == "LNG":
        references += (
            "https://www.nist.gov/publications/eos-lng-fundamental-equation-state-calculation-thermodynamic-properties-liquefied",
        )
    transport_source="fluid-specific EOS transport correlations; missing or out-of-range properties are explicit"
    if canonical == "LNG" and backend == "HEOS":
        from .mixture_transport import SOURCE, REFERENCE
        transport_source=SOURCE
        references+= (REFERENCE,)
        notes.append("TRAPP transport uses individual phase density/composition; no common mixture validation rectangle is asserted.")
    elif fluid == "Ethanol&Water":
        from .ethanol_transport import REFERENCES, VAPOR_REFERENCES
        transport_source="experimental liquid excess transport / dilute vapor mixture correlations; phase-qualified engineering prediction"
        references+= (*REFERENCES,*VAPOR_REFERENCES)
        notes.append("Experimental source grids, model calculation guards and EOS limits are separate; high-temperature/pressure mixture transport can be predictive.")
    transport_limits = tuple(
        CoolantTransportLimits(
            property_name,
            references=references,
            notes=("No common validated T/P rectangle is asserted; inspect the individual correlation and phase.",),
        )
        for property_name in ("conductivity_w_mk", "viscosity_pa_s")
    )
    if fluid == "Ethanol":
        transport_limits = (
            CoolantTransportLimits(
                "conductivity_w_mk", 159.1, 600.0, 245e6,
                ("https://doi.org/10.1063/1.4797368",),
                ("Reference conductivity correlation; excludes unvalidated extrapolation.",),
            ),
            transport_limits[1],
        )
    return CoolantPropertyLimits(
        canonical, backend, float(state.Tmin()), maximum, maximum_pressure,
        f"CoolProp {backend}: {fluid}",
        transport_source,
        references, tuple(notes), transport_limits,
    )


def _validate_eos_range(name: str, temperature_k: float, pressure_pa: float, backend: str) -> CoolantPropertyLimits:
    limits = coolant_property_limits(name, backend=backend)
    if not limits.minimum_temperature_k <= temperature_k <= limits.maximum_temperature_k:
        raise ValueError(
            f"EOS temperature {temperature_k:g} K outside documented bounds "
            f"[{limits.minimum_temperature_k:g}, {limits.maximum_temperature_k:g}] K"
        )
    if pressure_pa > limits.maximum_pressure_pa:
        raise ValueError(
            f"EOS pressure {pressure_pa:g} Pa exceeds documented maximum {limits.maximum_pressure_pa:g} Pa"
        )
    return limits


@lru_cache(maxsize=128)
def _critical_values(name: str, backend: str = "HEOS") -> tuple[float, float]:
    try:
        state = _abstract_state(name, saturation="critical", backend=backend)
        definition = _eos_definition(name)
        if definition is not None and definition[1]:
            stable = [point for point in state.all_critical_points() if point.stable and point.p > 0]
            if len(stable) == 1:
                return float(stable[0].T), float(stable[0].p)
            return nan, nan
        return float(state.T_critical()), float(state.p_critical())
    except (ValueError, ImportError, OSError):
        return nan, nan


@lru_cache(maxsize=8192)
def _saturation_at_pressure(name: str, pressure_pa: float, backend: str = "HEOS") -> float:
    import CoolProp.CoolProp as CP
    try:
        state = _abstract_state(name, saturation=True, backend=backend)
        state.unspecify_phase()
        state.update(CP.PQ_INPUTS, pressure_pa, 0.0)
        return float(state.T())
    except (ValueError, ImportError, OSError):
        return nan


@lru_cache(maxsize=8192)
def _saturation_at_temperature(name: str, temperature_k: float, backend: str = "HEOS") -> float:
    import CoolProp.CoolProp as CP
    try:
        state = _abstract_state(name, saturation=True, backend=backend)
        state.unspecify_phase()
        state.update(CP.QT_INPUTS, 0.0, temperature_k)
        return float(state.p())
    except (ValueError, ImportError, OSError):
        return nan


def coolant_saturation_pressure(name: object, temperature_k: float, *, backend: str = "HEOS") -> float:
    """Bubble pressure (pure-fluid saturation pressure); nan if unavailable."""
    canonical = get_coolant_model(name).name
    if not isfinite(temperature_k) or temperature_k <= 0:
        raise ValueError("saturation temperature must be finite and positive")
    return _saturation_at_temperature(canonical, float(temperature_k), _backend_name(backend))


@lru_cache(maxsize=8192)
def _mixture_boundaries(name: str, pressure_pa: float, backend: str) -> tuple[float, float, float, float] | None:
    """Exact-pressure bubble/dew T and feed-specific h, without reusing bulk state."""
    import CoolProp.CoolProp as CP
    _, pc = _critical_values(name, backend)
    if not isfinite(pc) or pressure_pa >= .98 * pc:
        return None  # No claim about retrograde regions or a near-critical envelope.
    try:
        state = _abstract_state(name, saturation="boundaries", backend=backend)
        state.unspecify_phase()
        state.update(CP.PQ_INPUTS, pressure_pa, 0.0)
        bubble_t, bubble_h = float(state.T()), float(state.hmass())
        state.update(CP.PQ_INPUTS, pressure_pa, 1.0)
        dew_t, dew_h = float(state.T()), float(state.hmass())
        if bubble_t <= dew_t and bubble_h < dew_h:
            return bubble_t, dew_t, bubble_h, dew_h
    except (ValueError, ImportError, OSError):
        pass
    return None


def _update_pressure_temperature(name: str, state: object, pressure_pa: float,
                                 temperature_k: float, *, backend: str = "HEOS") -> None:
    """Avoid blind mixture roots where a bubble/dew flash proves the phase.

    LNG at 150 K / 25 bar otherwise selects a spurious gas root with Cp around
    1.2 MJ/(kg K), although its bubble temperature is 174 K. Phase selection
    therefore uses the operating-pressure boundary, not a 0.1 Pc temperature.
    """
    import CoolProp.CoolProp as CP
    state.unspecify_phase()
    definition = _eos_definition(name)
    if definition is not None and definition[1]:
        boundaries = _mixture_boundaries(name, pressure_pa, backend)
        if boundaries is not None:
            bubble_t, dew_t, _, _ = boundaries
            if temperature_k < bubble_t:
                state.specify_phase(CP.iphase_liquid)
            elif temperature_k > dew_t:
                state.specify_phase(CP.iphase_gas)
            else:
                from scipy.optimize import brentq
                def residual(quality: float) -> float:
                    state.update(CP.PQ_INPUTS, pressure_pa, quality)
                    return float(state.T()) - temperature_k
                quality = brentq(residual, 0.0, 1.0, xtol=1e-12)
                state.update(CP.PQ_INPUTS, pressure_pa, quality)
                return
        else:
            # Above Pc a lower-pressure bubble point is only a sufficient
            # compressed-liquid proof. It does not define a retrograde envelope.
            _, pc = _critical_values(name, backend)
            reference_p = min(pressure_pa, .8 * pc) if isfinite(pc) else pressure_pa
            bubble = _saturation_at_pressure(name, max(1.0, reference_p), backend)
            if isfinite(bubble) and temperature_k < bubble:
                state.specify_phase(CP.iphase_liquid)
    try:
        state.update(CP.PT_INPUTS, pressure_pa, temperature_k)
    finally:
        state.unspecify_phase()


@lru_cache(maxsize=2048)
def _pseudocritical_temperature(name: str, pressure_pa: float, backend: str = "HEOS") -> float:
    import CoolProp.CoolProp as CP
    tc, pc = _critical_values(name, backend)
    if not isfinite(tc) or pressure_pa <= pc:
        return nan
    try:
        from scipy.optimize import minimize_scalar
        state = _abstract_state(name, saturation="cp_peak", backend=backend)
        limits = coolant_property_limits(name, backend=backend)
        def negative_cp(temperature: float) -> float:
            state.update(CP.PT_INPUTS, pressure_pa, temperature)
            return -float(state.cpmass())
        low = max(limits.minimum_temperature_k, .8 * tc)
        high = min(limits.maximum_temperature_k, 2.0 * tc)
        grid = [low + (high-low)*i/40 for i in range(41)]
        values = [negative_cp(t) for t in grid]
        best = min(range(len(grid)), key=lambda i: values[i])
        if best in {0, len(grid)-1}:
            return nan
        result = minimize_scalar(negative_cp, bounds=(grid[best-1], grid[best+1]), method="bounded")
        return float(result.x) if result.success else nan
    except (ValueError, ImportError, OSError):
        return nan


def _extract_phase(name: str, state: object, *, vapor: bool, backend: str) -> CoolantPhaseState:
    import CoolProp.CoolProp as CP
    temperature = float(state.T())
    fallback = get_coolant_model(name).at_temperature(temperature)
    output = state.saturated_vapor_keyed_output if vapor else state.saturated_liquid_keyed_output
    issues: list[str] = []
    def value(key: object, label: str, default: float, *, positive: bool = True) -> float:
        try:
            result = float(output(key))
            if not isfinite(result) or (positive and result <= 0):
                raise ValueError(f"invalid {label}")
            if name == "Ethanol (100%)" and label == "conductivity" and (
                temperature > 600.0 or float(state.p()) > 245e6
            ):
                raise ValueError("outside ethanol conductivity correlation bounds")
            return result
        except ValueError:
            issues.append(f"saturated {'vapor' if vapor else 'liquid'} {label} unavailable; screening property used")
            return default
    definition = _eos_definition(name)
    assert definition is not None
    components = tuple(definition[0].split("&"))
    fractions = tuple(float(x) for x in (state.mole_fractions_vapor() if vapor else state.mole_fractions_liquid())) if definition[1] else (1.0,)
    result = CoolantPhaseState(
        value(CP.iDmass, "density", fallback.density_kg_m3),
        value(CP.iCpmass, "cp", fallback.specific_heat_j_kgk),
        value(CP.iconductivity, "conductivity", fallback.conductivity_w_mk),
        value(CP.iviscosity, "viscosity", fallback.viscosity_pa_s),
        temperature, float(state.p()), value(CP.iHmass, "enthalpy", nan, positive=False),
        value(CP.imolar_mass, "molar mass", nan), "gas" if vapor else "liquid",
        f"CoolProp {backend} equilibrium phase", value(CP.ispeed_sound, "sound speed", nan),
        value(CP.iCvmass, "cv", nan), tuple(issues),
        component_names=components, mole_fractions=fractions,
    )
    if name == "LNG" and backend == "HEOS":
        result = _with_lng_phase_transport(result)
    elif components == ("Ethanol","Water"):
        result = _with_ethanol_phase_transport(result)
    return result


def _with_lng_phase_transport(phase: CoolantPhaseState) -> CoolantPhaseState:
    """NBS TN1039 transport at actual phase density/composition, not bulk Z."""
    from .mixture_transport import lng_ecs_transport
    try:
        result = lng_ecs_transport(temperature_k=phase.temperature_k,
            molar_density_mol_m3=phase.density_kg_m3/phase.molar_mass_kg_mol,
            components=phase.component_names,mole_fractions=phase.mole_fractions)
    except (ValueError, ArithmeticError) as error:
        return replace(phase, transport_applicability="unsupported",
            issues=(*phase.issues,f"NBS mixture transport unavailable: {error}"))
    # Existing native numbers can be finite even when individual mixture
    # components were evaluated beyond their transport surface. Replace both.
    issues=tuple(item for item in phase.issues if not any(
        text in item for text in ("conductivity unavailable", "viscosity unavailable")))
    return replace(phase,viscosity_pa_s=result.viscosity_pa_s,
        conductivity_w_mk=result.conductivity_w_mk,
        transport_source=result.source,transport_applicability=result.property_applicability,
        property_references=result.references,
        issues=(*issues,*result.issues))


def _with_ethanol_phase_transport(phase: CoolantPhaseState) -> CoolantPhaseState:
    from .ethanol_transport import ethanol_water_transport
    try:
        result=ethanol_water_transport(temperature_k=phase.temperature_k,
            pressure_pa=phase.pressure_pa,ethanol_mole_fraction=phase.mole_fractions[0],
            phase=phase.phase,phase_density_kg_m3=phase.density_kg_m3)
    except (ValueError,ArithmeticError) as error:
        return replace(phase,transport_applicability="unsupported",
            issues=(*phase.issues,f"ethanol-water phase transport unavailable: {error}"))
    issues=tuple(item for item in phase.issues if not any(
        text in item for text in ("conductivity unavailable","viscosity unavailable")))
    return replace(phase,viscosity_pa_s=result.viscosity_pa_s,
        conductivity_w_mk=result.conductivity_w_mk,transport_source=result.source,
        transport_applicability=result.property_applicability,property_references=result.references,
        property_evidence=(result.evidence,),issues=(*issues,*result.issues))


def _mixture_boiling_properties(name: str, state: object, pressure_pa: float,
                                 backend: str) -> dict[str, object]:
    """Local equilibrium data used by the separate mixture boiling model.

    Dew/bubble temperatures refer to the CURRENT liquid composition. dT/dh
    instead follows the feed-composition isobar, including composition glide.
    Separate cached state objects prevent a diagnostic flash mutating bulk h.
    """
    import CoolProp.CoolProp as CP
    definition = _eos_definition(name)
    assert definition is not None and definition[1]
    output: dict[str, object] = {
        "mixture_component_names":tuple(definition[0].split("&")),
        "mixture_overall_mole_fractions":tuple(float(x) for x in state.get_mole_fractions()),
    }
    issues: list[str] = []
    boundaries = _mixture_boundaries(name,pressure_pa,backend)
    if boundaries is not None:
        output.update(bubble_temperature_k=boundaries[0],dew_temperature_k=boundaries[1])
    if state.phase() != CP.iphase_twophase:
        return output
    try:
        local = _abstract_state(name,backend=backend,saturation="liquid_composition_glide")
        local.set_mole_fractions(state.mole_fractions_liquid())
        local.unspecify_phase()
        local.update(CP.PQ_INPUTS,pressure_pa,0.0)
        bubble = float(local.T())
        try:
            local.update(CP.PQ_INPUTS,pressure_pa,1.0)
            dew = float(local.T())
        except ValueError:
            # HEOS PQ's initial-temperature solver fails for some aqueous
            # compositions although the QT equilibrium surface is regular.
            # Invert that same EOS surface; do not substitute a fixed glide.
            from scipy.optimize import brentq
            def pressure_residual(temperature: float) -> float:
                local.update(CP.QT_INPUTS,1.0,temperature)
                return float(local.p())-pressure_pa
            lower=bubble
            low_error=pressure_residual(lower)
            upper=lower
            high_error=low_error
            step=2.0
            maximum=coolant_property_limits(name,backend=backend).maximum_temperature_k
            while high_error < 0 and upper < maximum:
                upper=min(maximum,bubble+step)
                high_error=pressure_residual(upper)
                step*=1.5
            if low_error > 0 or high_error < 0:
                raise ValueError("local dew QT surface does not bracket the requested pressure")
            dew=brentq(pressure_residual,lower,upper,xtol=1e-8,rtol=1e-12)
            issues.append("local dew PQ flash recovered by bracketed QT EOS inversion")
        if not isfinite(bubble) or not isfinite(dew) or dew < bubble-1e-5:
            raise ValueError("non-monotone liquid-composition temperature glide")
        output.update(mixture_liquid_bubble_temperature_k=bubble,
                      mixture_liquid_dew_temperature_k=max(bubble,dew))
    except (ValueError,ArithmeticError) as error:
        issues.append(f"local liquid-composition glide unavailable: {error}")
    try:
        derivative = _abstract_state(name,backend=backend,saturation="isobaric_glide_derivative")
        derivative.unspecify_phase()
        q=float(state.Q())
        low,high=max(0.0,q-1e-4),min(1.0,q+1e-4)
        derivative.update(CP.PQ_INPUTS,pressure_pa,low)
        t0,h0=float(derivative.T()),float(derivative.hmass())
        derivative.update(CP.PQ_INPUTS,pressure_pa,high)
        t1,h1=float(derivative.T()),float(derivative.hmass())
        slope=(t1-t0)/(h1-h0)
        if not isfinite(slope) or slope < -1e-8 or h1 <= h0:
            raise ValueError("non-monotone equilibrium h/T derivative")
        output["equilibrium_temperature_enthalpy_derivative_k_kg_j"]=max(0.0,slope)
    except (ValueError,ArithmeticError) as error:
        issues.append(f"isobaric temperature/enthalpy derivative unavailable: {error}")
    output["mixture_boiling_property_issues"]=tuple(issues)
    return output


def _mass_quality(state: object) -> float:
    import CoolProp.CoolProp as CP
    molar_quality = float(state.Q())
    liquid_m = float(state.saturated_liquid_keyed_output(CP.imolar_mass))
    vapor_m = float(state.saturated_vapor_keyed_output(CP.imolar_mass))
    return molar_quality*vapor_m / ((1.0-molar_quality)*liquid_m + molar_quality*vapor_m)


def _extract_eos_state(name: str, state: object, pressure_pa: float, *, backend: str = "HEOS") -> CoolantState:
    import CoolProp.CoolProp as CP
    temperature = float(state.T())
    limits = _validate_eos_range(name, temperature, pressure_pa, backend)
    fallback = get_coolant_model(name).at_temperature(temperature)
    issues: list[str] = []
    phase_names = {
        CP.iphase_liquid: "liquid", CP.iphase_gas: "gas",
        CP.iphase_twophase: "two_phase", CP.iphase_supercritical: "supercritical",
        CP.iphase_supercritical_liquid: "supercritical_liquid",
        CP.iphase_supercritical_gas: "supercritical_gas", CP.iphase_critical_point: "critical_point",
    }
    phase = phase_names.get(state.phase(), "unknown")
    unavailable: set[str] = set()
    def property_value(method: str, default: float) -> float:
        try:
            value = float(getattr(state, method)())
            if not isfinite(value) or value <= 0:
                raise ValueError(f"invalid {method}")
            if name == "Ethanol (100%)" and method == "conductivity" and (
                temperature > 600.0 or pressure_pa > 245e6
            ):
                raise ValueError("outside ethanol conductivity correlation bounds")
            return value
        except ValueError:
            unavailable.add(method)
            issues.append(f"{method} unavailable in EOS; screening transport/property used")
            return default
    density = property_value("rhomass", fallback.density_kg_m3)
    cp = property_value("cpmass", fallback.specific_heat_j_kgk)
    conductivity = property_value("conductivity", fallback.conductivity_w_mk)
    viscosity = property_value("viscosity", fallback.viscosity_pa_s)
    cv = property_value("cvmass", nan)
    sound = property_value("speed_sound", nan)
    definition = _eos_definition(name)
    assert definition is not None
    mixture = bool(definition[1])
    if mixture:
        issues.append("mixture EOS/transport require composition-specific validation")
    if name in {"LH2", "GH2"}:
        issues.append("normal-hydrogen EOS assumed; ortho/para composition and conversion heat not modelled")
    tc, pc = _critical_values(name, backend)
    mixture_data = _mixture_boiling_properties(name,state,pressure_pa,backend) if mixture else {}
    correlated_transport = None
    if mixture and phase == "liquid" and isfinite(pc) and pressure_pa > pc and temperature < tc:
        phase = "supercritical_liquid"
    if name == "LNG" and backend == "HEOS" and phase != "two_phase":
        from .mixture_transport import lng_ecs_transport
        try:
            correlated_transport=lng_ecs_transport(temperature_k=temperature,
                molar_density_mol_m3=float(state.rhomolar()),
                components=tuple(definition[0].split("&")),
                mole_fractions=tuple(float(x) for x in state.get_mole_fractions()))
            conductivity=correlated_transport.conductivity_w_mk
            viscosity=correlated_transport.viscosity_pa_s
            unavailable.difference_update({"conductivity","viscosity"})
            issues=[issue for issue in issues if not any(text in issue for text in (
                "conductivity unavailable", "viscosity unavailable"))]
            issues.extend(correlated_transport.issues)
        except (ValueError,ArithmeticError) as error:
            unavailable.update({"conductivity","viscosity"})
            issues.append(f"NBS mixture transport unavailable: {error}")
    elif definition[0] == "Ethanol&Water" and phase != "two_phase":
        from .ethanol_transport import ethanol_water_transport
        try:
            correlated_transport=ethanol_water_transport(temperature_k=temperature,
                pressure_pa=pressure_pa,ethanol_mole_fraction=float(state.get_mole_fractions()[0]),
                phase=phase,phase_density_kg_m3=density)
            conductivity=correlated_transport.conductivity_w_mk
            viscosity=correlated_transport.viscosity_pa_s
            unavailable.difference_update({"conductivity","viscosity"})
            issues=[issue for issue in issues if not any(text in issue for text in (
                "conductivity unavailable","viscosity unavailable"))]
            issues.extend(correlated_transport.issues)
        except (ValueError,ArithmeticError) as error:
            unavailable.update({"conductivity","viscosity"})
            issues.append(f"ethanol-water transport unavailable: {error}")
    diagnostic_pressure = floor(pressure_pa/10000.0)*10000.0 if mixture else pressure_pa
    if mixture:
        issues.append("mixture bubble-temperature diagnostic uses pressure rounded down by at most 0.1 bar")
    saturation_temperature = (
        nan if mixture and isfinite(pc) and diagnostic_pressure >= pc
        else _saturation_at_pressure(name, max(1.0, diagnostic_pressure), backend)
    )
    if mixture and isfinite(pc) and diagnostic_pressure >= pc:
        issues.append("mixture retrograde phase envelope above critical pressure not validated")
    liquid = vapor = None
    quality = surface_tension = equilibrium_residual = nan
    if phase == "two_phase":
        liquid = _extract_phase(name, state, vapor=False, backend=backend)
        vapor = _extract_phase(name, state, vapor=True, backend=backend)
        quality = _mass_quality(state)
        phase_enthalpy = (vapor.enthalpy_j_kg if mixture and quality>=1.0-1e-12 else
                          (1.0-quality)*liquid.enthalpy_j_kg + quality*vapor.enthalpy_j_kg)
        equilibrium_residual = float(state.hmass())-phase_enthalpy
        if abs(equilibrium_residual) > 1e-4*max(1.0, abs(float(state.hmass())), abs(phase_enthalpy)):
            raise ValueError("EOS equilibrium phase enthalpy closure exceeds relative tolerance 1e-4")
        if mixture and abs(equilibrium_residual) > 1e-7*max(1.0, abs(float(state.hmass()))):
            issues.append(f"mixture equilibrium phase enthalpy closure residual {equilibrium_residual:g} J/kg")
        if quality < 1.0-1e-12:
            issues.extend(liquid.issues)
        issues.extend(vapor.issues)
        issues=[issue for issue in issues if not any(issue.startswith(method+" unavailable")
                for method in ("rhomass","cpmass","conductivity","viscosity"))]
        # Bulk Cp, viscosity and k have no unique equilibrium two-phase
        # transport definition. Retain phase-weighted diagnostics only; boiling
        # correlations must explicitly use the phase-resolved properties.
        cp = (1.0-quality)*liquid.specific_heat_j_kgk + quality*vapor.specific_heat_j_kgk
        conductivity = (1.0-quality)*liquid.conductivity_w_mk + quality*vapor.conductivity_w_mk
        viscosity = (1.0-quality)*liquid.viscosity_pa_s + quality*vapor.viscosity_pa_s
        issues.append("two-phase bulk cp/transport are phase-weighted diagnostics; use saturated phase properties")
        try:
            surface_tension = float(state.surface_tension())
        except ValueError:
            issues.append("two-phase surface tension unavailable in EOS")
        # The dew endpoint is a genuine vapor state; do not feed x=1 into
        # a wet-wall boiling correlation with a vanishing liquid film.
        if mixture and quality >= 1.0-1e-12:
            phase = "gas"
            density=vapor.density_kg_m3
            cp=vapor.specific_heat_j_kgk
            conductivity=vapor.conductivity_w_mk
            viscosity=vapor.viscosity_pa_s
            cv=vapor.specific_heat_cv_j_kgk
            sound=vapor.speed_of_sound_m_s
    # The bulk Cp and transport of a two-phase equilibrium are diagnostics;
    # their native unavailability must not hide valid phase-resolved values.
    if liquid is not None and vapor is not None:
        required_phases=(vapor,) if phase=="gas" and quality>=1.0-1e-12 else (liquid,vapor)
        unavailable = {
            method for method, label in (("rhomass", "density"), ("cpmass", "cp"),
                                        ("conductivity", "conductivity"), ("viscosity", "viscosity"))
            if any(f" {label} unavailable" in issue for phase_state in required_phases
                   if phase_state is not None for issue in phase_state.issues)
        }
        thermo_fallback = any(
            any(f" {label} unavailable" in issue for label in ("density", "cp", "enthalpy", "molar mass"))
            for phase_state in required_phases for issue in phase_state.issues
        )
        transport_fallback = any(
            any(f" {label} unavailable" in issue for label in ("conductivity", "viscosity"))
            for phase_state in required_phases for issue in phase_state.issues
        )
        transport_fallback |= any(p.transport_applicability in {"screening","unsupported"}
                                  for p in required_phases)
        if transport_fallback:
            unavailable.update({"conductivity","viscosity"})
    else:
        thermo_fallback = bool(unavailable & {"rhomass", "cpmass"})
        transport_fallback = bool(unavailable & {"conductivity", "viscosity"})
    thermo_health = "screening" if thermo_fallback or phase == "unknown" else "eos"
    transport_health = "screening" if transport_fallback else "eos"
    if correlated_transport is not None or (
            liquid is not None and vapor is not None and
            all(p.transport_applicability=="correlated" for p in required_phases)):
        transport_health = "correlated"
    # Finite fallback numbers remain useful diagnostics, but cannot authorize
    # a heat-transfer calculation without the required native properties.
    health = ("eos" if transport_health=="eos" else "correlated") if thermo_health=="eos" and not transport_fallback else "unsupported"
    thermo_source = f"CoolProp {backend}: {definition[0]}"
    transport_source = (
        f"{thermo_source}; screening fallback present"
        if transport_fallback else thermo_source
    )
    if correlated_transport is not None:
        transport_source=correlated_transport.source
    elif liquid is not None and vapor is not None and transport_health=="correlated":
        transport_source=(vapor.transport_source if len(required_phases)==1 else
                          liquid.transport_source if liquid.transport_source==vapor.transport_source else
                          f"liquid: {liquid.transport_source}; vapor: {vapor.transport_source}")
    return CoolantState(
        density, cp, conductivity, viscosity, temperature_k=temperature, pressure_pa=pressure_pa,
        enthalpy_j_kg=float(state.hmass()), phase=phase, source=thermo_source,
        saturation_temperature_k=saturation_temperature,
        saturation_pressure_pa=_saturation_at_temperature(name, temperature, backend) if not mixture else nan,
        critical_temperature_k=tc, critical_pressure_pa=pc,
        pseudocritical_temperature_k=_pseudocritical_temperature(name, diagnostic_pressure, backend) if not mixture else nan,
        speed_of_sound_m_s=sound, specific_heat_cv_j_kgk=cv,
        gas_constant_j_kgk=float(state.gas_constant()/state.molar_mass()), issues=tuple(issues),
        vapor_quality_mass_fraction=quality, saturated_liquid=liquid, saturated_vapor=vapor,
        surface_tension_n_m=surface_tension, thermodynamic_source=thermo_source,
        transport_source=transport_source, property_limits=limits,
        equilibrium_energy_residual_j_kg=equilibrium_residual,
        property_applicability=health, thermodynamic_applicability=thermo_health,
        transport_applicability=transport_health,
        property_notes=(
            "EOS denotes the provider's model domain, not independent experimental validation of every state.",
            "Thermodynamic bounds and transport-correlation bounds are separate; unreported transport limits remain unknown.",
        ),
        property_references=tuple(dict.fromkeys((*limits.references,
            *(correlated_transport.references if correlated_transport is not None else ()),
            *(liquid.property_references if liquid is not None else ()),
            *(vapor.property_references if vapor is not None else ())))),
        property_evidence=tuple(
            dict(property_name=label,
                 source=("reference screening fallback" if method in unavailable else
                         transport_source if method in {"conductivity","viscosity"} else thermo_source),
                 applicability=("screening" if method in unavailable else
                                "correlated" if method in {"conductivity","viscosity"}
                                and transport_health=="correlated" else "eos"),
                 temperature_range_k=None, pressure_range_pa=None,
                 model_evidence=(getattr(correlated_transport,"evidence",None)
                     if correlated_transport is not None else
                     {"liquid":liquid.property_evidence,"vapor":vapor.property_evidence}
                     if liquid is not None and vapor is not None else None)
                     if method in {"conductivity","viscosity"} else None,
                 notes=("Use property_limits for EOS and separately known transport bounds; inspect issues for property-specific fallback.",))
            for label, method in (("density_kg_m3", "rhomass"), ("specific_heat_j_kgk", "cpmass"),
                                  ("conductivity_w_mk", "conductivity"), ("viscosity_pa_s", "viscosity"))
        ),
        **mixture_data,
    )


def _failed_eos_state(model: CoolantPropertyModel, temperature_k: float, pressure_pa: float,
                      error: object, *, enthalpy_j_kg: float | None = None) -> CoolantState:
    state = model.at_temperature(temperature_k)
    return replace(
        state, pressure_pa=pressure_pa,
        enthalpy_j_kg=state.enthalpy_j_kg if enthalpy_j_kg is None else enthalpy_j_kg,
        phase="unknown", issues=(f"{model.name}: EOS state unavailable ({error}); physical state unsupported",),
        property_applicability="unsupported", thermodynamic_applicability="unsupported",
        transport_applicability="screening",
    )


def coolant_state(name: object, temperature_k: float, pressure_pa: float, *, backend: str = "HEOS") -> CoolantState:
    """Pressure-dependent real-fluid state, with explicit backend/range failure."""
    model = get_coolant_model(name)
    backend = _backend_name(backend)
    temperature_k, pressure_pa = float(temperature_k), float(pressure_pa)
    if not isfinite(pressure_pa) or pressure_pa <= 0:
        raise ValueError("coolant pressure must be finite and positive")
    if model is COOLANT_MODELS["RP-1"]:
        if not isfinite(temperature_k) or temperature_k <= 0:
            raise ValueError("coolant temperature must be finite and positive")
        return _rp1_state(temperature_k, pressure_pa)
    fallback = model.at_temperature(temperature_k)
    if _eos_definition(model.name) is None:
        return replace(fallback, pressure_pa=pressure_pa, issues=fallback.issues + (
            f"{model.name}: no validated pressure/phase equation of state; native provider unsupported; screening diagnostics only",
        ), property_applicability="unsupported", thermodynamic_applicability="unsupported",
           transport_applicability="screening", property_evidence=tuple(
            dict(property_name=label, source="reference-temperature screening estimate",
                 applicability="screening", temperature_range_k=None, pressure_range_pa=None,
                 notes=(model.notes, "No independently established pressure, phase, or temperature range."))
            for label in ("density_kg_m3", "specific_heat_j_kgk", "conductivity_w_mk", "viscosity_pa_s")
        ))
    try:
        _validate_eos_range(model.name, temperature_k, pressure_pa, backend)
        state = _abstract_state(model.name, backend=backend)
        _update_pressure_temperature(model.name, state, pressure_pa, temperature_k, backend=backend)
        return _extract_eos_state(model.name, state, pressure_pa, backend=backend)
    except (ValueError, ImportError, OSError) as error:
        return _failed_eos_state(model, temperature_k, pressure_pa, error)


def _mixture_enthalpy_update(name: str, state: object, enthalpy_j_kg: float,
                             pressure_pa: float, temperature_hint_k: float,
                             backend: str) -> None:
    """Bracket a stable single phase or equilibrium PQ; never Newton through VLE."""
    import CoolProp.CoolProp as CP
    from scipy.optimize import brentq
    limits = coolant_property_limits(name, backend=backend)
    lower, upper = limits.minimum_temperature_k, limits.maximum_temperature_k
    imposed_phase = None
    boundaries = _mixture_boundaries(name, pressure_pa, backend)
    if boundaries is not None:
        bubble_t, dew_t, bubble_h, dew_h = boundaries
        if bubble_h <= enthalpy_j_kg <= dew_h:
            state.unspecify_phase()
            def residual_q(quality: float) -> float:
                state.update(CP.PQ_INPUTS, pressure_pa, quality)
                return float(state.hmass())-enthalpy_j_kg
            quality = brentq(residual_q, 0.0, 1.0, xtol=1e-12)
            state.update(CP.PQ_INPUTS, pressure_pa, quality)
            return
        if enthalpy_j_kg < bubble_h:
            upper = min(upper, bubble_t)
            imposed_phase = CP.iphase_liquid
        else:
            lower = max(lower, dew_t)
            imposed_phase = CP.iphase_gas
    def residual_t(temperature: float) -> float:
        state.unspecify_phase()
        if imposed_phase is not None:
            state.specify_phase(imposed_phase)
            try:
                state.update(CP.PT_INPUTS, pressure_pa, temperature)
            finally:
                state.unspecify_phase()
        else:
            _update_pressure_temperature(name, state, pressure_pa, temperature, backend=backend)
        return float(state.hmass())-enthalpy_j_kg
    center = min(upper, max(lower, temperature_hint_k))
    center_error = residual_t(center)
    tolerance = max(1.0, abs(enthalpy_j_kg))*1e-10
    if abs(center_error) <= tolerance:
        return
    left = right = center
    left_error = right_error = center_error
    step = 2.0
    for _ in range(32):
        if left_error > 0 and left > lower:
            left = max(lower, center-step)
            left_error = residual_t(left)
        if right_error < 0 and right < upper:
            right = min(upper, center+step)
            right_error = residual_t(right)
        if left_error <= 0 <= right_error:
            temperature = brentq(residual_t, left, right, xtol=1e-9, rtol=1e-12, maxiter=100)
            residual_t(temperature)
            return
        if left == lower and right == upper:
            break
        # Only one side expands for a monotone, stable isobaric h(T).
        if (left_error > 0 and left == lower) or (right_error < 0 and right == upper):
            break
        step *= 1.8
    raise ValueError("mixture enthalpy is outside a supported monotone phase bracket")


def _refine_pure_enthalpy_update(state: object, enthalpy_j_kg: float, pressure_pa: float) -> None:
    """Refine a native single-phase PH result with EOS-consistent PT updates.

    A native HmassP temperature stopping tolerance can leave sub-millijoule
    enthalpy errors, visible in tightly checked channel energy balances. Newton
    correction uses dh/dT|p=Cp and re-evaluates the complete EOS state; it never
    substitutes the requested enthalpy into an inconsistent returned state.
    Saturated/two-phase and unidentified states retain their native flash.
    """
    import CoolProp.CoolProp as CP
    phase = state.phase()
    if phase not in {
        CP.iphase_liquid, CP.iphase_gas, CP.iphase_supercritical,
        CP.iphase_supercritical_liquid, CP.iphase_supercritical_gas,
    }:
        return
    tolerance = max(1e-7, abs(enthalpy_j_kg) * 1e-11)
    best_temperature = float(state.T())
    best_error = abs(float(state.hmass()) - enthalpy_j_kg)
    if best_error <= tolerance:
        return
    for _ in range(6):
        residual = float(state.hmass()) - enthalpy_j_kg
        cp = float(state.cpmass())
        if not isfinite(cp) or cp <= 0:
            return
        temperature = float(state.T()) - residual / cp
        if not isfinite(temperature) or temperature <= 0 or temperature == float(state.T()):
            return
        try:
            state.update(CP.PT_INPUTS, pressure_pa, temperature)
            error = abs(float(state.hmass()) - enthalpy_j_kg)
            if state.phase() != phase or not isfinite(error) or error >= best_error:
                # Do not turn a saturated boundary into another physical phase
                # or retain a worse Newton step. Restore the best EOS state.
                state.update(CP.PT_INPUTS, pressure_pa, best_temperature)
                return
        except ValueError:
            # The native flash remains available at phase/solver boundaries.
            state.unspecify_phase()
            state.update(CP.HmassP_INPUTS, enthalpy_j_kg, pressure_pa)
            return
        best_temperature, best_error = temperature, error
        if error <= tolerance:
            return


def coolant_state_from_enthalpy(
    name: object, enthalpy_j_kg: float, pressure_pa: float,
    *, temperature_hint_k: float | None = None, backend: str = "HEOS",
) -> CoolantState:
    """PH flash: pure-fluid native flash; bracketed mixture PT/PQ inversion."""
    model = get_coolant_model(name)
    backend = _backend_name(backend)
    if not isfinite(enthalpy_j_kg) or not isfinite(pressure_pa) or pressure_pa <= 0:
        raise ValueError("coolant enthalpy and positive pressure must be finite")
    if model is COOLANT_MODELS["RP-1"]:
        from .rp1_surrogate import rp1_surrogate_from_enthalpy
        try:
            return CoolantState(**rp1_surrogate_from_enthalpy(enthalpy_j_kg,pressure_pa,
                temperature_hint_k=temperature_hint_k))
        except (ValueError,ImportError,OSError) as error:
            if temperature_hint_k is None:
                raise ValueError(f"RP-1: enthalpy flash failed ({error})") from error
            return _failed_eos_state(model,temperature_hint_k,pressure_pa,
                f"RP-1 enthalpy inversion failed: {error}",enthalpy_j_kg=enthalpy_j_kg)
    definition = _eos_definition(model.name)
    if definition is not None:
        try:
            import CoolProp.CoolProp as CP
            state = _abstract_state(model.name, backend=backend)
            if pressure_pa > coolant_property_limits(model.name, backend=backend).maximum_pressure_pa:
                raise ValueError("EOS pressure exceeds documented maximum")
            if definition[1]:
                _mixture_enthalpy_update(
                    model.name, state, enthalpy_j_kg, pressure_pa,
                    temperature_hint_k if temperature_hint_k is not None else model.reference_temperature_k,
                    backend,
                )
            else:
                state.unspecify_phase()
                state.update(CP.HmassP_INPUTS, enthalpy_j_kg, pressure_pa)
                _refine_pure_enthalpy_update(state, enthalpy_j_kg, pressure_pa)
            return _extract_eos_state(model.name, state, pressure_pa, backend=backend)
        except (ValueError, ImportError, OSError) as error:
            if temperature_hint_k is not None:
                return _failed_eos_state(model, temperature_hint_k, pressure_pa,
                    f"EOS enthalpy flash failed: {error}", enthalpy_j_kg=enthalpy_j_kg)
            raise ValueError(f"{model.name}: enthalpy flash failed ({error})") from error
    temperature = temperature_hint_k or model.reference_temperature_k
    for _ in range(40):
        state = model.at_temperature(temperature)
        residual = state.enthalpy_j_kg-enthalpy_j_kg
        if abs(residual) < max(1.0, abs(enthalpy_j_kg))*1e-10:
            return coolant_state(model.name, temperature, pressure_pa, backend=backend)
        temperature = max(1.0, temperature-residual/state.specific_heat_j_kgk)
    raise ValueError("screening coolant enthalpy inversion did not converge")


def coolant_state_from_quality(name: object, pressure_pa: float, vapor_quality_mass_fraction: float,
                               *, backend: str = "HEOS") -> CoolantState:
    """Equilibrium PQ flash with mass quality, also for mixtures with glide."""
    import CoolProp.CoolProp as CP
    from scipy.optimize import brentq
    model = get_coolant_model(name)
    backend = _backend_name(backend)
    quality = float(vapor_quality_mass_fraction)
    if not isfinite(quality) or not 0.0 <= quality <= 1.0:
        raise ValueError("vapor mass quality must be in [0, 1]")
    if not isfinite(pressure_pa) or pressure_pa <= 0:
        raise ValueError("coolant pressure must be finite and positive")
    state = _abstract_state(model.name, saturation="quality", backend=backend)
    state.unspecify_phase()
    definition = _eos_definition(model.name)
    assert definition is not None
    molar_quality = quality
    if definition[1] and 0.0 < quality < 1.0:
        def residual(molar: float) -> float:
            state.update(CP.PQ_INPUTS, pressure_pa, molar)
            return _mass_quality(state)-quality
        molar_quality = brentq(residual, 0.0, 1.0, xtol=1e-12)
    state.update(CP.PQ_INPUTS, pressure_pa, molar_quality)
    return _extract_eos_state(model.name, state, pressure_pa, backend=backend)
