# LPA Thermal Analysis Audit — 2026-07-21

> 이 문서는 당시 버전의 검토 이력입니다. 0.14.0의 EOS·공급 엔탈피·열전달 수정과 현재 적용범위는 [2026-10-11 수정 및 신뢰도 평가](RELEASE_REMEDIATION_2026-10-11.md)를 참조하십시오.

Status: Sections 1–11 are the **pre-patch audit baseline** and were written
before changing production calculation code.  Section 12 is the post-patch
verification record.  The existing Bartz gas-side correlation is kept; no
calibration multiplier or replacement heat-transfer model is introduced.

## 1. Executive finding

The reported results are not, by themselves, contradictory:

- The separate CuCrZr heat-sink calculation is a transient thermal-storage
  problem.  With multi-megawatt-per-square-metre heating, an uncooled copper
  wall can reach its temperature limit in seconds.
- LPA's regenerative/radiation wall solver is a **steady, axial collection of
  one-dimensional thermal-resistance balances**.  It has no solid density,
  heat capacity, radial mesh, firing duration, or time step.  It therefore
  cannot predict the 1–3 s heat-sink transient.
- In a representative 10 bar, O/F 2.6, 0.4301 kg/s GOX/GCH4 case with a 1 mm
  CuCrZr wall and 0.4301 kg/s water, the unchanged LPA code predicts a maximum
  hot wall of 645 K, a throat hot wall of 582 K, chamber heat flux of
  5.0–5.4 MW/m2, and throat heat flux of 16.16 MW/m2.  Radiation-off changes
  the maximum to 623 K and the throat to 579 K.  These numbers explain how a
  roughly 570 K result can coexist with a seconds-scale uncooled failure.
- The water-cooled result is **not yet a qualified design result**.  In the
  representative run, bulk water reaches 485.7 K at 23.9 bar while the local
  coolant-side wall reaches 630 K.  NIST's water vapor-pressure equation gives
  saturation temperatures of about 495.8 K at 25 bar and 493.2 K at 23.9 bar.
  LPA nevertheless continues to use a pressure-independent, single-phase
  liquid screening model.  It has no onset-of-boiling, subcooled boiling,
  critical heat flux, two-phase pressure drop, or dryout calculation.

The existing Bartz equation is implemented in the expected SI form.  An
independent arithmetic reconstruction agrees with production `h_g` and heat
flux within 0.005% at injector, cylinder end, throat, and exit for the
representative case.  No unit conversion, area-ratio inversion, exponent, or
double-application error was found in the Bartz function itself.

One production implementation defect is confirmed: coolant enthalpy rise uses
the axial projection `2*pi*r*dx`, while coolant pressure loss uses the actual
contour-following path `ds`.  Heat pickup must use the wetted hot-wall area
`2*pi*r*ds`.  The error under-predicts local heat pickup by `sec(theta)-1`
(15.47% on a straight 30 degree convergent and 3.53% on a 15 degree cone).  It
under-predicts total hot-wall area by 1.345% for the representative full-engine
geometry.  This is the only issue approved for a minimal production patch in
this audit.

## 2. Scope and classification

Each finding is assigned to one of four classes:

- **A — confirmed implementation defect:** code contradicts its equation,
  geometry, units, or an independently evaluated identity.
- **B — probable implementation/model-input issue:** technically questionable
  or misleading, but not sufficiently specified to change safely in this
  audit.
- **C — intrinsic model limitation:** outside the declared Bartz/steady
  one-dimensional resistance model; not fixed by altering a coefficient.
- **D — comparison/input mismatch:** two results describe different physical
  systems, locations, or boundary conditions.

No user-interface change is in scope.

## 3. End-to-end call flow

