"""Main LPA desktop window."""

from __future__ import annotations

import copy
import os
import sys
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from . import __version__
from .analysis import AnalysisService
from .project import (
    DEFAULT_PROJECT_EXTENSION,
    LEGACY_PROJECT_EXTENSIONS,
    load_project,
    make_project,
    save_project,
    validate_project,
)
from .ui.input_views import EngineDefinitionPage, ThermalAnalysisPage, ThrustChamberPage
from .ui.result_views import (
    ChamberResultsPage,
    ThermalResultsPage,
    ThermodynamicsResultsPage,
    ThrottledPerformancePage,
)
from .ui.theme import COLORS, FONT_UI, apply_theme


APP_TITLE = f"LPA {__version__}"


def resource_path(name: str) -> Path:
    """Resolve package resources in source and PyInstaller one-file modes."""

    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / "lpa" / "resources" / name
    return Path(__file__).resolve().parent / "resources" / name


class LPAApplication(tk.Tk):
    """RPA-inspired multipage desktop application."""

    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title(APP_TITLE)
        self.configure(background=COLORS["window"])
        self.geometry("1460x900")
        self.minsize(1080, 700)
        self.window_icon_path = resource_path("logo.ico")
        self.apply_child_icon(self, set_default=True)
        apply_theme(self)
        self._shutdown_started = False
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lpa-analysis")
        self._future: Future[dict[str, Any]] | None = None
        self._project_path: Path | None = None
        self._dirty = False
        self._loading = False
        self._analysis_service = AnalysisService()
        self.pages: dict[str, ttk.Frame] = {}
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.current_page = "engine"
        self._build_menu()
        self._build_layout()
        self._capture_defaults()
        self._attach_change_tracking()
        self.nav_engine_name.configure(
            text=str(self._default_project["engine"].get("engine_name", "Untitled engine"))
        )
        self.show_page("engine")
        self.after(50, self._finish_startup)

    def apply_child_icon(self, toplevel: tk.Toplevel | tk.Tk, *, set_default: bool = False) -> None:
        """Apply the LPA icon to the root window or an application dialog.

        Dialog implementations can call ``master.winfo_toplevel().apply_child_icon(dialog)``
        so source and PyInstaller one-file builds resolve the same bundled icon.
        """

        try:
            toplevel.iconbitmap(str(self.window_icon_path))
            if set_default:
                toplevel.iconbitmap(default=str(self.window_icon_path))
        except (tk.TclError, OSError):
            pass

    def _finish_startup(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu)
        file_menu.add_command(label="New Project", accelerator="Ctrl+N", command=self.new_project)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_project)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Save As…", accelerator="Ctrl+Shift+S", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close)
        menu.add_cascade(label="File", menu=file_menu)
        analysis_menu = tk.Menu(menu)
        analysis_menu.add_command(label="Run Analysis", accelerator="F5", command=self.run_analysis)
        analysis_menu.add_command(label="Clear Results", command=self.clear_results)
        menu.add_cascade(label="Analysis", menu=analysis_menu)
        help_menu = tk.Menu(menu)
        help_menu.add_command(label="Calculation Methods", command=self._show_methods)
        help_menu.add_command(label="About LPA", command=self._show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menu)
        self.bind_all("<Control-n>", lambda _e: self.new_project())
        self.bind_all("<Control-o>", lambda _e: self.open_project())
        self.bind_all("<Control-s>", lambda _e: self.save_project())
        self.bind_all("<Control-Shift-S>", lambda _e: self.save_project_as())
        self.bind_all("<F5>", lambda _e: self.run_analysis())

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_navigation()
        self._build_header()
        self.content = ttk.Frame(self, style="Surface.TFrame")
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self._build_pages()
        self._build_status_bar()

    def _build_navigation(self) -> None:
        nav = ttk.Frame(self, style="Nav.TFrame", width=238)
        nav.grid(row=0, column=0, rowspan=3, sticky="nsew")
        nav.grid_propagate(False)
        brand = ttk.Frame(nav, style="Nav.TFrame", padding=(17, 18, 12, 13))
        brand.pack(fill="x")
        titles = ttk.Frame(brand, style="Nav.TFrame")
        titles.pack(fill="x", expand=True)
        ttk.Label(titles, text="LPA", style="NavBrand.TLabel").pack(anchor="w")
        ttk.Label(titles, text="PROPULSION ANALYSIS", style="NavCaption.TLabel").pack(anchor="w")
        ttk.Separator(nav).pack(fill="x", padx=14, pady=(0, 11))
        self._nav_group(nav, "INPUT", (
            ("engine", "01  Engine Definition"),
            ("chamber", "02  Thrust Chamber"),
            ("thermal_input", "03  Thermal Analysis"),
        ))
        ttk.Separator(nav).pack(fill="x", padx=14, pady=11)
        self._nav_group(nav, "RESULTS", (
            # Keep navigation prefixes inside the Windows/Tk core font set.
            # Several mathematical Unicode symbols used here previously became
            # tofu boxes when ttk switched font fallback in the active state.
            ("size_result", "01  Thrust Chamber Size"),
            ("thermal_result", "02  Thermal Analysis"),
            ("thermo_result", "03  Thermodynamics"),
            ("throttle_result", "04  Throttled Performance"),
        ))
        spacer = ttk.Frame(nav, style="Nav.TFrame")
        spacer.pack(fill="both", expand=True)
        self.nav_engine_name = ttk.Label(nav, text="No project", style="NavCaption.TLabel", wraplength=200)
        self.nav_engine_name.pack(anchor="w", padx=17, pady=(0, 4))
        ttk.Label(nav, text=f"LPA {__version__}", style="NavCaption.TLabel").pack(anchor="w", padx=17, pady=(0, 16))

    def _nav_group(self, parent: ttk.Frame, title: str, items: tuple[tuple[str, str], ...]) -> None:
        ttk.Label(parent, text=title, style="NavGroup.TLabel").pack(anchor="w", padx=17, pady=(0, 4))
        for key, label in items:
            button = ttk.Button(parent, text=label, style="Nav.TButton", command=lambda item=key: self.show_page(item))
            button.pack(fill="x")
            self.nav_buttons[key] = button

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 8))
        header.grid(row=0, column=1, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        context = ttk.Frame(header, style="Header.TFrame")
        context.grid(row=0, column=0, sticky="ew", padx=(0, 18))
        self.context_title = ttk.Label(context, text="Engine Definition", style="Section.TLabel")
        self.context_title.pack(anchor="w")
        self.context_description = ttk.Label(
            context,
            text="",
            style="Subtitle.TLabel",
            wraplength=560,
        )
        self.context_description.pack(anchor="w", pady=(2, 0))
        actions = ttk.Frame(header, style="Header.TFrame")
        actions.grid(row=0, column=1, sticky="e")
        self.header_actions = actions
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=130)
        self.run_button = ttk.Button(actions, text="▶  Run Analysis", style="Primary.TButton", command=self.run_analysis)
        self.run_button.pack(side="right")
        ttk.Button(actions, text="Save", command=self.save_project).pack(side="right", padx=(0, 8))
        header.bind(
            "<Configure>",
            lambda event: self.context_description.configure(
                wraplength=max(280, event.width - self.header_actions.winfo_reqwidth() - 78)
            ),
            add="+",
        )

    def _build_pages(self) -> None:
        page_types: dict[str, type[ttk.Frame]] = {
            "engine": EngineDefinitionPage,
            "chamber": ThrustChamberPage,
            "thermal_input": ThermalAnalysisPage,
            "size_result": ChamberResultsPage,
            "thermal_result": ThermalResultsPage,
            "thermo_result": ThermodynamicsResultsPage,
            "throttle_result": ThrottledPerformancePage,
        }
        for key, page_type in page_types.items():
            page = page_type(self.content)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page

    def _build_status_bar(self) -> None:
        status = ttk.Frame(self, style="Alt.TFrame", padding=(12, 5))
        status.grid(row=2, column=1, sticky="ew")
        status.grid_columnconfigure(0, weight=1)
        self.status_text = tk.StringVar(self, value="Ready")
        ttk.Label(status, textvariable=self.status_text, style="Subtitle.TLabel").grid(row=0, column=0, sticky="w")
        self.backend_text = ttk.Label(
            status,
            text=self._analysis_service.backend_description,
            style="Subtitle.TLabel",
        )
        self.backend_text.grid(row=0, column=1, sticky="e")

    def _capture_defaults(self) -> None:
        self._default_project = copy.deepcopy(self.collect_project())

    def _attach_change_tracking(self) -> None:
        for key in ("engine", "chamber", "thermal_input"):
            page = self.pages[key]
            for variable in getattr(page, "variables", {}).values():
                variable.trace_add("write", self._on_change)
        engine_page = self.pages["engine"]
        getattr(engine_page, "description").bind("<<Modified>>", self._on_text_modified, add="+")

    def _on_change(self, *_args: Any) -> None:
        if not self._loading:
            self._set_dirty(True)
        try:
            engine_name = str(getattr(self.pages["engine"], "variables")["engine_name"].get())
            self.nav_engine_name.configure(text=engine_name or "Untitled engine")
        except (KeyError, tk.TclError):
            pass

    def _on_text_modified(self, event: tk.Event) -> None:
        widget = event.widget
        if widget.edit_modified():
            if not self._loading:
                self._set_dirty(True)
            widget.edit_modified(False)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        # Project state remains available to save/discard handling, but the
        # native window chrome deliberately exposes only the product/version.
        self.title(APP_TITLE)

    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        self.current_page = key
        page = self.pages[key]
        page.tkraise()
        title = str(getattr(page, "page_title", getattr(page, "title", "LPA")))
        description = str(
            getattr(page, "current_subtitle", getattr(page, "page_description", ""))
        )
        self.set_page_context(title, description)
        for item, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if item == key else "Nav.TButton")
        if hasattr(page, "scroll_to_top"):
            page.scroll_to_top()  # type: ignore[attr-defined]

    def set_page_context(self, title: str, description: str = "") -> None:
        """Update the compact page context shown beside the global actions."""

        self.context_title.configure(text=title)
        self.context_description.configure(text=description)

    def collect_project(self) -> dict[str, Any]:
        return make_project(
            getattr(self.pages["engine"], "values")(),
            getattr(self.pages["chamber"], "values")(),
            getattr(self.pages["thermal_input"], "values")(),
        )

    def load_project_data(self, project: dict[str, Any]) -> None:
        self._loading = True
        try:
            getattr(self.pages["engine"], "load_values")(project["engine"])
            getattr(self.pages["chamber"], "load_values")(project["thrust_chamber"])
            getattr(self.pages["thermal_input"], "load_values")(project["thermal"])
            refresh = getattr(self.pages["chamber"], "_refresh_states", None)
            if refresh:
                refresh()
        finally:
            self._loading = False
        self.nav_engine_name.configure(text=project["engine"].get("engine_name", "Untitled engine"))
        self.clear_results()
        self._set_dirty(False)

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self._project_path = None
        self.load_project_data(copy.deepcopy(self._default_project))
        self.show_page("engine")
        self.status_text.set("New project")

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Open LPA project",
            filetypes=(
                ("LPA project", f"*{DEFAULT_PROJECT_EXTENSION}"),
                ("Legacy LPA project", f"*{LEGACY_PROJECT_EXTENSIONS[0]}"),
                ("JSON file", f"*{LEGACY_PROJECT_EXTENSIONS[1]}"),
                ("All files", "*.*"),
            ),
        )
        if not path:
            return
        try:
            project = load_project(path)
            self._project_path = Path(path)
            self.load_project_data(project)
            self.status_text.set(f"Opened {self._project_path.name}")
        except Exception as exc:
            messagebox.showerror("Open project", f"The project could not be opened.\n\n{exc}", parent=self)

    def save_project(self) -> bool:
        if self._project_path is None:
            return self.save_project_as()
        try:
            save_project(self._project_path, self.collect_project())
            self._set_dirty(False)
            self.status_text.set(f"Saved {self._project_path.name}")
            return True
        except Exception as exc:
            messagebox.showerror("Save project", f"The project could not be saved.\n\n{exc}", parent=self)
            return False

    def save_project_as(self) -> bool:
        if self._project_path is None:
            initialfile = f"engine{DEFAULT_PROJECT_EXTENSION}"
        else:
            initialfile = self._project_path.name
            legacy_lpa_extension = LEGACY_PROJECT_EXTENSIONS[0]
            if initialfile.lower().endswith(legacy_lpa_extension):
                initialfile = f"{initialfile[:-len(legacy_lpa_extension)]}{DEFAULT_PROJECT_EXTENSION}"
            elif not initialfile.lower().endswith(DEFAULT_PROJECT_EXTENSION):
                initialfile = f"{Path(initialfile).stem}{DEFAULT_PROJECT_EXTENSION}"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save LPA project",
            defaultextension=DEFAULT_PROJECT_EXTENSION,
            initialfile=initialfile,
            filetypes=(("LPA project", f"*{DEFAULT_PROJECT_EXTENSION}"), ("All files", "*.*")),
        )
        if not path:
            return False
        self._project_path = Path(path)
        return self.save_project()

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved project",
            "Save changes before continuing?",
            parent=self,
        )
        if answer is None:
            return False
        return self.save_project() if answer else True

    def run_analysis(self) -> None:
        if self._future and not self._future.done():
            return
        project = self.collect_project()
        issues = validate_project(project)
        if issues:
            first = issues[0]
            target = {"engine": "engine", "thrust_chamber": "chamber", "thermal": "thermal_input"}.get(first.page, "engine")
            self.show_page(target)
            detail = "\n".join(f"• {issue.message}" for issue in issues[:12])
            if len(issues) > 12:
                detail += f"\n• …and {len(issues) - 12} more"
            messagebox.showerror("Input validation", f"Correct the following input values:\n\n{detail}", parent=self)
            self.status_text.set(f"Validation failed: {len(issues)} issue(s)")
            return
        self.run_button.state(["disabled"])
        self.progress.pack(side="right", padx=(0, 12))
        self.progress.start(9)
        self.status_text.set("Running propulsion and thermal analysis…")
        self._future = self._executor.submit(self._analysis_service.analyze, project)
        self.after(80, self._poll_analysis)

    def _poll_analysis(self) -> None:
        if not self._future:
            return
        if not self._future.done():
            self.after(80, self._poll_analysis)
            return
        self.progress.stop()
        self.progress.pack_forget()
        self.run_button.state(["!disabled"])
        try:
            result = self._future.result()
        except Exception as exc:
            self.status_text.set("Analysis failed")
            messagebox.showerror(
                "Analysis failed",
                f"LPA could not complete the calculation.\n\n{type(exc).__name__}: {exc}",
                parent=self,
            )
            self._future = None
            return
        self._future = None
        for key in ("size_result", "thermal_result", "thermo_result", "throttle_result"):
            getattr(self.pages[key], "set_result")(result)
        method = result.get("method", self._analysis_service.backend_description)
        self.backend_text.configure(text=str(method))
        self.status_text.set("Analysis complete")
        self.show_page("size_result")

    def clear_results(self) -> None:
        for key in ("size_result", "thermal_result", "thermo_result", "throttle_result"):
            getattr(self.pages[key], "clear")()
        self.status_text.set("Results cleared")

    def _show_methods(self) -> None:
        text = (
            "LPA calculation methods\n\n"
            "• Combustion/performance: RocketCEA equilibrium chemistry where supported.\n"
            "• Frozen flow: RocketCEA frozen-at-throat approximation with the requested criterion recorded.\n"
            "• Contour: circular-arc convergent, conical or Rao-style parabolic divergent.\n"
            "• Hot-gas heat transfer: Bartz correlation with local area/Mach correction.\n"
            "• Regenerative cooling: 1-D wall/TBC conduction, internal forced convection and coolant energy balance.\n"
            "• Radiation: gray-body outer-surface balance. Film cooling is treated as a boundary-layer correction.\n\n"
            "Method basis: RPA — Design Tool for Liquid Rocket Engine Analysis; Thermal Analysis of Thrust Chambers; RPA 4 User Manual."
        )
        messagebox.showinfo("Calculation methods", text, parent=self)

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About LPA",
            f"LGJ Propulsion Analysis\nVersion {__version__}\n\nLiquid rocket thrust chamber sizing, performance, thermodynamics, and thermal analysis.\n\n© LGJ",
            parent=self,
        )

    def _close(self) -> None:
        if self._future and not self._future.done():
            if not messagebox.askyesno("Analysis running", "An analysis is still running. Exit LPA?", parent=self):
                return
        if not self._confirm_discard():
            return
        self._shutdown_immediately()

    def _shutdown_immediately(self) -> None:
        """Release application resources exactly once, without user prompts."""

        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        try:
            if self.winfo_exists():
                self.destroy()
        except tk.TclError:
            # The Tcl interpreter may already be gone after an external stop.
            pass


def run() -> None:
    app = LPAApplication()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        # VS Code Code Runner and Ctrl+C interrupt Tk's blocking mainloop.
        # Treat that explicit stop request as a quiet, orderly GUI shutdown.
        pass
    finally:
        app._shutdown_immediately()
