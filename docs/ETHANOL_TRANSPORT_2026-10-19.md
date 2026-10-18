# Ethanol/water phase transport correlations

2026-10-19 KST. Standalone module and source-data checks; complete thermal
integration and release validation are separate work.

## Data and calibration

The original ThermoML JSON was obtained from NIST TRC, with original paper DOI
and SI values retained in `tests/data/ethanol_water_transport_reference.json`.
Only datasets whose component set is exactly ethanol/water were extracted;
the other alcohol, ester, ionic-liquid, and DMSO systems were excluded. Pressure
was converted from kPa/MPa to Pa, and mass fractions in the conductivity data
were converted to ethanol mole fractions using 0.04606844 and 0.018015268 kg/mol.

| Source | Role | Retained liquid data |
|---|---|---|
| [Gonzalez et al. (2007)](https://trc.nist.gov/ThermoML/10.1016/j.jct.2007.05.004.html) | Viscosity calibration | 37 points, 293.15/298.15/303.15 K, 101 kPa, full composition including pure endpoints |
| [Ono et al. (2016)](https://trc.nist.gov/ThermoML/10.1016/j.fluid.2015.07.012.html) | High-pressure viscosity calibration and withheld pressure check | 84 points, 350.7/373.2/476.2 K, 10/20/30/40 MPa, ethanol mole fractions 0.1/0.2/0.3/0.4/0.6/0.8/1.0 |
| [Hoga et al. (2018)](https://trc.nist.gov/ThermoML/10.1016/j.jct.2018.02.022.html) | Independent viscosity holdout, never fitted | 100 points, 293.15-308.15 K, 92.3 kPa, full composition |
| [Cui et al. (2019)](https://trc.nist.gov/ThermoML/10.1021/acs.jced.8b01147.html) | Conductivity calibration | 68 points, actual JSON temperatures 282.71-343.02 K, 100 kPa, full composition including endpoints |
| [Zhou et al. (2013)](https://trc.nist.gov/ThermoML/10.1021/je301171y.html) | Independent conductivity holdout, never fitted | 63 points, 279.23-338.71 K, 100 kPa |

The actual Cui binary JSON temperatures extend beyond the abstract's nominal
283.15-333.15 K range. The implementation reports the retained point extent;
it does not quietly replace the actual temperatures with the abstract range.
Source tables are sparse, not proof of a uniformly validated T/P rectangle.

## Liquid method

`ethanol_water_transport` accepts the phase mole fraction, T, P, identified
phase, and optional phase mass density. It returns viscosity in Pa s,
conductivity in W/(m K), source, references, issues, and property-specific
evidence. It does not calculate phase stability, mixture density, or bulk
two-phase transport. Overall-feed composition must not replace fractionated
liquid/vapor composition.

For liquid viscosity, the pure-liquid log mixture is corrected by an empirical
Redlich-Kister excess term. With `x=x_ethanol`, `z=2*x-1`, `u=300/T-1`, and
`q=(P/MPa-0.1)/40`:

`ln(mu) = x*ln(mu_E) + (1-x)*ln(mu_W) + x*(1-x)*[sum(a_jm*z**j*u**m) + q*sum(b_jm*z**j*u**m)]`.

The first sum uses `j=0..3,m=0..2`, and pressure terms use `j=0..2,m=0..1`.
Eighteen frozen coefficients are obtained by unweighted least squares of
log-viscosity residuals, using 31 interior Gonzalez points and 54 interior Ono
points. **Every 30 MPa point is withheld**. Pure endpoints do not determine
excess coefficients; their predictions retain the pure reference transport.

Conductivity uses the [Li (1976) liquid mixing rule](https://doi.org/10.1002/aic.690220520),
which is applicable to aqueous mixtures: phase volume fractions from pure
liquid molar volumes, with harmonic pair conductivity `2*k_i*k_j/(k_i+k_j)`.
This baseline is multiplied by `exp(x*(1-x)*sum(c_jm*z**j*u**m))`,
`j=0..3,m=0..1`. Eight frozen coefficients are fitted to log conductivity
residuals of the 54 interior Cui points. This empirical excess fit belongs to
LPA; it is not presented as a coefficient set published by Li or Cui.

Both baselines use pure CoolProp 8.0.0 transport. At a mixture-liquid temperature
where a pure component would be vapor at the mixture pressure, the explicitly
defined reference is that component's saturated liquid at T. Otherwise it is
compressed liquid at T/P. This avoids mixing pure gas transport into a liquid
baseline. The saturation-reference substitution is reported in evidence and
warnings. Pure-liquid references at/above a component's critical temperature
are rejected.

## Observed checks

`tests/test_ethanol_transport.py`: **26 passed in 1.83 s**. Tests reproduce
the independent holdout summaries stored in the module from retained source
values, verify endpoint/phase behavior, explicit prediction flags, reference
substitution, and unsupported-input guards.

| Comparison | Points | Mean absolute deviation | Maximum absolute deviation |
|---|---:|---:|---:|
| Gonzalez viscosity, all points | 37 | 0.958% | 3.147% |
| Ono viscosity, all points | 84 | 1.300% | 4.770% |
| Ono entire withheld 30 MPa level | 21 | 1.238% | 3.486% |
| Independent Hoga viscosity | 100 | 2.553% | 6.597% |
| Cui conductivity, all points | 68 | 0.305% | 2.451% |
| Independent Zhou conductivity | 63 | 0.586% | 2.180% |

These are comparisons with measured source values, not universal uncertainty
intervals. ThermoML's retained expanded uncertainties are approximately
1.19-1.55% for Gonzalez viscosity, **14.01-14.02% for Hoga viscosity**, and
approximately 1.8-2.25% for the conductivity data. The independent Hoga check
therefore should not be portrayed as a high-precision viscosity standard.

At 70 mass% ethanol, 293.15 K, 25 bar, the new model predicts
`mu=0.00224145 Pa s`, `k=0.241554 W/(m K)`. Both properties are explicitly
engineering predictions at that pressure; the low-temperature calibration
pressure is approximately atmospheric. This improves the old same-molar-density
HEOS mixture mixing path without asserting a measured 25 bar calibration.

## Prediction domains and vapor method

Liquid output has `property_applicability="correlated"` and
`validation_status="screening"`. Evidence distinguishes sparse calibration-hull
interpolation from engineering prediction for each property. In particular,
ambient-pressure k measurements do not validate a high-temperature or
high-pressure mixture correction, even when the pure references are available.
The 303-350.7 K / low-to-high-pressure data gap is visible through the prediction
flags. The chosen liquid calculation guard, 273.15-500 K and up to 40 MPa, is
**not an experimental validity claim**. No result is clipped to that guard;
inputs outside it raise `ValueError`.

Identified gas/vapor phases use [Wilke viscosity](https://doi.org/10.1063/1.1747673)
and the [Wassiljewa-Mason-Saxena conductivity formulation documented by
IDAES](https://idaes-pse.readthedocs.io/en/stable/explanations/components/property_package/general/transport_properties/thermal_conductivity_wms.html),
with pure dilute-gas HEOS references. This is a separate low-density engineering
estimate. Dense/nonideal gas, pressure above 1 MPa, and phase-qualified
supercritical continuation produce explicit limitations; no mixture critical
enhancement or validated dense-gas pressure correction is supplied. Gas
calculation guards are 273.15-600 K and up to 40 MPa, again without claiming
experimental coverage. Unknown phase, bulk two-phase, and unqualified
`supercritical` inputs are rejected.

ThermoML point provenance and independent comparisons do not validate boiling,
CHF/dryout, heat-transfer deterioration, channel flow, wall materials, or an
entire engine thermal solution. Those applicability checks remain separate.