```text
lpa/app.py
  LPAApplication._run_analysis
    -> lpa/analysis.py
       AnalysisService.analyze(project)
         -> _core_project(project)
         -> lpa/core/analysis.py
            analyze_engine(AnalysisInput)
              -> lpa/core/performance.py
                 evaluate_performance(...)
                   -> RocketCEAAdapter.evaluate(...)
              -> lpa/core/contour.py
                 generate_contour(...)
              -> lpa/core/thermodynamics.py
                 build_thermodynamics(...)
         -> lpa/analysis.py
            construct gas mapping and normalize thermal segments
         -> lpa/thermal/solver.py
            analyze_thermal(contour, gas, segments, settings)
              -> _build_mesh
              -> _prepare_gas
              -> validate/partition segments
              -> _effective_recovery_temperature (film, when present)
              -> _solve_regens
                   -> _solve_regen_station at each axial station
                        -> _gas_coefficient
                             -> bartz_heat_transfer_coefficient
                        -> internal_flow_heat_transfer
                        -> wall/TBC resistance balance
                   -> coolant bulk-temperature and pressure march
              -> _solve_radiation for radiation-only stations
              -> ThermalAnalysisResult
         -> lpa/ui/result_views.py
            ThermalResultsPage rendering
```

The heat-sink transient solver in the separate `Heat_Sink_Combustor` project is
not called anywhere in this flow.

## 4. Equation ledger

### 4.1 Performance and quasi-one-dimensional gas state

RocketCEA supplies ideal `c*` and chamber temperature.  LPA currently applies

```text
eta_r       = reaction_efficiency_percent / 100
c*_del      = eta_r c*_ideal
mdot_hot    = Pc At / c*_del
T0_used     = eta_r T_CEA
```

It obtains molecular weight and gamma from RocketCEA's **exit** method, then
uses those two constants at every axial station.  Local Mach is obtained from
the isentropic area–Mach relation, choosing the subsonic branch before the
throat and supersonic branch after it.  The exact contour throat is retained as
`M=1`.

```text
tau = 1 + (gamma - 1) M^2 / 2
T   = T0 / tau
p   = P0 / tau^[gamma/(gamma-1)]
cp  = gamma R / (gamma - 1)
rho = p / (R T)
a   = sqrt(gamma R T)
u   = M a
G   = mdot / A
```

The transport inputs passed to Bartz are not RocketCEA transport properties:

```text
mu(T) = 1.716e-5 (T/273.15)^1.5 (273.15+110.4)/(T+110.4)  [Pa s]
Pr    = clamp(0.72 - 0.018(gamma-1.2), 0.62, 0.78)
```

Those are an air Sutherland law and a bounded heuristic.

### 4.2 Gas-side Bartz correlation

At each station, with stagnation/reference `mu0`, `cp0`, and `Pr0` taken from
the first axial station:

```text
K_M   = (gamma - 1) M^2 / 2
r     = Pr0^(1/3)
Taw   = T0 (1 + r K_M)/(1 + K_M)

sigma = [0.5 (Twg/T0)(1+K_M) + 0.5]^-0.68 (1+K_M)^-0.12

hg = 0.026 / Dt^0.2
     * (mu0^0.2 cp0 / Pr0^0.6)
     * (Pc/c*)^0.8
     * (Dt/rc)^0.1
     * (At/A)^0.9
     * sigma

qconv'' = hg (Taw - Twg)
```

All dimensional inputs are SI: Pa, m, s, kg, K, J.  `A/At` is passed into
the function and inverted once.  `sigma` is applied once.  `rc` is the nozzle
throat axial curvature radius represented by the input `Rn/Rt`.

### 4.3 Gas radiation

```text
qrad'' = epsilon_g sigma_SB (T_g^4 - Twg^4)
qgas'' = qconv'' + qrad''
```

The default gas emissivity is 0.08.  Radiation is added once and is not hidden
inside `hg`.

### 4.4 Wall and coolant-side balance

For a regenerative station:

```text
Dh        = 2 w h / (w + h)
Aflow     = N w h
u_c       = mdot_c / (rho_c Aflow)
Re        = rho_c u_c Dh / mu_c
Pr_c      = cp_c mu_c / k_c
Nu        = 3.66 (laminar), transition blend, or Gnielinski (turbulent)
hc        = Nu k_c / Dh

R_tbc     = t_tbc/k_tbc
R_wall    = t_wall/k_wall(Tmean)
R_coolant = 1/hc

q'' = [hg (Taw - Tc) + qrad'']
      / [1 + hg (R_tbc + R_wall + R_coolant)]

Twc = Tc  + q''/hc
Twi = Twc + q'' R_wall
Twg = Twi + q'' R_tbc
```

