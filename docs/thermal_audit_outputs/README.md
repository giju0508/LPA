# Thermal audit generated outputs

Regenerate from the repository root with:

```powershell
python tools\thermal_audit.py --output-dir docs\thermal_audit_outputs --station-count 700
```

Files:

- `station_audit.csv`: one row per axial station.  The control volume is the
  local quasi-one-dimensional gas area multiplied by the axial control-cell
  width.  `slope_dr_dx` and acceleration use centered differences except at
  endpoints.  Bartz reference `mu`, `cp`, and `Pr` are explicitly separated
  from the local gas-property columns.
- `bartz_sensitivity.csv`: throat independent-Bartz response to +/-10% input
  perturbations.  These are sensitivities, not calibration factors.
- `axial_convergence.csv`: custom diagnostic-only 350/700/1400 station runs
  with gas radiation off and at the selected emissivity.
- `summary.json`: case definition, performance basis, phase-margin diagnostic,
  agreement metric, and absent-model flags.

This reference case is fully specified in the audit report.  It reproduces the
reported 10 bar/O/F/mass-flow class, but it is not asserted to be an exact copy
of a user project file that was not supplied.
