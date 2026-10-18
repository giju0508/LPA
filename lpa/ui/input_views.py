"""Input pages for engine definition, chamber geometry, and thermal analysis."""

from __future__ import annotations

import copy
import math
import tkinter as tk
import uuid
from tkinter import messagebox, ttk
from typing import Any

from ..core import (
    AnalysisInput,
    ContractionDefinitionMode,
    EngineDefinition,
    EquilibriumFlow,
    EquilibriumMode,
    MixtureRatioOptimum,
    NozzleEfficiency,
    NozzleExitCondition,
    NozzleGeometry,
    SizeMode,
    ThrustChamberInput,
    ThrustChamberSize,
    optimize_mixture_ratio,
    optimize_mixture_ratio_for_inputs,
)
from ..core.composition import aqueous_composition, engine_coolant_name, engine_selection
from ..core.propellants import LNG_DESCRIPTION
from .theme import COLORS, FONT_UI
from .widgets import Card, FieldGrid, ScrollableFrame, Tooltip, set_children_state, fit_tree_columns
from .validation import segment_numeric_issues


OXIDIZERS = ("LOX", "GOX", "H2O2", "N2O")
FUELS = (
    "Ethanol",
    "IPA",
    "RP-1",
    "Jet A-1",
    "LCH4",
    "LNG",
    "GCH4",
    "LH2",
    "GH2",
    "Propane",
)
COOLANTS = (
    "LOX", "GOX", "H2O2 70%", "H2O2 80%", "H2O2 90%", "H2O2 100%", "N2O",
    "Ethanol 70%", "Ethanol 80%", "Ethanol 90%", "Ethanol 100%", "IPA",
    "RP-1", "Jet A-1", "LCH4", "LNG", "GCH4", "LH2", "GH2", "Propane", "H2O",
)
REGEN_MATERIALS = ("CuCrZr", "IN625", "IN718", "AlSi10Mg")
RADIATION_MATERIALS = ("C103", "Ti64")


class InputPage(ScrollableFrame):
    """Scrollable input page with a variable registry.

    Page title and description are rendered once in the application's compact
    action header, leaving the scrollable area entirely for engineering input.
    """

    page_title = "Input"
    page_description = ""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=22)
        self.variables: dict[str, tk.Variable] = {}

    def string(self, name: str, value: str = "") -> tk.StringVar:
        variable = tk.StringVar(self, value=value)
        self.variables[name] = variable
        return variable

    def boolean(self, name: str, value: bool = False) -> tk.BooleanVar:
        variable = tk.BooleanVar(self, value=value)
        self.variables[name] = variable
        return variable

    def integer(self, name: str, value: int = 0) -> tk.IntVar:
        variable = tk.IntVar(self, value=value)
        self.variables[name] = variable
        return variable

    def values(self) -> dict[str, Any]:
        return {name: var.get() for name, var in self.variables.items()}

    def load_values(self, values: dict[str, Any]) -> None:
        for name, value in values.items():
            if name in self.variables:
                try:
                    self.variables[name].set(value)
                except tk.TclError:
                    pass


