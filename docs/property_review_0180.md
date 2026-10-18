# RP-1 engineering surrogate, 0.18.0 Beta

The 333.15 K limit belonged to the old atmospheric viscosity fit. Removing that
limit would not supply RP-1 density, Cp, enthalpy, pressure dependence, or phase
stability. The new `rp1_surrogate.py` therefore implements a different model with
pressure-dependent, thermodynamically consistent density, Cp and enthalpy, a
computed liquid boundary, and independently checked transport predictions.

This is an **LPA fitted trans-decalin/n-dodecane engineering surrogate**. It is
not the four-component NIST RP-1 surrogate, and its accuracy does not inherit the
published validation of that model. Its overall applicability is `correlated`;
fuel-lot variation, decomposition and hardware heat-transfer validation remain
separate limitations.

## Constituent thermodynamics and calibration

The trans-decalin Helmholtz coefficients, ideal-gas heat capacity and declared
EOS limits come from the publicly downloadable
[NIST TN1949 supplement](https://doi.org/10.6028/NIST.TN.1949s), `TDEC.FLD`, 2016
revision. The module contains the numerical coefficients needed for that model;
it does not bundle a REFPROP library or redistribute its commercial database.
n-Dodecane uses the installed CoolProp implementation of
[Lemmon and Huber (2004)](https://doi.org/10.1021/ef0341062).
CoolProp's explicit `linear` reducing-rule estimate supplies the binary parameters;
no fitted binary interaction parameters or experimental mixture VLE claims are
introduced.

One composition parameter was fitted to 12 actual RP-1 density measurements in
[Outcalt et al. (2009), Table 2](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=832303).
The fit temperatures were 290, 350, 410 and 470 K at nominal pressures 2, 5 and
10 MPa, using each table's actual pressure. The resulting mole fractions are
**0.59027610 trans-decalin / 0.40972390 n-dodecane**. The maximum fitting residual
is approximately **0.28%**. These fractions represent a fitted physical-property
proxy, not an asserted analysis of RP-1 chemical composition.

The mixture EOS calculates density, Cp, Cv, enthalpy and sound speed together.
Cp is the temperature derivative of that same enthalpy; no independent linear
Cp or density correction is applied. PH inversion brackets the supported liquid
branch of h(T,P), checks positive Cp and mechanical stability, and reevaluates all
properties at the actual pressure after inversion. The enthalpy reference is an
arbitrary EOS datum; its sign has no physical significance.

The source trans-decalin EOS has a calculated critical pressure of 3.151642 MPa,
slightly different from its older FLD header. The JSON critical and anchor states
use the actual EOS results consistently. Three ancillary curves were regenerated
from 75 numerical EOS coexistence solutions solely to initialize equilibrium
iterations. Scaled n-dodecane guesses had caused an almost-vacuum pure-fluid QT
root at low temperature. Tests now check equal Gibbs energies of the two phases
at 293, 400 and 600 K, rather than accepting a plausible liquid density alone.

For the final mixture, its calculated critical point is **675.45 K / 24.7275 bar**.
Its bubble temperature is **471.78 K at 1 bar** and **657.29 K at 20 bar**.
These are surrogate predictions, not measured RP-1 phase-envelope data. For
comparison, the original NIST four-component model reports an initial boiling
point of 475.6 K at standard pressure. The lower predicted initial boiling point
does not establish a conservative bound throughout the pressure range.

## Transport models

Viscosity uses the original nonpolar Ely–Hanley TRAPP one-fluid model with the
mixture EOS density. A two-parameter residual correction was fitted only to the
nine atmospheric RP-1 viscosity measurements, 293.38–373.15 K, in Outcalt Table 4:

`mu = mu_TRAPP * (1 + 1.0312314725505 * exp(-0.014600610562506*(T-293.15)))`.

The maximum fitting residual is **1.63%**. The correction decreases continuously
toward the uncorrected TRAPP prediction at high temperature. It does not extend
the old Eq. (1), impose a viscosity floor, or establish a measured compressed-liquid
viscosity domain. Pressure dependence and the high-temperature continuation are
engineering predictions checked against independent data.

Conductivity uses a smooth fit to radiation-corrected `lambda_c` from the public
NISTIR6646 table, rather than uncorrected high-temperature radiation contributions.
There are 271 training points with `Te < 550 K, P <= 50 MPa`. With P in MPa:

`k = (0.114548152 + 0.000393458921*P - 0.00000380512629*P^2)`
`    * (T/293.15)^(-(0.733478903 - 0.00674024775*P))`.

Training AAD is **0.85%**. The separate 50 measurements at
`550 <= Te < 630 K, P <= 50 MPa` were withheld: AAD is **2.06%**, maximum absolute
residual **3.40%**. The surface is predictive outside the sampled locations; its
rectangle is not a measured validity domain. The original sample was atypical,
and the dataset's stated radiation and thermal-history limitations still apply.

## Independent high-temperature checks

The full numerical tables for the following Elsevier papers were not accessible.
Their official publisher-hosted figures are public. The approximate readings below
are **graph-read checks**, with image-resolution uncertainty; they are not exact
source-table reproductions and were not used to fit composition or transport.

* [Cp, Fuel 2011, Fig. 2](https://ars.els-cdn.com/content/image/1-s2.0-S0016236110005090-gr2.jpg):
  at 20 MPa, approximately 535/577/634 K gives 2.89/3.08/3.29 kJ/(kg K), versus
  this surrogate's 2.817/2.959/3.142. At 40 MPa, approximately 2.86/3.00/3.13
  versus 2.790/2.926/3.099. Differences are about **−1.0 to −4.5%**, before
  allowing several percent for graph readings. The source reports heat-capacity
  measurements through 671 K and 60 MPa; that does not make every surrogate state
  in that rectangle independently validated.
* [Density, Fuel 2010, Fig. 3](https://ars.els-cdn.com/content/image/1-s2.0-S0016236109002968-gr3.jpg):
  around 595.57 K at 10/20/30/40/50 MPa, filled triangles read approximately
  582/612/636/650/657 kg/m³. The model predicts 589.7/619.2/640.5/657.5/671.8,
  about **+0.7 to +2.3%**. Image readings are uncertain by several kg/m³ and this
  experiment used a different RP-1 sample from the low-temperature density fit.
* [Viscosity, Fuel 2019](https://www.sciencedirect.com/science/article/abs/pii/S0016236118314418)
  measured RP-1 at 301–744 K and up to 60 MPa. Public
  [Fig. 3a](https://ars.els-cdn.com/content/image/1-s2.0-S0016236118314418-gr3a_lrg.jpg)
  permits separate comparison to its filled-circle measurements. Decomposition
  outliers above 650 K must be excluded; model curves and open-square older data
  must not be mistaken for these measurements. Independent reading of the
  filled-circle centers in the high-resolution publisher image gives:

  | T, approximately K | P, MPa | Graph reading, mPa·s | Prediction, mPa·s | Difference |
  |---:|---:|---:|---:|---:|
  | 530.0 | 10 | 0.1905 | 0.1949 | +2.3% |
  | 530.0 | 20 | 0.2107 | 0.2222 | +5.5% |
  | 630.0 | 10 | 0.1231 | 0.1164 | −5.4% |
  | 630.3 | 20 | 0.1407 | 0.1420 | +0.9% |

  Conservative reading uncertainties are T ±2 K and viscosity ±0.003 mPa·s.
  These points were not used to fit the low-temperature residual correction.

These checks support a useful conditional engineering model through the requested
293–600 K, 20–100 bar operating region. They do not demonstrate the sub-percent
accuracy of a reference-quality RP-1 EOS, nor do sparse high-pressure graph
checks validate every point at lower operating pressure.

## Domain and unresolved physical limits

The implementation accepts **270 <= T < 650 K**, **0 < P <= 50 MPa**, and only
the dense branch below its predicted bubble temperature, or the dense liquid-like
state above its critical pressure. The pressure maximum is the public
trans-decalin EOS limit. The lower-temperature choice follows the available RP-1
density measurement region; solid formation and the freezing curve are not
modelled. The upper cutoff is an explicit modelling policy motivated by reported
RP-1 decomposition near 650 K, not a guaranteed safe temperature for a channel.
Residence time, wetted material, wall temperature and fuel chemistry also matter.

The model rejects predicted boiling, an out-of-range enthalpy, an unstable dense
root, and the chosen decomposition boundary. It does not model RP-1 two-phase
transport, cracking, coking, deposit resistance or lifetime. Supercritical
convection near a Cp peak still requires its own applicable heat-transfer model.
Numerical completion of a channel is therefore distinct from physical validation.

No new runtime dependency is required. Targeted property regression tests include
independent density/Cp checks, the withheld conductivity data, QT Gibbs closure,
PH energy closure and the independent numerical identity `dh/dT|P = Cp`.
