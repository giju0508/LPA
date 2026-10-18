# Gas-side thermal method review and beta correction, 2026-10-19

The Bartz algebra was consistent with the published correlation, but its
reference-property selection and throat-curvature selection did not reproduce
the installed RPA implementation. The original investigation made no code
changes. The user subsequently authorized correction and a beta release.

## Frozen thermal reference and reacting nozzle flow

The conventional Bartz transport factor is

```text
mu_0^0.2 * Cp_0 / Pr_0^0.6
```

LPA previously supplied the first axial station's flow-selected CEA transport.
For shifting equilibrium that is `CPEQL/PREQL`; reaction contributions make
these differ substantially from frozen-composition `CPFRO/PRFRO`. The nozzle
chemistry selection does not, by itself, define the appropriate thermal
boundary-layer reference. Switching the nozzle to throat freezing also leaves
the chamber upstream of the freezing station in equilibrium.

`RocketCEAAdapter.bartz_reference_properties()` now queries the chamber
injector/stagnation state separately and copies frozen Cp, frozen Prandtl,
and viscosity from CEA. The query is independent of nozzle freezing. The
reference specific-heat ratio is frozen `Cp/(Cp-R)`, not the reacting-flow
isentropic exponent `GAMMAs`. CEA array units are converted using 4184 J per
thermochemical kcal and 1e-4 Pa s per millipoise, consistent with existing axial
property conversions.

`AxialThermodynamics` exposes these optional fields:

- `bartz_reference_specific_heat_j_kgk`
- `bartz_reference_viscosity_pa_s`
- `bartz_reference_prandtl`
- `bartz_reference_gamma`
- `bartz_reference_source`

The ordinary axial Cp, gamma, viscosity and Prandtl arrays continue to represent
the selected equilibrium/frozen nozzle flow. Existing callers and custom
adapters retain the previous dataclass construction contract through defaults.
If the frozen reference query fails, the valid axial flow is retained and an
explicit screening-fallback warning is emitted. The thermal solver consumes
the separate reference for Bartz and recovery temperature.

For reaction efficiency below 100%, the existing temperature/density closure
still does not re-equilibrate composition or transport. Its warning remains
applicable. This change does not qualify a reacting or catalytic boundary-layer
model or implement recombination kinetics.

## Direct RPA comparison

The reference was obtained by executing the installed RPA 4.0.13 bundle's
`RPA-Script.exe --stream` and reading `HeatTransferAnalysis.getResults()`.
The scripting executable reports PE version 4.0.8.0; its SHA-256 and a complete
reproduction script are recorded in
`tests/fixtures/rpa_bartz_fixed_wall_4_0_13.json` and
`tests/fixtures/rpa_bartz_fixed_wall_capture.js`.

Common conditions: gaseous O2/CH4, O/F 2.6, chamber pressure 10 bar,
Ac/At=Ae/At=4, throat diameter 31.79 mm, L*=1000 mm, contraction angle 30 degrees,
R1/Rt=1.5, R2/R2max=0.5, Rn/Rt=0.382, conical nozzle half-angle 15 degrees,
all assigned performance correction factors 1.0, shifting equilibrium,
Twg=1000 K, and no radiation, film, or wall cooling. RPA inserts the throat
station, producing 61 stations for a requested count of 60.

The RPA injector getters return frozen Cp=2520.17345 J/(kg K),
Pr=0.62185433, mu=9.98491909e-5 Pa s, and R=450.90712 J/(kg K).
The resulting frozen gamma is 1.21790676. Equilibrium Cp=6474.19661 J/(kg K)
and Pr=0.42874827 are separate getter outputs. For the combustion-end state,
the equilibrium/frozen transport factors differ by a factor of 3.2113.

At the throat:

