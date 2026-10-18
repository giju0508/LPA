"""Development RP-1 engineering surrogate using public constituent EOS data.

The trans-decalin coefficients below are from the freely available NIST TN1949
supplement, TDEC.FLD (2016 revision), DOI:10.6028/NIST.TN.1949s. This is NOT the
four-component RP-1 surrogate of Huber et al. (2009). Mixture fitting and its
validation are independent LPA work; no REFPROP library or license is required.
"""
from __future__ import annotations

import json
from functools import lru_cache
from math import exp, isfinite, nan, nextafter
from threading import RLock, local

TRANS_DECALIN_NAME = "LPA-TransDecalin-TN1949"
TRANS_DECALIN_SOURCE = "https://doi.org/10.6028/NIST.TN.1949s"
SURROGATE_MOLE_FRACTIONS = (.59027610, .40972390)
SURROGATE_SOURCE = "LPA fitted trans-decalin/n-dodecane engineering surrogate; public NIST constituent EOS"
SURROGATE_REFERENCES = (
    TRANS_DECALIN_SOURCE,
    "https://doi.org/10.1021/ef0341062",
    "https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=832303",
    "https://nvlpubs.nist.gov/nistpubs/Legacy/IR/nistir6646.pdf",
    "https://doi.org/10.1016/j.fuel.2010.09.038",
    "https://doi.org/10.1016/j.fuel.2018.08.073",
    "https://doi.org/10.1016/j.fuel.2009.06.015",
    "https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote1039.pdf",
)
_LOCAL = local()
_REGISTRATION_LOCK = RLock()

# (n, t, d, l) in n*delta**d*tau**t*exp(-delta**l); l=0 omits the exponential.
_POWER = (
    (.04969487665758,1.,4.,0.), (1.443817986834,.402926211651,1.,0.),
    (-2.122614529535,1.043469629952,1.,0.), (-.5020452928228,1.276959746520,2.,0.),
    (.1505721529737,.496854671723,3.,0.), (-1.006391327717,1.850510188720,1.,2.),
    (-.4534445220891,1.658436767771,3.,2.), (.6544921487280,2.302117773988,2.,1.),
    (-.3614866505541,2.600410432041,2.,2.), (-.02544256027025,.815175809957,7.,1.),
)
# (n,t,d,eta,beta,gamma,epsilon), positive widths, standard Helmholtz Gaussian.
_GAUSSIAN = (
    (.8576537558547,.781555734985,1.,1.02294837,1.6960156,1.096155129,.713433428),
    (-.3149844029289,1.911950551579,1.,1.38307932,1.5532084,.642059249,.917326058),
    (-.1252291539276,2.837779631545,3.,.99600153,1.0725397,.498472804,.688069217),
    (-.2862295181630,.931198266435,3.,7.03845800,87.1675081,1.259885647,.748061690),
)


