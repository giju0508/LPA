# LPA 0.16.0b1 Beta — thermal/property implementation log

Date: 2026-10-19 KST. Scope authorized after the read-only investigation:
correct gas heat transfer, improve propellant properties, introduce supported
two-phase channel calculations and plotting, version and upload the complete
working source and Beta distribution to the owner's private GitHub repository.

## Findings and corrections

1. LNG at 150 K/25 bar selected a spurious low-density HEOS root. The old
   0.1-Pcrit bubble-point guard did not cover this subcooled-liquid condition.
   Actual pressure bubble/dew boundaries and bracketed enthalpy inversion now
   preserve the liquid branch; 20/25/30 bar property/enthalpy tests pass.
2. Bartz had correct algebra but used flow-selected equilibrium transport and
   downstream Rn. Its thermal reference now uses separate frozen chamber
   Cp/Pr/mu/gamma, with actual upstream R1 curvature (including stretched
   convergent geometry). Reacting nozzle thermodynamic arrays are retained.
3. Saturated pure-fluid boiling uses pinned ht 1.2.0 / fluids 1.3.1:
   Li-Wu for 0.19–3.1 mm hydraulic diameter, Chen-Bennett for conventional
   diameters above 3.1 mm in automatic mode. Explicit Chen selection permits
   Dh >=3 mm. The 32 mm upper bound is a Beta computational envelope, not
   a guarantee of an experimental validity rectangle.
4. Lockhart-Martinelli/Chisholm smooth-channel friction is coupled with
   homogeneous acceleration using mean mass flux times velocity change.
   Boundary mass flux accounts for varying channel area. In two-phase cells,
   h+p coupling includes the kinetic-energy change; its contribution is
   reported separately from static enthalpy in the energy balance.
5. Vapor *mass* quality, phase and flow regime are recorded even at the first
   unsupported station. Temperature plots shade detected two-phase spans;
   CSV includes quality, regime and whether a wall solution exists.
6. A stopped/invalid upstream circuit cannot restart in a linked circuit.
   Outlet pressure exhaustion returns diagnostics instead of raising during
   the next circuit's property call. Valid completed screening/custom-property
   circuits retain existing serial-link behavior.

## Explicit Beta limits

- The default quality ceiling x=0.7 is a computational stop, **not a dryout
  quality, CHF estimate, or safety margin**. Pressure >=0.8 Pcrit is gated.
- Correlations assume pre-dryout saturated evaporation. Condensation, invalid
  heat flux and unavailable phase transport are rejected. No arbitrary positive
  clamp converts reverse heat transfer into boiling.
- LNG and aqueous-mixture two-phase **thermodynamics** and mass quality can be
  returned by the EOS. Mixture boiling/glide/mass-transfer heat transfer is
  unsupported and the wall march stops. Pure-fluid correlations are not applied
  to mixtures. N2O transport deficiencies also prevent a boiling calculation.
- Subcooled boiling, CHF/dryout, post-dryout, boiling instability, slip/flow
  pattern, compressible choking and supercritical heat-transfer deterioration
  remain unvalidated/unimplemented. Rectangular hydraulic-D/fin adaptations,
  cryogenic applicability and manufactured geometry require validation.
- Single-phase channels retain their existing distributed Darcy model;
  acceleration/kinetic-energy corrections are implemented for two-phase cells.
  Manifold, gravity and local/bend losses are not included.
- REFPROP is optional, separately installed/licensed and not bundled. Missing
  REFPROP never silently changes the requested backend to HEOS. Native HEOS
  remains the default. RP-1/Jet A-1 still use explicit screening because the
  complete NIST surrogate components/fluid files are unavailable here.

## Verification and execution record

- Property-specific regression tests: 12 passed; gas-specific and related
  performance tests: 45 passed; new channel tests: 10 passed.
- Final complete suite: **598 passed in 72.01 s**. `pytest.ini` now restricts
  discovery to tests/; the first repository-wide collection had encountered
  old inaccessible tmp/pytest directories, not application-test failures.
- A full-suite link regression exposed over-restrictive handling of completed
  screening/custom circuits. The guard was corrected without allowing failed
  EOS or partially traversed source circuits to continue; the full suite passed.
- Direct RPA fixture: chamber/throat/exit h and q within 3%; throat h -1.77%,
  q -1.88%. This compares a fixed-wall gas-side benchmark, not the user's complete
  LNG engine or experimental heat flux. Source and capture script are retained.
- Numerical boiling cylinder: 120/120 stations, 16 two-phase stations,
  integrated heat 42535.8798 W, static-enthalpy rise 42535.3565 W, two-phase
  kinetic change 0.523275 W, residual 2.18e-11 W. Its *overall* applicability
  remains unsupported because subcooled boiling precedes bulk saturation and
  its specified gas transport is screening. Energy closure is not a claim of
  physical heat-transfer accuracy; the phase handoff can be discontinuous.
- Dependencies, state matrix, RPA comparison, raw station CSV and plotted phase
  region are in [thermal_beta_outputs_0160](thermal_beta_outputs_0160/).
- Reproduction: `python -B -m tools.thermal_beta_benchmarks` and
  `python -B -m pytest -q -p no:cacheprovider --basetemp tmp/beta-test`.
- Runtime logging uses a rotating UTF-8 `%LOCALAPPDATA%/LPA/logs/lpa.log`
  (2 MB, four backups). It records version, inlet/outlet state, quality, solved
  station counts and applicability/stop reasons. A read-only log directory
  does not prevent application startup.
- Windows build, binary smoke check, hashes and publication results are
  recorded in [VALIDATION.md](VALIDATION.md).

## Sources and detailed reviews

- [Gas reference and RPA capture](THERMAL_GAS_METHOD_2026-10-19.md).
- [EOS, transport, REFPROP and RP-1 evidence](COOLANT_PROPERTIES_2026-10-19.md).
- [Plot/CSV/UI verification](TWO_PHASE_UI_2026-10-19.md).
- Bennett & Chen, AIChE J. 26 (1980), doi:10.1002/aic.690260317.
- Li & Wu, IJHMT 53 (2010), doi:10.1016/j.ijheatmasstransfer.2010.01.012.
- Chisholm, IJHMT 10 (1967), doi:10.1016/0017-9310(67)90047-6.
- [ht flow boiling documentation](https://ht.readthedocs.io/en/latest/ht.boiling_flow.html),
  [fluids two-phase documentation](https://fluids.readthedocs.io/fluids.two_phase.html).
