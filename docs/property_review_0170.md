# Coolant property evidence review, 0.17.0b1

This change separates the thermodynamic model, transport model, and the
applicability of the values required by heat transfer. An EOS state is not
experimental validation of every property over a rectangular temperature and
pressure domain. Missing transport cannot be repaired by silently presenting
reference estimates as an EOS result.

## RP-1: implemented evidence and limits

Primary source: [NISTIR 6646](https://nvlpubs.nist.gov/nistpubs/Legacy/IR/nistir6646.pdf).
Page numbers below are the report's printed numbers, six less than PDF pages.

* The default kinematic viscosity uses Eq. (1), p. 60, only between **243.29 and
  333.15 K**, the Table 11 measurement range. Its units are mm²/s before conversion
  to m²/s. The fit reproduces the reported measurements to approximately 1.1%.
  Dynamic viscosity multiplies this atmospheric correlation by the existing
  screening density. At operating pressure this remains a **pressure-independent
  screening diagnostic**; no validated compressed-liquid correction is claimed.
  Outside this temperature range, viscosity is NaN and the property state is
  `unsupported`. The former exponential extrapolation and viscosity floor do not
  authorize hot RP-1 calculations.
* The 465 original Table 10 points, pp. 47–57, provide radiation-corrected
  conductivity `lambda_c` at effective temperature `Te` and measured pressure.
  Conductivity uses linear interpolation inside the measured convex hull only.
  The individual coordinate extrema are 301.798–650.862 K and 0.1675–68.9229 MPa;
  **their enclosing rectangle is not a supported domain**. Outside that hull, a
  legacy conductivity estimate remains explicitly labeled screening. NIST
  discusses reaction, composition change and time dependence near 650 K, and
  approximately 4% conductivity uncertainty there (pp. 41–42). Interpolating
  these measurements does not establish the behavior of pristine RP-1 at 650 K.
* The 30 Table 12 points, p. 66, measure **viscosity times density**, not dynamic
  viscosity alone. `rp1_viscosity_density_product(T,P)` separately exposes
  log-linear interpolation inside their original measured convex hull. Its
  numerical extrema are 295.23–400.08 K and 0.1008–68.1731 MPa, again not a valid
  rectangle. The product uses kg²/(m⁴·s). These data are also recorded as separate
  per-state evidence and are **not automatically spliced into Eq. (1)**.
  The report describes impedance-analyzer resolution limitations and deviations
  of −3.5 to −11.7% from its surrogate model (pp. 64–65). Combining these data
  with atmospheric viscosity plus an estimated density would invent a sharp
  pressure trend near their join.
* Density and Cp retain explicitly identified reference-temperature screening
  estimates; enthalpy integrates that Cp consistently. The report says its broad
  high-pressure density and Cp datasets were privately communicated (pp. 37–38),
  rather than publishing their numerical data. No complete RP-1 EOS or validated
  four-property range is claimed. The original sample was anomalously rich in
  olefins; other lots had 7–10% higher viscosity at 298.15/313.15 K (pp. 59–60).
  This sample uncertainty is separate from interpolation and instrument error.

Consequently, RP-1 retains `phase="unknown"` and overall `screening` within the
bounded default viscosity fit, with per-property evidence showing the source of
each value. It becomes `unsupported` when required values are unavailable.
There is no supported full hot-wall regenerative march to 589 K from these data.
At 293 K/20 bar, even the finite viscosity is an atmospheric screening diagnostic,
not evidence that all required compressed-liquid properties are validated.

The [NIST four-component surrogate paper](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=900238)
does not itself install its dedicated fluid definitions. The currently installed
CoolProp HEOS library lacks three of those four components; substituting unrelated
available hydrocarbons is not an implementation of that validated surrogate.
A separately installed REFPROP library and the appropriate fluid/mixture files
would be needed to evaluate a genuine provider before enabling that path.

[RocketProps](https://rocketprops.readthedocs.io/en/latest/rp1_prop.html) and its
[source explanation](https://rocketprops.readthedocs.io/en/latest/sources.html)
were reviewed, as was the primary
[Aerojet propellant manual](https://rocketprops.readthedocs.io/en/latest/_static/Aerojet_Propellant_Properties.pdf).
The RP-1 chart includes estimated/extrapolated curves. These sources do not
establish a common independently measured four-property validity range, and no
RocketProps dependency or source code was copied.

## Other coolant paths

`CoolantState` reports `property_applicability`, `thermodynamic_applicability`,
`transport_applicability`, notes, references, and property-specific evidence.

* `eos` means the requested provider returned the required properties within
  the explicitly checked EOS domain. It is not a claim of fresh experimental
  validation. The previously implemented EOS and individual transport limits
  remain distinct; unknown correlation limits stay unknown.
* If required single-phase density, Cp, conductivity or viscosity falls back,
  overall applicability is `unsupported`. Available EOS thermodynamics can still
  be `eos`, transport can be `screening`, and finite fallback values remain for
  diagnostics. N2O transport missing from HEOS and ethanol conductivity outside
  its documented 600 K/245 MPa upper limits are examples.
* Equilibrium two-phase bulk Cp and transport have no unique transport law.
  Expected bulk diagnostic failures do not invalidate successful, native
  saturated-liquid and saturated-vapor properties. Required phase-property
  failures do invalidate the overall state. Boiling-correlation applicability
  remains a separate solver decision.
* IPA, peroxide mixtures, and Jet A-1 still have no installed validated EOS path.
  Their generic reference estimates and aqueous mixing remain finite screening
  diagnostics, phase unknown, with no invented pressure/temperature validity
  rectangle. Native provider calls mark the overall/thermodynamic state
  `unsupported`; explicitly selected screening-model calls remain available
  for research. Legacy clamps are now reported when active. Exponential evaluation
  is bounded before calculation to prevent overflow; that numerical safeguard
  establishes no physical validity.
* Existing HEOS/REFPROP selection, LNG phase-root correction, bracketed mixture
  PH/PQ flash and pure-fluid EOS caps are retained. An unavailable REFPROP
  installation remains explicit; it is never silently replaced by HEOS.

## Verification

The original Table 10 and Table 12 rows and units were independently checked
against the primary PDF. Regression coverage verifies original measurement
reproduction, rejection outside actual convex hulls, no high-temperature RP-1
viscosity floor, pressure-aware reevaluation after PH inversion, explicit EOS
transport failures, valid saturated properties, legacy clamp disclosure, and
preservation of explicit custom-property models. No new dependency is required;
the existing SciPy installation supplies bounded interpolation.

Command: `.venv-build\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
tests/test_coolant_property_evidence_0170.py tests/test_coolant_phase_flash_regression.py`.
Result: **30 passed**.