@lru_cache(maxsize=1)
def register_trans_decalin() -> str:
    """Register the publicly supplied Helmholtz coefficients once per process.

    Ancillary curves below are fitted to this exact EOS's numerical coexistence
    solutions and serve only as initial guesses. Final equilibrium is solved
    from the constituent Helmholtz energy, not from these ancillary fits.
    """
    import CoolProp.CoolProp as cp
    try:
        cp.AbstractState("HEOS", TRANS_DECALIN_NAME)
        return TRANS_DECALIN_NAME
    except ValueError:
        pass
    fluid = json.loads(cp.get_fluid_param_string("n-Dodecane", "JSON"))[0]
    tc, pc, rc, triple = 687.02, 3151642.388003063, 2018.013299, 242.76
    fluid["INFO"] = dict(NAME=TRANS_DECALIN_NAME, CAS="493-02-7", ALIASES=[],
                         REFPROP_NAME="TDEC", FORMULA="C10H18", INCHI_KEY="",
                         INCHI_STRING="", SMILES="")
    eos = fluid["EOS"][0]
    eos.pop("SUPERANCILLARY", None)
    eos.pop("critical_region_splines", None)
    eos.update(T_max=1000., Ttriple=triple, acentric=.292712, molar_mass=.13825,
               p_max=50e6, BibTeX_EOS="NIST-TN-1949", BibTeX_CP0="NIST-TN-1949")
    eos["alphar"] = [
        dict(type="ResidualHelmholtzPower", **{
            key:[row[i] for row in _POWER] for i,key in enumerate(("n","t","d","l"))}),
        dict(type="ResidualHelmholtzGaussian", **{
            key:[row[i] for row in _GAUSSIAN] for i,key in enumerate(("n","t","d","eta","beta","gamma","epsilon"))}),
    ]
    eos["alpha0"] = [
        dict(type="IdealGasHelmholtzLead", a1=0., a2=0.),
        dict(type="IdealGasHelmholtzLogTau", a=7.54281894224-1.),
        dict(type="IdealGasHelmholtzPlanckEinstein",
             n=[1.23966362903,39.2179327001,28.5288837726],
             t=[539.63248811/tc,2487.93008642/tc,1000.63521190/tc]),
    ]
    # Derived from the exact source EOS. Its critical Pc differs slightly from
    # the older FLD header; mixing the two would make the JSON inconsistent.
    points = {
        "critical":(tc,pc,rc,124125.76563442481,264.6494351018253),
        "reducing":(tc,pc,rc,124125.76563442481,264.6494351018253),
        "hs_anchor":(755.722,5193033.141987915,1816.2119691,155011.42124930804,306.0087628125544),
        "triple_liquid":(triple,1.750401000971254,6570.089119017624,-31600.64016415932,-68.11736526613572),
        "triple_vapor":(triple,1.750401000971254,.000867217031944142,19840.527729929363,143.783968949092),
    }
    for group in (eos["STATES"],fluid["STATES"]):
        for key,state in group.items():
            key=key.replace("sat_min_","triple_")
            t,p,r,h,s=points[key]
            state.update(T=t,p=p,rhomolar=r,hmolar=h,smolar=s)
    # Coexistence points: 25 T values from 242.76 to 440 K plus 50 from 450 to
    # 680 K, solved for equal pressure and chemical potential. Scaled dodecane
    # guesses were insufficient: they led native QT to an almost-vacuum root.
    fluid["ANCILLARIES"] = {
        "pS":dict(type="pV",using_tau_r=True,T_r=tc,Tmin=triple,Tmax=tc,
            reducing_value=pc,t=[1.,1.5,2.5,5.],
            n=[-7.61136434513768,2.0282467017863,-2.65420031151274,-2.93418667412158]),
        "rhoL":dict(type="rhoLnoexp",using_tau_r=False,T_r=tc,Tmin=triple,Tmax=tc,
            reducing_value=rc,t=[1/3,2/3,1.,4/3,2.,3.],
            n=[2.82756469649089,-2.73541515547917,4.43505636632703,-1.95044317877399,-.325120948695152,.789994817153528]),
        "rhoV":dict(type="rhoV",using_tau_r=True,T_r=tc,Tmin=triple,Tmax=tc,
            reducing_value=rc,t=[1/3,2/3,1.,4/3,2.,3.],
            n=[-1.7261008058387,-4.60852702694662,9.62166949238994,-16.3560417788586,13.4399896395267,-10.8590669815855]),
    }
    fluid.pop("TRANSPORT", None)
    cp.add_fluids_as_JSON("HEOS", json.dumps([fluid]))
    return TRANS_DECALIN_NAME


@lru_cache(maxsize=1)
def _configure_mixture() -> str:
    import CoolProp.CoolProp as cp
    with _REGISTRATION_LOCK:
        name = register_trans_decalin()
        try:
            cp.get_mixture_binary_pair_data("112-40-3", "493-02-7", "betaT")
        except ValueError:
            cp.apply_simple_mixing_rule("493-02-7", "112-40-3", "linear")
    return name+"&n-Dodecane"


def _state(kind: str = "bulk"):
    import CoolProp.CoolProp as cp
    cache = getattr(_LOCAL,"states",None)
    if cache is None:
        cache = _LOCAL.states = {}
    if kind not in cache:
        state = cp.AbstractState("HEOS", _configure_mixture())
        state.set_mole_fractions(SURROGATE_MOLE_FRACTIONS)
        cache[kind] = state
    return cache[kind]


@lru_cache(maxsize=1)
def surrogate_critical_properties() -> tuple[float,float,float]:
    """Stable critical point of this surrogate, not measured RP-1 constants."""
    points = [point for point in _state("critical").all_critical_points()
              if point.stable and 658.1 <= point.T <= 687.02 and point.p>0]
    if len(points)!=1:
        raise ValueError("RP-1 engineering-surrogate critical point is ambiguous")
    point=points[0]
    return float(point.T),float(point.p),float(point.rhomolar)


@lru_cache(maxsize=1024)
def surrogate_bubble_temperature(pressure_pa: float) -> float:
    """Exact EOS bubble boundary, below the surrogate's own critical pressure."""
    import CoolProp.CoolProp as cp
    tc,pc,_=surrogate_critical_properties()
    if pressure_pa>=pc:
        return nan
    state=_state("bubble")
    state.unspecify_phase()
    state.update(cp.PQ_INPUTS,pressure_pa,0.)
    temperature=float(state.T())
    liquid_density=float(state.saturated_liquid_keyed_output(cp.iDmass))
    vapor_density=float(state.saturated_vapor_keyed_output(cp.iDmass))
    if not 263.6<=temperature<=tc or liquid_density<=vapor_density:
        raise ValueError("RP-1 engineering-surrogate bubble flash failed its phase consistency check")
    return temperature


