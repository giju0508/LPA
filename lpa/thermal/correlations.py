"""Heat-transfer correlations for preliminary liquid-engine analysis.

The Bartz implementation follows the form printed in the supplied RPA
Thermal Analysis document.  Internal-flow helpers provide both the classic
Dittus-Boelter and the wider-range Gnielinski correlations.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    """Gnielinski turbulent correlation with a transition blend.

    A fully developed laminar value of 3.66 is used below Re=2300 and blended
    to the turbulent expression through Re=3000.  This keeps a mesh march
    numerically continuous when a channel crosses the transition range.
    """

    reynolds = _positive(reynolds, "Reynolds number")
    prandtl = _positive(prandtl, "Prandtl number")
    relative_roughness = _positive(
        relative_roughness, "relative roughness", allow_zero=True
    )
    if reynolds <= 2300.0:
        return 3.66
    turbulent_reynolds = max(reynolds, 3000.0)
    friction = darcy_friction_factor(turbulent_reynolds, relative_roughness)
    numerator = (friction / 8.0) * (turbulent_reynolds - 1000.0) * prandtl
    denominator = 1.0 + 12.7 * sqrt(friction / 8.0) * (prandtl ** (2.0 / 3.0) - 1.0)
    turbulent = max(3.66, numerator / denominator)
    if reynolds >= 3000.0:
        return turbulent
    blend = (reynolds - 2300.0) / 700.0
    return 3.66 + blend * (turbulent - 3.66)


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
) -> InternalFlowHeatTransfer:
    """Evaluate coolant-side convection for the sum of all parallel channels."""

    mass_flow_kg_s = _positive(mass_flow_kg_s, "coolant mass flow")
    total_flow_area_m2 = _positive(total_flow_area_m2, "channel flow area")
    hydraulic_diameter_m = _positive(hydraulic_diameter_m, "hydraulic diameter")
    density_kg_m3 = _positive(density_kg_m3, "coolant density")
    viscosity_pa_s = _positive(viscosity_pa_s, "coolant viscosity")
    conductivity_w_mk = _positive(conductivity_w_mk, "coolant conductivity")
    specific_heat_j_kgk = _positive(specific_heat_j_kgk, "coolant specific heat")
    velocity = mass_flow_kg_s / (density_kg_m3 * total_flow_area_m2)
    reynolds = density_kg_m3 * velocity * hydraulic_diameter_m / viscosity_pa_s
    prandtl = specific_heat_j_kgk * viscosity_pa_s / conductivity_w_mk
    name = str(correlation).strip().casefold().replace("-", "_")
    warnings: list[str] = []
    if name in {"dittus", "dittus_boelter", "db"}:
        if reynolds < 2300.0:
            nusselt = 3.66
        else:
            turbulent = dittus_boelter_nusselt(max(reynolds, 3000.0), prandtl)
            if reynolds < 3000.0:
                turbulent = 3.66 + (reynolds - 2300.0) / 700.0 * (turbulent - 3.66)
            nusselt = turbulent
    elif name in {"gnielinski", "gn"}:
        nusselt = gnielinski_nusselt(
            reynolds, prandtl, relative_roughness=relative_roughness
        )
    else:
        raise ValueError("correlation must be 'gnielinski' or 'dittus_boelter'")
    friction = darcy_friction_factor(reynolds, relative_roughness)
    if reynolds < 3000.0 and channel_aspect_ratio is not None:
        aspect = _positive(channel_aspect_ratio, "channel aspect ratio")
        aspect = min(aspect, 1.0 / aspect)
        # Shah & London fully developed rectangular-duct results: Darcy
        # Poiseuille number and uniform heat flux on all four walls. The
        # conjugate rocket-channel boundary condition is separately flagged.
        laminar_friction = 96.0 / reynolds * (
            1 - 1.3553*aspect + 1.9467*aspect**2 - 1.7012*aspect**3
            + 0.9564*aspect**4 - 0.2537*aspect**5
        )
        laminar_nusselt = 8.235 * (
            1 - 2.0421*aspect + 3.0853*aspect**2 - 2.4765*aspect**3
            + 1.0578*aspect**4 - 0.1861*aspect**5
        )
        if reynolds < 2300.0:
            friction, nusselt = laminar_friction, laminar_nusselt
            warnings.append("laminar rectangular Nu uses uniform all-wall heat flux; conjugate boundary requires validation")
        else:
            blend=(reynolds-2300.0)/700.0
            turbulent_nusselt=(dittus_boelter_nusselt(3000.,prandtl)
                if name in {"dittus","dittus_boelter","db"}
                else gnielinski_nusselt(3000.,prandtl,relative_roughness=relative_roughness))
            nusselt=laminar_nusselt+blend*(turbulent_nusselt-laminar_nusselt)
            friction=laminar_friction+blend*(darcy_friction_factor(3000.,relative_roughness)-laminar_friction)
    if 2300.0 <= reynolds < 3000.0:
        warnings.append("transition heat-transfer blend is not experimentally validated")
    if name in {"gnielinski", "gn"} and reynolds >= 3000 and (
        reynolds > 5e6 or not 0.5 <= prandtl <= 2000
    ):
        warnings.append("Gnielinski Reynolds/Prandtl applicability range exceeded")
    if name in {"dittus", "dittus_boelter", "db"} and (
        reynolds < 10000 or not 0.7 <= prandtl <= 160
    ):
        warnings.append("Dittus-Boelter Reynolds/Prandtl applicability range exceeded")
    if heated_length_m is not None and heated_length_m > 0:
        if reynolds < 2300 and heated_length_m < 0.05 * reynolds * prandtl * hydraulic_diameter_m:
            warnings.append("thermal entrance region: fully developed laminar correlation not applicable")
        elif reynolds >= 2300 and heated_length_m < 10 * hydraulic_diameter_m:
            warnings.append("short heated entrance region: fully developed turbulent correlation unverified")
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