The nonlinear temperature dependence is iterated with 0.62 under-relaxation.
There is no radial finite-volume wall mesh and no thermal storage.

Coolant pressure is marched with Darcy–Weisbach and a Haaland friction factor:

```text
dp/ds = f (rho_c u_c^2/2) / Dh
```

Coolant enthalpy is marched as:

```text
dTc = q'' dA_hot / (mdot_c cp_c)
```

Production currently evaluates `dA_hot = 2*pi*r*dx`; the correct local
axisymmetric contour area is `2*pi*r*ds` to first order, or the exact conical
frustum area over a linear interval.

## 5. Variable, unit, evaluation, and source ledger

| Variable | Production unit | Evaluation location | Production source |
|---|---:|---|---|
| `Pc` | Pa | chamber total | UI bar x 100000 |
| `At`, `A` | m2 | throat/local contour | circular contour geometry |
| `Dt` | m | throat | sized or user input |
| `rc` | m | throat axial curvature | `Rn/Rt * Rt` |
| `c*` | m/s | chamber performance | RocketCEA ideal x reaction efficiency |
| `T0` | K | chamber total | RocketCEA chamber T x reaction efficiency |
| `gamma`, MW | -, kg/kmol | all stations | RocketCEA exit values, held constant |
| `M` | - | every contour station | area–Mach relation |
| `p`, `T` | Pa, K | every station | constant-gamma isentropic relations |
| `mu` | Pa s | every station, but Bartz uses station 0 | air Sutherland estimate |
| `cp` | J/(kg K) | every station, but Bartz uses station 0 | constant gamma and R |
| `Pr` | - | every station, but Bartz uses station 0 | bounded heuristic |
| `Taw` | K | every station | recovery-temperature relation |
| `Twg/Twi/Twc/Tc` | K | every station | steady resistance solution |
| `hg`, `hc` | W/(m2 K) | every station | Bartz; internal-flow correlation |
| `qconv/qrad/qtotal` | W/m2 | every station | convection; Stefan–Boltzmann; sum |
| coolant `rho/cp/k/mu` | SI | film mean temperature | temperature-only screening curves |
| coolant pressure | bar in result | every station | Darcy–Weisbach march |

Important: coolant pressure is calculated and displayed, but is not supplied to
the coolant property model or a phase-equilibrium check.

## 6. Independent Bartz check

Representative audit definition (not claimed to reproduce an unavailable user
project file exactly): GOX/GCH4, `Pc=10 bar`, `O/F=2.6`, `Dt=31.79 mm`,
`Ac/At=4`, `Ae/At=4`, `L*=1000 mm`, `eta_r=98%`, `Rn/Rt=0.382`, 1 mm CuCrZr,
60 rectangular channels with 2/1/2 mm heights and 1.4/0.8/1.4 mm widths,
counterflow H2O at 293.15 K and 25 bar, coolant flow equal to total propellant
flow.  RocketCEA gives `mdot=0.430062 kg/s`, `c*=1845.611 m/s`, and
`T0=3123.079 K` after LPA's efficiency transformations.

The independent calculator re-entered the equation above without calling the
production Bartz function:

| Station | A/At | M | sigma | independent hg | production hg | qconv | qrad | qtotal |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Injector | 4.000 | 0.1499 | 1.4093 | 1831.91 | 1831.90 | 4.538 | 0.427 | 4.965 |
| Cylinder end | 4.000 | 0.1499 | 1.4544 | 1890.53 | 1890.53 | 5.005 | 0.427 | 5.432 |
| Throat | 1.000 | 1.0000 | 1.3955 | 6316.51 | 6316.50 | 15.865 | 0.295 | 16.160 |
| Exit | 4.000 | 2.6169 | 1.2797 | 1663.38 | 1663.38 | 4.141 | 0.054 | 4.195 |

`hg` is in W/(m2 K); heat flux columns are MW/m2.  The small residual is from
rounding/resampling, not a formula difference.