def _transport(temperature_k: float, molar_density: float):
    from .mixture_transport import TransportComponent, lng_ecs_transport
    # Consistent critical point calculated from this exact Helmholtz equation;
    # the FLD header's older Pc differs slightly from the EOS's critical value.
    cp0=8.314472*(7.54281894224+sum(
        n*(theta/temperature_k)**2*exp(theta/temperature_k)/(exp(theta/temperature_k)-1.)**2
        for n,theta in ((1.23966362903,539.63248811),(39.2179327001,2487.93008642),
                        (28.5288837726,1000.63521190))))
    component=TransportComponent("trans-Decalin",687.02,3151642.388003063,
                                  2018.013299,.13825,.292712,cp0)
    return lng_ecs_transport(temperature_k=temperature_k,
        molar_density_mol_m3=molar_density, components=(component,"n-Dodecane"),
        mole_fractions=SURROGATE_MOLE_FRACTIONS)


def _viscosity_factor(temperature_k: float) -> float:
    """LPA residual correction fitted only to the nine 2009 RP-1 measurements.

    It decays continuously to the uncorrected nonpolar TRAPP prediction rather
    than imposing a high-temperature viscosity floor or extending the old Eq1.
    The high-temperature prediction is independently checked against 2019 data.
    """
    return 1. + 1.0312314725505*exp(-.014600610562506*(temperature_k-293.15))


def _conductivity(temperature_k: float, pressure_pa: float) -> float:
    """Smooth fit to radiation-corrected NISTIR6646 data; high-T holdout checks.

    271 source points with Te<550 K and P<=50 MPa fit these five coefficients.
    The separate 50 source points at 550<=Te<630 K are not used in the fit.
    This is a predictive surface, not an assertion that its rectangle is measured.
    """
    p=pressure_pa/1e6
    baseline=.114548152+.000393458921*p-.00000380512629*p*p
    exponent=.733478903-.00674024775*p
    return baseline*(temperature_k/293.15)**(-exponent)


def rp1_surrogate_estimate(temperature_k: float, pressure_pa: float) -> dict:
    """Return CoolantState-compatible fields for a conditional liquid model.

    Raises ValueError outside its declared domain or in a predicted non-liquid
    state. This engineering surrogate is calibrated on RP-1 density and tested
    independently; it never inherits the original NIST four-component accuracy.
    """
    import CoolProp.CoolProp as cp
    if not isfinite(temperature_k) or not 270.<=temperature_k<650.:
        raise ValueError("RP-1 engineering surrogate requires 270 <= T < 650 K; thermal decomposition is unmodelled")
    if not isfinite(pressure_pa) or not 0.<pressure_pa<=50e6:
        raise ValueError("RP-1 engineering surrogate requires 0 < P <= 50 MPa (constituent EOS limit)")
    tc,pc,_=surrogate_critical_properties()
    bubble=surrogate_bubble_temperature(pressure_pa)
    if isfinite(bubble) and temperature_k>=bubble:
        raise ValueError("RP-1 engineering-surrogate state reaches predicted boiling; its two-phase/volatile distribution model is not validated")
    state=_state()
    # The exact bubble solution, or P >= Pc with T < Tc, supplies the liquid
    # branch proof. Unforced HEOS PT can select a spurious dense gas root here.
    state.specify_phase(cp.iphase_liquid)
    try:
        state.update(cp.PT_INPUTS,pressure_pa,temperature_k)
    finally:
        state.unspecify_phase()
    rho,heat_capacity=float(state.rhomass()),float(state.cpmass())
    if (not all(isfinite(v) and v>0 for v in (rho,heat_capacity))
            or state.first_partial_deriv(cp.iP,cp.iDmolar,cp.iT)<=0):
        raise ValueError("RP-1 engineering-surrogate liquid root is mechanically unstable")
    transport=_transport(temperature_k,float(state.rhomolar()))
    viscosity=transport.viscosity_pa_s*_viscosity_factor(temperature_k)
    conductivity=_conductivity(temperature_k,pressure_pa)
    issues=(
        "RP-1 uses a newly fitted two-component engineering surrogate, not the published NIST four-component RP-1 model",
        "RP-1 surrogate density calibration and independent Cp/transport checks do not validate an individual fuel lot or its vapor-liquid envelope",
        "RP-1 high-temperature transport remains predictive; thermal decomposition/coking and deposit resistance are not modelled",
        "RP-1 viscosity uses a low-temperature empirical residual correction to TRAPP; conductivity is a separate radiation-corrected NIST-data fit",
        *transport.issues,
    )
    evidence=tuple(dict(property_name=label,source=SURROGATE_SOURCE if label in {
        "density_kg_m3","specific_heat_j_kgk"} else "NISTIR6646 radiation-corrected conductivity fit" if label=="conductivity_w_mk"
        else transport.source+"; LPA low-temperature residual correction",
        applicability="correlated",temperature_range_k=(270.,650.),pressure_range_pa=(0.,50e6),
        maximum_temperature_inclusive=False,minimum_pressure_inclusive=False,
        notes=("Declared engineering model domain [270,650) K; not a rectangular measured or fuel-lot validation range.",))
        for label in ("density_kg_m3","specific_heat_j_kgk","conductivity_w_mk","viscosity_pa_s"))
    return dict(temperature_k=temperature_k,pressure_pa=pressure_pa,
        density_kg_m3=rho,specific_heat_j_kgk=heat_capacity,
        conductivity_w_mk=conductivity,viscosity_pa_s=viscosity,
        enthalpy_j_kg=float(state.hmass()),phase="liquid" if pressure_pa<pc else "supercritical_liquid",
        source=SURROGATE_SOURCE,thermodynamic_source=SURROGATE_SOURCE,
        transport_source=transport.source+" + RP-1 residual correction; NIST corrected-conductivity fit",property_applicability="correlated",
        thermodynamic_applicability="correlated",transport_applicability="correlated",
        critical_temperature_k=tc,critical_pressure_pa=pc,saturation_temperature_k=bubble,
        speed_of_sound_m_s=float(state.speed_sound()),specific_heat_cv_j_kgk=float(state.cvmass()),
        gas_constant_j_kgk=float(state.gas_constant()/state.molar_mass()),
        property_notes=("Conditional engineering surrogate; quoted NIST four-component errors do not apply.",),
        property_references=SURROGATE_REFERENCES,property_evidence=evidence,issues=issues)