class EngineDefinitionPage(InputPage):
    page_title = "Engine Definition"
    page_description = ""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self._optimum_signature: tuple[Any, ...] | None = None
        self._optimum_cache: dict[tuple[Any, ...], MixtureRatioOptimum] = {}
        self._optimization_after_id: str | None = None
        self._chamber_traces_attached = False
        identity = Card(self.body, "Project identity")
        identity.pack(fill="x", pady=(0, 14))
        grid = FieldGrid(identity.content, columns=2)
        grid.pack(fill="x")
        name = ttk.Entry(grid, textvariable=self.string("engine_name", "LPA Demonstrator"))
        grid.add("Engine name", name)
        description = tk.Text(
            grid,
            height=3,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
            background=COLORS["surface"],
            foreground=COLORS["text"],
            padx=7,
            pady=6,
        )
        description.insert("1.0", "Liquid rocket thrust chamber analysis")
        # Initial content is a clean project, even when Tk delivers the
        # pending <<Modified>> event after the app attaches change tracking.
        description.edit_modified(False)
        self.description = description
        grid.add("Description", description)

        operating = Card(self.body, "Operating point")
        operating.pack(fill="x", pady=(0, 14))
        fields = FieldGrid(operating.content, columns=2)
        fields.pack(fill="x")
        self.chamber_pressure_var = self.string("chamber_pressure_bar", "20")
        self.chamber_pressure_entry = ttk.Entry(fields, textvariable=self.chamber_pressure_var)
        fields.add("Chamber pressure", self.chamber_pressure_entry, unit="bar(a)")

        ratio_box = ttk.Frame(fields, style="Surface.TFrame")
        ratio_box.grid_columnconfigure(0, weight=1)
        self.mixture_ratio_var = self.string("mixture_ratio", "1.3")
        self.mixture_ratio_entry = ttk.Entry(ratio_box, textvariable=self.mixture_ratio_var)
        self.mixture_ratio_entry.grid(row=0, column=0, sticky="ew")
        self.mixture_ratio_auto_var = self.boolean("mixture_ratio_auto", False)
        self.automatic_mixture_ratio_checkbox = ttk.Checkbutton(
            ratio_box,
            text="Auto O/F: maximum theoretical vacuum Isp",
            variable=self.mixture_ratio_auto_var,
            command=self._on_auto_mixture_ratio,
        )
        self.automatic_mixture_ratio_checkbox.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.mixture_ratio_status = ttk.Label(
            ratio_box,
            text="",
            style="Muted.TLabel",
            wraplength=360,
        )
        self.mixture_ratio_status.grid(row=2, column=0, sticky="w", pady=(3, 0))
        self.mixture_ratio_status.grid_remove()
        fields.add("Mixture ratio (O/F)", ratio_box, columnspan=2)

        oxidizer_box = ttk.Frame(fields, style="Surface.TFrame")
        oxidizer_box.grid_columnconfigure(0, weight=1)
        fuel_box = ttk.Frame(fields, style="Surface.TFrame")
        fuel_box.grid_columnconfigure(0, weight=1)
        self.oxidizer_var = self.string("oxidizer", "LOX")
        self.oxidizer_combo = ttk.Combobox(
            oxidizer_box, textvariable=self.oxidizer_var, values=OXIDIZERS, state="readonly"
        )
        self.oxidizer_combo.grid(row=0, column=0, sticky="ew")
        fields.add("Oxidizer", oxidizer_box)
        self.fuel_var = self.string("fuel", "Ethanol")
        self.fuel_combo = ttk.Combobox(
            fuel_box, textvariable=self.fuel_var, values=FUELS, state="readonly"
        )
        self.fuel_combo.grid(row=0, column=0, sticky="ew")
        fields.add("Fuel", fuel_box)
        self.oxidizer_fraction_box, self.oxidizer_fraction_entry = self._fraction_input(
            oxidizer_box, "oxidizer_mass_fraction_pct", "90"
        )
        self.fuel_fraction_box, self.fuel_fraction_entry = self._fraction_input(
            fuel_box, "fuel_mass_fraction_pct", "70"
        )
        self.lng_description = ttk.Label(
            fuel_box, text=LNG_DESCRIPTION, style="Muted.TLabel", wraplength=380
        )
        self.lng_description.grid(row=2, column=0, sticky="w", pady=(5, 0))
        fuel_box.bind(
            "<Configure>",
            lambda event: self.lng_description.configure(wraplength=max(120, event.width - 4)),
        )
        self._refresh_propellant_fields()

        for kind, label in (("oxidizer", "Oxidizer supply temperature (optional)"),
                            ("fuel", "Fuel supply temperature (optional)")):
            variable = self.string(f"{kind}_temperature_k", "")
            fields.add(label, ttk.Entry(fields, textvariable=variable), unit="K",
                       hint="Blank uses the registered propellant reference state.")
            variable.trace_add("write", self._on_optimization_variable)
        for kind, label in (("oxidizer", "Oxidizer supply pressure (optional)"),
                            ("fuel", "Fuel supply pressure (optional)")):
            variable = self.string(f"{kind}_pressure_bar", "")
            fields.add(label, ttk.Entry(fields, textvariable=variable), unit="bar(a)",
                       hint="Blank retains the reference pressure: 1.01325 bar; LNG uses 5 bar.")
            variable.trace_add("write", self._on_optimization_variable)

        self.chamber_pressure_entry.bind("<FocusOut>", self._on_optimization_input_event, add="+")
        self.chamber_pressure_entry.bind("<Return>", self._on_optimization_input_event, add="+")
        self.chamber_pressure_var.trace_add("write", self._on_optimization_variable)
        self.oxidizer_var.trace_add("write", self._on_propellant_change)
        self.fuel_var.trace_add("write", self._on_propellant_change)
        for key in ("oxidizer_mass_fraction_pct", "fuel_mass_fraction_pct"):
            self.variables[key].trace_add("write", self._on_optimization_variable)
        self._set_mixture_ratio_entry_state()

    def _fraction_input(self, parent: ttk.Frame, key: str, default: str) -> tuple[ttk.Frame, ttk.Entry]:
        box = ttk.Frame(parent, style="Surface.TFrame")
        box.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        box.grid_columnconfigure(1, weight=1)
        ttk.Label(box, text="Mass fraction", style="Field.TLabel").grid(row=0, column=0, padx=(0, 7))
        entry = ttk.Entry(box, textvariable=self.string(key, default), width=8)
        entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(box, text="% (balance: H2O)", style="Unit.TLabel").grid(row=0, column=2, padx=(7, 0))
        return box, entry

    def _refresh_propellant_fields(self) -> None:
        for name, box in ((self.oxidizer_var.get(), self.oxidizer_fraction_box), (self.fuel_var.get(), self.fuel_fraction_box)):
            if name in {"H2O2", "Ethanol", "IPA"}:
                box.grid()
            else:
                box.grid_remove()
        if self.fuel_var.get() == "LNG":
            self.lng_description.grid()
        else:
            self.lng_description.grid_remove()

    def _on_propellant_change(self, *_args: Any) -> None:
        self._refresh_propellant_fields()
        self._schedule_mixture_ratio_refresh()

    def _set_mixture_ratio_entry_state(self) -> None:
        if self.mixture_ratio_auto_var.get():
            self.mixture_ratio_entry.state(["readonly", "!disabled"])
        else:
            self.mixture_ratio_entry.state(["!readonly", "!disabled"])
            self.mixture_ratio_status.configure(text="")
            self.mixture_ratio_status.grid_remove()

    def _ensure_chamber_traces(self) -> None:
        if self._chamber_traces_attached:
            return
        pages = getattr(self.winfo_toplevel(), "pages", {})
        chamber_page = pages.get("chamber") if isinstance(pages, dict) else None
        variables = getattr(chamber_page, "variables", {})
        if not isinstance(variables, dict):
            return
        keys = (
            "contraction_mode",
            "contraction_area_ratio",
            "chamber_diameter_mm",
            "sizing_mode",
            "throat_diameter_mm",
            "exit_condition_mode",
            "exit_condition_value",
            "flow_model",
            "freeze_value",
            "nominal_thrust",
            "thrust_unit",
            "nominal_thrust_ambient_atm",
            "reaction_efficiency_pct",
            "nozzle_efficiency_mode",
            "nozzle_efficiency_pct",
            "nozzle_type",
            "nozzle_half_angle_deg",
            "rao_length_pct",
            "rn_rt",
            "rao_start_angle_deg",
            "rao_exit_angle_deg",
        )
        if not all(key in variables for key in keys):
            return
        for key in keys:
            variables[key].trace_add("write", self._on_optimization_variable)
        self._chamber_traces_attached = True

    def _optimization_context(self) -> tuple[tuple[Any, ...], dict[str, Any]]:
        chamber_pressure = float(self.chamber_pressure_var.get())
        if not math.isfinite(chamber_pressure) or chamber_pressure <= 0:
            raise ValueError("Enter a positive chamber pressure before optimizing O/F.")

        contraction_ratio = 4.0
        expansion_ratio: float | None = 40.0
        ambient_pressure: float | None = None
        equilibrium_mode = EquilibriumMode.SHIFTING
        freeze_value: float | None = None
        context_warning: str | None = None
        chamber_signature: tuple[Any, ...] = ()
        coupled_inputs: AnalysisInput | None = None
        pages = getattr(self.winfo_toplevel(), "pages", {})
        chamber_page = pages.get("chamber") if isinstance(pages, dict) else None
        variables = getattr(chamber_page, "variables", {})
        if isinstance(variables, dict) and variables:
            for key, options in (("contraction_mode", {"Area ratio (Ac/At)", "Chamber diameter (Dc)"}),
                                 ("sizing_mode", {"Engine nominal thrust", "Chamber throat diameter"}),
                                 ("nozzle_type", {"Conical nozzle", "Parabolic contour (Rao)"}),
                                 ("nozzle_efficiency_mode", {"Estimate", "Specified"}),
                                 ("thrust_unit", {"N", "kN"})):
                if variables[key].get() not in options:
                    raise ValueError(f"Select a supported {key.replace('_', ' ')} before optimizing O/F.")
            contraction_ratio = (4.0 if variables["contraction_mode"].get() == "Chamber diameter (Dc)"
                                 else float(variables["contraction_area_ratio"].get()))
            if (
                variables["contraction_mode"].get() == "Chamber diameter (Dc)"
                and variables["sizing_mode"].get() == "Chamber throat diameter"
            ):
                chamber_diameter = float(variables["chamber_diameter_mm"].get())
                throat_diameter = float(variables["throat_diameter_mm"].get())
                contraction_ratio = (chamber_diameter / throat_diameter) ** 2
            exit_label = variables["exit_condition_mode"].get()
            if exit_label == "Expansion area ratio":
                expansion_ratio = float(variables["exit_condition_value"].get())
                NozzleExitCondition(mode="expansion_ratio", expansion_area_ratio=expansion_ratio)
            elif exit_label == "Ambient pressure":
                expansion_ratio = None
                ambient_pressure = float(variables["exit_condition_value"].get())
                NozzleExitCondition(mode="ambient_pressure", ambient_pressure_atm=ambient_pressure)
            else:
                raise ValueError("Select a supported nozzle exit condition before optimizing O/F.")
            flow_label = str(variables["flow_model"].get())
            flow_modes = {
                "Shifting equilibrium": EquilibriumMode.SHIFTING,
                "Freezing at pressure ratio": EquilibriumMode.FROZEN_PRESSURE,
                "Freezing at area ratio": EquilibriumMode.FROZEN_AREA,
                "Frozen at chamber": EquilibriumMode.FROZEN_PRESSURE,
                "Frozen at throat": EquilibriumMode.FROZEN_AREA,
            }
            if flow_label not in flow_modes:
                raise ValueError("Select a supported chemistry flow model before optimizing O/F.")
            equilibrium_mode = flow_modes[flow_label]
            if equilibrium_mode is EquilibriumMode.FROZEN_PRESSURE:
                raise ValueError("Chamber-frozen chemistry and pressure-ratio freezing are unsupported for finite-area chambers.")
            if equilibrium_mode is EquilibriumMode.FROZEN_AREA:
                freeze_value = 1.0 if flow_label == "Frozen at throat" else float(variables["freeze_value"].get())
                EquilibriumFlow(mode=equilibrium_mode, freeze_area_ratio=freeze_value)
                if freeze_value != 1.0:
                    context_warning = (f"Freezing at A/At={freeze_value:g} is unsupported; automatic O/F uses the throat-frozen approximation.")
            # Recalculate preview after the same exit, flow, geometry and sizing
            # edits that invalidate an analysis. Losses are excluded from the
            # objective but can affect Ac/At in direct-Dc thrust sizing.
            chamber_signature = tuple((key, variable.get()) for key, variable in variables.items()
                                      if key in {"contraction_mode", "contraction_area_ratio", "chamber_diameter_mm",
                                                 "sizing_mode", "throat_diameter_mm", "exit_condition_mode",
                                                 "exit_condition_value", "flow_model", "freeze_value", "nominal_thrust",
                                                 "thrust_unit", "nominal_thrust_ambient_atm", "reaction_efficiency_pct",
                                                 "nozzle_efficiency_mode", "nozzle_efficiency_pct", "nozzle_type",
                                                 "nozzle_half_angle_deg", "rao_length_pct", "rn_rt",
                                                 "rao_start_angle_deg", "rao_exit_angle_deg"})

        values = super().values()
        oxidizer, oxidizer_fraction = engine_selection(values, "oxidizer")
        fuel, fuel_fraction = engine_selection(values, "fuel")
        engine = EngineDefinition(
            name="O/F optimization",
            chamber_pressure_bar=chamber_pressure,
            mixture_ratio=1.0,
            oxidizer=oxidizer,
            fuel=fuel,
            oxidizer_mass_fraction=oxidizer_fraction,
            fuel_mass_fraction=fuel_fraction,
            oxidizer_temperature_k=(float(values["oxidizer_temperature_k"]) if str(values["oxidizer_temperature_k"]).strip() else None),
            fuel_temperature_k=(float(values["fuel_temperature_k"]) if str(values["fuel_temperature_k"]).strip() else None),
            oxidizer_pressure_bar=(float(values["oxidizer_pressure_bar"]) if str(values["oxidizer_pressure_bar"]).strip() else None),
            fuel_pressure_bar=(float(values["fuel_pressure_bar"]) if str(values["fuel_pressure_bar"]).strip() else None),
        )
        if (
            isinstance(variables, dict)
            and variables
            and variables["contraction_mode"].get() == "Chamber diameter (Dc)"
            and variables["sizing_mode"].get() == "Engine nominal thrust"
        ):
            equilibrium = EquilibriumFlow(
                mode=equilibrium_mode,
                freeze_pressure_ratio=(
                    freeze_value
                    if equilibrium_mode is EquilibriumMode.FROZEN_PRESSURE
                    else None
                ),
                freeze_area_ratio=(
                    freeze_value
                    if equilibrium_mode is EquilibriumMode.FROZEN_AREA
                    else None
                ),
            )
            if expansion_ratio is not None:
                exit_condition = NozzleExitCondition(
                    mode="expansion_ratio",
                    expansion_area_ratio=expansion_ratio,
                    ambient_pressure_atm=None,
                )
            else:
                exit_condition = NozzleExitCondition(
                    mode="ambient_pressure",
                    ambient_pressure_atm=ambient_pressure,
                )
            thrust_n = float(variables["nominal_thrust"].get())
            if variables["thrust_unit"].get() == "kN":
                thrust_n *= 1000.0
            nozzle_efficiency_mode = str(variables["nozzle_efficiency_mode"].get())
            nozzle_efficiency = NozzleEfficiency(
                mode="estimate" if nozzle_efficiency_mode == "Estimate" else "direct",
                value_percent=(
                    None
                    if nozzle_efficiency_mode == "Estimate"
                    else float(variables["nozzle_efficiency_pct"].get())
                ),
            )
            nozzle_type = str(variables["nozzle_type"].get())
            bell = nozzle_type == "Parabolic contour (Rao)"
            chamber = ThrustChamberInput(
                contraction_mode=ContractionDefinitionMode.CHAMBER_DIAMETER,
                contraction_area_ratio=contraction_ratio,
                chamber_diameter_mm=float(variables["chamber_diameter_mm"].get()),
                exit_condition=exit_condition,
                equilibrium=equilibrium,
                reaction_efficiency_percent=float(
                    variables["reaction_efficiency_pct"].get()
                ),
                nozzle_efficiency=nozzle_efficiency,
                size=ThrustChamberSize(
                    mode=SizeMode.NOMINAL_THRUST,
                    nominal_thrust_n=thrust_n,
                    thrust_ambient_pressure_atm=float(
                        variables["nominal_thrust_ambient_atm"].get()
                    ),
                    throat_diameter_mm=None,
                ),
                nozzle=NozzleGeometry(
                    contour_type=(
                        "rao_bell"
                        if nozzle_type == "Parabolic contour (Rao)"
                        else "conical"
                    ),
                    conical_half_angle_deg=15.0 if bell else float(variables["nozzle_half_angle_deg"].get()),
                    bell_length_percent=float(variables["rao_length_pct"].get()) if bell else 80.0,
                    throat_radius_ratio=float(variables["rn_rt"].get()),
                    rao_initial_angle_deg=(float(variables["rao_start_angle_deg"].get())
                                           if bell and str(variables["rao_start_angle_deg"].get()).strip() else None),
                    rao_exit_angle_deg=(float(variables["rao_exit_angle_deg"].get())
                                        if bell and str(variables["rao_exit_angle_deg"].get()).strip() else None),
                ),
            )
            coupled_inputs = AnalysisInput(engine=engine, thrust_chamber=chamber)
        signature = (
            round(chamber_pressure, 9),
            oxidizer,
            fuel,
            oxidizer_fraction,
            fuel_fraction,
            engine.oxidizer_temperature_k,
            engine.fuel_temperature_k,
            engine.oxidizer_pressure_bar,
            engine.fuel_pressure_bar,
            round(contraction_ratio, 9),
            None if expansion_ratio is None else round(expansion_ratio, 9),
            None if ambient_pressure is None else round(ambient_pressure, 9),
            equilibrium_mode.value,
            freeze_value,
            chamber_signature,
        )
        settings = {
            "engine": engine,
            "contraction_area_ratio": contraction_ratio,
            "expansion_ratio": expansion_ratio,
            "ambient_pressure_atm": ambient_pressure,
            "equilibrium_mode": equilibrium_mode,
            "_context_warning": context_warning,
        }
        if coupled_inputs is not None:
            settings["_coupled_inputs"] = coupled_inputs
        return signature, settings

    def _refresh_automatic_mixture_ratio(self, *, force: bool = False) -> None:
        self._set_mixture_ratio_entry_state()
        if not self.mixture_ratio_auto_var.get():
            self._optimum_signature = None
            return
        self._ensure_chamber_traces()
        try:
            signature, settings = self._optimization_context()
            if not force and signature == self._optimum_signature:
                return
            optimum = self._optimum_cache.get(signature)
            context_warning = settings.pop("_context_warning", None)
            if optimum is None:
                coupled_inputs = settings.pop("_coupled_inputs", None)
                if coupled_inputs is None:
                    optimum = optimize_mixture_ratio(**settings)
                else:
                    optimum = optimize_mixture_ratio_for_inputs(coupled_inputs)
                self._optimum_cache[signature] = optimum
            value = f"{optimum.mixture_ratio:.5f}".rstrip("0").rstrip(".")
            self.mixture_ratio_var.set(value)
            self._optimum_signature = signature
            warnings = (["Automatic O/F used the engineering fallback model (screening estimate)."]
                        if optimum.source != "rocketcea" else [])
            warnings.extend(str(item) for item in (optimum.warning, context_warning) if item)
            if warnings:
                self.mixture_ratio_status.configure(text=" ".join(dict.fromkeys(warnings)), style="Warning.TLabel")
                self.mixture_ratio_status.grid()
            else:
                self.mixture_ratio_status.configure(text="")
                self.mixture_ratio_status.grid_remove()
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            self._optimum_signature = None
            self.mixture_ratio_status.configure(text=str(error), style="Error.TLabel")
            self.mixture_ratio_status.grid()

    def _on_auto_mixture_ratio(self) -> None:
        self._refresh_automatic_mixture_ratio(force=True)

    def _on_optimization_input_event(self, _event: tk.Event) -> None:
        self._schedule_mixture_ratio_refresh()

    def _on_optimization_variable(self, *_args: Any) -> None:
        self._schedule_mixture_ratio_refresh()

    def _schedule_mixture_ratio_refresh(self) -> None:
        if not self.mixture_ratio_auto_var.get():
            return
        if self._optimization_after_id is not None:
            try:
                self.after_cancel(self._optimization_after_id)
            except tk.TclError:
                pass
        top = self.winfo_toplevel()
        delay = 0 if bool(getattr(top, "_loading", False)) else 180
        self._optimization_after_id = self.after(delay, self._run_scheduled_mixture_ratio_refresh)

    def _run_scheduled_mixture_ratio_refresh(self) -> None:
        self._optimization_after_id = None
        self._refresh_automatic_mixture_ratio()

    def values(self) -> dict[str, Any]:
        self._refresh_automatic_mixture_ratio()
        result = super().values()
        result["description"] = self.description.get("1.0", "end-1c")
        return result

    def load_values(self, values: dict[str, Any]) -> None:
        values = dict(values)
        for key in ("oxidizer_temperature_k", "fuel_temperature_k", "oxidizer_pressure_bar", "fuel_pressure_bar"):
            if values.get(key) is None:
                values[key] = ""
        for kind in ("oxidizer", "fuel"):
            if kind in values:
                name, fraction = engine_selection(values, kind)
                values[kind] = name
                if aqueous_composition(name):
                    values[f"{kind}_mass_fraction_pct"] = f"{100.0 * fraction:.12g}"
        if "mixture_ratio_auto" not in values:
            self.mixture_ratio_auto_var.set(False)
        super().load_values(values)
        self._refresh_propellant_fields()
        self._set_mixture_ratio_entry_state()
        if self.mixture_ratio_auto_var.get():
            self._ensure_chamber_traces()
            self._schedule_mixture_ratio_refresh()
        if "description" in values:
            self.description.delete("1.0", "end")
            self.description.insert("1.0", str(values["description"]))
            # Clear Tk's modified latch before the deferred <<Modified>> event
            # runs, otherwise opening a project is immediately marked dirty.
            self.description.edit_modified(False)


