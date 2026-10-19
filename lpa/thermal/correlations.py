"""Heat-transfer correlations for preliminary liquid-engine analysis.

The Bartz implementation follows the form printed in the supplied RPA
Thermal Analysis document.  Internal-flow helpers provide both the classic
Dittus-Boelter and the wider-range Gnielinski correlations.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import exp, isfinite, log, log10, pi, sqrt, tanh


STEFAN_BOLTZMANN_W_M2K4 = 5.670374419e-8


def _positive(value: float, name: str, *, allow_zero: bool = False) -> float:
    value = float(value)
    valid = value >= 0 if allow_zero else value > 0
    if not isfinite(value) or not valid:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return value


def adiabatic_wall_temperature(
    stagnation_temperature_k: float,
    mach: float,
    gamma: float,
    prandtl: float,
) -> float:
    """Bartz/RPA recovery temperature at a local Mach number."""

    stagnation_temperature_k = _positive(
        stagnation_temperature_k, "stagnation temperature"
    )
    mach = _positive(mach, "Mach number", allow_zero=True)
    gamma = _positive(gamma, "gamma")
    prandtl = _positive(prandtl, "Prandtl number")
    if gamma <= 1.0:
        raise ValueError("gamma must be greater than one")
    kinetic = 0.5 * (gamma - 1.0) * mach * mach
    recovery = prandtl ** (1.0 / 3.0)
    return stagnation_temperature_k * (1.0 + recovery * kinetic) / (1.0 + kinetic)


def bartz_correction_factor(
    wall_temperature_k: float,
    stagnation_temperature_k: float,
    mach: float,
    gamma: float,
) -> float:
    """Return the dimensionless Bartz sigma wall-temperature correction."""

    wall_temperature_k = _positive(wall_temperature_k, "wall temperature")
    stagnation_temperature_k = _positive(
        stagnation_temperature_k, "stagnation temperature"
    )
    mach = _positive(mach, "Mach number", allow_zero=True)
    gamma = _positive(gamma, "gamma")
    if gamma <= 1.0:
        raise ValueError("gamma must be greater than one")
    kinetic = 0.5 * (gamma - 1.0) * mach * mach
    temperature_term = 0.5 * wall_temperature_k / stagnation_temperature_k
    temperature_term *= 1.0 + kinetic
    temperature_term += 0.5
    return temperature_term ** -0.68 * (1.0 + kinetic) ** -0.12


def bartz_heat_transfer_coefficient(
    *,
    chamber_pressure_pa: float,
    characteristic_velocity_m_s: float,
    throat_diameter_m: float,
    throat_radius_of_curvature_m: float,
    area_ratio: float,
    wall_temperature_k: float,
    stagnation_temperature_k: float,
    mach: float,
    viscosity_pa_s: float,
    specific_heat_j_kgk: float,
    prandtl: float,
    gamma: float,
) -> float:
    """Return gas-side ``h`` in W/(m2 K) using the Bartz correlation.

    ``area_ratio`` is local A/At. The curvature is the actual upstream
    converging contour radius at the throat (R1), not downstream nozzle Rn.
    """

    chamber_pressure_pa = _positive(chamber_pressure_pa, "chamber pressure")
    characteristic_velocity_m_s = _positive(
        characteristic_velocity_m_s, "characteristic velocity"
    )
    throat_diameter_m = _positive(throat_diameter_m, "throat diameter")
    throat_radius_of_curvature_m = _positive(
        throat_radius_of_curvature_m, "throat radius of curvature"
    )
    area_ratio = _positive(area_ratio, "area ratio")
    viscosity_pa_s = _positive(viscosity_pa_s, "gas viscosity")
    specific_heat_j_kgk = _positive(specific_heat_j_kgk, "gas specific heat")
    prandtl = _positive(prandtl, "gas Prandtl number")
    sigma = bartz_correction_factor(
        wall_temperature_k,
        stagnation_temperature_k,
        mach,
        gamma,
    )
    leading = 0.026 / throat_diameter_m**0.2
    transport = viscosity_pa_s**0.2 * specific_heat_j_kgk / prandtl**0.6
    mass_flux = (chamber_pressure_pa / characteristic_velocity_m_s) ** 0.8
    curvature = (throat_diameter_m / throat_radius_of_curvature_m) ** 0.1
    geometry = (1.0 / area_ratio) ** 0.9
    return leading * transport * mass_flux * curvature * geometry * sigma


def bartz_heat_flux(
    *,
    adiabatic_wall_temperature_k: float,
    wall_temperature_k: float,
    heat_transfer_coefficient_w_m2k: float,
) -> float:
    """Signed convective heat flux from gas to wall in W/m2."""

    adiabatic_wall_temperature_k = _positive(
        adiabatic_wall_temperature_k, "adiabatic wall temperature"
    )
    wall_temperature_k = _positive(wall_temperature_k, "wall temperature")
    heat_transfer_coefficient_w_m2k = _positive(
        heat_transfer_coefficient_w_m2k, "heat-transfer coefficient"
    )
    return heat_transfer_coefficient_w_m2k * (
        adiabatic_wall_temperature_k - wall_temperature_k
    )


def dittus_boelter_nusselt(
    reynolds: float,
    prandtl: float,
    *,
    heating_fluid: bool = True,
) -> float:
    """Classic smooth-tube turbulent Nusselt number.

    ``heating_fluid=True`` applies the 0.4 Prandtl exponent appropriate for a
    rocket coolant receiving heat from the wall.
    """

    reynolds = _positive(reynolds, "Reynolds number")
    prandtl = _positive(prandtl, "Prandtl number")
    exponent = 0.4 if heating_fluid else 0.3
    return 0.023 * reynolds**0.8 * prandtl**exponent


def darcy_friction_factor(reynolds: float, relative_roughness: float = 0.0) -> float:
    """Darcy factor using laminar theory or the explicit Haaland equation."""

    reynolds = _positive(reynolds, "Reynolds number")
    relative_roughness = _positive(
        relative_roughness, "relative roughness", allow_zero=True
    )
    if reynolds < 2300.0:
        return 64.0 / reynolds
    inverse_sqrt = -1.8 * log10((relative_roughness / 3.7) ** 1.11 + 6.9 / reynolds)
    return 1.0 / inverse_sqrt**2


def gnielinski_nusselt(
    reynolds: float,
    prandtl: float,
    *,
    relative_roughness: float = 0.0,
) -> float:
    """Circular fully developed Gnielinski result with 2013 transition limits.

    Gnielinski (2013), doi:10.1016/j.ijheatmasstransfer.2013.04.015,
    interpolates between the laminar endpoint at Re=2300 and turbulent
    endpoint at Re=4000. Rectangular/developing flow is handled separately by
    ``internal_flow_heat_transfer`` rather than assuming this laminar limit.
    """

    reynolds = _positive(reynolds, "Reynolds number")
    prandtl = _positive(prandtl, "Prandtl number")
    relative_roughness = _positive(
        relative_roughness, "relative roughness", allow_zero=True
    )
    if reynolds <= 2300.0:
        return 3.66
    turbulent_reynolds = max(reynolds, 4000.0)
    friction = darcy_friction_factor(turbulent_reynolds, relative_roughness)
    numerator = (friction / 8.0) * (turbulent_reynolds - 1000.0) * prandtl
    denominator = 1.0 + 12.7 * sqrt(friction / 8.0) * (prandtl ** (2.0 / 3.0) - 1.0)
    turbulent = max(3.66, numerator / denominator)
    if reynolds >= 4000.0:
        return turbulent
    blend = (reynolds - 2300.0) / 1700.0
    return 3.66 + blend * (turbulent - 3.66)


# Gauss-Legendre abscissae and weights on [0, 1]. The square-coordinate
# substitution in the cell integral removes the inlet z**(-1/2) singularity.
_ENTRY_QUADRATURE = (
    (0.001368069075259215, 0.003509305004735253),
    (0.007194244227365809, 0.008137197365452872),
    (0.017618872206246805, 0.012696032654631012),
    (0.03254696203113017, 0.017136931456510882),
    (0.051839422116973954, 0.021417949011113418),
    (0.07531619313371501, 0.025499029631188046),
    (0.10275810201602881, 0.029342046739267783),
    (0.13390894062985514, 0.03291111138818084),
    (0.16847786653489238, 0.03617289705442417),
    (0.20614212137961885, 0.039096947893535114),
    (0.24655004553388532, 0.041655962113473353),
    (0.28932436193468236, 0.04382604650220189),
    (0.33406569885893617, 0.04558693934788189),
    (0.38035631887393145, 0.046922199540402255),
    (0.42776401920860174, 0.047819360039637354),
    (0.4758461671561308, 0.04827004425736383),
    (0.5241538328438692, 0.04827004425736383),
    (0.5722359807913983, 0.047819360039637354),
    (0.6196436811260685, 0.046922199540402255),
    (0.6659343011410639, 0.04558693934788189),
    (0.7106756380653176, 0.04382604650220189),
    (0.7534499544661146, 0.041655962113473353),
    (0.7938578786203812, 0.039096947893535114),
    (0.8315221334651076, 0.03617289705442417),
    (0.8660910593701449, 0.03291111138818084),
    (0.8972418979839711, 0.029342046739267783),
    (0.924683806866285, 0.025499029631188046),
    (0.948160577883026, 0.021417949011113418),
    (0.9674530379688698, 0.017136931456510882),
    (0.9823811277937532, 0.012696032654631012),
    (0.9928057557726342, 0.008137197365452872),
    (0.9986319309247408, 0.003509305004735253),
)


def _rectangular_poiseuille_number(aspect: float) -> float:
    """Darcy f*Re, Shah-London fully developed rectangular duct."""
    return 96.0 * (
        1 - 1.3553*aspect + 1.9467*aspect**2 - 1.7012*aspect**3
        + 0.9564*aspect**4 - 0.2537*aspect**5
    )


def _rectangular_fully_developed_nusselt(aspect: float) -> float:
    return 8.235 * (
        1 - 2.0421*aspect + 3.0853*aspect**2 - 2.4765*aspect**3
        + 1.0578*aspect**4 - 0.1861*aspect**5
    )


def _turbulent_cell_entry_factor(diameter: float, start: float, length: float) -> float:
    """Integrate local Nu implied by mean Nu=Nu_fd*(1+(Dh/L)**(2/3)).

    Differencing L*mean_Nu at the cell faces is essential: using the mean
    inlet-to-position factor independently in every cell double-counts entry
    enhancement. The algebraic cube difference avoids cancellation far from
    the inlet and remains finite for the first cell.
    """
    end = start+length
    denominator = end**(2.0/3.0)+(start*end)**(1.0/3.0)+start**(2.0/3.0)
    return 1.0+diameter**(2.0/3.0)/denominator


def _developing_laminar_parameters(
    prandtl: float, aspect: float | None, uniform_temperature: bool,
) -> tuple[float, float, float, float, float, float]:
    """Muzychka-Yovanovich (2004) Eq.21/22/43/46, Table 1.

    The paper's f is Fanning, and its characteristic length is sqrt(A) for
    ONE duct. Return lambda/Dh, f*Re_lambda, Nu_fd, C3, f(Pr), m.
    """
    if aspect is None:  # Circular duct limit, not a fictitious square duct.
        length_ratio = sqrt(pi)/2.0
        f_re = 16.0*length_ratio
        shape = 1.0
    else:
        length_ratio = (1.0+aspect)/(2.0*sqrt(aspect))
        f_re = 12.0/(sqrt(aspect)*(1.0+aspect)*(
            1.0-192.0*aspect/pi**5*tanh(pi/(2.0*aspect))
        ))
        shape = aspect**0.1  # epsilon**gamma OUTSIDE sqrt(pi), Eq.22, gamma=1/10.
    if uniform_temperature:
        c1, c3, c0, c_infinity_ratio = 3.24, 0.409, 0.564, 1.664
    else:
        c1, c3, c0, c_infinity_ratio = 3.86, 0.501, 0.886, 1.909
    nu_fd = c1*f_re/(8.0*sqrt(pi)*shape)
    f_pr = c0/(1.0+(c_infinity_ratio*prandtl**(1.0/6.0))**4.5)**(2.0/9.0)
    exponent = 2.27+1.65*prandtl**(1.0/3.0)
    return length_ratio, f_re, nu_fd, c3, f_pr, exponent


def _developing_laminar_local_value(
    z_star: float,
    parameters: tuple[float, float, float, float, float, float],
) -> float:
    """Evaluate Eq.45 locally, returning Nu based on hydraulic diameter."""
    ratio, f_re, nu_fd, c3, f_pr, exponent = parameters
    flat_plate = f_pr / sqrt(z_star)
    leveque = c3 * (f_re / z_star) ** (1.0 / 3.0)
    graetz = (leveque**5 + nu_fd**5) ** 0.2
    # Scale the generalized mean to avoid overflow at very small entry length.
    scale = max(flat_plate, graetz)
    local_nu = scale * (
        (flat_plate / scale) ** exponent + (graetz / scale) ** exponent
    ) ** (1.0 / exponent)
    return local_nu / ratio


@lru_cache(maxsize=32768)
def developing_laminar_local_nusselt(
    reynolds: float, prandtl: float, hydraulic_diameter_m: float,
    distance_from_inlet_m: float,
    *, channel_aspect_ratio: float | None = None,
    uniform_wall_temperature: bool = False,
) -> float:
    """Local Muzychka-Yovanovich Eq.45/Table1 Nu at a positive inlet distance.

    The reference has an integrable inlet singularity and is intentionally
    undefined at exactly zero. A conjugate finite-cell wall balance can sample
    this local coefficient at quadrature nodes, solve the local resistance
    network there, then integrate heat flux and wall temperature separately.
    Averaging h before that nonlinear balance generally gives a different
    answer. The same constant-property/section and boundary assumptions as
    ``developing_laminar_cell_nusselt`` apply.
    """
    reynolds = _positive(reynolds, "Reynolds number")
    prandtl = _positive(prandtl, "Prandtl number")
    diameter = _positive(hydraulic_diameter_m, "hydraulic diameter")
    distance = _positive(distance_from_inlet_m, "distance from heated inlet")
    aspect = channel_aspect_ratio
    if aspect is not None:
        aspect = _positive(aspect, "channel aspect ratio")
        aspect = min(aspect, 1.0 / aspect)
    if prandtl < 0.1 or (aspect is not None and aspect < 0.01):
        raise ValueError("developing laminar reference requires Pr >= 0.1 and rectangular aspect ratio >= 0.01")
    parameters = _developing_laminar_parameters(prandtl, aspect, uniform_wall_temperature)
    ratio = parameters[0]
    z_star = distance / (reynolds * prandtl * diameter * ratio**2)
    return _developing_laminar_local_value(z_star, parameters)


@lru_cache(maxsize=8192)
def developing_laminar_cell_nusselt(
    reynolds: float, prandtl: float, hydraulic_diameter_m: float,
    distance_from_inlet_m: float, cell_length_m: float,
    *, channel_aspect_ratio: float | None = None,
    uniform_wall_temperature: bool = False,
) -> float:
    """Cell-average local combined-entry Nu, Muzychka-Yovanovich (2004).

    Eq.45 with Table 1's LOCAL coefficients is integrated over the actual
    heated cell. doi:10.1115/1.1643752. Constant-property, constant-section,
    all-perimeter UWF/UWT reference; actual conjugate rocket channels require
    a boundary-condition adaptation warning. Entry origin is the coolant
    heated inlet, never the gas injector or total axial segment length.
    """
    reynolds = _positive(reynolds, "Reynolds number")
    prandtl = _positive(prandtl, "Prandtl number")
    diameter = _positive(hydraulic_diameter_m, "hydraulic diameter")
    start = _positive(distance_from_inlet_m, "distance from heated inlet", allow_zero=True)
    length = _positive(cell_length_m, "heated cell length")
    aspect = channel_aspect_ratio
    if aspect is not None:
        aspect = _positive(aspect, "channel aspect ratio")
        aspect = min(aspect, 1.0/aspect)
    if prandtl < 0.1 or (aspect is not None and aspect < 0.01):
        raise ValueError("developing laminar reference requires Pr >= 0.1 and rectangular aspect ratio >= 0.01")
    parameters = _developing_laminar_parameters(
        prandtl, aspect, uniform_wall_temperature,
    )
    ratio = parameters[0]
    thermal_length = reynolds*prandtl*diameter*ratio**2
    total = 0.0
    for coordinate, weight in _ENTRY_QUADRATURE:
        z_star = (start+length*coordinate**2)/thermal_length
        local_nu = _developing_laminar_local_value(z_star, parameters)
        total += weight*2.0*coordinate*local_nu
    return total


@dataclass(frozen=True, slots=True)
class InternalFlowHeatTransfer:
    coefficient_w_m2k: float
    nusselt: float
    reynolds: float
    prandtl: float
    hydraulic_diameter_m: float
    velocity_m_s: float
    flow_area_m2: float
    friction_factor: float
    warnings: tuple[str, ...] = ()
    applicability: str = "screening"
    flow_regime: str = ""
    nusselt_model: str = ""


def internal_flow_heat_transfer(
    *,
    mass_flow_kg_s: float,
    total_flow_area_m2: float,
    hydraulic_diameter_m: float,
    density_kg_m3: float,
    viscosity_pa_s: float,
    conductivity_w_mk: float,
    specific_heat_j_kgk: float,
    relative_roughness: float = 0.0,
    correlation: str = "gnielinski",
    channel_aspect_ratio: float | None = None,
    heated_length_m: float | None = None,
    distance_from_inlet_m: float | None = None,
    cell_length_m: float | None = None,
    thermal_boundary_condition: str = "conjugate",
    entry_sample_fraction: float | None = None,
) -> InternalFlowHeatTransfer:
    """Coolant convection with local/cell-average entry development.

    Paired distance/cell arguments are actual coolant-path lengths. Missing
    distances retain fully developed legacy values and explicit warnings.
    Finite properties are local bulk samples; the entry model does not solve
    variable-property/history or the actual conjugate wall boundary condition.
    ``entry_sample_fraction`` samples a local coefficient inside the cell;
    callers can integrate the conjugate balance instead of averaging h first.
    """

    mass_flow_kg_s = _positive(mass_flow_kg_s, "coolant mass flow")
    total_flow_area_m2 = _positive(total_flow_area_m2, "channel flow area")
    hydraulic_diameter_m = _positive(hydraulic_diameter_m, "hydraulic diameter")
    density_kg_m3 = _positive(density_kg_m3, "coolant density")
    viscosity_pa_s = _positive(viscosity_pa_s, "coolant viscosity")
    conductivity_w_mk = _positive(conductivity_w_mk, "coolant conductivity")
    specific_heat_j_kgk = _positive(specific_heat_j_kgk, "coolant specific heat")
    relative_roughness = _positive(relative_roughness, "relative roughness", allow_zero=True)
    velocity = mass_flow_kg_s / (density_kg_m3 * total_flow_area_m2)
    reynolds = density_kg_m3 * velocity * hydraulic_diameter_m / viscosity_pa_s
    prandtl = specific_heat_j_kgk * viscosity_pa_s / conductivity_w_mk
    name = str(correlation).strip().casefold().replace("-", "_")
    if name not in {"dittus", "dittus_boelter", "db", "gnielinski", "gn"}:
        raise ValueError("correlation must be 'gnielinski' or 'dittus_boelter'")
    warnings: list[str] = []
    applicability = "screening"
    boundary = str(thermal_boundary_condition).strip().casefold()
    if boundary not in {"conjugate", "one_sided", "uniform_heat_flux", "uniform_wall_temperature"}:
        raise ValueError("unknown internal-flow thermal boundary condition")
    if (distance_from_inlet_m is None) != (cell_length_m is None):
        raise ValueError("distance_from_inlet_m and cell_length_m must be supplied together")
    if distance_from_inlet_m is not None:
        distance_from_inlet_m = _positive(distance_from_inlet_m, "distance from heated inlet", allow_zero=True)
        cell_length_m = _positive(cell_length_m, "heated cell length")
    if entry_sample_fraction is not None:
        entry_sample_fraction = _positive(entry_sample_fraction, "entry sample fraction")
        if entry_sample_fraction >= 1.0:
            raise ValueError("entry sample fraction must be strictly between zero and one")
        if distance_from_inlet_m is None:
            raise ValueError("entry sample fraction requires inlet distance and cell length")
    aspect = None
    if channel_aspect_ratio is not None:
        aspect = _positive(channel_aspect_ratio, "channel aspect ratio")
        aspect = min(aspect, 1.0 / aspect)
    poiseuille = 64.0 if aspect is None else _rectangular_poiseuille_number(aspect)
    uniform_temperature = boundary == "uniform_wall_temperature"
    developing = distance_from_inlet_m is not None
    if reynolds < 4000.0 and boundary in {"conjugate", "one_sided"}:
        warnings.append("laminar rectangular Nu uses uniform all-wall heat flux reference; conjugate/one-sided heated boundary requires validation")
    if reynolds < 4000.0 and developing and (prandtl < 0.1 or (aspect is not None and aspect < 0.01)):
        developing = False
        applicability = "unsupported"
        warnings.append("developing laminar correlation outside Pr >= 0.1 / aspect ratio >= 0.01 domain; fully developed diagnostic fallback")

    def laminar_at(value: float) -> float:
        if developing:
            if entry_sample_fraction is not None:
                return developing_laminar_local_nusselt(
                    value, prandtl, hydraulic_diameter_m,
                    distance_from_inlet_m + entry_sample_fraction * cell_length_m,
                    channel_aspect_ratio=aspect, uniform_wall_temperature=uniform_temperature,
                )
            return developing_laminar_cell_nusselt(
                value, prandtl, hydraulic_diameter_m, distance_from_inlet_m, cell_length_m,
                channel_aspect_ratio=aspect, uniform_wall_temperature=uniform_temperature,
            )
        if aspect is None:
            return 3.66
        if uniform_temperature:
            ratio, _f_re, nu_fd, *_rest = _developing_laminar_parameters(prandtl, aspect, True)
            return nu_fd/ratio
        return _rectangular_fully_developed_nusselt(aspect)

    def turbulent_at(value: float) -> float:
        if name in {"dittus", "dittus_boelter", "db"}:
            return dittus_boelter_nusselt(value, prandtl)
        value = gnielinski_nusselt(value, prandtl, relative_roughness=relative_roughness)
        if distance_from_inlet_m is not None:
            if entry_sample_fraction is None:
                value *= _turbulent_cell_entry_factor(hydraulic_diameter_m, distance_from_inlet_m, cell_length_m)
            else:
                distance = distance_from_inlet_m + entry_sample_fraction * cell_length_m
                value *= 1.0 + (hydraulic_diameter_m / distance) ** (2.0 / 3.0) / 3.0
        return value

    if reynolds <= 2300.0:
        nusselt = laminar_at(reynolds)
        friction = poiseuille/reynolds
        regime = "laminar"
    elif reynolds < 4000.0:
        blend = (reynolds-2300.0)/1700.0
        lower = laminar_at(2300.0)
        upper = turbulent_at(4000.0)
        nusselt = (1.0-blend)*lower+blend*upper
        friction = (1.0-blend)*poiseuille/2300.0+blend*darcy_friction_factor(4000.0, relative_roughness)
        regime = "transition"
        warnings.append("Gnielinski (2013) Re=2300..4000 transition interpolation; rectangular/conjugate adaptation is not experimentally validated")
        warnings.append("transition Darcy friction uses continuous endpoint interpolation; transition hydraulics require validation")
        if lower > upper:
            warnings.append("short-entry laminar endpoint exceeds turbulent endpoint; transition interpolation is non-monotone and requires validation")
    else:
        nusselt = turbulent_at(reynolds)
        friction = darcy_friction_factor(reynolds, relative_roughness)
        regime = "turbulent"
    model = "fully developed internal flow"
    if developing and reynolds < 4000:
        model = "Muzychka-Yovanovich (2004) " + ("local" if entry_sample_fraction is not None else "cell-average") + " combined-entry " + ("UWT" if uniform_temperature else "UWF")
    elif distance_from_inlet_m is not None and name in {"gnielinski", "gn"}:
        model = "Gnielinski " + ("local" if entry_sample_fraction is not None else "cell-average") + " thermal-entry correction"
    if developing and reynolds < 4000:
        warnings.append("developing laminar reference assumes constant section/properties and uniform inlet profiles; local-property channel adaptation requires validation")
        warnings.append("laminar Darcy friction uses fully developed duct reference; hydrodynamic entrance pressure loss is not included")
    if distance_from_inlet_m is not None and reynolds > 2300 and name in {"gnielinski", "gn"}:
        warnings.append("turbulent thermal-entry factor adapted from circular tubes; rectangular/conjugate channel requires validation")
    if name in {"gnielinski", "gn"} and reynolds > 2300 and (
        reynolds > 5e6 or not 0.5 <= prandtl <= 2000
    ):
        applicability = "unsupported"
        warnings.append("Gnielinski Reynolds/Prandtl applicability range exceeded")
    if name in {"dittus", "dittus_boelter", "db"} and reynolds > 2300 and (
        reynolds < 10000 or not 0.7 <= prandtl <= 160
    ):
        applicability = "unsupported"
        warnings.append("Dittus-Boelter Reynolds/Prandtl applicability range exceeded")
    if distance_from_inlet_m is None:
        if reynolds < 4000:
            warnings.append("heated inlet distance/cell length unavailable; fully developed laminar reference used")
        if heated_length_m is not None and heated_length_m > 0 and reynolds < 2300 and heated_length_m < 0.05 * reynolds * prandtl * hydraulic_diameter_m:
            warnings.append("thermal entrance region: fully developed laminar correlation not applicable")
    entry_distance = distance_from_inlet_m if distance_from_inlet_m is not None else heated_length_m
    if reynolds >= 4000 and entry_distance is not None:
        if entry_distance < 10 * hydraulic_diameter_m:
            warnings.append("short turbulent entrance: circular-tube correction and inlet-profile assumptions require validation")
    coefficient = nusselt * conductivity_w_mk / hydraulic_diameter_m
    return InternalFlowHeatTransfer(
        coefficient_w_m2k=coefficient,
        nusselt=nusselt,
        reynolds=reynolds,
        prandtl=prandtl,
        hydraulic_diameter_m=hydraulic_diameter_m,
        velocity_m_s=velocity,
        flow_area_m2=total_flow_area_m2,
        friction_factor=friction,
        warnings=tuple(warnings),
        applicability=applicability,
        flow_regime=regime,
        nusselt_model=model,
    )


def rectangular_fin_area_ratio(
    *, channel_width_m: float, channel_height_m: float, pitch_m: float,
    coolant_coefficient_w_m2k: float, wall_conductivity_w_mk: float,
) -> tuple[float, float]:
    """Effective wetted width/pitch with straight adiabatic-tip rib fins.

    The closeout is adiabatic. The result includes the channel floor and
    both sidewalls, with fin efficiency rather than a unity area assumption.
    """
    width = _positive(channel_width_m, "channel width")
    height = _positive(channel_height_m, "channel height")
    pitch = _positive(pitch_m, "channel pitch")
    rib = pitch - width
    if rib <= 0:
        raise ValueError("channel pitch must exceed channel width")
    h = _positive(coolant_coefficient_w_m2k, "coolant coefficient")
    k = _positive(wall_conductivity_w_mk, "wall conductivity")
    mh = sqrt(2.0 * h / (k * rib)) * height
    efficiency = tanh(mh) / mh if mh > 1e-12 else 1.0
    return (width + 2.0 * height * efficiency) / pitch, efficiency


def cylindrical_conduction_resistance(
    inner_radius_m: float, thickness_m: float, conductivity_w_mk: float,
    *, reference_radius_m: float | None = None,
) -> float:
    """Radial resistance in m2 K/W referred to the chosen surface area."""
    radius = _positive(inner_radius_m, "inner radius")
    thickness = _positive(thickness_m, "wall thickness", allow_zero=True)
    conductivity = _positive(conductivity_w_mk, "conductivity")
    reference = radius if reference_radius_m is None else _positive(reference_radius_m, "reference radius")
    return reference * log(1.0 + thickness / radius) / conductivity


def rectangular_channel_geometry(
    width_m: float,
    height_m: float,
    channel_count: int,
) -> tuple[float, float]:
    """Return total flow area and hydraulic diameter for parallel rectangles."""

    width_m = _positive(width_m, "channel width")
    height_m = _positive(height_m, "channel height")
    if isinstance(channel_count, bool) or int(channel_count) < 1:
        raise ValueError("channel count must be an integer >= 1")
    total_area = int(channel_count) * width_m * height_m
    hydraulic_diameter = 2.0 * width_m * height_m / (width_m + height_m)
    return total_area, hydraulic_diameter


def radiative_heat_flux(
    hot_temperature_k: float,
    cold_temperature_k: float,
    emissivity: float,
) -> float:
    """Signed diffuse-grey radiation heat flux from hot to cold surface."""

    hot_temperature_k = _positive(hot_temperature_k, "hot temperature")
    cold_temperature_k = _positive(cold_temperature_k, "cold temperature")
    emissivity = _positive(emissivity, "emissivity", allow_zero=True)
    if emissivity > 1.0:
        raise ValueError("emissivity must not exceed one")
    return emissivity * STEFAN_BOLTZMANN_W_M2K4 * (
        hot_temperature_k**4 - cold_temperature_k**4
    )


def film_effectiveness(
    distance_downstream_m: float,
    film_mass_fraction: float,
    boundary_layer_thickness_m: float,
    *,
    mixing_coefficient: float = 1.0e-3,
    surface_layer_mass_fraction: float = 0.10,
) -> float:
    """Return a bounded film/BLC effectiveness based on RPA mixing form.

    RPA uses ``xi = 1-exp(-M*(x/Hs)^2)`` with
    ``M = Kt*m_surface/m_film`` and Kt in approximately 0.0005..0.002.
    Effectiveness is taken as the unmixed fraction ``1-xi``.  Positions ahead
    of the injector have zero effectiveness.
    """

    distance_downstream_m = float(distance_downstream_m)
    if not isfinite(distance_downstream_m):
        raise ValueError("distance must be finite")
    film_mass_fraction = _positive(film_mass_fraction, "film mass fraction")
    if film_mass_fraction >= 1.0:
        raise ValueError("film mass fraction must be below one")
    boundary_layer_thickness_m = _positive(
        boundary_layer_thickness_m, "surface-layer thickness"
    )
    mixing_coefficient = _positive(mixing_coefficient, "mixing coefficient")
    surface_layer_mass_fraction = _positive(
        surface_layer_mass_fraction, "surface-layer mass fraction"
    )
    if distance_downstream_m < 0.0:
        return 0.0
    normalized_distance = distance_downstream_m / boundary_layer_thickness_m
    mixing = mixing_coefficient * surface_layer_mass_fraction / film_mass_fraction
    return exp(-mixing * normalized_distance * normalized_distance)


def film_cooled_recovery_temperature(
    core_recovery_temperature_k: float,
    coolant_temperature_k: float,
    effectiveness: float,
) -> float:
    """Mix core and coolant recovery temperatures using film effectiveness."""

    core_recovery_temperature_k = _positive(
        core_recovery_temperature_k, "core recovery temperature"
    )
    coolant_temperature_k = _positive(coolant_temperature_k, "coolant temperature")
    effectiveness = _positive(effectiveness, "effectiveness", allow_zero=True)
    if effectiveness > 1.0:
        raise ValueError("film effectiveness must not exceed one")
    return (
        (1.0 - effectiveness) * core_recovery_temperature_k
        + effectiveness * coolant_temperature_k
    )


def annular_wall_area(radius_m: float, axial_step_m: float) -> float:
    """Lateral wall area of an axisymmetric axial cell."""

    return 2.0 * pi * _positive(radius_m, "radius") * _positive(
        axial_step_m, "axial step"
    )