For fixed `sigma`, the logarithmic sensitivities are exactly the printed Bartz
exponents: `Pc:+0.8`, `c*:-0.8`, `mu:+0.2`, `cp:+1`, `Pr:-0.6`,
`rc:-0.1`, `A/At:-0.9`.  With a geometrically similar throat where `rc/Dt`
is fixed, `Dt:-0.2`.  These are useful diagnostics; they are not calibration
parameters.

## 7. Mesh, energy, radiation, and acceleration checks

### 7.1 Existing axial levels

| Axial sections | Radiation | max Twg (K) | throat Twg (K) | throat q (MW/m2) | water Tout (K) |
|---:|---:|---:|---:|---:|---:|
| 120 | off | 623.116 | 578.415 | 15.9006 | 474.801 |
| 300 | off | 623.385 | 578.720 | 15.8977 | 474.760 |
| 700 | off | 623.488 | 578.836 | 15.8966 | 474.744 |
| 120 | 0.08 | 644.879 | 581.874 | 16.1629 | 485.696 |
| 300 | 0.08 | 645.235 | 582.184 | 16.1600 | 485.651 |
| 700 | 0.08 | 645.370 | 582.302 | 16.1589 | 485.634 |

The 300-to-700 change is 0.135 K in peak wall temperature and 0.0011 MW/m2 at
the throat.  LPA exposes only 120/300/700.  Requested 350/700/1400 axial and
radial/time convergence cannot all be executed through the production solver:
there is no 350/1400 setting, radial mesh, or time step.  This absence is a
model capability finding, not a passed convergence test.

### 7.2 Acceleration parameter diagnostic

Using `K = (nu/u^2) du/ds` on the 700-station representative solution:

| Station | Re based on local diameter | K |
|---|---:|---:|
| Injector/cylinder | 1.13e5 | approximately 0 |
| Throat | 2.37e5 | 9.83e-6 |
| Exit | 1.49e5 | 1.19e-6 |
| Maximum in convergent | 1.41e5 | 1.50e-5 |

Values exceed commonly cited canonical relaminarization-onset ranges of about
`2e-6` to `4.4e-6` through a substantial part of the convergent.  The exact
threshold is geometry-, history-, Mach-, thermal-boundary-, and
combustion-dependent, so this is a warning, not a correction factor.  Bartz's
fully turbulent assumption can over-predict heat transfer when strong
acceleration suppresses turbulence.

### 7.3 Heat-sink order-of-magnitude check

For an illustrative 10 mm CuCrZr wall, `rho*cp*t` is roughly
`8800*400*0.010 = 35,200 J/(m2 K)`.  A 5 MW/m2 chamber flux gives an initial
adiabatic heating rate around 142 K/s; a 16 MW/m2 throat flux gives about
455 K/s.  Even after conduction and temperature dependence are included,
seconds-scale approach to a copper temperature limit is physically credible.

## 8. Findings

### A. Confirmed implementation defect

**A1 — coolant heat-pickup area uses `dx` instead of contour path `ds`.**

- Location: `lpa/thermal/solver.py`, coolant temperature march.
- Evidence: pressure loss already integrates `_channel_path_length_in_range`,
  whereas heat pickup passes `_cell_width_in_range` to `annular_wall_area`.
- Numerical direction: coolant heat pickup and downstream bulk temperature are
  under-predicted in sloped regions.  The wall-temperature effect depends on
  flow direction, but the coolant enthalpy balance is definitively wrong.
- Minimal correction: use the same clipped contour path length for wall area.
- No correlation, coefficient, exponent, or interface changes are needed.

### B. Probable implementation/model-input issues — no automatic patch

**B1 — gas transport data are presented downstream of RocketCEA but are an air
Sutherland law plus a Prandtl heuristic.**  Bartz is highly sensitive to `cp`
and moderately sensitive to `Pr` and `mu`; product-gas reference properties
should ultimately come from a documented CEA/RPA-compatible source.

**B2 — exit molecular weight and gamma are applied globally.**  Local reacting
gas properties and shifting/frozen chemistry are not propagated into the
thermal calculation, despite the performance selection.

