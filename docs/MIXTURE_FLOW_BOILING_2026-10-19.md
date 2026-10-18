# Mixture wet-wall flow boiling — 0.18 Beta

`lpa/thermal/two_phase.py::mixture_saturated_boiling` adds an explicitly
engineering route for a zeotropic mixture. It combines the Gungor–Winterton
1987 flow-boiling terms with the nucleate mass-transfer correction of
Thome–Shakir and the convective sensible-heat resistance of Bell–Ghaly, using
the procedure evaluated by Shah. This is distinct from passing averaged
mixture properties into a pure-fluid correlation without correction.

This route assumes a **continuously wetted wall for every computed two-phase
state**. It does not predict CHF, dryout onset, mist-flow/post-dryout heat
transfer, flow stability, maldistribution, or liquid-film thickness. A complete
computed liquid → two-phase → gas path is therefore not evidence of a safe,
continuously wetted physical channel. An actual dry patch could make its
predicted wall temperature substantially too low.

## Primary evidence and its limits

- Shah (2015), *A method for predicting heat transfer during boiling of
  mixtures in plain tubes*, Applied Thermal Engineering 89, 812–821,
  [DOI 10.1016/j.applthermaleng.2015.06.047](https://doi.org/10.1016/j.applthermaleng.2015.06.047),
  [publisher record](https://www.sciencedirect.com/science/article/pii/S1359431115006031).
  The published database covers 45 mixtures from 21 studies, D=0.19–14 mm,
  G=50–930 kg/(m² s), reduced pressure 0.05–0.63 and glides up to 156 K.
  These are the database's aggregate bounds, not a jointly validated rectangle
  or proof for every composition. The paper's full journal text was not
  available during this implementation; the method and equations were checked
  in the author's open conference predecessor below and the publisher text.
- Shah (2014), IHTC15-8351, *Evaluation of a method for predicting heat
  transfer during boiling of mixtures in plain tubes*,
  [author-hosted complete primary paper](https://mmshah.org/publications/IHTC15%20published%20mixture%20boiling.pdf),
  Eqs.1–8,15–16 and §5.2. Its smaller predecessor database has 695 points,
  42 datasets, D=2–14 mm, G=50–930 kg/(m² s), reduced pressure approximately
  0.05–0.63 and glide up to 28 K. Table 1 does **not** give a global quality
  interval; a plotted x-axis spanning 0–1 does not establish full-range
  validation. It evaluates each phase composition and its properties at each
  quality. The method's combined Thome–Shakir/Bell–Ghaly correction is the
  part reused here; it is not a dryout model.
- Ardhapurkar et al. (2014), *Flow boiling heat transfer coefficients at
  cryogenic temperatures for multi-component refrigerant mixtures of
  nitrogen–hydrocarbons*, Cryogenics 59, 84–92,
  [author-institution full paper](https://www.me.iitb.ac.in/~matrey/PDF%27s/Papers%20in%20International%20Journals/Flow%20boiling%20heat%20transfer%20coefficients%20at%20cryogenic%20temperatures%20for%20multi-component%20refrigerant%20mixtures%20of%20nitrogen%E2%80%93hydrocarbons.pdf).
  Eqs.9–12 give GW87 and the mixture nucleate correction; Eqs.21–23 give
  the added vapor sensible resistance. The underlying tests use a 0.835 mm
  tube, approximately 256–840 kg/(m² s), 0.394–1.439 MPa, and 79–83 kW/m²,
  with nitrogen-rich four/five-component compositions. These do not validate
  methane-rich LNG under rocket heat flux. The tested mixture corrections
  still have appreciable errors and composition dependence.
- Thome and Shakir (1987), *A new correlation for nucleate pool boiling of
  aqueous mixtures*, AIChE Symposium Series 83(257), 46–51, is the original
  mass-transfer correction. Its equation and recommended empirical beta were
  checked in Shah's primary paper, rather than claiming direct access to the
  1987 full text. Beta=0.0003 m/s is not a measured LNG/Et70 diffusion
  coefficient and is not fitted to LPA's output.
- Shah (2023), *Prediction of Critical Heat Flux of Mixtures Flowing in
  Channels*, [DOI 10.3390/fluids8030090](https://doi.org/10.3390/fluids8030090),
  [author-hosted primary paper](https://www.mmshah.org/publications/2023%20CHF%20mixtures%20in%20channels.pdf).
  Its comparison excludes water/alcohol mixtures because reliable general
  mixture transport was unavailable; the analyzed CHF data are for vertical
  upflow. It does not justify transplanting a CHF threshold to a one-sided
  rectangular rocket channel with arbitrary orientation.
- Tsou, Fu and Pan (2012), *Boiling heat transfer and critical heat flux of
  ethanol–water mixtures flowing through a diverging microchannel with
  artificial cavities*, [DOI 10.1016/j.ijheatmasstransfer.2011.11.051](https://doi.org/10.1016/j.ijheatmasstransfer.2011.11.051).
  Its experiments demonstrate composition/Marangoni effects on both heat
  transfer and CHF. This particular structured diverging microchannel is not
  a general Et70 or LPA-channel validation.

The LNG set discussed in Shah's mixture analysis was an exception: the
uncorrected pure-fluid GW/Shah equations agreed better for that set. No special
case is fitted to force agreement in LPA. Methane-containing mixtures receive
an explicit fluid-specific validation warning. Aqueous/alcohol mixtures receive
an `unsupported` correlation-validation label while returning the requested
finite engineering estimate, because their flow-boiling and Marangoni behavior
is outside the demonstrated Shah database.

## State/API contract

The existing `saturated_boiling` pure-fluid route and its default x≤0.7
calculation guard are preserved. That quality limit remains a software guard,
not a dryout prediction. The separate API is:

```python
mixture_saturated_boiling(
    *, state, mass_flow_kg_s, total_flow_area_m2, hydraulic_diameter_m,
    wall_temperature_k, wall_heat_flux_w_m2,
    model="shah_gungor_winterton", mass_transfer_coefficient_m_s=3e-4,
)
```

Heat flux must be referred to the **actual heated coolant surface**, in W/m²;
the solid/gas reference flux must be converted consistently by the solver.
G is total mass flow divided by the total area of parallel channels. Hydraulic
diameter adapts the circular reference; channel count must not scale G twice.

Required state data include component identities, P, T, critical P, mass vapor
quality, and both equilibrium phases' density, Cp, k, viscosity, h and molecular
weight. Molecular weights use kg/mol. Surface tension is not required. Native
or explicit engineering phase transport is accepted; missing phase transport
replaced by legacy screening fallback is rejected. Invalid/NaN/negative
properties, cold wall, nonpositive heat flux, critical/supercritical pressure,
and invalid quality raise `TwoPhaseApplicabilityError`.

Three additional state fields are required:

1. `mixture_liquid_bubble_temperature_k` and
   `mixture_liquid_dew_temperature_k`: bubble/dew at the current pressure and
   **the same current liquid-phase mole composition**. Their difference is the
   local Thome–Shakir boiling range. The bubble point must agree with the local
   equilibrium T to within max(0.01 K,1e-5 T). A constant initial-overall-z
   bubble/dew span misses enrichment of the residual liquid.
2. `equilibrium_temperature_enthalpy_derivative_k_kg_j`: local equilibrium
   dT/dh at fixed P and fixed overall composition z, in K kg/J. A neighboring
   PQ flash can supply it with mass-quality conversion and mixture h. It is
   not 1/Cp from an arbitrary two-phase bulk EOS getter and does not include
   the pressure drop along the channel.

The quality is mass based. Using a provider's mole quality directly would
corrupt G_l/G_v, HEM density, the molecular-weight conversion and Bell–Ghaly Y.
No molecular diffusivity is guessed. The input beta has units m/s, distinct
from diffusivity in m²/s.

## Equations and conventions

For `0 <= x < 1`, using current phase properties:

```
G = m_dot/A_total                  [kg/(m2 s)]
Re_l = G*(1-x)*Dh/mu_l
Re_GS = G*x*Dh/mu_v
Pr_i = Cp_i*mu_i/k_i
h_l = 0.023*Re_l^0.8*Pr_l^0.4*k_l/Dh
Bo = q/(G*(h_v-h_l_phase))
h_nb = 3000*Bo^0.86*h_l
h_cb = [1+1.12*(x/(1-x))^0.75*(rho_l/rho_v)^0.41]*h_l
h_GS = 0.023*Re_GS^0.8*Pr_v^0.4*k_v/Dh

h_I = Cooper(P,Pcritical,MW_g_per_mol,q), default Rp=1 micrometre
DeltaT_bp = Tdew(P,z_liquid)-Tbubble(P,z_liquid)
F_TS = {1+(h_I/q)*DeltaT_bp*[1-exp(-q/(rho_l*(h_v-h_l_phase)*beta))]}^-1
Y = x*Cp_v*(dT/dh)|P,z
h_mix = F_TS*h_nb + [1/h_cb+Y/h_GS]^-1
```

Cooper is evaluated using the state's overall mixture critical pressure and
the overall molecular weight recovered from the phases:
`MW_kg/mol = 1/[(1-x)/MW_liquid+x/MW_vapor]`, followed by multiplication by
1000 for g/mol. The reference-critical/MW choice and use of `h_v-h_l_phase`
as the mixture vaporization enthalpy are explicit engineering conventions;
neither replaces a rigorous multicomponent interfacial/film solution. The
provider's actual phase transport and local glide change throughout boiling.

`expm1` retains the small-q mass-transfer limit. The convective expression is
evaluated in its algebraically equivalent stable form:

```
h_cb = h_LO*[(1-x)^0.8+1.12*x^0.75*(1-x)^0.05*(rho_l/rho_v)^0.41]
```

This avoids a divergent intermediate `(x/(1-x))` at high quality without
clipping quality or inserting a heat-transfer floor. At x=0, Y=0 and the vapor
resistance vanishes; the exact liquid pressure-loss limit avoids a library
zero-vapor-Re division. Smooth-channel Lockhart–Martinelli friction and HEM
density are used as in the existing route. Acceleration, kinetic energy,
changing area and the final gas branch are the solver's responsibility.

## High quality and applicability

The wet GW87 expression tends mathematically to zero as x→1 because its
dominant power is `(1-x)^0.05`. It **does not** approach single-phase vapor h.
LPA neither invents a blend nor uses a quality floor to conceal this limit.
At the equilibrium dew endpoint, the channel solver switches to single-phase
gas convection; that model switch can cause a discontinuity and is exposed as
an engineering limitation. A finite x<1 estimate at very high quality is not
a post-dryout calculation.

All results are at best `screening`. D, G, reduced P and glide outside the
aggregate Shah database, phase Pr outside 0.7–160 or phase Re below the
underlying Dittus–Boelter turbulent reference of 10000 are marked
`unsupported`, while finite engineering values are returned. This separates
computability from validation. Endpoint phase Re naturally leaves the
turbulent reference as x approaches zero or one; this does not authorize a
fabricated laminar-film/dryout model. Y>1 is also explicitly flagged, because
it leaves its sensible-heat-fraction interpretation.

`BoilingResult` provides corrected/uncorrected nucleate and convective h,
vapor-reference h, both correction factors, local glide, Y, Bo, regime,
applicability and warnings. `wet_wall_assumed=True` is explicit;
`critical_heat_flux_w_m2` and `dryout_vapor_quality` remain NaN.

`tests/test_mixture_flow_boiling.py` checks resistance limits and pure-mixture
limit reduction, independent Cooper unit conversion, local-glide sensitivity,
mass-flux invariance, exact x=0 and the largest representable x<1, explicit
unknown CHF/dryout, invalid/fallback rejection, and finite estimates with
unsupported composition/domain labels. These tests verify implementation
and numerical guards; independent LNG/Et70 channel measurements remain absent.

## UI, project persistence and export

The thermal input selection has three modes: `Auto (Beta)` enables both the
pure-fluid and mixture routes, `Pure fluids only` disables only mixture
boiling, and `Disabled` disables both. The project persists the mixture mode
and empirical beta; old files missing them receive stable defaults rather
than the preceding project's values. A file with an explicit disabled mixture
mode opens as `Pure fluids only`. The ordinary UI identifies wet-wall and
unpredicted CHF/dryout limitations without presenting beta as measured data.

Axial results and CSV add local liquid-composition glide, F_TS, F_BG and the
wet-wall assumption. Boolean false, true and unknown remain distinct. Unknown
legacy values are empty in CSV and shown as a dash in the table. A diagnosed
unsolved station can retain its known phase and mixture diagnostics while its
wall temperatures stay empty. CSV retains numerical completion, station
applicability, the mixture method/beta metadata, and segment outlet phase and
property applicability. Numerical completion never promotes an unsupported
engineering result to a validated physical result.
