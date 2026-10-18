# Rao parabolic bell construction

The implementation follows the parabolic approximation in
[NASA SP-125, Design of Liquid Propellant Rocket Engines](https://ntrs.nasa.gov/citations/19710019929),
printed pp. 90-91, Eq. (4-7) and Figs. 4-13/4-14. The worked example on
printed p. 98 supplies an independent numerical reference. PDF page numbers
are 99-100 and 107, respectively. NASA SP-8120, printed p. 15, Fig. 5(b),
independently confirms the expansion/length trends of the wall angles.

## Automatic wall angles and their limits

`lpa/core/rao.py` contains samples read from SP-125 Fig. 4-14, with five
length curves (60, 70, 80, 90 and 100 percent) and twelve expansion-ratio
stations (5, 7.5, 10, 14, 15, 20, 25, 30, 35, 40, 45 and 50).
Piecewise linear interpolation is applied in expansion ratio and length
fraction; both chart axes are linear. The denser stations at low expansion
ratios capture the greater curvature there.

Within **5 <= Ae/At <= 50** and **60 <= Le/Lc15 <= 100 percent**, automatic
angle selection retains the NASA interpolation. The chart itself is never
extrapolated. Outside it, the flow-based extension below selects the angles.
Within the chart, the initial angle Tn increases with
expansion ratio, the exit angle Te decreases, and both decrease with length.
Small plateaus in the table reflect rounding of chart readings.

Most chart samples are rounded to 0.5 degrees. Allow roughly 0.5 degrees
for chart reading and interpolation uncertainty; this is an engineering
estimate, not a guaranteed error bound. The SP-125 p. 98 example is explicitly
listed as **Ae/At = 14, Le/Lc15 = 80 percent, Tn = 27.4 degrees,
Te = 9.8 degrees**, and is retained exactly as a table anchor. The geometric
construction preserves the selected angles to floating-point precision;
the precision of that construction does not improve the underlying chart.

## RPA flow-based extension

Version 0.13.0 removes the automatic 5-50 area-ratio restriction. Automatic
selection accepts finite **Ae/At > 1** and **50-120 percent bell length**,
subject to the geometric feasibility of the specified length and Rn/Rt.

The [official RPA manual](https://app.rocket-propulsion.com/downloads/4/docs/RPA_4_User_Manual.pdf)
documents parabolic automatic angles and its scripting interface, but does
not publish their formulas. Using the installed official scripting utility
in the RPA 4.0.13 bundle, both angles were measured with the angle inputs
omitted. Twelve area-ratio cases and eight propellant/pressure/freezing/radius
cases were compared with the following relations. They match those **20
measured states to approximately 5e-12 degrees or better**; this is a verified
observation, not a claim to possess RPA's proprietary source code.

Let Me be supersonic exit Mach, Kt the throat isentropic exponent, and Ke the
exit isentropic exponent. Compute the Prandtl-Meyer angle nu in radians:

```text
nu = sqrt((Kt+1)/(Kt-1)) * atan(sqrt((Kt-1)/(Kt+1) * (Me^2-1)))
     - atan(sqrt(Me^2-1))
Tn_preference = degrees(nu / 3)
Te_nominal = degrees(0.5 * asin(2 * sqrt(Me^2-1) / (Ke * Me^2)))
Te_preference = max(8 degrees, Te_nominal)
if Te_preference > Tn_preference:
    Te_preference = 0.9 * Tn_preference
```

The order and strict comparison matter. For example, at area ratio 5 the
observed Te may exceed 0.9 Tn while still being less than Tn; a simple
`min(0.9*Tn, Te_preference)` does not reproduce that behavior. A series form
of nu avoids cancellation close to sonic Mach, and the exit expression uses
inverse Mach to avoid unnecessary overflow.

LPA supplies Me from RocketCEA `get_MachNumber` and station exponents from
`get_Throat_MolWt_gamma` and `get_exit_MolWt_gamma`. CEA GAMMAs is the exponent
in `a^2 = K*R*T`, which is not necessarily equilibrium Cp/Cv. The selected
equilibrium/frozen flags are forwarded. For throat freezing, the sonic
exit-property API at epsilon=1 is used because the throat getter does not
accept `frozenAtThroat`. Missing auxiliary getters use documented constant-
gamma estimates; metadata distinguishes actual, partial and estimated states.
Geometry-only callers without a performance state assume ideal-gas K=1.2.
The implementation needs no RPA installation at runtime.

The source fixture `tests/fixtures/rpa_rao_4_0_13.json` preserves all 20
input configurations, measured flow states, angles, lengths and executable
hashes. The bundle's GUI PE version is 4.0.13.0; its Script PE version is
4.0.8.0, and the shared DLL PE resources are 4.0.0.0. These actual versions
are recorded separately rather than inferring them from the installation
folder. Captured configurations contain no manually specified Tn or Te.

The pure flow preferences need not fit an arbitrary selected bell length.
Actual RPA output also exhibited increased length at low area ratios and
nonmonotone curves in some combinations. LPA instead preserves its requested
length and Rn/Rt, tests feasibility, and if necessary projects Tn into the
admissible tangent interval and lowers Te below the N-E chord angle before
constructing Q. Raw preferences and applied values are recorded separately;
such adjustments produce a functional result warning. The projection is an
LPA geometric policy, not an assertion of RPA thrust optimization.

NASA interpolation and RPA flow preferences are distinct models. Switching
between them at the chart boundaries can change angles discontinuously.
For geometry parameter sweeps, inspect `rao_angle_method` and do not interpret
that source switch as a smooth optimized-angle curve. Manual angles can be
used for a study requiring a single prescribed contour family.

Using LPA's thermochemical values also means the final angles need not be
numerically identical to a full RPA analysis. The verified equality applies
to the relation evaluated with the same measured Me, Kt and Ke.

## Explicit angles and project compatibility

The two GUI inputs `Rao start angle Tn` and `Rao exit angle Te` are optional.
Leave both blank for automatic chart/flow selection, including outside the
chart. To specify a prescribed design, provide both angles.
Explicit inputs must be finite and satisfy **0 <= Te < Tn < 90 degrees**.
The existing 50-120 percent bell-length input range is retained for these
explicit designs. A single supplied angle is an input error.

Project keys are `rao_start_angle_deg` and `rao_exit_angle_deg`; core input
fields are `rao_initial_angle_deg` and `rao_exit_angle_deg` in `NozzleGeometry`.
Legacy projects without these keys use automatic angles. Projects outside
the chart domain now use the flow extension automatically; they no longer
require an explicit angle pair. Conical contours do not use these inputs.

## Geometric construction

Let Rt be throat radius, Rn the downstream throat-blend radius, epsilon the
area ratio, and f the length fraction. All wall angles are measured relative
to the nozzle axis. The reference cone uses the same rounded throat:

```text
Re = Rt * sqrt(epsilon)
Lc15 = (Re - Rt) / tan(15 deg) + Rn * tan(7.5 deg)
Le = f * Lc15
N = (Rn * sin(Tn), Rt + Rn * (1 - cos(Tn)))
E = (Le, Re)
```

This length expression is identical to SP-125 Eq. (4-7), since
`(sec(15 deg) - 1) / tan(15 deg) = tan(7.5 deg)`. The downstream circular arc
joins the parabola at N with tangent Tn. Q is the exact intersection of the
Tn tangent through N and the Te tangent through E. The N-Q-E quadratic
Bezier is the skewed parabola described by the reference.

A valid downstream bell requires `Nx < Le`, `Ny < Re`, and
`tan(Te) < (Re - Ny)/(Le - Nx) < tan(Tn)`. These conditions put Q downstream
of N and upstream of E, and guarantee increasing axial coordinates and
radii over the entire continuous curve, including between plot samples.
Incompatible inputs produce an error containing expansion ratio, length,
Rn/Rt and both angles. Q is never moved to make an invalid design appear
valid; doing so would change one of the actual wall angles.

The nozzle's fixed interval budget is split between the arc and parabola,
with at least four intervals per section. The shared N sample appears once,
and the exit is included exactly, preserving the requested total point count.

SP-125's near-optimum chart uses the conventional downstream blend
`Rn/Rt = 0.382`. Other positive blend radii are permitted if the above
geometric conditions hold; their geometry remains tangent-correct, but
the chart does not establish their thrust optimality. This is a parabolic
approximation, not a characteristic-method flowfield optimization.

## Provenance and verification

Bell metadata records `rao_angle_method=nasa_sp125_chart_interpolation`,
`rpa_observed_flow_auto`, or `user_specified`, together with
`rao_angle_source`, the used expansion/length ratios, N and Q coordinates,
wall angles and the rounded 15-degree reference length. Flow selections also
record Me, Kt, Ke, `rao_flow_source`, `rao_initial_preference_deg`,
`rao_exit_preference_deg` and `rao_geometry_adjusted`.

`tests/test_rao_angles.py` verifies the published example, representative
chart readings, both monotonic trends, bounds and nonfinite input rejection.
`tests/test_core_contour.py` verifies the exact endpoint tangents, throat-arc
junction, continuous-curve monotonicity, exit area, reference length and
point budgets at several resolutions. It includes the old intersection-clamp
and low-expansion malformed-contour regressions. `tests/test_rao_inputs.py`
checks manual input validation, mapping, CFG/JSON round trips and GUI loading.
`tests/test_rpa_flow_angles.py` compares the pure flow relations with the
20 actual RPA outputs and validates extended contours and warning propagation.
`tests/test_rao_flow_state.py` checks CEA station data and freezing arguments;
`tests/test_rao_geometry_constraints.py` checks feasibility and projection.

In the captured A-1 configuration at Ae/At=14 and 80 percent, both RPA angles
automatic give Tn=27.291945 degrees and Te=13.760652 degrees. Specifying
only Te=8 degrees while leaving Tn automatic gives 27.291945/8 instead.
The earlier 8-degree comparison must not be read as a universal automatic
Te default. Both differ from the NASA worked-example angle pair.

### Source validation on 2026-10-06 (KST)

- Full regression suite: **296 passed**, using
  `.venv-build/Scripts/python.exe -m pytest tests -q --basetemp tmp/pytest-rao-final-20261006`.
- `compileall` for `main.py`, `lpa` and `tests`, and `git diff --check`: passed.
- Independent geometric review sampled **8,803 inputs**: 3,731 dense chart
  cases, 3,024 blend-radius/size/resolution combinations, 2,000 manual-angle
  cases and 48 special regressions. There were 7,390 valid constructions and
  1,413 expected input rejections, with no mismatches against an independently
  calculated chord/tangent feasibility condition.
- Among valid constructions, maximum endpoint-tangent discrepancy was
  approximately **1.20e-12 degrees**, and maximum exit-area-ratio relative
  discrepancy was **5.55e-16**. These are construction errors, not chart-angle
  accuracy estimates.
- Actual RocketCEA/Bartz integration, manual angles outside the chart,
  result serialization and a converged regenerative-cooling case were checked.
  This entry describes source/runtime validation; it does not certify a newly
  packaged executable.

### NASA-chart-only build 0.12.0 on 2026-10-08 (KST)

The earlier chart-only implementation was included in **LPA 0.12.0**. Its
full suite passed 299 tests; the EXE had Windows FileVersion/ProductVersion
0.12.0 and reproduced the published 27.4/9.8-degree example.
GUI startup, response and normal shutdown were checked on the build PC.
Version timestamps, artifact hashes and build/test/smoke log paths are recorded
in [the 0.12.0 validation record](VALIDATION.md).

### Extended automatic build 0.13.0 on 2026-10-08 (KST)

The full suite passed **390 tests**. Actual RocketCEA+Bartz analysis of
area ratios 2/4/100/250/1000 and lengths 50/80/120 percent passed 15 combinations;
the area-ratio-100 regenerative-cooling case converged in 13 iterations.
An independent 5,000-case geometry review found 4,503 valid cases and 497
expected dimension errors, with no feasibility mismatches.

The rebuilt EXE was independently checked against source bytecode and used
to execute the 20 measured RPA states without importing workspace modules.
Maximum pure flow-angle discrepancy was **2.84e-14 degrees**. Its archived
contour implementation also preserved area, length, mesh and tangents for
area ratios 1.0001/2/4/100/250/1000. GUI startup/response/normal exit passed.
The EXE includes no external RPA binary dependency. Artifact hashes, actual
version resources and logs are in [the 0.13.0 validation record](VALIDATION.md).