**B3 — reaction efficiency scales both `c*` and chamber temperature linearly.**
`c*` efficiency is defined by delivered/theoretical characteristic velocity;
it does not independently establish `T_actual/T_ideal = eta_c*`.  The current
double use lacks a documented thermochemical closure.  It is not changed here
because the intended UI definition and compatibility requirement must first be
specified.

**B4 — channel-side area ratio and fin efficiency are omitted.**  `hc` is
computed from channel geometry, but `1/hc` is used per hot-wall area with an
implicit cold-side/hot-side area ratio of one.  Channel sidewalls and rib fin
efficiency can materially change the effective coolant resistance.  This needs
a documented conjugate-channel formulation, not a one-line coefficient tweak.

### C. Intrinsic limitations of the present model

**C1 — no transient heat-sink model.**  No firing duration, density, solid heat
capacity, radial discretization, or thermal storage exists.

**C2 — no axial or circumferential solid conduction.**  Stations are
independent except for coolant bulk-temperature and pressure marching.  The
throat cannot conduct heat upstream/downstream in the wall.

**C3 — planar thin-wall resistance.**  The solver uses `t/k`, not cylindrical
logarithmic resistance, and does not resolve wall/channel geometry.

**C4 — single-phase, pressure-independent coolant screening properties.**  No
phase boundary, subcooled boiling, critical heat flux, dryout, compressibility,
or two-phase pressure loss is represented.  Gas coolant densities are also
fixed screening values unless manually overridden.

**C5 — Bartz is a rapid fully turbulent engineering correlation.**  It does not
resolve injector-local combustion, boundary-layer development, acceleration
history/relaminarization, roughness, three-dimensional flow, or conjugate axial
conduction.  This audit keeps Bartz as required; the limitation must be carried
as uncertainty.

**C6 — constant-gamma quasi-one-dimensional gas path.**  This is not a local
equilibrium/frozen CEA station calculation.

### D. Comparison and boundary-condition mismatches

**D1 — transient uncooled versus steady actively cooled.**  The two quoted
temperatures do not answer the same question.

**D2 — chamber experimental flux versus nozzle-throat peak.**  Silvestri et al.
report about 2.9 MW/m2 at 10 bar, O/F 2.6 in the cylindrical chamber, not the
throat.  The representative LPA chamber value is 5.0–5.4 MW/m2 and its throat
value is 16.16 MW/m2.

**D3 — coolant mass-flow definition.**  A custom regenerative coolant setting
of 100% means water mass flow equal to total engine propellant mass flow.  For
this case that is about 0.430 kg/s of additional water, a very strong cooling
boundary condition.

**D4 — phase validity.**  A numerically converged single-phase solution is not
a physically validated solution when the coolant-side wall is above saturation
and boiling/CHF are absent.

## 9. Literature sanity checks

- Silvestri et al.'s single-element GOX/GCH4 heat-sink chamber used copper,
  short burns, and a transient thermal-mass balance.  At O/F 2.6 it reports
  approximately 5.6 MW/m2 at 20 bar and 2.9 MW/m2 at 10 bar in the chamber;
  tests from 10–25 bar followed the Bartz `Pc^0.8` trend.  This supports the
  multi-MW/m2 order of magnitude and seconds-scale heat-sink heating, but not a
  direct throat validation.
- Perakis et al. report approximately 6.5 MW/m2 in a 20 bar GOX/GCH4 chamber;
  water calorimetry and inverse conduction differed by less than 5% in middle
  chamber segments.  Near the nozzle, axial heat conducted upstream from the
  hotter nozzle caused larger differences, directly demonstrating a mechanism
  omitted by LPA's independent-station wall model.
- NASA's Bartz documentation defines the properties as chamber total/reference
  properties and `R` as the axial throat curvature radius, consistent with the
  implemented equation structure.  NASA also describes Bartz as an engineering
  approximation rather than a general conjugate boundary-layer solution.
- NIST SRD 69 gives the water vapor-pressure relation used for the phase-margin
  check.  NISTIR 5078 tabulates water/steam properties from IAPWS-95.

Primary sources:

