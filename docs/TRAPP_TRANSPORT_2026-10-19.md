# Nonpolar mixture transport: NBS TN 1039 adaptation

2026-10-19 KST. This record covers the standalone transport module and its
targeted tests. Integration, complete engine thermal validation, and release
builds are separate checks.

## Why native HEOS mixture transport needs replacement

For the existing LNG mole fractions CH4/C2H6/C3H8/n-C4H10/N2 =
0.94/0.047/0.008/0.002/0.003, the liquid EOS state at 150 K and 25 bar is
384.368774556 kg/m3, or 22548.2165236 mol/m3. Native HEOS viscosity is NaN.

CoolProp 8.0.0's mixture viscosity implementation evaluates each pure component
at the mixture molar density and temperature, then takes a mole-weighted
logarithmic mean. At this state the resulting propane pure-fluid evaluation
has density 994.2776 kg/m3 and viscosity -0.0456730 Pa s, causing log/NaN.
This is a failure of that approximate transport path, not the stable mixture's
density or equilibrium thermodynamics. Native conductivity is finite
(0.140413694 W/(m K)), but its n-butane component is -2.08748 W/(m K);
finite mixture output alone therefore does not validate this mixing procedure.

Primary implementation:
[CoolProp 8.0.0 HelmholtzEOSMixtureBackend.cpp](https://raw.githubusercontent.com/CoolProp/CoolProp/v8.0.0/src/Backends/Helmholtz/HelmholtzEOSMixtureBackend.cpp),
`calc_viscosity` and `calc_conductivity`.

## Implemented method and units

`lpa/thermal/mixture_transport.py` implements the nonpolar one-fluid model of
Ely and Hanley, *A Computer Program for the Prediction of Viscosity and Thermal
Conductivity in Hydrocarbon Mixtures*, NBS Technical Note 1039 (1981).
[NIST primary PDF](https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote1039.pdf)
and [US Government Publishing Office primary mirror](https://www.govinfo.gov/content/pkg/GOVPUB-C13-dc6cad90c53569abc571b009039a551b/pdf/GOVPUB-C13-dc6cad90c53569abc571b009039a551b.pdf).
The coefficient tables, equations, and Appendix B listing were checked from
rendered source pages, including the sample-output digits and unit headings.

The caller supplies a single equilibrium phase's T in kelvin, molar density in
mol/m3, and phase mole fractions. Overall two-phase feed composition must not
be substituted for the liquid/vapor phase compositions. A declared nonpolar
pure-component set or explicit `TransportComponent` records supply critical
T/P/molar density, molar mass in kg/mol, acentric factor, and ideal-gas Cp in
J/(mol K).

The implementation includes:

- Shape functions and fixed-point mapping, Eqs. 13-20 and Table 2. The report's
  upper reduced-T and reduced-volume shape bounds are retained as model
  equations; its lower reduced-T restriction is removed as described in
  section 4 and the supplied Fortran.
- One-fluid and separate viscosity/conductivity effective-mass mixing rules,
  Eqs. 21-27, with zero binary correction parameters as in the original report.
- Original methane dilute, linear-density, and residual transport terms,
  Tables 3-4. Table 3 yields units of 1e-7 Pa s; Table 4 yields mW/(m K);
  both use reference mass density in g/cm3. External results use SI.
- Nonconformality correction, Eq. 29 and Appendix B `ECSTX`/`VSCTY`/`TCOND`.
  The temperature derivative of the mapping is evaluated numerically at fixed
  supplied molar density. The published mixture size correction is retained.
- Eucken translational dilute conductivity and Bromley/internal contribution,
  Eqs. 9-12, with internal contribution factor 1.32.

The report's methane pVT density solver is deliberately replaced with the
caller-supplied phase EOS density. Modern CoolProp pure critical data, ideal
Cp, molar masses, and SI gas constant replace the report's 1981 component
library values. Consequently this is an adaptation, rather than a claim that
the complete original TRAPP executable is reproduced exactly.

## Checks performed

`tests/test_mixture_transport.py`: **23 passed in 1.59 s** in `.venv-build`.

The tests use independently transcribed published densities and transport
results. They do not calculate expected values by repeating the implementation.

| Published examples | Inputs tested | Comparison with published transport |
|---|---|---|
| Table A2, methane | 100/120/120/140/190 K, supplied densities 439.219/1.654/410.533/377.755/239.837 kg/m3 | viscosity maximum deviation 0.0522%; conductivity maximum deviation 1.334% |
| Table A3, methane/propane/nitrogen | phase mole fractions 0.3/0.1/0.6 and 0.7/0.05/0.25; all five printed examples, including -300 degF | viscosity within 1%; conductivity maximum deviation approximately 2.062% |

The Table A3 unit conversions independently use 0.45359237 kg/lb,
0.3048 m/ft, 3600 s/h, and 1055.05585262 J/BTU. The low-temperature
printed example is **-300 degF, 1450 psia**, density 44.8939 lb/ft3,
viscosity 0.553857 lb/(ft h), conductivity 0.11165 BTU/(ft h degF).
The preceding example is **-100 degF**, not -1 degF; image inspection was
necessary to resolve OCR errors.

Tests also cover component-order invariance, differing phase compositions,
custom nonpolar component data, polar rejection, invalid mole fractions,
nonpositive/nonfinite inputs, numerical overflow, and the native LNG NaN
condition. The latter now gives viscosity about 6.70774e-5 Pa s and
conductivity 0.139015 W/(m K). These are correlation predictions, not new
experimental reference values.

Additional direct phase-density probes returned finite positive transport at
111.66 K/5 bar, 150 K/25 bar, 300 K/100 bar, and 600 K/250 bar for the current
LNG composition. This establishes numerical availability at those inputs,
not experimental accuracy throughout the surrounding pressure/temperature
region. Phase equilibrium and density were supplied independently.

## Applicability and remaining limits

Successful output is `property_applicability="correlated"` and
`validation_status="screening"`. It is not a legacy constant-property fallback.
The report's historical average errors do not establish a universal error bar
for this adaptation, every LNG composition, or a real cooling channel.

This method is for nonpolar phases and supplies no aqueous/alcohol mixing
rule, phase stability solver, solid boundary, diffusion contribution, critical
conductivity enhancement, heat-transfer deterioration, or mixture boiling
model. A caller must still enforce EOS/property phase validity and heat-transfer
applicability. The original methane correlation's explicit low-T extension is
40 K. This implementation's 40-1000 K **mapped reference-temperature calculation
interval** includes a chosen upper calculation guard; 1000 K is not a published
validation limit. All component mapped reference temperatures must satisfy the
guard. Invalid/nonpositive/nonfinite results and failed mapping raise
`ValueError`; no transport result is clipped into range.

For more detailed mixture ECS validation see
[Chichester and Huber, NISTIR 6650](https://doi.org/10.6028/NIST.IR.6650).
An installed REFPROP backend can be preferable for supported LNG mixtures.
The local environment/configuration, four standard installation paths, and
Windows uninstall registry did not identify an installed REFPROP library;
no license contents were opened. This limited inspection cannot prove that
no installation exists elsewhere.

Ethanol/water remains a separate polar problem. The
[official REFPROP mixture-transport notes](https://pages.nist.gov/REFPROP-docs/#transport-properties-for-mixtures)
exclude alcohol mixtures and mixtures containing more than 5 mol% water from
the general mixture transport capability. Selecting REFPROP alone therefore
does not establish ethanol/water transport validity.