class ThrustChamberPage(InputPage):
    page_title = "Thrust Chamber"
    page_description = ""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self._build_flow_card()
        self._build_size_card()
        self._build_geometry_card()
        self._build_sweep_card()
        self._refresh_states()

    def load_values(self, values: dict[str, Any]) -> None:
        # Projects saved before 0.4.0 contain only Ac/At.  Explicitly restore
        # that legacy basis even when such a file is opened after a direct-Dc
        # project in the same application session.
        if "contraction_mode" not in values:
            self.contraction_mode_var.set("Area ratio (Ac/At)")
        # Legacy projects have automatic angles.  Clear a previous project's
        # manual pair rather than retaining it when these keys are absent.
        for key in ("rao_start_angle_deg", "rao_exit_angle_deg"):
            if key not in values or values[key] is None:
                values = {**values, key: ""}
        super().load_values(values)
        self._refresh_states()

    def _build_flow_card(self) -> None:
        card = Card(self.body, "Flow & performance model")
        card.pack(fill="x", pady=(0, 14))
        fields = FieldGrid(card.content, columns=2)
        fields.pack(fill="x")
        contraction_box = ttk.Frame(fields, style="Surface.TFrame")
        contraction_box.grid_columnconfigure(1, weight=1)
        self.contraction_mode_var = self.string("contraction_mode", "Area ratio (Ac/At)")
        self.contraction_mode_combo = ttk.Combobox(
            contraction_box,
            textvariable=self.contraction_mode_var,
            values=("Area ratio (Ac/At)", "Chamber diameter (Dc)"),
            state="readonly",
            width=21,
        )
        self.contraction_mode_combo.grid(row=0, column=0, padx=(0, 7), sticky="w")
        self.contraction_area_ratio_var = self.string("contraction_area_ratio", "6.25")
        self.chamber_diameter_var = self.string("chamber_diameter_mm", "50.0")
        self.contraction_value = ttk.Entry(
            contraction_box,
            textvariable=self.contraction_area_ratio_var,
            width=10,
        )
        self.contraction_value.grid(row=0, column=1, sticky="ew")
        self.contraction_unit = ttk.Label(contraction_box, text="Ac/At", style="Unit.TLabel")
        self.contraction_unit.grid(row=0, column=2, padx=(7, 0))
        fields.add(
            "Contraction definition",
            contraction_box,
        )
        self.contraction_mode_var.trace_add("write", lambda *_: self._refresh_states())

        exit_box = ttk.Frame(fields, style="Surface.TFrame")
        exit_box.grid_columnconfigure(1, weight=1)
        exit_mode = self.string("exit_condition_mode", "Ambient pressure")
        exit_combo = ttk.Combobox(
            exit_box,
            textvariable=exit_mode,
            values=("Ambient pressure", "Expansion area ratio"),
            state="readonly",
            width=21,
        )
        exit_combo.grid(row=0, column=0, padx=(0, 7), sticky="w")
        self.exit_value = ttk.Entry(exit_box, textvariable=self.string("exit_condition_value", "1.0"), width=10)
        self.exit_value.grid(row=0, column=1, sticky="ew")
        self.exit_unit = ttk.Label(exit_box, text="atm", style="Unit.TLabel")
        self.exit_unit.grid(row=0, column=2, padx=(7, 0))
        fields.add("Nozzle exit condition", exit_box)
        exit_mode.trace_add("write", lambda *_: self._refresh_states())

        fields.add(
            "Equilibrium flow",
            ttk.Combobox(
                fields,
                textvariable=self.string("flow_model", "Shifting equilibrium"),
                values=("Shifting equilibrium", "Frozen at throat"),
                state="readonly",
            ),
        )
        freeze = ttk.Frame(fields, style="Surface.TFrame")
        freeze.grid_columnconfigure(0, weight=1)
        self.freeze_value = ttk.Entry(freeze, textvariable=self.string("freeze_value", "10.0"))
        self._supported_freeze_display = tk.StringVar(self, value="")
        self.freeze_value.grid(row=0, column=0, sticky="ew")
        self.freeze_unit = ttk.Label(freeze, text="Pc/P", style="Unit.TLabel")
        self.freeze_unit.grid(row=0, column=1, padx=(7, 0))
        fields.add("Freezing location / legacy criterion", freeze)
        self.variables["flow_model"].trace_add("write", lambda *_: self._refresh_states())

        fields.add(
            "Reaction efficiency",
            ttk.Entry(fields, textvariable=self.string("reaction_efficiency_pct", "98.0")),
            unit="%",
        )
        nozzle_eff_box = ttk.Frame(fields, style="Surface.TFrame")
        nozzle_eff_box.grid_columnconfigure(0, weight=1)
        self.nozzle_eff_mode = ttk.Combobox(
            nozzle_eff_box,
            textvariable=self.string("nozzle_efficiency_mode", "Estimate"),
            values=("Estimate", "Specified"),
            state="readonly",
            width=14,
        )
        self.nozzle_eff_mode.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        self.nozzle_eff_value = ttk.Entry(
            nozzle_eff_box,
            textvariable=self.string("nozzle_efficiency_pct", "96.0"),
            width=8,
        )
        self.nozzle_eff_value.grid(row=0, column=1)
        ttk.Label(nozzle_eff_box, text="%", style="Unit.TLabel").grid(row=0, column=2, padx=(5, 0))
        fields.add("Nozzle efficiency", nozzle_eff_box)
        self.variables["nozzle_efficiency_mode"].trace_add("write", lambda *_: self._refresh_states())

    def _build_sweep_card(self) -> None:
        card = Card(self.body, "Operating envelopes")
        card.pack(fill="x", pady=(0, 14))

        throttle_header = ttk.Frame(card.content, style="Surface.TFrame")
        throttle_header.pack(fill="x")
        throttle_enabled = self.boolean("throttle_enabled", False)
        ttk.Checkbutton(
            throttle_header,
            text="Analyze throttle settings",
            variable=throttle_enabled,
            command=self._refresh_states,
        ).pack(side="left")
        self.throttle_frame = ttk.Frame(card.content, style="Surface.TFrame")
        self.throttle_frame.pack(fill="x", pady=(6, 11))
        self.throttle_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="throttle")
        throttle_mode = self.string("throttle_mode", "Fixed throttle value")
        ttk.Combobox(
            self.throttle_frame,
            textvariable=throttle_mode,
            values=("Fixed throttle value", "Throttle values range"),
            state="readonly",
        ).grid(row=0, column=0, padx=(0, 7), sticky="ew")
        self.throttle_fixed = self._compact_field(self.throttle_frame, "Value", "throttle_fixed_pct", "100", "%", 1)
        self.throttle_min = self._compact_field(self.throttle_frame, "Min", "throttle_min_pct", "40", "%", 2)
        self.throttle_max = self._compact_field(self.throttle_frame, "Max", "throttle_max_pct", "100", "%", 3)
        self.throttle_points = self._compact_field(self.throttle_frame, "Points", "throttle_points", "7", "", 4)
        throttle_mode.trace_add("write", lambda *_: self._refresh_states())

        ttk.Separator(card.content).pack(fill="x", pady=(2, 11))
        ambient_header = ttk.Frame(card.content, style="Surface.TFrame")
        ambient_header.pack(fill="x")
        ambient_enabled = self.boolean("ambient_enabled", False)
        ttk.Checkbutton(
            ambient_header,
            text="Analyze ambient conditions",
            variable=ambient_enabled,
            command=self._refresh_states,
        ).pack(side="left")
        self.ambient_frame = ttk.Frame(card.content, style="Surface.TFrame")
        self.ambient_frame.pack(fill="x", pady=(6, 0))
        self.ambient_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="ambient")
        ambient_mode = self.string("ambient_mode", "Fixed ambient pressure")
        ttk.Combobox(
            self.ambient_frame,
            textvariable=ambient_mode,
            values=("Fixed ambient pressure", "Ambient pressure range"),
            state="readonly",
        ).grid(row=0, column=0, padx=(0, 7), sticky="ew")
        self.ambient_fixed = self._compact_field(self.ambient_frame, "Value", "ambient_fixed_atm", "1.0", "atm", 1)
        self.ambient_min = self._compact_field(self.ambient_frame, "Min", "ambient_min_atm", "0.0", "atm", 2)
        self.ambient_max = self._compact_field(self.ambient_frame, "Max", "ambient_max_atm", "1.0", "atm", 3)
        self.ambient_points = self._compact_field(self.ambient_frame, "Points", "ambient_points", "6", "", 4)
        ambient_mode.trace_add("write", lambda *_: self._refresh_states())

    def _compact_field(
        self,
        parent: ttk.Frame,
        label: str,
        key: str,
        default: str,
        unit: str,
        column: int,
    ) -> ttk.Frame:
        box = ttk.Frame(parent, style="Surface.TFrame")
        box.grid(row=0, column=column, padx=(0 if column == 0 else 7, 0), sticky="ew")
        box.grid_columnconfigure(0, weight=1)
        ttk.Label(box, text=label, style="Field.TLabel").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(box, textvariable=self.string(key, default), width=8)
        entry.grid(row=1, column=0, sticky="ew")
        if unit:
            ttk.Label(box, text=unit, style="Unit.TLabel").grid(row=1, column=1, padx=(4, 0))
        box.input_entry = entry  # type: ignore[attr-defined]
        return box

    def _build_size_card(self) -> None:
        card = Card(self.body, "Thrust chamber size")
        card.pack(fill="x", pady=(0, 14))
        sizing_mode = self.string("sizing_mode", "Engine nominal thrust")
        choices = ttk.Frame(card.content, style="Surface.TFrame")
        choices.pack(fill="x", pady=(0, 8))
        for value in ("Engine nominal thrust", "Chamber throat diameter"):
            ttk.Radiobutton(
                choices,
                text=value,
                value=value,
                variable=sizing_mode,
                command=self._refresh_states,
            ).pack(side="left", padx=(0, 18))
        fields = FieldGrid(card.content, columns=2)
        fields.pack(fill="x")
        thrust_box = ttk.Frame(fields, style="Surface.TFrame")
        thrust_box.grid_columnconfigure(0, weight=1)
        self.nominal_thrust = ttk.Entry(thrust_box, textvariable=self.string("nominal_thrust", "2000"))
        self.nominal_thrust.grid(row=0, column=0, sticky="ew")
        self.thrust_unit = ttk.Combobox(
            thrust_box,
            textvariable=self.string("thrust_unit", "N"),
            values=("N", "kN"),
            state="readonly",
            width=5,
        )
        self.thrust_unit.grid(row=0, column=1, padx=(7, 0))
        fields.add("Nominal thrust", thrust_box)
        self.thrust_ambient = ttk.Entry(fields, textvariable=self.string("nominal_thrust_ambient_atm", "1.0"))
        fields.add("Thrust reference ambient", self.thrust_ambient, unit="atm")
        self.throat_diameter = ttk.Entry(fields, textvariable=self.string("throat_diameter_mm", "25"))
        fields.add("Chamber throat diameter", self.throat_diameter, unit="mm")

        ttk.Separator(card.content).pack(fill="x", pady=(4, 12))
        length_mode = self.string("chamber_length_mode", "Characteristic length L*")
        length_choices = ttk.Frame(card.content, style="Surface.TFrame")
        length_choices.pack(fill="x", pady=(0, 8))
        for value in ("Direct Lc and Lcyl", "Characteristic length L*"):
            ttk.Radiobutton(
                length_choices,
                text=value,
                value=value,
                variable=length_mode,
                command=self._refresh_states,
            ).pack(side="left", padx=(0, 18))
        length_fields = FieldGrid(card.content, columns=3)
        length_fields.pack(fill="x")
        self.lc = ttk.Entry(length_fields, textvariable=self.string("chamber_length_mm", "120"))
        self.lcyl = ttk.Entry(length_fields, textvariable=self.string("cylindrical_length_mm", "80"))
        self.lstar = ttk.Entry(length_fields, textvariable=self.string("characteristic_length_mm", "1200"))
        length_fields.add("Total chamber length Lc", self.lc, unit="mm")
        length_fields.add("Cylindrical length Lcyl", self.lcyl, unit="mm")
        length_fields.add(
            "Characteristic length L*",
            self.lstar,
            unit="mm",
        )

    def _build_geometry_card(self) -> None:
        card = Card(self.body, "Contour geometry")
        card.pack(fill="x", pady=(0, 10))
        fields = FieldGrid(card.content, columns=3)
        fields.pack(fill="x")
        fields.add("Contraction angle β", ttk.Entry(fields, textvariable=self.string("contraction_angle_deg", "30")), unit="deg")
        fields.add("R2 / R2max", ttk.Entry(fields, textvariable=self.string("r2_ratio", "0.5")))
        fields.add("R1 / Rt", ttk.Entry(fields, textvariable=self.string("r1_rt", "1.5")))

        nozzle_type = self.string("nozzle_type", "Conical nozzle")
        nozzle_combo = ttk.Combobox(
            fields,
            textvariable=nozzle_type,
            values=("Conical nozzle", "Parabolic contour (Rao)"),
            state="readonly",
        )
        fields.add("Divergent contour", nozzle_combo)
        self.conical_angle = ttk.Entry(fields, textvariable=self.string("nozzle_half_angle_deg", "15"))
        fields.add("Conical half-angle", self.conical_angle, unit="deg")
        self.rao_length = ttk.Entry(fields, textvariable=self.string("rao_length_pct", "80"))
        fields.add("Parabolic Le / Lc15", self.rao_length, unit="%")
        fields.add("Rn / Rt", ttk.Entry(fields, textvariable=self.string("rn_rt", "0.382")))
        self.rao_start_angle = ttk.Entry(
            fields, textvariable=self.string("rao_start_angle_deg", "")
        )
        fields.add("Rao start angle Tn (optional)", self.rao_start_angle, unit="deg")
        self.rao_exit_angle = ttk.Entry(
            fields, textvariable=self.string("rao_exit_angle_deg", "")
        )
        fields.add("Rao exit angle Te (optional)", self.rao_exit_angle, unit="deg")
        nozzle_type.trace_add("write", lambda *_: self._refresh_states())

    @staticmethod
    def _state(widget: tk.Widget, enabled: bool) -> None:
        if isinstance(widget, ttk.Widget):
            widget.state(["!disabled" if enabled else "disabled"])

    def _refresh_states(self) -> None:
        if not hasattr(self, "exit_value"):
            return
        direct_chamber_diameter = self.contraction_mode_var.get() == "Chamber diameter (Dc)"
        self.contraction_value.configure(
            textvariable=(
                self.chamber_diameter_var
                if direct_chamber_diameter
                else self.contraction_area_ratio_var
            )
        )
        self.contraction_unit.configure(text="mm" if direct_chamber_diameter else "Ac/At")
        exit_area = self.variables["exit_condition_mode"].get() == "Expansion area ratio"
        self.exit_unit.configure(text="Ae/At" if exit_area else "atm")
        frozen = self.variables["flow_model"].get() != "Shifting equilibrium"
        flow_model = self.variables["flow_model"].get()
        supported = flow_model in {"Frozen at chamber", "Frozen at throat"}
        self._supported_freeze_display.set("Chamber" if flow_model == "Frozen at chamber" else "Throat")
        self.freeze_value.configure(textvariable=self._supported_freeze_display if supported else self.variables["freeze_value"])
        self._state(self.freeze_value, frozen and not supported)
        self.freeze_unit.configure(
            text=("Pc/P" if flow_model == "Freezing at pressure ratio" else "A/At" if flow_model == "Freezing at area ratio" else "—")
        )
        self._state(self.nozzle_eff_value, self.variables["nozzle_efficiency_mode"].get() == "Specified")

        throttle_enabled = bool(self.variables["throttle_enabled"].get())
        set_children_state(self.throttle_frame, throttle_enabled)
        throttle_range = self.variables["throttle_mode"].get() == "Throttle values range"
        self._state(self.throttle_fixed.input_entry, throttle_enabled and not throttle_range)  # type: ignore[attr-defined]
        for box in (self.throttle_min, self.throttle_max, self.throttle_points):
            self._state(box.input_entry, throttle_enabled and throttle_range)  # type: ignore[attr-defined]

        ambient_enabled = bool(self.variables["ambient_enabled"].get())
        set_children_state(self.ambient_frame, ambient_enabled)
        ambient_range = self.variables["ambient_mode"].get() == "Ambient pressure range"
        self._state(self.ambient_fixed.input_entry, ambient_enabled and not ambient_range)  # type: ignore[attr-defined]
        for box in (self.ambient_min, self.ambient_max, self.ambient_points):
            self._state(box.input_entry, ambient_enabled and ambient_range)  # type: ignore[attr-defined]

        thrust_size = self.variables["sizing_mode"].get() == "Engine nominal thrust"
        for widget in (self.nominal_thrust, self.thrust_unit, self.thrust_ambient):
            self._state(widget, thrust_size)
        self._state(self.throat_diameter, not thrust_size)
        direct_length = self.variables["chamber_length_mode"].get() == "Direct Lc and Lcyl"
        self._state(self.lc, direct_length)
        self._state(self.lcyl, direct_length)
        self._state(self.lstar, not direct_length)
        parabolic = self.variables["nozzle_type"].get() == "Parabolic contour (Rao)"
        self._state(self.conical_angle, not parabolic)
        self._state(self.rao_length, parabolic)
        self._state(self.rao_start_angle, parabolic)
        self._state(self.rao_exit_angle, parabolic)


