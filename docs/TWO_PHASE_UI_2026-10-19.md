# Two-phase thermal result UI — 2026-10-19

## Changes

- `lpa/ui/result_views.py` shades the cells whose reported `coolant_phase` is `two_phase` on the temperature plot. Amber hatching and one “Two-phase coolant” legend entry identify the region. Cell edges use adjacent station midpoints; a phase gap or a change in `active_segment_id` starts a new span.
- A reported two-phase state is still shown when its wall solution is unavailable. The overlay does not fabricate wall or coolant temperatures in unsolved cells.
- “Numerically converged” retains its local iteration meaning. A separate “Solved wall stations n/N · Unsolved m” label counts finite hot-wall temperatures, so a partial result cannot appear complete solely because its solved stations converged.
- The representative axial table includes vapor mass quality (0–1) and the reported flow/boiling regime. Invalid quality values, EOS sentinels, and missing values display as `—`.
- All-station CSV exports add `coolant_vapor_quality`, `coolant_flow_regime`, and `wall_solution_available`. They retain a diagnosed phase/quality/regime on an unsolved station while leaving unavailable temperatures blank. Source metadata includes `two_phase_model` and `two_phase_model_by_segment`.
- The diagnostics dialog includes solved/unsolved counts, the number of two-phase stations, the reported quality range, flow/boiling status counts, and the existing full model/source metadata.

These are result displays. The presence of a shaded region or a quality value does not itself establish physical applicability; the solver's physical status and stop reasons remain visible in diagnostics.

## Verification

The following targeted command passed on 2026-10-19:

```powershell
./.venv-build/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp=tmp/pytest-two-phase-ui-20261019-3 tests/test_two_phase_ui.py tests/test_thermal_result_sampling.py tests/test_release_ui_fixes.py tests/test_ui_smoke.py -k 'two_phase or representative_indices or thermal_contour or thermal_regen_summary or unsupported_thermal_result or thermal_csv or full_warning or reactant_supply_model'
```

Result: **13 passed, 62 deselected**. Coverage includes circuit/gap separation, a diagnosed unsolved two-phase cell, quality endpoints/sentinels, rendered plot spans and legend, Tk summary/table content, complete CSV rows and source metadata, legacy result display, and existing contour/pressure-summary behavior.

A fixture plot was rendered with Matplotlib Agg and visually inspected at `tmp/two-phase-ui-preview.png`. Hatching remains visible over the contour fill, and missing temperatures remain gaps. This fixture image is a display check, not a physical benchmark.

The first test attempt could not create files in the existing system `pytest-of-LGJ` temporary directory (`PermissionError`). Re-running with an explicit workspace `--basetemp` resolved that environment issue.
