"""Analysis result pages and engineering plots."""

from __future__ import annotations

import csv
import json
import math
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.ticker import AutoMinorLocator

from .theme import COLORS, FONT_UI
from .widgets import EmptyState, ScrollableFrame, fit_tree_columns


def _resource_path(name: str) -> Path:
    """Resolve bundled UI resources in source and PyInstaller one-file modes."""

    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / "lpa" / "resources" / name
    return Path(__file__).resolve().parents[1] / "resources" / name


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _get(data: Any, *paths: str, default: Any = None) -> Any:
    for path in paths:
        current = data
        found = True
        for part in path.split("."):
            if isinstance(current, dict):
                if part not in current:
                    found = False
                    break
                current = current[part]
            else:
                if not hasattr(current, part):
                    found = False
                    break
                current = getattr(current, part)
        if found and current is not None:
            return current
    return default


def _array(data: Any, *paths: str) -> np.ndarray:
    value = _get(data, *paths, default=[])
    try:
        return np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return np.array([], dtype=float)


def _number(value: Any, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _display_number(value: Any, digits: int = 3) -> str:
    number = _number(value)
    return f"{number:.{digits}f}" if math.isfinite(number) else "—"


def _thermal_station_completion(thermal: Any) -> tuple[int, int]:
    """Count wall solutions independently of local nonlinear convergence."""

    x = _array(thermal, "x_mm", "x", "x_m")
    hot_wall = _array(thermal, "twg_k", "Twg_K", "Twg")
    total = len(x) or max(0, int(_number(_get(thermal, "section_count", default=0), 0)))
    return int(np.count_nonzero(np.isfinite(hot_wall[:total]))), total


def _thermal_completion_details(thermal: Any) -> dict[str, Any]:
    """Keep available wall solutions separate from a completed coolant march."""

    solved, total = _thermal_station_completion(thermal)
    metadata = _mapping(_get(thermal, "metadata", default={}))
    segments = _mapping(metadata.get("regen_segment_completion"))
    applicability = _get(thermal, "station_applicability", default=[]) or []
    unsupported = (sum(value == "unsupported" for value in applicability) if applicability
                   else metadata.get("unsupported_station_count"))
    return {
        "solved_wall_station_count": solved,
        "requested_wall_station_count": total,
        "wall_solution_complete": bool(total and solved == total and metadata.get("wall_solution_complete", True)),
        "unsupported_station_count": unsupported,
        "incomplete_regen_segment_ids": [str(key) for key, value in segments.items()
                                         if _mapping(value).get("wall_march_completed") is False],
    }


def _thermal_two_phase_regions(thermal: Any, x: np.ndarray) -> list[tuple[float, float, str | None]]:
    """Return contiguous phase cells, including a diagnosed unsolved cell."""

    phases = _get(thermal, "coolant_phase", default=[]) or []
    active = _get(thermal, "active_segment_id", default=[]) or []
    if len(phases) != len(x):
        return []
    regions: list[tuple[float, float, str | None]] = []
    index = 0
    while index < len(x):
        if str(phases[index]).replace("-", "_") != "two_phase" or not math.isfinite(float(x[index])):
            index += 1
            continue
        start = index
        identifier = active[index] if len(active) == len(x) else None
        index += 1
        while (index < len(x) and str(phases[index]).replace("-", "_") == "two_phase"
               and math.isfinite(float(x[index]))
               and (active[index] if len(active) == len(x) else None) == identifier):
            index += 1
        end = index - 1
        left = float(x[start]) if start == 0 or not math.isfinite(float(x[start - 1])) else float(0.5 * (x[start - 1] + x[start]))
        right = float(x[end]) if end == len(x) - 1 or not math.isfinite(float(x[end + 1])) else float(0.5 * (x[end] + x[end + 1]))
        regions.append((left, right, identifier))
    return regions


def _coolant_quality_array(thermal: Any) -> np.ndarray:
    """Do not display an EOS sentinel or an invalid quality as a mass fraction."""

    quality = _array(thermal, "coolant_vapor_quality")
    return np.where((quality >= 0.0) & (quality <= 1.0), quality, np.nan)


def _coolant_phase_counts(thermal: Any) -> dict[str, int]:
    """Property phase is independent of the selected convection correlation."""

    counts: dict[str, int] = {}
    for phase in _get(thermal, "coolant_phase", default=[]) or []:
        if phase:
            name = str(phase).replace("-", "_")
            counts[name] = counts.get(name, 0) + 1
    return counts


def engineering_force(value_n: Any) -> tuple[str, str]:
    value = _number(value_n, 0.0)
    return (f"{value / 1000:.3f}", "kN") if abs(value) >= 1000 else (f"{value:.2f}", "N")


def engineering_flow(value_kg_s: Any) -> tuple[str, str]:
    value = _number(value_kg_s, 0.0)
    return (f"{value * 1000:.2f}", "g/s") if abs(value) < 1 else (f"{value:.4f}", "kg/s")




class ResultPage(ttk.Frame):
    title = "Results"
    page_description = ""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.data: dict[str, Any] | None = None
        self.current_subtitle = self.page_description
        self.empty = EmptyState(self, "No analysis results", "Complete the inputs and select Run Analysis.")
        self.empty.pack(fill="both", expand=True)
        top = self.winfo_toplevel()
        self.film_display_var = getattr(top, "film_correction_var", tk.BooleanVar(self, value=False))
        self.report_warnings: list[str] = []

    def clear(self) -> None:
        self.data = None
        self.current_subtitle = self.page_description
        for child in self.winfo_children():
            child.pack_forget()
        self.empty.pack(fill="both", expand=True)
        self._update_page_context(self.title, self.current_subtitle)

    def set_result(self, data: dict[str, Any]) -> None:
        self.data = data

    def _select_sweep_rows(self, rows: list[Any]) -> list[dict[str, Any]]:
        basis = "with_film" if self.film_display_var.get() else "without_film"
        selected = []
        for item in rows:
            row = dict(_mapping(item))
            row.update(_mapping(row.get(basis)))
            row["display_basis"] = basis
            selected.append(row)
        return selected

    def _toggle_film_display(self) -> None:
        pages = getattr(self.winfo_toplevel(), "pages", {})
        targets = (pages.get(key) for key in ("size_result", "throttle_result", "ambient_result"))
        for page in targets:
            if page is not None and page.data is not None:
                page.set_result(page.data)

    def _film_display_control(self, parent: tk.Misc) -> None:
        ttk.Checkbutton(parent, text="Display film correction", variable=self.film_display_var,
                        command=self._toggle_film_display).pack(anchor="e", pady=(0, 7))

    def _result_diagnostics(self, parent: tk.Misc, data: dict[str, Any]) -> None:
        thermal = _mapping(data.get("thermal"))
        raw = list(data.get("warnings", [])) + list(thermal.get("warnings", [])) + list(thermal.get("physical_issues", []))
        for rows in (data.get("throttle", []), _get(data, "ambient.pressure_rows", default=[]),
                     _get(data, "ambient.altitude_rows", default=[])):
            for row in rows if isinstance(rows, list) else []:
                raw.extend(_mapping(row).get("warnings", []))
        self.report_warnings = list(dict.fromkeys(str(item) for item in raw if str(item).strip()))
        row = ttk.Frame(parent, style="Surface.TFrame")
        row.pack(fill="x", pady=(0, 8))
        status = str(thermal.get("physical_validity", "not_assessed"))
        label_text = {"valid": "Within reported model limits", "screening": "Screening model: review limits",
                      "invalid": "Outside model limits", "unsupported": "Unsupported physical state",
                      "not_assessed": "Not assessed"}.get(status, status)
        if data.get("thermal_enabled", bool(thermal.get("section_count"))):
            label = ttk.Label(row, text=f"Physical applicability: {label_text}",
                              style=("Badge.TLabel" if status == "valid" else "Error.TLabel"
                                     if status in {"invalid", "unsupported"} else "Warning.TLabel"),
                              wraplength=500)
            label.pack(side="left", fill="x", expand=True)
            row.bind("<Configure>", lambda event: label.configure(
                wraplength=max(100, event.width - details.winfo_reqwidth() - 24)), add="+")
        details = ttk.Button(row, text=f"Warnings ({len(self.report_warnings)}) / model details…",
                             command=self._show_diagnostics)
        details.pack(side="right")
        if self.report_warnings:
            preview = ttk.Label(parent, text=self.report_warnings[0], style="Warning.TLabel", wraplength=700)
            preview.pack(fill="x", pady=(0, 8))
            preview.bind("<Configure>", lambda event: preview.configure(wraplength=max(120, event.width - 24)), add="+")

    def _diagnostic_text(self) -> str:
        data = self.data or {}
        thermal = _mapping(data.get("thermal"))
        lines = [f"Backend: {data.get('method', 'Unknown')}",
                 f"Numerical convergence: {thermal.get('converged', 'Not assessed')}",
                 f"Physical applicability: {thermal.get('physical_validity', 'Not assessed')}", "", "Warnings:"]
        if thermal:
            solved, total = _thermal_station_completion(thermal)
            completion = _thermal_completion_details(thermal)
            phase_counts = _coolant_phase_counts(thermal)
            two_phase = phase_counts.get("two_phase", 0)
            quality = _coolant_quality_array(thermal)
            finite_quality = quality[np.isfinite(quality)]
            regimes = thermal.get("coolant_flow_regime", []) or []
            counts = {str(regime): regimes.count(regime) for regime in dict.fromkeys(regimes) if regime}
            lines[3:3] = [f"Solved wall stations: {solved}/{total}; unsolved: {total - solved}",
                          f"Wall solution complete: {completion['wall_solution_complete']}",
                          "Incomplete regenerative marches: " + (", ".join(completion["incomplete_regen_segment_ids"]) or "none reported"),
                          "Unsupported stations: " + str(completion["unsupported_station_count"]
                                                         if completion["unsupported_station_count"] is not None else "not reported"),
                          "Coolant property phase: " + (json.dumps(phase_counts, ensure_ascii=False) if phase_counts else "not reported"),
                          f"Two-phase coolant stations: {two_phase}",
                          "Vapor mass quality (0–1): " + (f"{min(finite_quality):.5f} to {max(finite_quality):.5f}"
                                                         if len(finite_quality) else "not reported"),
                          "Coolant heat-transfer correlation / regime: " + (json.dumps(counts, ensure_ascii=False) if counts else "not reported")]
        lines.extend(f"{index}. {warning}" for index, warning in enumerate(self.report_warnings, 1))
        if not self.report_warnings:
            lines.append("No reported warnings.")
        metadata = _mapping(thermal.get("metadata"))
        lines.extend(("", "Model capabilities / property sources:", json.dumps(metadata, indent=2, ensure_ascii=False, default=str)))
        for key, title in (("reactant_supply_states", "Reactant supply states / enthalpy model:"),
                           ("regen_feed_feedback", "Regen feed feedback:"),
                           ("mixture_ratio_optimization", "Automatic O/F: theoretical vacuum Isp optimization:")):
            if key in data:
                lines.extend(("", title, json.dumps(data[key], indent=2, ensure_ascii=False, default=str)))
        return "\n".join(lines)

    def _show_diagnostics(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Analysis warnings and model applicability")
        dialog.geometry("780x600")
        dialog.minsize(540, 360)
        dialog.transient(self.winfo_toplevel())
        icon = getattr(self.winfo_toplevel(), "apply_child_icon", None)
        if callable(icon):
            icon(dialog)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", font=(FONT_UI, 10))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.configure(yscrollcommand=scroll.set)
        contents = self._diagnostic_text()
        text.insert("1.0", contents)
        text.configure(state="disabled")
        def copy_all() -> None:
            dialog.clipboard_clear()
            dialog.clipboard_append(contents)
        ttk.Button(dialog, text="Copy all", command=copy_all).pack(side="right", padx=12, pady=10)
        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(side="right", pady=10)

    def _update_page_context(self, title: str, subtitle: str = "") -> None:
        self.current_subtitle = subtitle or self.page_description
        top = self.winfo_toplevel()
        pages = getattr(top, "pages", {})
        current = getattr(top, "current_page", None)
        if isinstance(pages, dict) and pages.get(current) is self:
            update = getattr(top, "set_page_context", None)
            if callable(update):
                update(title, self.current_subtitle)

    def _header(self, parent: tk.Misc, title: str, subtitle: str = "") -> ttk.Frame:
        """Create only the page-specific controls row.

        The title and explanatory text live in the global action header so the
        same information is not repeated inside every result page.
        """

        self._update_page_context(title, subtitle)
        header = ttk.Frame(parent, style="Surface.TFrame")
        header.pack(fill="x", pady=(0, 8))
        return header


class MetricTile(ttk.Frame):
    def __init__(self, master: tk.Misc, label: str, value: str, unit: str, note: str = "") -> None:
        super().__init__(master, style="Card.TFrame", padding=(10, 7), relief="solid", borderwidth=1)
        # A bounded request prevents wrapped text from feeding its own grid
        # allocation back into Tk's geometry negotiation.
        heading = ttk.Label(self, text=label, style="Muted.TLabel", font=(FONT_UI, 8, "bold"), wraplength=120)
        heading.pack(anchor="w", fill="x")
        row = ttk.Frame(self, style="Surface.TFrame")
        row.pack(anchor="w", pady=(2, 0))
        ttk.Label(row, text=value, style="Surface.TLabel", font=(FONT_UI, 13, "bold")).pack(side="left")
        ttk.Label(row, text=unit, style="Muted.TLabel", font=(FONT_UI, 8)).pack(side="left", padx=(4, 0), pady=(3, 0))
        if note:
            ttk.Label(self, text=note, style="Muted.TLabel", font=(FONT_UI, 7)).pack(anchor="w", pady=(2, 0))
        self._heading = heading


def style_axis(axis: Any, *, xlabel: str = "", ylabel: str = "", title: str = "") -> None:
    axis.set_facecolor("#fbfcfd")
    axis.grid(True, which="major", color=COLORS["grid"], linewidth=0.7)
    axis.grid(True, which="minor", color="#edf1f4", linewidth=0.45, linestyle=":")
    axis.xaxis.set_minor_locator(AutoMinorLocator())
    axis.yaxis.set_minor_locator(AutoMinorLocator())
    axis.tick_params(labelsize=8, colors=COLORS["muted"])
    axis.set_xlabel(xlabel, fontsize=9, color=COLORS["text"])
    axis.set_ylabel(ylabel, fontsize=9, color=COLORS["text"])
    axis.set_title(title, fontsize=12, fontweight="bold", color=COLORS["text"], pad=10)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color(COLORS["border"])


class FigurePanel(ttk.Frame):
    def __init__(self, master: tk.Misc, figure: Figure) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.figure = figure
        self.canvas = FigureCanvasTkAgg(figure, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar_frame = ttk.Frame(self, style="Surface.TFrame")
        toolbar_frame.pack(fill="x")
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="left")


class ChamberResultsPage(ResultPage):
    title = "Thrust Chamber Size"
    page_description = "Nominal performance, film-cooling correction, Rao geometry parameters, and true-scale contour."

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.scroll = ScrollableFrame(self, padding=20)
        self.film_blc_var = self.film_display_var
        self.rao_reference_image: tk.PhotoImage | None = None
        try:
            self.rao_reference_image = tk.PhotoImage(
                master=self,
                file=_resource_path("rao_contour_reference.png"),
            )
        except (tk.TclError, OSError):
            # Keep the results usable if an unpacked development tree is
            # missing the optional reference image.
            self.rao_reference_image = None

    def _toggle_film_blc(self) -> None:
        self._toggle_film_display()

    def set_result(self, data: dict[str, Any]) -> None:
        super().set_result(data)
        self.empty.pack_forget()
        for child in self.scroll.body.winfo_children():
            child.destroy()
        self.scroll.pack(fill="both", expand=True)
        header = self._header(
            self.scroll.body,
            self.title,
            self.page_description,
        )
        ttk.Label(
            header,
            text=str(data.get("method", "Analysis complete")),
            style="Badge.TLabel",
        ).pack(side="right", anchor="e")
        ttk.Checkbutton(
            header,
            text="Display film correction",
            variable=self.film_blc_var,
            command=self._toggle_film_blc,
        ).pack(side="right", padx=(0, 12))
        self._result_diagnostics(self.scroll.body, data)
        source = _get(data, "performance", default=data)
        summary = ttk.Frame(self.scroll.body, style="Surface.TFrame")
        summary.pack(fill="x", pady=(0, 12))
        summary.grid_columnconfigure(0, weight=3)
        summary.grid_columnconfigure(1, weight=2)
        summary.grid_rowconfigure(0, weight=1)
        performance_card = self._performance_section(summary, source, data)
        mass_flow_card = self._mass_flow_section(summary, source)
        performance_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        mass_flow_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        def arrange(event: tk.Event) -> None:
            scale = float(self.tk.call("tk", "scaling")) / (96.0 / 72.0)
            stacked = event.width < 730 * scale + 25
            if getattr(summary, "_stacked", None) == stacked:
                return
            summary._stacked = stacked  # type: ignore[attr-defined]
            performance_card.grid_configure(columnspan=2 if stacked else 1,
                                            sticky="ew" if stacked else "nsew", padx=(0, 0 if stacked else 6))
            mass_flow_card.grid_configure(row=1 if stacked else 0, column=0 if stacked else 1,
                                         columnspan=2 if stacked else 1, sticky="ew" if stacked else "nsew",
                                         padx=(0 if stacked else 6, 0), pady=(8 if stacked else 0, 0))
        summary.bind("<Configure>", arrange, add="+")
        self._geometry_section(data)
        self._contour_section(data)
        self._rao_reference_section()

    def _metric_grid(self, parent: tk.Misc, metrics: list[tuple[str, str, str, str]], columns: int = 3) -> None:
        frame = ttk.Frame(parent, style="Surface.TFrame")
        frame.pack(fill="x", pady=(5, 4))
        for column in range(columns):
            frame.grid_columnconfigure(column, weight=1, uniform="metric")
        for index, (label, value, unit, note) in enumerate(metrics):
            MetricTile(frame, label, value, unit, note).grid(
                row=index // columns,
                column=index % columns,
                padx=(0 if index % columns == 0 else 5, 0),
                pady=(0, 5),
                sticky="nsew",
            )

    def _performance_section(self, parent: tk.Misc, source: Any, data: Any) -> ttk.LabelFrame:
        card = ttk.LabelFrame(parent, text="  Performance  ", padding=9)
        if self.film_blc_var.get():
            selected = _get(source, "with_film", "film_corrected", default=source)
        else:
            selected = _get(source, "without_film", "ideal", "uncorrected", default=source)
        thrust_values = [
            _number(_get(selected, key, key.replace("_n", ""), default=None))
            for key in ("sea_level_thrust_n", "optimal_thrust_n", "vacuum_thrust_n")
        ]
        force_unit = "kN" if max((abs(value) for value in thrust_values if math.isfinite(value)), default=0.0) >= 1000.0 else "N"
        force_scale = 0.001 if force_unit == "kN" else 1.0
        thrust_metrics: list[tuple[str, str, str, str]] = []
        for value, label in zip(thrust_values, ("Sea-level thrust", "Optimal thrust", "Vacuum thrust")):
            formatted = _display_number(value * force_scale, 3 if force_unit == "kN" else 2)
            thrust_metrics.append((label, formatted, force_unit, ""))
        for key, label in (("sea_level_isp_s", "Sea-level Isp"), ("optimal_isp_s", "Optimal Isp"), ("vacuum_isp_s", "Vacuum Isp")):
            thrust_metrics.append((label, _display_number(_get(selected, key), 2), "s", ""))
        geometry = _get(data, "geometry", "contour.metrics", default={})
        chamber_pressure = _get(source, "chamber_pressure_bar", default=None)
        exit_pressure = _get(source, "exit_pressure_bar", default=None)
        residence_time = _get(geometry, "gas_residence_time_ms", default=None)
        thrust_metrics.extend(
            (
                (
                    "Chamber pressure",
                    _display_number(chamber_pressure, 3),
                    "bar(a)",
                    "",
                ),
                (
                    "Nozzle exit pressure",
                    _display_number(exit_pressure, 4),
                    "bar(a)",
                    "",
                ),
                (
                    "Gas residence time",
                    _display_number(residence_time, 3),
                    "ms",
                    "",
                ),
            )
        )
        self._metric_grid(card, thrust_metrics)
        return card

    def _mass_flow_section(self, parent: tk.Misc, source: Any) -> ttk.LabelFrame:
        card = ttk.LabelFrame(parent, text="  Mass flow rates  ", padding=9)
        total = _get(source, "mass_flow.total_kg_s", "total_mass_flow_kg_s", "mass_flow_kg_s")
        oxidizer = _get(source, "mass_flow.oxidizer_kg_s", "oxidizer_mass_flow_kg_s")
        fuel = _get(source, "mass_flow.fuel_kg_s", "fuel_mass_flow_kg_s")
        film = _get(source, "mass_flow.film_kg_s", "film_mass_flow_kg_s")
        external_coolants = _get(
            source, "mass_flow.external_regen_coolants", default=[]
        )
        metrics = []
        use_grams = abs(_number(total, 0.0)) < 1.0
        unit = "g/s" if use_grams else "kg/s"
        scale = 1000.0 if use_grams else 1.0
        for label, value in (("Total", total), ("Oxidizer", oxidizer), ("Fuel", fuel), ("Film", film)):
            formatted = _display_number(_number(value) * scale, 2 if use_grams else 4)
            metrics.append((label, formatted, unit, ""))
        for coolant_flow in external_coolants if isinstance(external_coolants, (list, tuple)) else ():
            item = _mapping(coolant_flow)
            coolant = str(item.get("coolant", "Coolant"))
            segment_name = str(item.get("segment_name", "Regen"))
            label = f"{coolant} coolant ({segment_name})"
            value = _number(item.get("kg_s"), 0.0)
            formatted = f"{value * scale:.2f}" if use_grams else f"{value:.4f}"
            metrics.append((label, formatted, unit, ""))
        self._metric_grid(card, metrics, columns=2)
        return card

    def _geometry_section(self, data: Any) -> None:
        geometry = _get(data, "geometry", "contour.metrics", default={})
        card = ttk.LabelFrame(self.scroll.body, text="  Chamber & Rao geometry  ", padding=11)
        card.pack(fill="x", pady=(0, 12))
        # Keep related dimensions together in three-column rows:
        # diameters, radii, axial lengths, blend radii, angles, and ratios.
        definitions = (
            ("Chamber diameter Dc", ("chamber_diameter_mm", "dc_mm"), "mm"),
            ("Throat diameter Dt", ("throat_diameter_mm", "dt_mm"), "mm"),
            ("Exit diameter De", ("exit_diameter_mm", "de_mm"), "mm"),
            ("Chamber radius Rc", ("chamber_radius_mm", "rc_mm"), "mm"),
            ("Throat radius Rt", ("throat_radius_mm", "rt_mm"), "mm"),
            ("Exit radius Re", ("exit_radius_mm", "re_mm"), "mm"),
            ("Cylindrical length Lcyl", ("cylindrical_length_mm", "lcyl_mm"), "mm"),
            ("Chamber length Lc", ("chamber_length_mm", "lc_mm"), "mm"),
            ("Nozzle length Le", ("nozzle_length_mm", "le_mm"), "mm"),
            ("Upstream throat radius R1", ("R1_mm", "r1_mm"), "mm"),
            ("Chamber blend radius R2", ("R2_mm", "r2_mm"), "mm"),
            ("Nozzle throat radius Rn", ("Rn_mm", "rn_mm"), "mm"),
            ("Contraction angle b", ("contraction_angle_deg", "beta_deg"), "deg"),
            ("Rao start angle Tn", ("rao_start_angle_deg", "theta_n_deg"), "deg"),
            ("Rao exit angle Te", ("rao_exit_angle_deg", "theta_e_deg"), "deg"),
            ("Contraction area ratio Ac/At", ("contraction_area_ratio",), ""),
            ("Expansion area ratio Ae/At", ("expansion_ratio", "area_ratio"), ""),
            ("Characteristic length L*", ("characteristic_length_mm", "lstar_mm"), "mm"),
        )
        metrics = []
        for label, keys, unit in definitions:
            value = next((_get(geometry, key, default=None) for key in keys if _get(geometry, key, default=None) is not None), None)
            formatted = _display_number(value, 3)
            metrics.append((label, formatted, unit, ""))
        self._metric_grid(card, metrics)

    def _contour_section(self, data: Any) -> None:
        card = ttk.LabelFrame(self.scroll.body, text="  Thrust chamber contour (true scale)  ", padding=8)
        card.pack(fill="both", expand=True, pady=(0, 12))
        x = _array(data, "contour.x_mm", "geometry.x_mm", "x_mm")
        radius = _array(data, "contour.radius_mm", "geometry.radius_mm", "radius_mm")
        if not len(x) or len(x) != len(radius):
            ttk.Label(card, text="Contour data is unavailable.", style="Muted.TLabel").pack(padx=20, pady=30)
            return
        figure = Figure(figsize=(10.3, 3.9), dpi=100, facecolor=COLORS["surface"])
        axis = figure.add_subplot(111)
        axis.plot(x, radius, color=COLORS["plot_contour"], linewidth=1.8)
        axis.plot(x, -radius, color=COLORS["plot_contour"], linewidth=1.8)
        axis.fill_between(x, radius, -radius, color="#dfe5e9", alpha=0.45)
        axis.axhline(0, color="#86939e", linewidth=0.65, linestyle="--")
        style_axis(axis, xlabel="Axial location, mm", ylabel="Radius, mm")
        axis.set_aspect("equal", adjustable="datalim")
        axis.margins(x=0.03, y=0.15)
        figure.tight_layout()
        FigurePanel(card, figure).pack(fill="both", expand=True)

    def _rao_reference_section(self) -> None:
        card = ttk.LabelFrame(
            self.scroll.body,
            text="  Rao contour geometry reference  ",
            padding=(12, 9),
        )
        card.pack(fill="x", pady=(0, 12))
        if self.rao_reference_image is None:
            ttk.Label(
                card,
                text="Rao contour reference image is unavailable.",
                style="Muted.TLabel",
            ).pack(pady=18)
            return
        ttk.Label(
            card,
            image=self.rao_reference_image,
            style="Surface.TLabel",
        ).pack(anchor="center", padx=12, pady=6)


class ThermalResultsPage(ResultPage):
    title = "Thermal Analysis"
    page_description = "Bartz-based conjugate wall and coolant temperature analysis."

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        # The result can contain up to 30 axial rows in addition to the plot.
        # Keep the whole page scrollable so the plot never has to collapse at
        # the minimum supported window height.
        self.scroll = ScrollableFrame(self, padding=18)
        self.shell = self.scroll.body
        self.figure = Figure(figsize=(10.5, 5.2), dpi=100, facecolor=COLORS["surface"])
        self.axis = self.figure.add_subplot(111)
        self.contour_axis = None
        self.panel: FigurePanel | None = None
        self.circuit_tree: ttk.Treeview | None = None
        self.channel_geometry_tree: ttk.Treeview | None = None
        self.axial_tree: ttk.Treeview | None = None
        self.smooth = tk.BooleanVar(self, value=False)
        self._temperature_data_bounds: tuple[float, float] | None = None
        self._contour_radius_max = 0.0

    def set_result(self, data: dict[str, Any]) -> None:
        super().set_result(data)
        self.empty.pack_forget()
        for child in self.shell.winfo_children():
            child.destroy()
        self.circuit_tree = None
        self.channel_geometry_tree = None
        self.axial_tree = None
        self.panel = None
        self.scroll.pack(fill="both", expand=True)
        self.scroll.scroll_to_top()
        thermal = _get(data, "thermal", default={})
        sections = int(_number(_get(thermal, "section_count", "mesh_count", default=0), 0))
        resolution = _get(thermal, "resolution", default="Medium")
        header = self._header(
            self.shell,
            self.title,
            f"Bartz-based conjugate result · {resolution} density · {sections} axial sections",
        )
        toolbar = ttk.Frame(header, style="Surface.TFrame")
        toolbar.pack(side="right", anchor="e")
        ttk.Checkbutton(toolbar, text="Smooth curves", variable=self.smooth, command=self._draw).pack(side="left")
        export_button = ttk.Button(toolbar, text="Export all stations…", command=self._export_all_stations)
        export_button.pack(side="left", padx=(8, 0))
        if not data.get("thermal_enabled", bool(thermal.get("section_count"))):
            export_button.state(["disabled"])
        self._result_diagnostics(self.shell, data)
        if not _get(data, "thermal_enabled", default=bool(_mapping(thermal))):
            ttk.Label(
                self.shell,
                text="Thermal analysis was disabled for this run. Enable it under Input → Thermal Analysis.",
                style="Warning.TLabel",
            ).pack(fill="x", pady=(8, 0))
            return
        summary = ttk.Frame(self.shell, style="Surface.TFrame")
        summary.pack(fill="x", pady=(0, 9))
        converged = bool(_get(thermal, "converged", default=True))
        iterations = int(_number(_get(thermal, "iterations", default=0), 0))
        solved, total = _thermal_station_completion(thermal)
        numerical_text = ("No wall iterations performed" if not solved and not iterations
                          else "Numerically converged" if converged else "Numerical iteration did not converge")
        numerical_label = ttk.Label(
            summary,
            text=numerical_text + f" · {iterations} max station iterations",
            style="Badge.TLabel" if converged else "Warning.TLabel",
        )
        numerical_label.pack(side="left", fill="x", expand=True)
        summary.bind("<Configure>", lambda event: numerical_label.configure(
            wraplength=max(140, (event.width - 20) // 2)), add="+")
        completion = ttk.Label(self.shell,
                               text=f"Solved wall stations {solved}/{total} · Unsolved {total - solved}",
                               style="Badge.TLabel" if solved == total and total else "Warning.TLabel")
        completion.pack(fill="x", pady=(0, 9))
        completion_details = _thermal_completion_details(thermal)
        march_text = "Wall solution complete" if completion_details["wall_solution_complete"] else "Wall solution incomplete"
        if completion_details["unsupported_station_count"] is not None:
            march_text += f" · Unsupported stations {completion_details['unsupported_station_count']}"
        incomplete_marches = completion_details["incomplete_regen_segment_ids"]
        if incomplete_marches:
            march_text += " · Regen march incomplete: " + ", ".join(incomplete_marches)
        march_label = ttk.Label(self.shell, text=march_text, wraplength=700,
                               style="Warning.TLabel" if incomplete_marches or not completion_details["wall_solution_complete"]
                               else "Badge.TLabel")
        march_label.pack(fill="x", pady=(0, 9))
        march_label.bind("<Configure>", lambda event: march_label.configure(
            wraplength=max(120, event.width - 12)), add="+")
        phase_counts = _coolant_phase_counts(thermal)
        if phase_counts.get("unknown"):
            phase_note = ttk.Label(self.shell,
                                  text=f"Coolant property phase unknown at {phase_counts['unknown']} stations; "
                                       "a convection correlation does not verify the physical phase.",
                                  style="Warning.TLabel", wraplength=700)
            phase_note.pack(fill="x", pady=(0, 9))
            phase_note.bind("<Configure>", lambda event: phase_note.configure(
                wraplength=max(120, event.width - 12)), add="+")
        hot_wall = _array(thermal, "twg_k", "Twg_K", "Twg")
        finite_hot_wall = hot_wall[np.isfinite(hot_wall)]
        if len(finite_hot_wall):
            diagnostic_wall = (_get(thermal, "physical_validity", default="") in {"unsupported", "invalid"}
                               or bool(phase_counts.get("unknown")))
            maximum_title = "Diagnostic maximum wall Twg" if diagnostic_wall else "Maximum inner wall Twg"
            maximum_label = ttk.Label(
                summary,
                text=f"{maximum_title}  {float(np.max(finite_hot_wall)):.2f} K",
                style="Warning.TLabel" if diagnostic_wall else "Badge.TLabel",
            )
            maximum_label.pack(side="right", fill="x", expand=True)
            summary.bind("<Configure>", lambda event: maximum_label.configure(
                wraplength=max(140, (event.width - 20) // 2)), add="+")
        inlets = _mapping(_get(thermal, "coolant_inlet_temperature_k", default={}))
        outlets = _mapping(_get(thermal, "coolant_outlet_temperature_k", default={}))
        pressure_inlets = _mapping(_get(thermal, "coolant_inlet_pressure_bar", default={}))
        pressure_outlets = _mapping(_get(thermal, "coolant_outlet_pressure_bar", default={}))
        pressure_drops = _mapping(_get(thermal, "coolant_pressure_drop_bar", default={}))
        coolant_names = _mapping(
            _get(
                thermal,
                "segment_coolants",
                "metadata.coolant_identity_by_segment",
                default={},
            )
        )
        if outlets:
            names = _mapping(_get(thermal, "segment_names", default={}))
            circuit_box = ttk.LabelFrame(self.shell, text="  Regenerative coolant circuits  ", padding=(9, 7))
            circuit_box.pack(fill="x", pady=(0, 9))
            columns = (
                "Segment",
                "Coolant / propellant",
                "Inlet temperature",
                "Outlet temperature",
                "Temperature rise",
                "Inlet pressure",
                "Outlet pressure",
                "Pressure drop",
            )
            circuit_tree = ttk.Treeview(
                circuit_box,
                columns=columns,
                show="headings",
                height=max(1, min(5, len(outlets))),
            )
            self.circuit_tree = circuit_tree
            circuit_tree.pack(fill="x")
            heading_text = {
                "Segment": "Segment",
                "Coolant / propellant": "Coolant / propellant",
                "Inlet temperature": "Inlet T (K)",
                "Outlet temperature": "Outlet T (K)",
                "Temperature rise": "ΔT (K)",
                "Inlet pressure": "Inlet p (bar)",
                "Outlet pressure": "Outlet p (bar)",
                "Pressure drop": "Δp (bar)",
            }
            for column, width in zip(columns, (90, 130, 80, 85, 75, 85, 90, 85)):
                circuit_tree.heading(column, text=heading_text[column])
                circuit_tree.column(
                    column,
                    width=width,
                    anchor="w" if column in {"Segment", "Coolant / propellant"} else "e",
                )
            for identifier, outlet in outlets.items():
                inlet = _number(inlets.get(identifier, math.nan))
                outlet_value = _number(outlet)
                inlet_pressure = _number(pressure_inlets.get(identifier, math.nan))
                outlet_pressure = _number(pressure_outlets.get(identifier, math.nan))
                pressure_drop = _number(pressure_drops.get(identifier, math.nan))

                def pressure_text(value: float) -> str:
                    return f"{value:.3f} bar" if math.isfinite(value) else "—"

                circuit_tree.insert(
                    "",
                    "end",
                    values=(
                        names.get(identifier, identifier),
                        coolant_names.get(identifier, "—"),
                        f"{inlet:.2f} K",
                        f"{outlet_value:.2f} K",
                        f"{outlet_value - inlet:+.2f} K",
                        pressure_text(inlet_pressure),
                        pressure_text(outlet_pressure),
                        pressure_text(pressure_drop),
                    ),
                )
            fit_tree_columns(circuit_tree)
        angle_geometry = _mapping(
            _get(
                thermal,
                "metadata.angle_channel_geometry_by_segment",
                "angle_channel_geometry_by_segment",
                default={},
            )
        )
        if angle_geometry:
            names = _mapping(_get(thermal, "segment_names", default={}))
            geometry_box = ttk.LabelFrame(
                self.shell,
                text="  Occupied-angle channel geometry  ",
                padding=(9, 7),
            )
            geometry_box.pack(fill="x", pady=(0, 9))
            columns = ("Segment", "a1", "a min", "a2", "b1", "b min", "b2")
            tree = ttk.Treeview(
                geometry_box,
                columns=columns,
                show="headings",
                height=max(1, min(5, len(angle_geometry))),
            )
            self.channel_geometry_tree = tree
            tree.pack(fill="x")
            headings = {
                "Segment": "Segment",
                "a1": "Channel a1 (mm)",
                "a min": "Channel a min (mm)",
                "a2": "Channel a2 (mm)",
                "b1": "Rib b1 (mm)",
                "b min": "Rib b min (mm)",
                "b2": "Rib b2 (mm)",
            }
            for column, width in zip(columns, (110, 96, 110, 96, 86, 100, 86)):
                tree.heading(column, text=headings[column])
                tree.column(column, width=width, anchor="w" if column == "Segment" else "e")
            for identifier, raw_geometry in angle_geometry.items():
                geometry = _mapping(raw_geometry)
                channel_widths = tuple(geometry.get("channel_width_mm", ()))
                rib_widths = tuple(geometry.get("rib_width_mm", ()))
                if len(channel_widths) != 3 or len(rib_widths) != 3:
                    continue
                tree.insert(
                    "",
                    "end",
                    values=(
                        names.get(identifier, identifier),
                        *(f"{_number(value):.4f}" for value in channel_widths),
                        *(f"{_number(value):.4f}" for value in rib_widths),
                    ),
                )
            fit_tree_columns(tree)
        orifices = _get(thermal, "film_orifices", default=[])
        if orifices:
            orifice_box = ttk.LabelFrame(self.shell, text="  Film orifice sizing  ", padding=(10, 7))
            orifice_box.pack(fill="x", pady=(0, 9))
            for row in orifices:
                mapping = _mapping(row)
                text = (
                    f"{mapping.get('name', 'Film')}: Ø {_number(mapping.get('diameter_mm')):.4f} mm × "
                    f"{int(_number(mapping.get('orifice_count'), 0))}  ·  Δp {_number(mapping.get('pressure_drop_bar')):.3f} bar  ·  "
                    f"ṁ {_number(mapping.get('mass_flow_kg_s')):.6f} kg/s"
                )
                model = str(mapping.get("model", "Model not reported"))
                choking = ("yes" if mapping.get("choked") else "no") if model.startswith("compressible") else "not applicable"
                lines = (
                    text,
                    f"Model: {model} · applicability: {mapping.get('physical_validity', 'not assessed')}",
                    f"Regen outlet: {_display_number(mapping.get('temperature_k'), 2)} K, "
                    f"{_display_number(mapping.get('upstream_pressure_bar'), 3)} bar(a) · "
                    f"local gas: {_display_number(mapping.get('gas_pressure_bar'), 3)} bar(a) · "
                    f"phase: {mapping.get('phase', 'not reported')} · choked: {choking}",
                )
                for line in lines:
                    label = ttk.Label(orifice_box, text=line, style="Surface.TLabel", wraplength=700)
                    label.pack(fill="x", pady=(0, 3))
                    label.bind("<Configure>", lambda event, item=label:
                               item.configure(wraplength=max(120, event.width - 8)), add="+")
            note = ttk.Label(orifice_box,
                text="Uses the linked Regen outlet state and local injection gas pressure. "
                     "Film is an independent stream; the link supplies state only. Additional feed-line losses are not modeled.",
                style="Muted.TLabel", wraplength=700)
            note.pack(fill="x", pady=(2, 0))
            note.bind("<Configure>", lambda event: note.configure(wraplength=max(120, event.width - 8)), add="+")
        self.panel = FigurePanel(self.shell, self.figure)
        self.panel.pack(fill="x")
        self.panel.canvas.mpl_connect("resize_event", self._on_figure_resize)
        self._draw()
        self._build_axial_table(thermal)

    def _export_all_stations(self) -> None:
        if not self.data:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export all thermal stations",
                                          defaultextension=".csv", initialfile="thermal-all-stations.csv",
                                          filetypes=(("CSV table", "*.csv"),))
        if not path:
            return
        try:
            self.export_all_stations(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export thermal stations", str(exc), parent=self)

    def export_all_stations(self, path: str | Path) -> None:
        """Export unfiltered stations with numerical/physical status and warnings."""
        thermal = _mapping(_get(self.data or {}, "thermal", default={}))
        x = _array(thermal, "x_mm", "x")
        fields = {"radius_mm": ("radius_mm",), "heat_flux_w_m2": ("heat_flux_w_m2",),
                  "twg_k": ("twg_k", "Twg_K"), "twi_k": ("twi_k", "Twi_K"),
                  "twc_k": ("twc_k", "Twc_K"), "tc_k": ("tc_k", "Tc_K"),
                  "coolant_pressure_bar": ("coolant_pressure_bar",),
                  "coolant_velocity_m_s": ("coolant_velocity_m_s",),
                  "coolant_density_kg_m3": ("coolant_density_kg_m3",),
                  "coolant_reynolds": ("coolant_reynolds",),
                  "coolant_nusselt": ("coolant_nusselt",),
                  "coolant_raw_coefficient_w_m2k": ("coolant_raw_coefficient_w_m2k",),
                  "coolant_vapor_quality": ("coolant_vapor_quality",),
                  "gas_coefficient_w_m2k": ("gas_coefficient_w_m2k",),
                  "coolant_coefficient_w_m2k": ("coolant_coefficient_w_m2k",),
                  "film_effectiveness": ("film_effectiveness",)}
        arrays = {key: _array(thermal, *paths) for key, paths in fields.items()}
        arrays["coolant_vapor_quality"] = _coolant_quality_array(thermal)
        phases = thermal.get("coolant_phase", [])
        regimes = thermal.get("coolant_flow_regime", [])
        applicability = thermal.get("station_applicability", [])
        active = thermal.get("active_segment_id", [])
        warnings = " | ".join(self.report_warnings)
        metadata = _mapping(thermal.get("metadata"))
        source_keys = ("model_capabilities", "coolant_property_sources", "coolant_property_metadata", "material_references", "gas_state_source",
                       "gas_side_model", "coolant_side_model", "wall_model", "radiation_model", "film_model",
                       "two_phase_model", "two_phase_model_by_segment", "regen_segment_completion")
        sources = json.dumps({key: metadata[key] for key in source_keys if key in metadata},
                             ensure_ascii=False, default=str)
        hot_wall = _array(thermal, "twg_k", "Twg_K", "Twg")
        completion = _thermal_completion_details(thermal)
        segment_completion = _mapping(metadata.get("regen_segment_completion"))
        keys = ["station_index", "x_mm", *fields, "active_segment_id", "coolant_phase", "coolant_flow_regime",
                "station_applicability", "wall_solution_available", "wall_solution_complete",
                "solved_wall_station_count", "requested_wall_station_count", "unsupported_station_count",
                "segment_solved_wall_stations", "segment_requested_wall_stations", "segment_wall_march_completed",
                "numerically_converged", "physical_validity", "warnings", "model_and_property_sources"]
        with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=keys)
            writer.writeheader()
            for index, position in enumerate(x):
                identifier = active[index] if len(active) == len(x) else ""
                segment = _mapping(segment_completion.get(identifier))
                row = {"station_index": index, "x_mm": float(position),
                       "active_segment_id": identifier,
                       "coolant_phase": phases[index] if len(phases) == len(x) else "",
                       "coolant_flow_regime": regimes[index] if len(regimes) == len(x) else "",
                       "station_applicability": applicability[index] if len(applicability) == len(x) else "",
                       "wall_solution_available": len(hot_wall) == len(x) and math.isfinite(float(hot_wall[index])),
                       **{key: completion[key] for key in ("wall_solution_complete", "solved_wall_station_count",
                                                          "requested_wall_station_count", "unsupported_station_count")},
                       "segment_solved_wall_stations": segment.get("solved_wall_stations", ""),
                       "segment_requested_wall_stations": segment.get("requested_wall_stations", ""),
                       "segment_wall_march_completed": segment.get("wall_march_completed", ""),
                       "numerically_converged": thermal.get("converged", ""),
                       "physical_validity": thermal.get("physical_validity", "not_assessed"), "warnings": warnings,
                       "model_and_property_sources": sources}
                row.update({key: float(values[index]) if len(values) == len(x) and math.isfinite(float(values[index])) else ""
                            for key, values in arrays.items()})
                writer.writerow(row)

    @staticmethod
    def _representative_indices(count: int, limit: int = 30) -> list[int]:
        """Return deterministic, endpoint-preserving indices for a report."""

        if count <= 0:
            return []
        if count <= limit:
            return list(range(count))
        return [round(index * (count - 1) / (limit - 1)) for index in range(limit)]

    def _build_axial_table(self, thermal: Any) -> None:
        x = _array(thermal, "x_mm", "x")
        indices = self._representative_indices(len(x))
        if not indices:
            return
        table_box = ttk.LabelFrame(
            self.shell,
            text=f"  Axial thermal and coolant data · {len(indices)} representative stations  ",
            padding=(9, 7),
        )
        table_box.pack(fill="x", pady=(10, 0))
        columns = ("x", "q", "Twg", "Twi", "Twc", "Tc", "pc", "wc", "rho", "Re", "Nu", "hc_raw",
                   "applicability", "phase", "quality", "regime")
        headings = {
            "x": "Axial x (mm)",
            "q": "Heat flux (MW/m²)",
            "Twg": "Twg (K)",
            "Twi": "Twi (K)",
            "Twc": "Twc (K)",
            "Tc": "Tc (K)",
            "pc": "pc (bar)",
            "wc": "wc (m/s)",
            "rho": "rho (kg/m³)",
            "Re": "Coolant Re",
            "Nu": "Coolant Nu",
            "hc_raw": "Raw hc (W/m²K)",
            "applicability": "Station applicability",
            "phase": "Property phase",
            "quality": "Vapor x (0–1)",
            "regime": "HT correlation / regime",
        }
        tree = ttk.Treeview(
            table_box,
            columns=columns,
            show="headings",
            height=len(indices),
        )
        self.axial_tree = tree
        tree.pack(fill="x")
        horizontal = ttk.Scrollbar(table_box, orient="horizontal", command=tree.xview)
        horizontal.pack(fill="x")
        tree.configure(xscrollcommand=horizontal.set)
        scale = float(tree.tk.call("tk", "scaling")) / (96.0 / 72.0)
        for column, base_width in zip(columns, (82, 124, 76, 76, 76, 76, 85, 85, 96, 100, 100, 130, 155, 116, 100, 210)):
            width = max(1, round(base_width * scale))
            tree.heading(column, text=headings[column])
            tree.column(column, width=width, minwidth=width, stretch=False,
                        anchor="w" if column in {"phase", "regime", "applicability"} else "e")

        arrays = {
            "q": _array(thermal, "heat_flux_w_m2"),
            "Twg": _array(thermal, "twg_k", "Twg_K", "Twg"),
            "Twi": _array(thermal, "twi_k", "Twi_K", "Twi"),
            "Twc": _array(thermal, "twc_k", "Twc_K", "Twc"),
            "Tc": _array(thermal, "tc_k", "Tc_K", "Tc"),
            "pc": _array(thermal, "coolant_pressure_bar"),
            "wc": _array(thermal, "coolant_velocity_m_s"),
            "rho": _array(thermal, "coolant_density_kg_m3"),
            "Re": _array(thermal, "coolant_reynolds"),
            "Nu": _array(thermal, "coolant_nusselt"),
            "hc_raw": _array(thermal, "coolant_raw_coefficient_w_m2k"),
            "quality": _coolant_quality_array(thermal),
        }
        regimes = _get(thermal, "coolant_flow_regime", default=[]) or []
        phases = _get(thermal, "coolant_phase", default=[]) or []
        applicability = _get(thermal, "station_applicability", default=[]) or []

        def value_at(key: str, index: int) -> float:
            values = arrays[key]
            return float(values[index]) if len(values) == len(x) else math.nan

        def display(value: float, decimals: int) -> str:
            return f"{value:.{decimals}f}" if math.isfinite(value) else "—"

        for index in indices:
            heat_flux = value_at("q", index)
            tree.insert(
                "",
                "end",
                values=(
                    f"{x[index]:.3f}",
                    display(heat_flux / 1.0e6, 4),
                    display(value_at("Twg", index), 2),
                    display(value_at("Twi", index), 2),
                    display(value_at("Twc", index), 2),
                    display(value_at("Tc", index), 2),
                    display(value_at("pc", index), 3),
                    display(value_at("wc", index), 3),
                    display(value_at("rho", index), 2),
                    display(value_at("Re", index), 1),
                    display(value_at("Nu", index), 3),
                    display(value_at("hc_raw", index), 2),
                    str(applicability[index]) if len(applicability) == len(x) and applicability[index] else "—",
                    str(phases[index]) if len(phases) == len(x) and phases[index] else "—",
                    display(value_at("quality", index), 4),
                    str(regimes[index]) if len(regimes) == len(x) and regimes[index] else "—",
                ),
            )

    def _smooth_values(self, values: np.ndarray) -> np.ndarray:
        if not self.smooth.get() or len(values) < 7:
            return values
        result = values.astype(float, copy=True)
        finite = np.isfinite(values)
        start = 0
        while start < len(values):
            while start < len(values) and not finite[start]:
                start += 1
            end = start
            while end < len(values) and finite[end]:
                end += 1
            length = end - start
            if length >= 7:
                window = max(3, min(11, length // 20 * 2 + 1))
                kernel = np.ones(window) / window
                padded = np.pad(values[start:end], (window // 2, window // 2), mode="edge")
                result[start:end] = np.convolve(padded, kernel, mode="valid")
            start = end + 1
        return result

    def _draw(self) -> None:
        if not self.data:
            return
        thermal = _get(self.data, "thermal", default={})
        x = _array(thermal, "x_mm", "x")
        self.figure.clear()
        self._temperature_data_bounds = None
        self._contour_radius_max = 0.0
        # The contour is a transparent twin of the temperature axis.  This is
        # one composite engineering plot: both layers therefore use exactly
        # the same x transform instead of merely sharing nominal x limits.
        self.axis = self.figure.add_subplot(111)
        self.contour_axis = self.axis.twinx()
        for index, (left, right, _identifier) in enumerate(_thermal_two_phase_regions(thermal, x)):
            # This transparent axis sits above the grey contour fill, so the
            # phase highlight stays visible even where the contour overlaps it.
            self.contour_axis.axvspan(left, right, facecolor="#f5b041", edgecolor="#b36a00",
                                     alpha=0.18, linewidth=0.7, hatch="//", zorder=2,
                                     label="Two-phase coolant" if index == 0 else "_nolegend_")
        series = (
            ("Twi", ("twi_k", "Twi_K", "Twi"), "#ff22d3"),
            ("Twg", ("twg_k", "Twg_K", "Twg"), COLORS["plot_hot"]),
            ("Twc", ("twc_k", "Twc_K", "Twc"), "#8a8214"),
        )
        plotted_temperatures: list[np.ndarray] = []
        for label, paths, color in series:
            values = next((_array(thermal, path) for path in paths if len(_array(thermal, path))), np.array([]))
            if len(values) == len(x):
                smoothed = self._smooth_values(values)
                self.axis.plot(x, smoothed, label=label, color=color, linewidth=1.45)
                plotted_temperatures.append(smoothed)
        coolant = next(
            (_array(thermal, path) for path in ("tc_k", "Tc_K", "Tc") if len(_array(thermal, path))),
            np.array([]),
        )
        active = list(_get(thermal, "active_segment_id", default=[]))
        names = _mapping(_get(thermal, "segment_names", default={}))
        segment_types = _mapping(_get(thermal, "segment_types", default={}))
        regen_ids: list[str] = []
        for identifier in active:
            if (
                identifier
                and segment_types.get(str(identifier), "Regen") == "Regen"
                and identifier not in regen_ids
            ):
                regen_ids.append(str(identifier))
        coolant_colors = ("#2667d8", "#1b9e77", "#7b61c9", "#d97706", "#008c95")
        if len(coolant) == len(x) and len(active) == len(x) and regen_ids:
            for index, identifier in enumerate(regen_ids):
                masked = np.asarray(
                    [value if current == identifier else np.nan for value, current in zip(coolant, active)],
                    dtype=float,
                )
                if np.isfinite(masked).any():
                    self.axis.plot(
                        x,
                        masked,
                        label=f"Tc · {names.get(identifier, identifier)}",
                        color=coolant_colors[index % len(coolant_colors)],
                        linewidth=1.45,
                    )
                    plotted_temperatures.append(masked)
        elif len(coolant) == len(x):
            smoothed_coolant = self._smooth_values(coolant)
            self.axis.plot(x, smoothed_coolant, label="Tc", color=COLORS["plot_cool"], linewidth=1.45)
            plotted_temperatures.append(smoothed_coolant)

        # Prefer the radius interpolated onto the thermal mesh.  It has the
        # exact same x stations as every temperature array; older result files
        # fall back to the core contour arrays.
        radius = _array(thermal, "radius_mm")
        contour_x = x if len(radius) == len(x) else np.array([])
        if not len(contour_x):
            radius = _array(self.data, "contour.radius_mm", "geometry.radius_mm")
            contour_x = _array(self.data, "contour.x_mm", "geometry.x_mm")
        if len(radius) and len(radius) == len(contour_x):
            self.contour_axis.plot(contour_x, radius, color=COLORS["plot_contour"], linewidth=1.8)
            self.contour_axis.fill_between(contour_x, 0.0, radius, color="#cbd4da", alpha=0.62)
            self.contour_axis.axhline(0.0, color="#87939d", linewidth=0.55, linestyle="--")
            finite_radius = radius[np.isfinite(radius)]
            if len(finite_radius):
                radius_max = float(np.max(finite_radius))
                self._contour_radius_max = radius_max
                self.contour_axis.set_yticks((0.0, radius_max))
                self.contour_axis.set_yticklabels(("0", f"{radius_max:g}"))
        style_axis(self.axis, xlabel="Axial location, mm", ylabel="Temperature, K", title="Temperature and thrust chamber contour")
        self.contour_axis.set_facecolor("none")
        self.contour_axis.patch.set_visible(False)
        self.contour_axis.grid(False)
        self.contour_axis.tick_params(axis="y", labelsize=8, colors=COLORS["muted"], length=3)
        self.contour_axis.set_ylabel("Radius, mm", fontsize=9, color=COLORS["text"])
        self.contour_axis.spines[["top", "left", "bottom"]].set_visible(False)
        self.contour_axis.spines["right"].set_color(COLORS["border"])
        self.contour_axis.set_zorder(self.axis.get_zorder() + 0.1)
        if plotted_temperatures:
            finite_series = [values[np.isfinite(values)] for values in plotted_temperatures if np.isfinite(values).any()]
            finite_values = np.concatenate(finite_series) if finite_series else np.array([])
            if len(finite_values):
                low = float(np.min(finite_values))
                high = float(np.max(finite_values))
                self._temperature_data_bounds = (low, high)
        injector_x = _get(thermal, "injector_x_mm", default=None)
        throat_x = _get(thermal, "throat_x_mm", "nozzle_throat_x_mm", default=None)
        for value, text in ((injector_x, "Injector"), (throat_x, "Nozzle throat")):
            if value is not None:
                self.axis.axvline(float(value), color=COLORS["success"], linewidth=0.8, linestyle="--")
                self.axis.text(float(value), 0.5, text, color=COLORS["success"], rotation=90, transform=self.axis.get_xaxis_transform(), va="center", fontsize=8)
        lines, labels = self.axis.get_legend_handles_labels()
        phase_handles, phase_labels = self.contour_axis.get_legend_handles_labels()
        lines.extend(phase_handles)
        labels.extend(phase_labels)
        if lines:
            self.axis.legend(lines, labels, loc="upper right", ncol=min(4, len(lines)), frameon=False, fontsize=8)
        self.axis.text(
            0.012,
            0.018,
            "Upper-half contour · true 1:1 x/y engineering scale",
            transform=self.axis.transAxes,
            color=COLORS["muted"],
            fontsize=8,
            zorder=5,
            bbox={"facecolor": COLORS["surface"], "edgecolor": "none", "alpha": 0.82, "pad": 2},
        )
        self.figure.subplots_adjust(left=0.075, right=0.93, top=0.92, bottom=0.12)
        self._sync_contour_scale()
        self._set_temperature_limits()
        if self.panel:
            self.panel.canvas.draw_idle()

    def _sync_contour_scale(self) -> None:
        """Keep contour millimetres equal in x and y without moving its box."""

        if self.contour_axis is None or self.axis is None:
            return
        x_low, x_high = self.axis.get_xlim()
        x_span = x_high - x_low
        position = self.axis.get_position()
        figure_width, figure_height = self.figure.get_size_inches()
        if x_span <= 0 or position.width <= 0 or figure_width <= 0:
            return
        y_span = x_span * (position.height * figure_height) / (position.width * figure_width)
        self.contour_axis.set_ylim(0.0, max(1.0, y_span))
        # ``datalim`` retains the identical twin-axis bounding box.  The
        # manually matched spans make the resulting engineering scale 1:1.
        self.contour_axis.set_aspect("equal", adjustable="datalim")

    def _set_temperature_limits(self) -> None:
        """Anchor the temperature scale at absolute zero with a readable top."""

        if self._temperature_data_bounds is None:
            if self.axis is not None:
                self.axis.set_ylim(0.0, 1.0)
            return
        if self.contour_axis is None:
            return
        low, high = self._temperature_data_bounds
        data_span = max(1.0, high - low)
        # Thermal temperatures are absolute values.  Keeping the lower bound
        # at exactly 0 K makes different runs directly comparable; a modest
        # data-driven headroom preserves legibility without fixing the upper
        # limit.  The true-scale contour remains on its independent twin y
        # axis and is intentionally allowed to overlap the temperature layer.
        upper_padding = max(1.0, data_span * 0.08, high * 0.05)
        self.axis.set_ylim(0.0, max(1.0, high + upper_padding))

    def _on_figure_resize(self, _event: Any) -> None:
        self._sync_contour_scale()
        self._set_temperature_limits()
        if self.panel:
            self.panel.canvas.draw_idle()


THERMO_PROPERTIES = (
    ("pressure_bar", "Pressure", "bar"),
    ("temperature_k", "Temperature", "K"),
    ("enthalpy_kj_kg", "Enthalpy", "kJ/kg"),
    ("entropy_kj_kgk", "Entropy", "kJ/(kg·K)"),
    ("cp_kj_kgk", "Specific heat", "kJ/(kg·K)"),
    ("gamma", "Gamma", "-"),
    ("gas_constant_j_kgk", "Gas constant", "J/(kg·K)"),
    ("density_kg_m3", "Density", "kg/m³"),
    ("sonic_velocity_m_s", "Sonic velocity", "m/s"),
    ("mach", "Mach number", "-"),
    ("mass_flux_kg_m2s", "Mass flux", "kg/(m²·s)"),
    ("viscosity_pa_s", "Viscosity", "Pa·s"),
    ("prandtl", "Prandtl number", "-"),
)


class ThermodynamicsResultsPage(ResultPage):
    title = "Thermodynamics"
    page_description = "CEA station properties and selectable axial distributions from injector to nozzle exit."

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        # Keep the 13-row station table free of an unnecessary internal
        # scrollbar, while allowing the complete table + plot report to remain
        # usable at LPA's minimum window height.
        self.scroll = ScrollableFrame(self, padding=18)
        self.shell = self.scroll.body
        self.property_var = tk.StringVar(self, value="Temperature")

    def set_result(self, data: dict[str, Any]) -> None:
        super().set_result(data)
        self.empty.pack_forget()
        for child in self.shell.winfo_children():
            child.destroy()
        self.scroll.pack(fill="both", expand=True)
        self.scroll.scroll_to_top()
        header = self._header(
            self.shell,
            self.title,
            self.page_description,
        )
        selector = ttk.Frame(header, style="Surface.TFrame")
        selector.pack(side="right")
        ttk.Label(selector, text="Plot", style="Muted.TLabel").pack(side="left", padx=(0, 5))
        combo = ttk.Combobox(
            selector,
            textvariable=self.property_var,
            values=[label for _, label, _ in THERMO_PROPERTIES],
            state="readonly",
            width=18,
        )
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._draw_plot(data))
        self._result_diagnostics(self.shell, data)
        self._build_table(data)
        self.plot_frame = ttk.LabelFrame(self.shell, text="  Axial property plot  ", padding=8)
        self.plot_frame.pack(fill="both", expand=True, pady=(12, 0))
        self._draw_plot(data)

    def _station_dict(self, data: Any) -> dict[str, Any]:
        stations = _get(data, "thermodynamics.stations", "stations", default={})
        if isinstance(stations, list):
            result = {}
            for item in stations:
                mapping = _mapping(item)
                result[str(mapping.get("name", mapping.get("station", len(result))))] = mapping
            return result
        return _mapping(stations)

    def _build_table(self, data: Any) -> None:
        stations = self._station_dict(data)
        canonical = (
            ("Injector", ("Injector", "injector", "chamber")),
            ("Nozzle inlet", ("Nozzle inlet", "nozzle_inlet", "inlet")),
            ("Nozzle throat", ("Nozzle throat", "nozzle_throat", "throat")),
            ("Nozzle exit", ("Nozzle exit", "nozzle_exit", "exit")),
        )
        columns = ("Property", "Unit") + tuple(item[0] for item in canonical)
        frame = ttk.LabelFrame(self.shell, text="  Station properties  ", padding=8)
        frame.pack(fill="x")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=len(THERMO_PROPERTIES))
        tree.pack(fill="both", expand=True)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, anchor="e" if column not in ("Property", "Unit") else "w", width=130, minwidth=70)
        tree.column("Property", width=155)
        tree.column("Unit", width=85)
        for key, label, unit in THERMO_PROPERTIES:
            values: list[str] = []
            for _, aliases in canonical:
                station = next((stations[name] for name in aliases if name in stations), {})
                value = _get(station, key, default=math.nan)
                values.append("—" if not math.isfinite(_number(value)) else f"{_number(value):.6g}")
            tree.insert("", "end", values=(label, unit, *values))
        fit_tree_columns(tree)

    def _draw_plot(self, data: Any) -> None:
        if not hasattr(self, "plot_frame"):
            return
        for child in self.plot_frame.winfo_children():
            child.destroy()
        selected = self.property_var.get()
        key, label, unit = next((item for item in THERMO_PROPERTIES if item[1] == selected), THERMO_PROPERTIES[1])
        axial = _get(data, "thermodynamics.axial", "thermodynamics", default={})
        x = _array(axial, "x_mm", "x")
        values = _array(axial, key)
        if not len(x) or len(values) != len(x):
            ttk.Label(self.plot_frame, text=f"No axial {label.lower()} data are available.", style="Muted.TLabel").pack(pady=30)
            return
        figure = Figure(figsize=(10.4, 4.0), dpi=100, facecolor=COLORS["surface"])
        axis = figure.add_subplot(111)
        axis.plot(x, values, color=COLORS["accent"], linewidth=1.6)
        style_axis(axis, xlabel="Axial location, mm", ylabel=f"{label}, {unit}", title=label)
        figure.tight_layout()
        FigurePanel(self.plot_frame, figure).pack(fill="both", expand=True)


class AmbientConditionPerformancePage(ResultPage):
    title = "Ambient Condition Performance"
    page_description = (
        "Fixed-hardware performance by ambient pressure and U.S. Standard Atmosphere 1976 "
        "altitude (-5 to approximately 86 km)."
    )

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.shell = ttk.Frame(self, style="Surface.TFrame", padding=18)

    @staticmethod
    def _display(value: Any, digits: int) -> str:
        number = _number(value)
        return "—" if not math.isfinite(number) else f"{number:.{digits}f}"

    def set_result(self, data: dict[str, Any]) -> None:
        super().set_result(data)
        self.empty.pack_forget()
        for child in self.shell.winfo_children():
            child.destroy()
        self.shell.pack(fill="both", expand=True)
        self._update_page_context(self.title, self.page_description)
        self._film_display_control(self.shell)
        self._result_diagnostics(self.shell, data)
        pressure_rows = _get(data, "ambient.pressure_rows", default=[])
        altitude_rows = _get(data, "ambient.altitude_rows", default=[])
        pressure_rows = self._select_sweep_rows(pressure_rows) if isinstance(pressure_rows, list) else []
        altitude_rows = self._select_sweep_rows(altitude_rows) if isinstance(altitude_rows, list) else []
        if not pressure_rows and not altitude_rows:
            ttk.Label(
                self.shell,
                text="Ambient-condition analysis was not selected. Enable it under Input → Thrust Chamber.",
                style="Warning.TLabel",
            ).pack(fill="x")
            return

        notebook = ttk.Notebook(self.shell)
        notebook.pack(fill="both", expand=True)
        pressure_tab = ttk.Frame(notebook, style="Surface.TFrame", padding=8)
        altitude_tab = ttk.Frame(notebook, style="Surface.TFrame", padding=8)
        notebook.add(pressure_tab, text="Ambient pressure")
        notebook.add(altitude_tab, text="Standard altitude")
        self._build_pressure_table(pressure_tab, pressure_rows)
        self._build_altitude_table(altitude_tab, altitude_rows)

    def _build_pressure_table(self, parent: ttk.Frame, rows: list[Any]) -> None:
        if not rows:
            ttk.Label(parent, text="No ambient-pressure points are available.", style="Muted.TLabel").pack(pady=30)
            return
        columns = (
            "Ambient atm",
            "Ambient bar",
            "ISA altitude km",
            "Thrust N",
            "Isp s",
            "ṁ kg/s",
            "Cf",
            "Source",
        )
        frame = ttk.Frame(parent, style="Surface.TFrame")
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)
        widths = (95, 95, 105, 105, 90, 100, 80, 130)
        for column, width in zip(columns, widths):
            tree.heading(column, text=column)
            tree.column(column, width=width, minwidth=65, anchor="e")
        tree.column("Source", anchor="w")
        for item in rows:
            row = _mapping(item)
            tree.insert(
                "",
                "end",
                values=(
                    self._display(row.get("ambient_pressure_atm"), 6),
                    self._display(row.get("ambient_pressure_bar"), 6),
                    self._display(row.get("standard_altitude_km"), 3),
                    self._display(row.get("thrust_n"), 4),
                    self._display(row.get("isp_s"), 4),
                    self._display(row.get("mass_flow_kg_s"), 6),
                    self._display(row.get("thrust_coefficient"), 5),
                    str(row.get("status", "OK")),
                ),
            )
        fit_tree_columns(tree)
        ttk.Button(
            parent,
            text="Export CSV…",
            command=lambda: self._export(rows, "ambient-pressure-performance.csv"),
        ).pack(anchor="e", pady=(9, 0))

    def _build_altitude_table(self, parent: ttk.Frame, rows: list[Any]) -> None:
        if not rows:
            ttk.Label(parent, text="No standard-atmosphere points are available.", style="Muted.TLabel").pack(pady=30)
            return
        columns = (
            "Altitude km",
            "Ambient atm",
            "Temperature K",
            "Density kg/m³",
            "Thrust N",
            "Isp s",
            "Cf",
            "Source",
        )
        frame = ttk.Frame(parent, style="Surface.TFrame")
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)
        widths = (100, 95, 105, 110, 105, 90, 80, 130)
        for column, width in zip(columns, widths):
            tree.heading(column, text=column)
            tree.column(column, width=width, minwidth=65, anchor="e")
        tree.column("Source", anchor="w")
        for item in rows:
            row = _mapping(item)
            tree.insert(
                "",
                "end",
                values=(
                    self._display(row.get("standard_altitude_km"), 3),
                    self._display(row.get("ambient_pressure_atm"), 6),
                    self._display(row.get("standard_temperature_k"), 3),
                    self._display(row.get("standard_density_kg_m3"), 6),
                    self._display(row.get("thrust_n"), 4),
                    self._display(row.get("isp_s"), 4),
                    self._display(row.get("thrust_coefficient"), 5),
                    str(row.get("status", "OK")),
                ),
            )
        fit_tree_columns(tree)
        ttk.Button(
            parent,
            text="Export CSV…",
            command=lambda: self._export(rows, "altitude-performance.csv"),
        ).pack(anchor="e", pady=(9, 0))

    def _export(self, rows: list[Any], initialfile: str) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export ambient-condition performance",
            defaultextension=".csv",
            initialfile=initialfile,
            filetypes=(("CSV table", "*.csv"), ("All files", "*.*")),
        )
        if not path:
            return
        mappings = [_mapping(row) for row in rows]
        keys = sorted({key for row in mappings for key in row})
        with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=keys)
            writer.writeheader()
            writer.writerows(mappings)


class ThrottledPerformancePage(ResultPage):
    title = "Throttled Performance"
    page_description = "Performance across requested throttle settings."

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.shell = ttk.Frame(self, style="Surface.TFrame", padding=18)

    def set_result(self, data: dict[str, Any]) -> None:
        super().set_result(data)
        self.empty.pack_forget()
        for child in self.shell.winfo_children():
            child.destroy()
        self.shell.pack(fill="both", expand=True)
        self._update_page_context(self.title, self.page_description)
        self._film_display_control(self.shell)
        self._result_diagnostics(self.shell, data)
        rows = _get(data, "throttle", "throttled_performance", "sweeps.throttle", default=[])
        if isinstance(rows, dict):
            rows = rows.get("rows", [])
        rows = self._select_sweep_rows(rows)
        if not rows:
            ttk.Label(
                self.shell,
                text="Throttle analysis was not selected. Enable it under Input → Thrust Chamber.",
                style="Warning.TLabel",
            ).pack(fill="x")
            return
        columns = ("Throttle %", "Ambient atm", "Pc bar", "Thrust N", "Isp s", "ṁ kg/s", "Cf", "Status")
        frame = ttk.LabelFrame(self.shell, text="  Sweep table  ", padding=8)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)
        widths = (85, 90, 90, 115, 90, 100, 75, 135)
        for column, width in zip(columns, widths):
            tree.heading(column, text=column)
            tree.column(column, width=width, anchor="e", minwidth=65)
        tree.column("Status", anchor="w")
        for item in rows:
            row = _mapping(item)
            tree.insert(
                "",
                "end",
                values=(
                    f"{_number(_get(row, 'throttle_pct', 'throttle', default=0)):.3f}",
                    f"{_number(_get(row, 'ambient_atm', 'ambient_pressure_atm', default=0)):.4f}",
                    f"{_number(_get(row, 'chamber_pressure_bar', 'pc_bar', default=0)):.4f}",
                    _display_number(_get(row, 'thrust_n', 'thrust'), 4),
                    _display_number(_get(row, 'isp_s', 'specific_impulse_s'), 4),
                    _display_number(_get(row, 'mass_flow_kg_s', 'mdot_kg_s'), 6),
                    _display_number(_get(row, 'thrust_coefficient', 'cf'), 5),
                    str(_get(row, "status", default="OK")),
                ),
            )
        fit_tree_columns(tree)
        ttk.Button(self.shell, text="Export CSV…", command=lambda: self._export(rows)).pack(anchor="e", pady=(9, 0))

    def _export(self, rows: list[Any]) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export throttled performance",
            defaultextension=".csv",
            filetypes=(("CSV table", "*.csv"), ("All files", "*.*")),
        )
        if not path:
            return
        mappings = [_mapping(row) for row in rows]
        keys = sorted({key for row in mappings for key in row})
        with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=keys)
            writer.writeheader()
            writer.writerows(mappings)