def resolve_effective_regen_coolant(
    regen_id: str,
    segments: list[dict[str, Any]],
    engine: dict[str, Any] | None = None,
) -> str | None:
    """Resolve the propellant used by a Regen circuit through linked sources.

    The editor keeps linked Regen segments intentionally sparse.  Film segments,
    however, need to show and persist the *actual* coolant, so follow the same
    source chain used by the thermal solver and account for engine-stream
    definitions along the way.
    """

    by_id = {
        str(segment.get("id", "")): segment
        for segment in segments
        if segment.get("type") == "Regen"
    }
    current = by_id.get(str(regen_id))
    visited: set[str] = set()
    while current is not None:
        identifier = str(current.get("id", ""))
        if not identifier or identifier in visited:
            return None
        visited.add(identifier)
        source_mode = str(
            current.get(
                "coolant_source_mode",
                "Receive from Regen segment"
                if current.get("coolant_definition_mode") == "Receive from Regen segment"
                else "Custom coolant",
            )
        )
        if source_mode == "Receive from Regen segment":
            current = by_id.get(str(current.get("coolant_source_id", "")))
            continue
        if source_mode == "Engine oxidizer":
            value = engine_coolant_name(engine or {}, "oxidizer")
        elif source_mode == "Engine fuel":
            value = engine_coolant_name(engine or {}, "fuel")
        else:
            value = current.get("coolant")
        text = str(value or "").strip()
        return text or None
    return None