- [Silvestri et al., GOX/GCH4 single-element chamber](https://www.jstage.jst.go.jp/article/tastj/14/ists30/14_Pa_13/_article/-char/en)
- [Perakis et al., inverse heat-flux calculation](https://www.eucass.eu/doi/EUCASS2017-366.pdf)
- [NASA CR-2002-211587, Bartz implementation and definitions](https://ntrs.nasa.gov/api/citations/20020065525/downloads/20020065525.pdf)
- [NASA SP-125, Design of Liquid Propellant Rocket Engines](https://ntrs.nasa.gov/citations/19710019929)
- [NIST Chemistry WebBook water vapor pressure](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7732185&Type=ANTOINE)
- [NISTIR 5078 / IAPWS-95 water tables](https://www.nist.gov/srd/nistir-5078)
- [NASA accelerated turbulent-boundary-layer review/data record](https://ntrs.nasa.gov/citations/19740020645)
- [Bartz, rapidly accelerating rocket-gas boundary layers](https://ntrs.nasa.gov/citations/19650013685)

## 10. Verification plan and patch gate

The following must be completed after this pre-patch report:

1. Add a standalone audit command that emits a station CSV with geometry, gas
   state, Bartz factors, heat-flux split, wall temperatures, Reynolds number,
   and acceleration parameter.
2. Keep an independent Bartz implementation in the audit command and regression
   tests; it must not call production `bartz_heat_transfer_coefficient`.
3. Add a regression test proving coolant heat pickup follows contour length.
4. Apply only A1, changing heat-pickup area from axial width to clipped contour
   path length.
5. Re-run the same representative case at 120/300/700 sections, radiation on
   and off, and record pre/post differences.
6. Run all non-GUI tests and record the environment-specific GUI test blocker.
7. Do not modify Bartz coefficients, exponents, or add empirical factors.

## 11. Five explicit conclusions

1. **Is 570 K automatically evidence of a thermal bug? — No.**  It is a
   plausible numerical consequence of a high-flow steady water boundary, not
   the result of the uncooled transient problem.
2. **Is the seconds-scale CuCrZr heat-sink failure automatically nonphysical? —
   No.**  Multi-MW/m2 chamber/throat flux and copper areal heat capacity make
   that time scale credible.
3. **Is LPA's Bartz equation coded with a confirmed unit/exponent/area-ratio
   error? — No.**  Independent reconstruction matches production to within
   0.005% in the audit case.
4. **Can the present water-cooled temperature be used as a high-confidence
   design value? — No.**  The computed coolant-side wall crosses the water
   saturation boundary while the solver remains pressure-independent and
   single-phase; channel fin/area effects and axial conduction are also absent.
5. **What production code should change now? — Only the confirmed `dx` versus
   `ds` coolant heat-pickup area error.**  Gas-property sourcing, efficiency
   semantics, phase change, fin efficiency, and transient conduction require
   separately specified model upgrades and validation, not silent tuning.

## 12. Post-patch verification record

The A1 patch replaced the axial cell width passed to
`annular_wall_area(radius, length)` with the already available clipped
contour-following channel path.  The same path value is reused for
Darcy–Weisbach pressure loss.  No Bartz, material, coolant-property, geometry,
or user-interface value changed.

### 12.1 Same-input before/after comparison at 700 stations

| Radiation | Quantity | Before | After | Change |
|---:|---|---:|---:|---:|
| off | maximum Twg (K) | 623.488 | 625.974 | +2.486 |
| off | throat Twg (K) | 578.836 | 579.387 | +0.551 |
| off | throat q (MW/m2) | 15.8966 | 15.8913 | -0.0052 |
| off | water outlet (K) | 474.744 | 478.067 | +3.323 |
| 0.08 | maximum Twg (K) | 645.370 | 648.500 | +3.130 |
| 0.08 | throat Twg (K) | 582.302 | 582.858 | +0.556 |
| 0.08 | throat q (MW/m2) | 16.1589 | 16.1536 | -0.0053 |
| 0.08 | water outlet (K) | 485.634 | 489.057 | +3.423 |

The coolant receives the previously omitted sloped-wall heat, so its upstream
counterflow temperature and maximum chamber wall temperature rise.  The small
decrease in local throat flux is the coupled response to the slightly warmer
wall/coolant state; no heat-transfer coefficient was reduced manually.

### 12.2 Requested custom axial convergence after the patch

| Stations | Radiation | max Twg (K) | throat Twg (K) | throat q (MW/m2) | water Tout (K) |
|---:|---:|---:|---:|---:|---:|
| 350 | off | 625.894 | 578.978 | 15.8708 | 478.075 |
| 700 | off | 625.974 | 579.387 | 15.8913 | 478.067 |
| 1400 | off | 626.013 | 579.359 | 15.8861 | 478.062 |
| 350 | 0.08 | 648.396 | 582.413 | 16.1303 | 489.065 |
| 700 | 0.08 | 648.500 | 582.858 | 16.1536 | 489.057 |
| 1400 | 0.08 | 648.551 | 582.823 | 16.1477 | 489.051 |

The 700-to-1400 maximum-wall change is 0.051 K with radiation and 0.039 K
without it.  Throat differences are dominated by the nearest station's exact
distance from the contour throat.  Radial and time-step convergence remain not
applicable because those discretizations do not exist in this solver.

### 12.3 Reproducible artifacts and tests

- `tools/thermal_audit.py` is a command-line audit driver.  Its independent
  Bartz function does not call the production Bartz implementation.
- `docs/thermal_audit_outputs/station_audit.csv` contains all 700 stations and
  the requested geometry, gas state, transport, Bartz factors, wall state,
  convective/radiative split, Reynolds number, and acceleration parameter.
- `docs/thermal_audit_outputs/bartz_sensitivity.csv` contains +/-10% input
  sensitivities at the throat.
- `docs/thermal_audit_outputs/axial_convergence.csv` contains the 350/700/1400,
  radiation-on/off runs.
- `docs/thermal_audit_outputs/summary.json` records the case, RocketCEA values,
  phase-margin diagnostic, model capabilities, and maximum independent versus
  production Bartz discrepancy (`1.43e-6` relative, or `0.000143%`).
- Targeted thermal/audit tests: 21 passed.  The final full suite, including the
  GUI smoke tests, passed 124 tests.  The initial Tcl path failure did not
  reproduce on the final run and is treated as an environment transient rather
  than a thermal-code result.

## 13. Residual uncertainty and required instrumentation

The residual uncertainty is physical/model-form dominated, not axial-grid
dominated.  In descending practical importance for the reference water-cooled
case:

1. coolant phase regime, subcooled-boiling heat transfer, CHF, and dryout;
2. effective channel cooling area, rib/sidewall fin efficiency, and as-built
   additive/manufacturing geometry;
3. combustion-product `mu`, `cp`, `k`, `Pr`, local gamma, and chemistry state;
4. injector-dependent chamber boundary-layer development and acceleration
   relaminarization;
5. axial/circumferential wall conduction and contact/coating resistance;
6. material-property scatter and temperature-dependent strength/fatigue;
7. Bartz model-form uncertainty;
8. axial numerical discretization, which is already small in this case.

An instrumented validation firing should record, on a synchronized time base:

- chamber pressure and independently calibrated oxidizer/fuel mass flows;
- water mass flow, inlet/outlet pressure and temperature, and high-frequency
  channel pressure fluctuations that can indicate boiling/flow instability;
- multiple water circuits or calorimeter segments so that local heat pickup is
  not inferred only from one whole-engine outlet temperature;
- embedded wall thermocouples at at least two depths per selected axial plane,
  including mid-chamber, convergent, just upstream of the throat, throat, and
  early divergent locations;
- a documented inverse-conduction reduction with sensor time constants,
  material-property uncertainty, and axial-boundary sensitivity;
- as-built channel dimensions, roughness, wall thickness, and throat contour
  metrology before and after firing;
- strain or displacement measurements if a thermal-stress/FoS conclusion is
  intended.

For every run, close the measured coolant enthalpy rise against the integrated
inferred wall heat within stated uncertainty, and report chamber and throat
separately.  Use those measurements to validate model assumptions and property
sources; do not fit an undocumented global multiplier to force agreement.