| Calculation | h, W/(m2 K) | Convective q, MW/m2 |
| --- | ---: | ---: |
| Direct RPA, BARTZ | 5637.825 | 12.11842 |
| Pre-correction LPA correlation using matched RPA gas inputs, equilibrium reference and Rn | 20587.222 | 44.06539 |
| Frozen chamber reference, frozen gamma and upstream R1 | 5538.274 | 11.89098 |

The second row is a controlled correlation reconstruction with RPA gas inputs,
not a complete recreation of the user's LNG engine. Its recovery temperature
uses local equilibrium Prandtl, as the previous production solver did. The last
row evaluates the final consistent frozen-reference method. Its h and q differ
from RPA by -1.766% and -1.877%. No coefficient was fitted to reduce the residual.

The same final method gives chamber h/q differences of -1.595%/-1.598% and exit
differences of -2.490%/-2.791%. The regression accepts 3% for this specific
fixed-wall software comparison. This is not a universal physical accuracy
statement or a hot-fire validation.

The RPA internal Bartz source is unavailable. Matching its outputs closely
with frozen transport is strong numerical evidence, not proof of its exact
internal property-selection implementation. Differences in reference state,
specific-heat ratio, and recovery-temperature treatment remain. In particular,
the RPA throat recovery temperature inferred from q/h is 3149.486 K; the final
frozen-reference method gives 3147.054 K.

## Curvature and other method differences

An isolated RPA sensitivity check changed upstream R1/Rt from 1.5 to 0.382:
the throat h increased from 5637.825 to 6464.194 W/(m2 K), or 14.6576%.
Changing only downstream Rn/Rt from 0.382 to 1.5 left the throat h unchanged.
This establishes that the RPA comparison uses upstream throat curvature.
LPA geometry already distinguishes R1 and Rn and reports the actual upstream
curvature after any axial scaling. The thermal calculation should use that
actual upstream curvature, not the downstream nozzle blend radius.

For the same common case, RPA Ievlev gives throat q=5.99769 MW/m2 versus
Bartz 12.11842 MW/m2. Neither is a universal experimental truth. LPA's fixed
gray emissivity also differs from the species/partial-pressure/path-dependent
radiation described in the RPA document. These differences require separate
qualification when total heat flux, film cooling, or reacting boundary layers
are important. The present fixed-wall comparison excludes radiation and film
to isolate convection.

## Verification

- Independent public RocketCEA infinite-combustor frozen-transport getters
  reproduce the new FAC injector reference, including the documented IT versus
  thermochemical calorie conversion.
- Shifting and throat-frozen flow produce the same Bartz reference while their
  ordinary axial nozzle properties retain their selected flow definitions.
- A failed Bartz-reference query preserves valid local CEA axial states and
  reports an explicit warning.
- The captured RPA chamber/throat/exit regression checks both h and q.
- Targeted core tests: `tests/test_bartz_gas_reference.py` and
  `tests/test_release_performance_fixes.py`: 45 passed.

## Primary sources

- [Ponomarenko, RPA Thermal Analysis of Thrust Chambers](https://rocket-propulsion.com/downloads/pub/RPA_ThermalAnalysis.pdf),
  p.7 for Bartz and sigma; p.12-13 for radiation; p.22 for model limitations.
- [RPA 4 User Manual](https://rocket-propulsion.com/downloads/4/docs/RPA_4_User_Manual.pdf),
  p.9-10 for stream execution, p.70 for transport getters, p.97-103 for the
  fixed-wall heat-transfer interface and returned quantities.
- [Tinker, Lusk and Gradl, NASA MSFC](https://ntrs.nasa.gov/api/citations/20220017723/downloads/2022-11-21_NTP-NNE-MaterialTrade_Paper.pdf?attachment=true),
  p.8 explicitly identifies chemically frozen Cp/viscosity and converging
  throat curvature in its Bartz definition. Its application is NTP, so it is
  used for equation definitions, not chemical-engine hot-fire validation.
- [Bartz, survey of theory and experiment](https://ntrs.nasa.gov/citations/19690030800),
  on combustion- and injector-dependent departures from general correlations.