class ThermalAnalysisPage(InputPage):
    page_title = "Thermal Analysis"
    page_description = ""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.segments: list[dict[str, Any]] = []
        self._build_control_card()
        self._build_segment_card()
        self._refresh_enabled()

    def _build_control_card(self) -> None:
        card = Card(self.body, "Thermal solver")
        card.pack(fill="x", pady=(0, 14))
        top = ttk.Frame(card.content, style="Surface.TFrame")
        top.pack(fill="x")
        enabled = self.boolean("thermal_enabled", False)
        ttk.Checkbutton(
            top,
            text="Enable thermal analysis",
            variable=enabled,
            command=self._refresh_enabled,
        ).pack(side="left")
        self.thermal_controls = ttk.Frame(card.content, style="Surface.TFrame")
        self.thermal_controls.pack(fill="x", pady=(10, 0))
        fields = FieldGrid(self.thermal_controls, columns=2)
        fields.pack(fill="x")
        fields.add(
            "Calculation density",
            ttk.Combobox(
                fields,
                textvariable=self.string("thermal_resolution", "Medium"),
                values=("Low", "Medium", "High"),
                state="readonly",
            ),
        )
        fields.add(
            "Maximum solver iterations",
            ttk.Entry(fields, textvariable=self.string("thermal_max_iterations", "200")),
        )
        fields.add("Coolant properties",ttk.Combobox(fields,
            textvariable=self.string("coolant_property_backend","CoolProp HEOS"),
            values=("CoolProp HEOS","REFPROP (separate installation)"),state="readonly"))
        fields.add("Two-phase channel calculation",ttk.Combobox(fields,
            textvariable=self.string("two_phase_model","Auto (Beta)"),
            values=("Auto (Beta)","Disabled"),state="readonly"))
        ttk.Checkbutton(self.thermal_controls, text="Couple Regen outlet to reactant state",
                        variable=self.boolean("regen_feed_feedback_enabled", False)).pack(anchor="w", pady=(3, 0))

    def _build_segment_card(self) -> None:
        card = Card(self.body, "Cooling segments")
        card.pack(fill="both", expand=True, pady=(0, 14))
        toolbar = ttk.Frame(card.content, style="Surface.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        self.add_regen_button = ttk.Button(toolbar, text="+ Regen", command=lambda: self._add_segment("Regen"))
        self.add_regen_button.pack(side="left", padx=(0, 6))
        self.add_film_button = ttk.Button(toolbar, text="+ Film", command=lambda: self._add_segment("Film"))
        self.add_film_button.pack(side="left", padx=(0, 6))
        self.add_radiation_button = ttk.Button(toolbar, text="+ Radiation", command=lambda: self._add_segment("Radiation"))
        self.add_radiation_button.pack(side="left")
        self.duplicate_button = ttk.Button(toolbar, text="Duplicate", command=self._duplicate_selected)
        self.duplicate_button.pack(side="right", padx=(6, 0))
        self.remove_button = ttk.Button(toolbar, text="Remove", style="Danger.TButton", command=self._remove_selected)
        self.remove_button.pack(side="right", padx=(6, 0))
        self.edit_button = ttk.Button(toolbar, text="Edit", command=self._edit_selected)
        self.edit_button.pack(side="right")

        columns = ("Order", "Type", "Name", "Range / location", "Coolant / material", "Status")
        frame = ttk.Frame(card.content, style="Surface.TFrame")
        frame.pack(fill="both", expand=True)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=9, selectmode="browse")
        widths = (55, 80, 150, 180, 190, 170)
        for col, width in zip(columns, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, minwidth=50, anchor="w", stretch=col not in ("Order", "Type"))
        self.tree.column("Order", anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        fit_tree_columns(self.tree)
        self.tree.bind("<Double-1>", lambda _e: self._edit_selected())
        self.tree.tag_configure("invalid", foreground=COLORS["danger"])
        self.tree.tag_configure("warning", foreground=COLORS["warning"])
        self.segment_warning = ttk.Label(card.content, text="", style="Error.TLabel", wraplength=900)

    def _refresh_enabled(self) -> None:
        enabled = bool(self.variables["thermal_enabled"].get())
        set_children_state(self.thermal_controls, enabled)
        for button in (
            self.add_regen_button,
            self.add_film_button,
            self.add_radiation_button,
            self.duplicate_button,
            self.remove_button,
            self.edit_button,
        ):
            button.state(["!disabled" if enabled else "disabled"])
        if not enabled:
            self.segment_warning.pack_forget()

    def _add_segment(self, kind: str) -> None:
        defaults = default_segment(kind, len(self.segments) + 1)
        dialog = SegmentDialog(self, defaults, self._regen_options())
        self.wait_window(dialog)
        if dialog.result:
            self.segments.append(dialog.result)
            self._refresh_tree()
            self._notify_segments_changed()

    def _selected_index(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            return None
        try:
            return int(selected[0])
        except (ValueError, IndexError):
            return None

    def _edit_selected(self) -> None:
        if not self.variables["thermal_enabled"].get():
            return
        index = self._selected_index()
        if index is None or not (0 <= index < len(self.segments)):
            messagebox.showinfo("Cooling segments", "Select a segment to edit.", parent=self)
            return
        dialog = SegmentDialog(self, copy.deepcopy(self.segments[index]), self._regen_options(exclude=index))
        self.wait_window(dialog)
        if dialog.result:
            self.segments[index] = dialog.result
            self._refresh_tree(select=index)
            self._notify_segments_changed()

    def _duplicate_selected(self) -> None:
        if not self.variables["thermal_enabled"].get():
            return
        index = self._selected_index()
        if index is None or not (0 <= index < len(self.segments)):
            messagebox.showinfo("Cooling segments", "Select a segment to duplicate.", parent=self)
            return
        clone = copy.deepcopy(self.segments[index])
        clone["id"] = uuid.uuid4().hex
        clone["name"] = f"{clone.get('name', clone['type'])} copy"
        self.segments.insert(index + 1, clone)
        self._refresh_tree(select=index + 1)
        self._notify_segments_changed()

    def _remove_selected(self) -> None:
        if not self.variables["thermal_enabled"].get():
            return
        index = self._selected_index()
        if index is None or not (0 <= index < len(self.segments)):
            messagebox.showinfo("Cooling segments", "Select a segment to remove.", parent=self)
            return
        segment = self.segments[index]
        if not messagebox.askyesno(
            "Remove cooling segment",
            f"Remove '{segment.get('name', segment['type'])}'? Linked segments will be marked invalid.",
            parent=self,
        ):
            return
        removed_id = segment.get("id")
        del self.segments[index]
        for other in self.segments:
            if other.get("coolant_source_id") == removed_id:
                other["link_broken"] = True
            if other.get("temperature_source_id") == removed_id:
                other["temperature_link_broken"] = True
        self._refresh_tree()
        self._notify_segments_changed()

    def _notify_segments_changed(self) -> None:
        callback = getattr(self.winfo_toplevel(), "_on_change", None)
        if callable(callback):
            callback()

    def _regen_options(self, exclude: int | None = None) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = []
        for index, segment in enumerate(self.segments):
            if index != exclude and segment.get("type") == "Regen":
                identifier = str(segment.get("id", ""))
                name = str(segment.get("name", f"Regen {index + 1}"))
                options.append((identifier, name))
        counts = {name: sum(label == name for _, label in options) for _, name in options}
        options = [(identifier, f"{name} [{identifier}]" if counts[name] > 1 else name)
                   for identifier, name in options]
        return options

    def _engine_values(self) -> dict[str, Any]:
        top = self.winfo_toplevel()
        pages = getattr(top, "pages", {})
        page = pages.get("engine") if isinstance(pages, dict) else None
        if page is not None and hasattr(page, "values"):
            try:
                return dict(page.values())
            except (tk.TclError, TypeError, ValueError):
                pass
        return {"oxidizer": "LOX", "fuel": "RP-1"}

    def _synchronize_linked_film_coolants(self) -> None:
        """Keep linked Film coolant identities consistent after every edit/load."""

        engine = self._engine_values()
        regen_ids = {
            str(segment.get("id", ""))
            for segment in self.segments
            if segment.get("type") == "Regen"
        }
        for segment in self.segments:
            if (
                segment.get("type") != "Film"
                or segment.get("temperature_mode") != "Temperature from Regen segment"
            ):
                continue
            source_id = str(segment.get("temperature_source_id", ""))
            coolant = resolve_effective_regen_coolant(source_id, self.segments, engine)
            if coolant is None:
                segment["temperature_link_broken"] = True
                continue
            segment["coolant"] = coolant
            if source_id not in regen_ids:
                segment["temperature_link_broken"] = True
            elif segment.get("temperature_link_broken"):
                segment["temperature_link_broken"] = False

    def _refresh_tree(self, select: int | None = None) -> None:
        self._synchronize_linked_film_coolants()
        self.tree.delete(*self.tree.get_children())
        warnings = validate_segment_layout(self.segments)
        warning_ids = {item for warning in warnings for item in warning.get("ids", [])}
        for index, segment in enumerate(self.segments):
            status = "Ready"
            tag = ""
            if segment.get("link_broken") or segment.get("temperature_link_broken"):
                status = "Broken segment link"
                tag = "invalid"
            elif segment.get("id") in warning_ids:
                status = "Range overlap"
                tag = "warning"
            location = segment_location_text(segment)
            detail = segment.get("coolant", segment.get("material", "-"))
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(index + 1, segment.get("type"), segment.get("name"), location, detail, status),
                tags=(tag,) if tag else (),
            )
        if select is not None and str(select) in self.tree.get_children():
            self.tree.selection_set(str(select))
            self.tree.see(str(select))
        if warnings:
            self.segment_warning.configure(text="  ".join(warning["message"] for warning in warnings))
            self.segment_warning.pack(fill="x", pady=(8, 0))
        else:
            self.segment_warning.pack_forget()

    def values(self) -> dict[str, Any]:
        self._synchronize_linked_film_coolants()
        result = super().values()
        result["segments"] = copy.deepcopy(self.segments)
        return result

    def load_values(self, values: dict[str, Any]) -> None:
        super().load_values(values)
        self.segments = copy.deepcopy(values.get("segments", []))
        self._refresh_tree()
        self._refresh_enabled()


def default_segment(kind: str, index: int) -> dict[str, Any]:
    common: dict[str, Any] = {"id": uuid.uuid4().hex, "type": kind, "name": f"{kind} {index}"}
    if kind == "Regen":
        common.update(
            {
                "x1": "TOP",
                "x2": "BOTTOM",
                "start_mode": "TOP",
                "start_mm": "0",
                "end_mode": "BOTTOM",
                "end_mm": "0",
                "conductivity_mode": "Material",
                "material": "CuCrZr",
                "thermal_conductivity": "330",
                "wall_thickness_mm": "1.0",
                "channel_height_1_mm": "2.0",
                "channel_height_min_mm": "1.0",
                "channel_height_2_mm": "2.0",
                "channel_width_mode": "Channel width",
                "channel_width_1_mm": "1.4",
                "channel_width_min_mm": "0.8",
                "channel_width_2_mm": "1.4",
                "rib_width_1_mm": "0.8",
                "rib_width_min_mm": "0.5",
                "rib_width_2_mm": "0.8",
                "channel_angle_deg": "2.0",
                "channel_count": "60",
                "roughness_enabled": False,
                "roughness_height_mm": "0.04",
                "roughness_step_mm": "0.10",
                "coolant_definition_mode": "Define coolant",
                "coolant_source_mode": "Engine fuel",
                "coolant": "Ethanol 100%",
                "coolant_inlet_pressure_bar": "25",
                "coolant_inlet_temperature_k": "293.15",
                "relative_mass_flow_pct": "100",
                "coolant_source_id": "",
                "reverse_coolant_flow": False,
                "tbc_enabled": False,
                "tbc_conductivity_w_mk": "1.5",
                "tbc_thickness_mm": "0.10",
            }
        )
    elif kind == "Film":
        common.update(
            {
                "position_mode": "Injector Face",
                "position_mm": "0",
                "coolant": "Ethanol 100%",
                "manual_coolant": "Ethanol 100%",
                "temperature_mode": "Specified temperature",
                "coolant_temperature_k": "293.15",
                "temperature_source_id": "",
                "orifice_enabled": False,
                "discharge_coefficient": "0.6",
                "orifice_count": "30",
                "relative_mass_flow_pct": "5.0",
            }
        )
    else:
        common.update(
            {
                "x1": "TOP",
                "x2": "BOTTOM",
                "start_mode": "TOP",
                "start_mm": "0",
                "end_mode": "BOTTOM",
                "end_mm": "0",
                "conductivity_mode": "Material",
                "material": "C103",
                "thermal_conductivity": "50",
                "wall_thickness_mm": "1.0",
                "tbc_enabled": False,
                "tbc_conductivity_w_mk": "1.5",
                "tbc_thickness_mm": "0.01",
                "emissivity": "0.8",
            }
        )
    return common


def _position_value(value: Any, *, top: float = -math.inf, bottom: float = math.inf) -> float | None:
    text = str(value).strip().upper()
    if text in {"TOP", "INJECTOR", "START", "UPSTREAM"}:
        return top
    if text in {"BOTTOM", "EXIT", "END", "DOWNSTREAM"}:
        return bottom
    if text in {"CONV_BOUNDARY", "BOUNDARY", "CONTRACTION BOUNDARY", "CONVERGENT BOUNDARY"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def validate_segment_layout(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    regen = [item for item in segments if item.get("type") == "Regen"]
    radiation = [item for item in segments if item.get("type") == "Radiation"]
    for reg in regen:
        r1, r2 = _position_value(reg.get("x1")), _position_value(reg.get("x2"))
        if r1 is None or r2 is None:
            continue
        rlo, rhi = sorted((r1, r2))
        for rad in radiation:
            d1, d2 = _position_value(rad.get("x1")), _position_value(rad.get("x2"))
            if d1 is None or d2 is None:
                continue
            dlo, dhi = sorted((d1, d2))
            if max(rlo, dlo) < min(rhi, dhi):
                warnings.append(
                    {
                        "ids": [reg.get("id"), rad.get("id")],
                        "message": f"Regen '{reg.get('name')}' overlaps Radiation '{rad.get('name')}'.",
                    }
                )
    for left_index, left in enumerate(regen):
        l1, l2 = _position_value(left.get("x1")), _position_value(left.get("x2"))
        if l1 is None or l2 is None:
            continue
        llo, lhi = sorted((l1, l2))
        for right in regen[left_index + 1 :]:
            r1, r2 = _position_value(right.get("x1")), _position_value(right.get("x2"))
            if r1 is None or r2 is None:
                continue
            rlo, rhi = sorted((r1, r2))
            if max(llo, rlo) < min(lhi, rhi):
                warnings.append(
                    {
                        "ids": [left.get("id"), right.get("id")],
                        "message": f"Regen '{left.get('name')}' overlaps Regen '{right.get('name')}'.",
                    }
                )
    for item in segments:
        if item.get("link_broken") or item.get("temperature_link_broken"):
            warnings.append(
                {"ids": [item.get("id")], "message": f"'{item.get('name')}' refers to a deleted Regen segment."}
            )
    return warnings


def segment_location_text(segment: dict[str, Any]) -> str:
    if segment.get("type") == "Film":
        position_mode = segment.get("position_mode")
        if position_mode == "Injector Face":
            return "Injector Face (0 mm)"
        if position_mode == "Chamber/convergent boundary":
            return "Chamber / convergent boundary"
        return f"x = {segment.get('position_mm', '?')} mm"
    labels = {
        "TOP": "TOP",
        "BOTTOM": "BOTTOM",
        "CONV_BOUNDARY": "Conv Boundary",
    }
    start = labels.get(str(segment.get("x1", "?")).upper(), f"{segment.get('x1', '?')} mm")
    end = labels.get(str(segment.get("x2", "?")).upper(), f"{segment.get('x2', '?')} mm")
    return f"{start} → {end}"


class SegmentDialog(tk.Toplevel):
    """Modal editor covering all Regen, Film, and Radiation properties."""

    def __init__(self, master: tk.Misc, segment: dict[str, Any], regen_options: list[tuple[str, str]]) -> None:
        super().__init__(master)
        self.segment = segment
        counts = {name: sum(label == name for _, label in regen_options) for _, name in regen_options}
        self.regen_options = [(identifier, f"{name} [{identifier}]" if counts[name] > 1 else name)
                              for identifier, name in regen_options]
        self.engine_values = self._read_engine_values()
        self._prepare_legacy_fields()
        self.result: dict[str, Any] | None = None
        self.vars: dict[str, tk.Variable] = {}
        self.title(f"{segment['type']} cooling segment")
        self.geometry("760x780")
        self.minsize(680, 620)
        self.transient(master.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        top = master.winfo_toplevel()
        apply_icon = getattr(top, "apply_child_icon", None)
        if callable(apply_icon):
            apply_icon(self)
        else:
            try:
                self.iconbitmap(top.iconbitmap())
            except tk.TclError:
                pass
        shell = ttk.Frame(self, style="Surface.TFrame")
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell, style="Header.TFrame", padding=(20, 15))
        header.pack(fill="x")
        ttk.Label(header, text=f"{segment['type']} segment", style="Title.TLabel").pack(anchor="w")
        ttk.Separator(shell).pack(fill="x")
        scroll = ScrollableFrame(shell, padding=18)
        scroll.pack(fill="both", expand=True)
        self.form = scroll.body
        self._build_common()
        if segment["type"] == "Regen":
            self._build_regen()
        elif segment["type"] == "Film":
            self._build_film()
        else:
            self._build_radiation()
        self.error = ttk.Label(shell, text="", style="Error.TLabel", wraplength=650)
        footer = ttk.Frame(shell, style="Surface.TFrame", padding=(18, 12))
        self.footer = footer
        footer.pack(fill="x")
        ttk.Button(footer, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="Apply segment", style="Primary.TButton", command=self._save).pack(
            side="right", padx=(0, 8)
        )
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._save())
        self.grab_set()
        self.after_idle(self._center)

    def _read_engine_values(self) -> dict[str, Any]:
        top = self.master.winfo_toplevel()
        pages = getattr(top, "pages", {})
        page = pages.get("engine") if isinstance(pages, dict) else None
        if page is not None and hasattr(page, "values"):
            try:
                return dict(page.values())
            except (tk.TclError, TypeError, ValueError):
                pass
        return {"oxidizer": "LOX", "fuel": "RP-1", "mixture_ratio": "1.0"}

    def _read_regen_segments(self) -> list[dict[str, Any]]:
        segments = getattr(self.master, "segments", None)
        if isinstance(segments, list):
            return segments
        top = self.master.winfo_toplevel()
        pages = getattr(top, "pages", {})
        page = pages.get("thermal_input") if isinstance(pages, dict) else None
        segments = getattr(page, "segments", None)
        return segments if isinstance(segments, list) else []

    def _selected_regen_id(self) -> str:
        return self.regen_label_to_id.get(self.linked_regen_label.get(), "")

    def _selected_regen_coolant(self) -> str | None:
        return resolve_effective_regen_coolant(
            self._selected_regen_id(),
            self._read_regen_segments(),
            self.engine_values,
        )

    def _prepare_legacy_fields(self) -> None:
        if self.segment.get("type") == "Film":
            # UI projects persist the descriptive position mode.  Also accept
            # core/legacy film mappings so an Injector Face selection survives
            # either serialization path without being confused with a generic
            # user-specified zero.
            mode = str(self.segment.get("position_mode", "")).strip()
            if mode.casefold() in {"injector face", "injector face (0 mm)"} or bool(
                self.segment.get("injector_face", False)
            ):
                self.segment["position_mode"] = "Injector Face"
                self.segment["position_mm"] = "0"
            elif not mode and bool(self.segment.get("chamber_contraction_boundary", False)):
                self.segment["position_mode"] = "Chamber/convergent boundary"
                self.segment.setdefault("position_mm", "0")
            elif not mode and self.segment.get("injection_location_mm") is not None:
                self.segment["position_mode"] = "Specified location"
                self.segment["position_mm"] = str(self.segment["injection_location_mm"])
        else:
            for endpoint, mode_key, value_key, primary, boundary in (
                ("x1", "start_mode", "start_mm", "TOP", "Conv Boundary"),
                ("x2", "end_mode", "end_mm", "BOTTOM", "Conv Boundary"),
            ):
                if mode_key in self.segment:
                    if self.segment[mode_key] == "Contraction boundary":
                        self.segment[mode_key] = "Conv Boundary"
                    continue
                value = str(self.segment.get(endpoint, primary)).strip()
                upper = value.upper()
                if upper == primary:
                    self.segment[mode_key] = primary
                    self.segment[value_key] = "0"
                elif upper in {"CONV_BOUNDARY", "BOUNDARY", "CONTRACTION BOUNDARY", "CONVERGENT BOUNDARY"}:
                    self.segment[mode_key] = boundary
                    self.segment[value_key] = "0"
                else:
                    self.segment[mode_key] = "Specified location"
                    self.segment[value_key] = value
        if self.segment.get("type") == "Regen" and "coolant_source_mode" not in self.segment:
            self.segment["coolant_source_mode"] = (
                "Receive from Regen segment"
                if self.segment.get("coolant_definition_mode") == "Receive from Regen segment"
                else "Custom coolant"
            )

    def var(self, key: str, default: Any = "") -> tk.Variable:
        value = self.segment.get(key, default)
        variable: tk.Variable
        if isinstance(value, bool):
            variable = tk.BooleanVar(self, value=value)
        else:
            variable = tk.StringVar(self, value=str(value))
        self.vars[key] = variable
        return variable

    def _center(self) -> None:
        self.update_idletasks()
        parent = self.master.winfo_toplevel()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")

    def _build_common(self) -> None:
        card = Card(self.form, "Segment identity and location")
        card.pack(fill="x", pady=(0, 12))
        columns = 3 if self.segment["type"] in {"Regen", "Film"} else 2
        fields = FieldGrid(card.content, columns=columns)
        fields.pack(fill="x")
        fields.add("Name", ttk.Entry(fields, textvariable=self.var("name")))
        if self.segment["type"] == "Film":
            position_mode = self.var("position_mode")
            fields.add(
                "Injection position",
                ttk.Combobox(
                    fields,
                    textvariable=position_mode,
                    values=("Injector Face", "Chamber/convergent boundary", "Specified location"),
                    state="readonly",
                ),
            )
            self.position_entry = ttk.Entry(fields, textvariable=self.var("position_mm"))
            fields.add("Specified location", self.position_entry, unit="mm")
            position_mode.trace_add("write", lambda *_: self._refresh())
        else:
            start_box = ttk.Frame(fields, style="Surface.TFrame")
            start_box.grid_columnconfigure(1, weight=1)
            start_mode = self.var("start_mode")
            ttk.Combobox(
                start_box,
                textvariable=start_mode,
                values=("TOP", "Conv Boundary", "Specified location"),
                state="readonly",
                width=13,
            ).grid(row=0, column=0, padx=(0, 7), sticky="ew")
            self.start_location_entry = ttk.Entry(start_box, textvariable=self.var("start_mm"), width=7)
            self.start_location_entry.grid(row=0, column=1, sticky="ew")
            ttk.Label(start_box, text="mm", style="Unit.TLabel").grid(row=0, column=2, padx=(6, 0))
            fields.add("Start", start_box)

            end_box = ttk.Frame(fields, style="Surface.TFrame")
            end_box.grid_columnconfigure(1, weight=1)
            end_mode = self.var("end_mode")
            ttk.Combobox(
                end_box,
                textvariable=end_mode,
                values=("Conv Boundary", "BOTTOM", "Specified location"),
                state="readonly",
                width=13,
            ).grid(row=0, column=0, padx=(0, 7), sticky="ew")
            self.end_location_entry = ttk.Entry(end_box, textvariable=self.var("end_mm"), width=7)
            self.end_location_entry.grid(row=0, column=1, sticky="ew")
            ttk.Label(end_box, text="mm", style="Unit.TLabel").grid(row=0, column=2, padx=(6, 0))
            fields.add("End", end_box)
            start_mode.trace_add("write", lambda *_: self._refresh())
            end_mode.trace_add("write", lambda *_: self._refresh())

    def _conductivity_fields(self, materials: tuple[str, ...]) -> tuple[ttk.Entry, ttk.Combobox]:
        card = Card(self.form, "Wall definition")
        card.pack(fill="x", pady=(0, 12))
        fields = FieldGrid(card.content, columns=2)
        fields.pack(fill="x")
        mode = self.var("conductivity_mode")
        fields.add(
            "Thermal conductivity source",
            ttk.Combobox(fields, textvariable=mode, values=("Material", "Specified value"), state="readonly"),
        )
        material = ttk.Combobox(fields, textvariable=self.var("material"), values=materials, state="readonly")
        fields.add("Wall material", material)
        conductivity = ttk.Entry(fields, textvariable=self.var("thermal_conductivity"))
        fields.add("Specified conductivity", conductivity, unit="W/(m·K)")
        fields.add("Inner wall thickness", ttk.Entry(fields, textvariable=self.var("wall_thickness_mm")), unit="mm")
        mode.trace_add("write", lambda *_: self._refresh())
        self.conductivity_entry = conductivity
        self.material_combo = material
        return conductivity, material

    def _build_regen(self) -> None:
        self._conductivity_fields(REGEN_MATERIALS)
        channel = Card(self.form, "Cooling channel geometry")
        channel.pack(fill="x", pady=(0, 12))
        fields = FieldGrid(channel.content, columns=3)
        fields.pack(fill="x")
        fields.add("Channel height hc1", ttk.Entry(fields, textvariable=self.var("channel_height_1_mm")), unit="mm")
        fields.add("Channel height hc min", ttk.Entry(fields, textvariable=self.var("channel_height_min_mm")), unit="mm")
        fields.add("Channel height hc2", ttk.Entry(fields, textvariable=self.var("channel_height_2_mm")), unit="mm")
        width_mode = self.var("channel_width_mode")
        fields.add(
            "Width definition",
            ttk.Combobox(
                fields,
                textvariable=width_mode,
                values=("Channel width", "Rib width", "Channel occupied angle"),
                state="readonly",
            ),
        )
        angle = ttk.Entry(fields, textvariable=self.var("channel_angle_deg"))
        fields.add("Occupied angle per channel", angle, unit="deg")
        fields.add("Number of channels", ttk.Entry(fields, textvariable=self.var("channel_count")))
        width_entries: list[ttk.Entry] = []
        for key, label in (
            ("channel_width_1_mm", "Channel width a1"),
            ("channel_width_min_mm", "Channel width a min"),
            ("channel_width_2_mm", "Channel width a2"),
            ("rib_width_1_mm", "Rib width b1"),
            ("rib_width_min_mm", "Rib width b min"),
            ("rib_width_2_mm", "Rib width b2"),
        ):
            entry = ttk.Entry(fields, textvariable=self.var(key))
            fields.add(label, entry, unit="mm")
            width_entries.append(entry)
        self.width_entries = width_entries
        self.channel_angle_entry = angle
        width_mode.trace_add("write", lambda *_: self._refresh())

        coolant = Card(self.form, "Coolant definition")
        coolant.pack(fill="x", pady=(0, 12))
        coolant_fields = FieldGrid(coolant.content, columns=2)
        coolant_fields.pack(fill="x")
        source_mode = self.var("coolant_source_mode")
        coolant_fields.add(
            "Coolant source",
            ttk.Combobox(
                coolant_fields,
                textvariable=source_mode,
                values=(
                    "Engine oxidizer",
                    "Engine fuel",
                    "Custom coolant",
                    "Receive from Regen segment",
                ),
                state="readonly",
            ),
        )
        labels = [label for _, label in self.regen_options]
        self.regen_label_to_id = {label: item_id for item_id, label in self.regen_options}
        current_id = self.segment.get("coolant_source_id", "")
        current_label = next((label for item_id, label in self.regen_options if item_id == current_id), "")
        self.linked_regen_label = tk.StringVar(self, value=current_label)
        self.linked_regen_combo = ttk.Combobox(
            coolant_fields, textvariable=self.linked_regen_label, values=labels, state="readonly"
        )
        coolant_fields.add("Source Regen segment", self.linked_regen_combo)
        self.coolant_combo = ttk.Combobox(
            coolant_fields, textvariable=self.var("coolant"), values=COOLANTS, state="readonly"
        )
        coolant_fields.add("Coolant", self.coolant_combo)
        self.coolant_pressure = ttk.Entry(coolant_fields, textvariable=self.var("coolant_inlet_pressure_bar"))
        coolant_fields.add("Inlet pressure", self.coolant_pressure, unit="bar(a)")
        self.coolant_temperature = ttk.Entry(coolant_fields, textvariable=self.var("coolant_inlet_temperature_k"))
        coolant_fields.add("Inlet temperature", self.coolant_temperature, unit="K")
        self.coolant_flow = ttk.Entry(coolant_fields, textvariable=self.var("relative_mass_flow_pct"))
        coolant_fields.add("Relative mass flow rate", self.coolant_flow, unit="% of engine flow")
        ttk.Checkbutton(
            coolant.content,
            text="Reverse default direction (flow with combustion gas)",
            variable=self.var("reverse_coolant_flow"),
        ).pack(anchor="w", pady=(6, 0))
        source_mode.trace_add("write", lambda *_: self._refresh())

        self._build_tbc(default_thickness="0.10")

        rough = Card(self.form, "Surface roughness")
        rough.pack(fill="x", pady=(0, 12))
        rough_enabled = self.var("roughness_enabled")
        ttk.Checkbutton(
            rough.content,
            text="Enable wall roughness",
            variable=rough_enabled,
            command=self._refresh,
        ).pack(anchor="w")
        self.rough_frame = FieldGrid(rough.content, columns=2)
        self.roughness_height_entry = ttk.Entry(
            self.rough_frame, textvariable=self.var("roughness_height_mm"))
        self.rough_frame.add(
            "Equivalent sand-grain height",
            self.roughness_height_entry,
            unit="mm",
        )
        self.roughness_step_entry = ttk.Entry(
            self.rough_frame, textvariable=self.var("roughness_step_mm"), state="disabled")
        self.rough_frame.add(
            "Roughness step",
            self.roughness_step_entry,
            unit="mm",
            hint="Spacing not used by this model",
        )
        if bool(rough_enabled.get()):
            self.rough_frame.pack(fill="x", pady=(6, 0))
        self.after_idle(self._refresh)

    def _build_film(self) -> None:
        card = Card(self.form, "Film coolant")
        card.pack(fill="x", pady=(0, 12))
        fields = FieldGrid(card.content, columns=2)
        fields.pack(fill="x")
        self._manual_film_coolant = str(
            self.segment.get("manual_coolant", self.segment.get("coolant", "Ethanol 100%"))
        )
        self._film_last_linked = (
            self.segment.get("temperature_mode") == "Temperature from Regen segment"
        )
        self.film_coolant_combo = ttk.Combobox(
            fields,
            textvariable=self.var("coolant"),
            values=COOLANTS[:-1],
            state="readonly",
        )
        fields.add("Coolant", self.film_coolant_combo)
        self.film_coolant_combo.bind(
            "<<ComboboxSelected>>", self._remember_manual_film_coolant, add="+"
        )
        temp_mode = self.var("temperature_mode")
        fields.add(
            "Temperature source",
            ttk.Combobox(
                fields,
                textvariable=temp_mode,
                values=("Specified temperature", "Temperature from Regen segment"),
                state="readonly",
            ),
        )
        self.film_temperature = ttk.Entry(fields, textvariable=self.var("coolant_temperature_k"))
        fields.add("Film temperature", self.film_temperature, unit="K")
        labels = [label for _, label in self.regen_options]
        self.regen_label_to_id = {label: item_id for item_id, label in self.regen_options}
        current_id = self.segment.get("temperature_source_id", "")
        current_label = next((label for item_id, label in self.regen_options if item_id == current_id), "")
        self.linked_regen_label = tk.StringVar(self, value=current_label)
        self.linked_regen_combo = ttk.Combobox(fields, textvariable=self.linked_regen_label, values=labels, state="readonly")
        fields.add("Regen segment", self.linked_regen_combo)
        fields.add("Relative film mass flow", ttk.Entry(fields, textvariable=self.var("relative_mass_flow_pct")), unit="% of engine flow")
        temp_mode.trace_add("write", lambda *_: self._refresh())
        self.linked_regen_label.trace_add("write", lambda *_: self._refresh())

        orifice = Card(self.form, "Film orifice sizing")
        orifice.pack(fill="x", pady=(0, 12))
        enabled = self.var("orifice_enabled")
        self.orifice_check = ttk.Checkbutton(
            orifice.content,
            text="Calculate film orifice diameter",
            variable=enabled,
            command=self._refresh,
        )
        self.orifice_check.pack(anchor="w")
        self.orifice_frame = FieldGrid(orifice.content, columns=2)
        self.orifice_frame.pack(fill="x", pady=(6, 0))
        self.orifice_frame.add("Discharge coefficient Cd", ttk.Entry(self.orifice_frame, textvariable=self.var("discharge_coefficient")))
        self.orifice_frame.add("Number of orifices", ttk.Entry(self.orifice_frame, textvariable=self.var("orifice_count")))
        self.after_idle(self._refresh)

    def _remember_manual_film_coolant(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self.vars["temperature_mode"].get() == "Specified temperature":
            value = str(self.vars["coolant"].get()).strip()
            if value:
                self._manual_film_coolant = value

    def _build_radiation(self) -> None:
        self._conductivity_fields(RADIATION_MATERIALS)
        card = Card(self.form, "External radiation")
        card.pack(fill="x", pady=(0, 12))
        fields = FieldGrid(card.content, columns=2)
        fields.pack(fill="x")
        fields.add("Outer-wall emissivity", ttk.Entry(fields, textvariable=self.var("emissivity")))
        self._build_tbc(default_thickness="0.01")
        self.after_idle(self._refresh)

    def _build_tbc(self, default_thickness: str) -> None:
        card = Card(self.form, "Thermal barrier coating")
        card.pack(fill="x", pady=(0, 12))
        enabled = self.var("tbc_enabled")
        ttk.Checkbutton(card.content, text="Enable inner-wall TBC", variable=enabled, command=self._refresh).pack(anchor="w")
        self.tbc_frame = FieldGrid(card.content, columns=2)
        self.tbc_frame.add("TBC conductivity", ttk.Entry(self.tbc_frame, textvariable=self.var("tbc_conductivity_w_mk", "1.5")), unit="W/(m·K)")
        self.tbc_frame.add("TBC thickness", ttk.Entry(self.tbc_frame, textvariable=self.var("tbc_thickness_mm", default_thickness)), unit="mm")
        if bool(enabled.get()):
            self.tbc_frame.pack(fill="x", pady=(6, 0))

    @staticmethod
    def _widget_state(widget: tk.Widget, enabled: bool) -> None:
        if isinstance(widget, ttk.Widget):
            widget.state(["!disabled" if enabled else "disabled"])

    def _refresh(self) -> None:
        kind = self.segment["type"]
        if kind == "Film":
            position_mode = self.vars["position_mode"].get()
            specified_position = position_mode == "Specified location"
            self._widget_state(self.position_entry, specified_position)
            if position_mode == "Injector Face":
                self.vars["position_mm"].set("0")
            linked = self.vars["temperature_mode"].get() == "Temperature from Regen segment"
            if linked and not self._film_last_linked:
                self._remember_manual_film_coolant()
            elif not linked and self._film_last_linked:
                self.vars["coolant"].set(self._manual_film_coolant)
            if linked:
                effective_coolant = self._selected_regen_coolant()
                self.vars["coolant"].set(
                    effective_coolant or "Unavailable — select a valid Regen segment"
                )
            self._film_last_linked = linked
            self._widget_state(self.film_coolant_combo, not linked)
            self._widget_state(self.film_temperature, not linked)
            self._widget_state(self.linked_regen_combo, linked and bool(self.regen_options))
            self._widget_state(self.orifice_check, linked)
            if not linked:
                self.vars["orifice_enabled"].set(False)
            set_children_state(self.orifice_frame, linked and bool(self.vars["orifice_enabled"].get()))
            return
        self._widget_state(
            self.start_location_entry,
            self.vars["start_mode"].get() == "Specified location",
        )
        self._widget_state(
            self.end_location_entry,
            self.vars["end_mode"].get() == "Specified location",
        )
        material = self.vars["conductivity_mode"].get() == "Material"
        self._widget_state(self.material_combo, material)
        self._widget_state(self.conductivity_entry, not material)
        if bool(self.vars["tbc_enabled"].get()):
            if not self.tbc_frame.winfo_manager():
                self.tbc_frame.pack(fill="x", pady=(6, 0))
        else:
            self.tbc_frame.pack_forget()
        if kind == "Regen":
            mode = self.vars["channel_width_mode"].get()
            for index, entry in enumerate(self.width_entries):
                self._widget_state(entry, (mode == "Channel width" and index < 3) or (mode == "Rib width" and index >= 3))
            self._widget_state(self.channel_angle_entry, mode == "Channel occupied angle")
            if bool(self.vars["roughness_enabled"].get()):
                if not self.rough_frame.winfo_manager():
                    self.rough_frame.pack(fill="x", pady=(6, 0))
            else:
                self.rough_frame.pack_forget()
            source_mode = self.vars["coolant_source_mode"].get()
            linked = source_mode == "Receive from Regen segment"
            engine_stream = source_mode in {"Engine oxidizer", "Engine fuel"}
            if engine_stream:
                try:
                    ratio = max(1.0e-12, float(self.engine_values.get("mixture_ratio", 1.0)))
                except (TypeError, ValueError):
                    ratio = 1.0
                if source_mode == "Engine oxidizer":
                    self.vars["coolant"].set(engine_coolant_name(self.engine_values, "oxidizer"))
                    fraction = 100.0 * ratio / (1.0 + ratio)
                else:
                    self.vars["coolant"].set(engine_coolant_name(self.engine_values, "fuel"))
                    fraction = 100.0 / (1.0 + ratio)
                self.vars["relative_mass_flow_pct"].set(f"{fraction:.6g}")
            self._widget_state(self.linked_regen_combo, linked and bool(self.regen_options))
            self._widget_state(self.coolant_combo, source_mode == "Custom coolant")
            self._widget_state(self.coolant_flow, source_mode == "Custom coolant")
            self._widget_state(self.coolant_pressure, not linked)
            self._widget_state(self.coolant_temperature, not linked)

    def _save(self) -> None:
        result = copy.deepcopy(self.segment)
        result.update({key: var.get() for key, var in self.vars.items()})
        name = str(result.get("name", "")).strip()
        if not name:
            self._show_error("Segment name is required.")
            return
        if self.segment["type"] != "Film":
            start_mode = str(result.get("start_mode", "TOP"))
            end_mode = str(result.get("end_mode", "BOTTOM"))
            result["x1"] = (
                "TOP"
                if start_mode == "TOP"
                else "CONV_BOUNDARY"
                if start_mode == "Conv Boundary"
                else str(result.get("start_mm", ""))
            )
            result["x2"] = (
                "BOTTOM"
                if end_mode == "BOTTOM"
                else "CONV_BOUNDARY"
                if end_mode == "Conv Boundary"
                else str(result.get("end_mm", ""))
            )
            for key, label in (("x1", "Start"), ("x2", "End")):
                if _position_value(result.get(key)) is None:
                    self._show_error(f"{label} must use a valid preset or non-negative numeric location.")
                    return
                if str(result.get(key, "")).upper() not in {
                    "TOP",
                    "BOTTOM",
                    "CONV_BOUNDARY",
                } and float(result[key]) < 0:
                    self._show_error(f"{label} location must be non-negative.")
                    return
            start = _position_value(result.get("x1"))
            end = _position_value(result.get("x2"))
            boundary_used = "CONV_BOUNDARY" in {str(result.get("x1")).upper(), str(result.get("x2")).upper()}
            if not boundary_used and start is not None and end is not None and start >= end:
                self._show_error("Segment End must be downstream of Start.")
                return
        else:
            if result.get("position_mode") == "Injector Face":
                result["position_mm"] = "0"
            elif result.get("position_mode") == "Specified location":
                try:
                    if float(result.get("position_mm", "")) < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    self._show_error("Specified film location must be a non-negative number.")
                    return
            if result.get("temperature_mode") == "Specified temperature":
                try:
                    if float(result.get("coolant_temperature_k", "")) <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    self._show_error("Film coolant temperature must be greater than zero kelvin.")
                    return
            if result.get("orifice_enabled"):
                try:
                    coefficient = float(result.get("discharge_coefficient", ""))
                    count_value = float(result.get("orifice_count", ""))
                    if not 0 < coefficient <= 1 or count_value < 1 or not count_value.is_integer():
                        raise ValueError
                except (TypeError, ValueError):
                    self._show_error("Orifice Cd must be in (0, 1] and hole count must be a positive integer.")
                    return
        numeric_issues = segment_numeric_issues(result)
        if numeric_issues:
            self._show_error(numeric_issues[0])
            return
        if self.segment["type"] == "Regen":
            linked = result.get("coolant_source_mode") == "Receive from Regen segment"
            result["coolant_definition_mode"] = "Receive from Regen segment" if linked else "Define coolant"
            if linked:
                label = self.linked_regen_label.get()
                source_id = self.regen_label_to_id.get(label, "")
                if not source_id:
                    self._show_error("Select a valid Regen segment as coolant source.")
                    return
                result["coolant_source_id"] = source_id
                result["link_broken"] = False
            else:
                result["coolant_source_id"] = ""
                result["link_broken"] = False
        if self.segment["type"] == "Film":
            linked = result.get("temperature_mode") == "Temperature from Regen segment"
            if linked:
                label = self.linked_regen_label.get()
                source_id = self.regen_label_to_id.get(label, "")
                if not source_id:
                    self._show_error("Select a valid Regen segment as film temperature source.")
                    return
                effective_coolant = resolve_effective_regen_coolant(
                    source_id,
                    self._read_regen_segments(),
                    self.engine_values,
                )
                if not effective_coolant:
                    self._show_error("The selected Regen segment has no valid coolant source.")
                    return
                result["temperature_source_id"] = source_id
                result["coolant"] = effective_coolant
                result["manual_coolant"] = self._manual_film_coolant
                result["temperature_link_broken"] = False
            else:
                result["temperature_source_id"] = ""
                result["coolant"] = self._manual_film_coolant
                result["manual_coolant"] = self._manual_film_coolant
                result["temperature_link_broken"] = False
        self.result = result
        self.destroy()

    def _show_error(self, text: str) -> None:
        self.error.configure(text=text)
        self.error.pack(fill="x", padx=18, pady=(8, 0), before=self.footer)