def rp1_surrogate_from_enthalpy(enthalpy_j_kg: float, pressure_pa: float,
                                *, temperature_hint_k: float | None = None) -> dict:
    """Bracket h(T,P) on the supported dense branch, then reevaluate all fields.

    A native-mixture PH Newton flash can cross a VLE boundary or select a
    spurious root. Only h is evaluated inside this bracket, making this helper
    faster than iterating the full empirical transport calculation.
    """
    import CoolProp.CoolProp as cp
    from scipy.optimize import brentq
    if not isfinite(enthalpy_j_kg):
        raise ValueError("RP-1 surrogate enthalpy must be finite")
    if not isfinite(pressure_pa) or not 0.<pressure_pa<=50e6:
        raise ValueError("RP-1 engineering surrogate requires 0 < P <= 50 MPa")
    bubble=surrogate_bubble_temperature(pressure_pa)
    lower,upper=270.,nextafter(650.,0.)
    if isfinite(bubble):
        upper=min(upper,nextafter(bubble,0.))
    if upper<=lower:
        raise ValueError("No supported liquid-temperature bracket for RP-1 surrogate at this pressure")
    state=_state("enthalpy")
    def residual(temperature: float) -> float:
        state.specify_phase(cp.iphase_liquid)
        try:
            state.update(cp.PT_INPUTS,pressure_pa,temperature)
        finally:
            state.unspecify_phase()
        if state.cpmass()<=0 or state.first_partial_deriv(cp.iP,cp.iDmolar,cp.iT)<=0:
            raise ValueError("Unstable RP-1 surrogate branch during h-p inversion")
        return float(state.hmass())-enthalpy_j_kg
    low_residual,high_residual=residual(lower),residual(upper)
    tolerance=max(1.,abs(enthalpy_j_kg))*1e-10
    if low_residual>tolerance or high_residual < -tolerance:
        raise ValueError("RP-1 enthalpy lies outside supported liquid branch [270,650) K or reaches boiling")
    if abs(low_residual)<=tolerance:
        temperature=lower
    elif abs(high_residual)<=tolerance:
        temperature=upper
    else:
        temperature=brentq(residual,lower,upper,xtol=1e-9,rtol=1e-12)
    result=rp1_surrogate_estimate(temperature,pressure_pa)
    if abs(result["enthalpy_j_kg"]-enthalpy_j_kg)>max(1e-4,abs(enthalpy_j_kg)*1e-8):
        raise ValueError("RP-1 surrogate h-p inversion fails energy closure")
    return result
