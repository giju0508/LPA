"""Reusable Tk widgets used throughout LPA."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable, Iterable
from tkinter import ttk
from typing import Any

from .theme import COLORS, FONT_UI, _install_combobox_wheel_guard


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable frame that also supports the mouse wheel."""

    def __init__(self, master: tk.Misc, *, padding: int = 20, **kwargs: Any) -> None:
        super().__init__(master, style="Surface.TFrame", **kwargs)
        self.canvas = tk.Canvas(
            self,
            background=COLORS["surface"],
            highlightthickness=0,
            borderwidth=0,
        )
        self._scrollable = False
        self._wheel_bindings: list[tuple[str, str]] = []
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, style="Surface.TFrame", padding=padding)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.body.bind("<Configure>", self._on_body_configure, add="+")
        self.canvas.bind("<Configure>", self._on_canvas_configure, add="+")
        _install_combobox_wheel_guard(self)
        self._bind_mousewheel()
        self.bind("<Destroy>", self._release_mousewheel_bindings, add="+")

    def _on_body_configure(self, _event: tk.Event) -> None:
        self._sync_scrollregion()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._sync_scrollregion()

    def _sync_scrollregion(self) -> None:
        """Match the scroll extent to the viewport when content is shorter."""

        try:
            bbox = self.canvas.bbox(self._window)
            viewport_width = max(1, self.canvas.winfo_width())
            viewport_height = max(1, self.canvas.winfo_height())
        except tk.TclError:
            return
        if bbox is None:
            return

        content_width = max(0, bbox[2] - bbox[0])
        content_height = max(0, bbox[3] - bbox[1])
        self._scrollable = content_height > viewport_height
        self.canvas.configure(
            scrollregion=(
                0,
                0,
                max(viewport_width, content_width),
                max(viewport_height, content_height),
            )
        )
        if not self._scrollable:
            self.canvas.yview_moveto(0.0)
            # Canvas rounding can briefly report a fractional thumb while it
            # processes a resize; force the correct visual state immediately.
            self.scrollbar.set(0.0, 1.0)

    def _bind_mousewheel(self) -> None:
        """Route descendant wheel events without modifying the global bindtag."""

        top = self.winfo_toplevel()
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            binding_id = top.bind(sequence, self._route_mousewheel, add="+")
            if binding_id:
                self._wheel_bindings.append((sequence, binding_id))

    def _release_mousewheel_bindings(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        try:
            top = self.winfo_toplevel()
            for sequence, binding_id in self._wheel_bindings:
                top.unbind(sequence, binding_id)
        except tk.TclError:
            pass
        self._wheel_bindings.clear()

    @staticmethod
    def _nearest_scroll_container(widget: tk.Misc | None) -> tk.Misc | None:
        while widget is not None:
            if callable(getattr(widget, "_lpa_handle_mousewheel", None)):
                return widget
            widget = getattr(widget, "master", None)
        return None

    def _route_mousewheel(self, event: tk.Event) -> str | None:
        if self._nearest_scroll_container(event.widget) is not self:
            return None
        return self._lpa_handle_mousewheel(event)

    def _lpa_handle_mousewheel(self, event: tk.Event) -> str:
        self._sync_scrollregion()
        if not self._scrollable:
            self.canvas.yview_moveto(0.0)
            self.scrollbar.set(0.0, 1.0)
            return "break"

        button = getattr(event, "num", None)
        if button == 4:
            delta = -1
        elif button == 5:
            delta = 1
        else:
            raw_delta = int(getattr(event, "delta", 0) or 0)
            if raw_delta == 0:
                return "break"
            delta = -int(raw_delta / 120)
            if delta == 0:
                delta = -1 if raw_delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")
        return "break"

    def _on_mousewheel(self, event: tk.Event) -> str:
        """Backward-compatible direct wheel handler used by older callers."""

        return self._lpa_handle_mousewheel(event)

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0.0)


class Card(ttk.Frame):
    """A titled, bordered content group."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        description: str = "",
        *,
        columns: int = 2,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style="Card.TFrame", padding=(16, 13), **kwargs)
        self.configure(relief="solid", borderwidth=1)
        self.grid_columnconfigure(0, weight=1)
        heading = ttk.Frame(self, style="Surface.TFrame")
        heading.grid(row=0, column=0, sticky="ew", columnspan=max(columns, 1), pady=(0, 10))
        ttk.Label(heading, text=title, style="Section.TLabel").pack(side="left")
        if description:
            ttk.Label(heading, text=description, style="Muted.TLabel", wraplength=700).pack(
                side="left", padx=(12, 0)
            )
        ttk.Separator(self).grid(row=1, column=0, sticky="ew", columnspan=max(columns, 1), pady=(0, 11))
        self.content = ttk.Frame(self, style="Surface.TFrame")
        self.content.grid(row=2, column=0, sticky="nsew", columnspan=max(columns, 1))
        self.content.grid_columnconfigure(tuple(range(max(columns, 1))), weight=1, uniform="card")


class FieldGrid(ttk.Frame):
    """Two-column responsive form grid with consistent labels and units."""

    def __init__(self, master: tk.Misc, *, columns: int = 2) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.columns = columns
        self._count = 0
        for col in range(columns):
            # Each logical field owns value, unit, and gutter columns.  Form
            # controls are direct children of FieldGrid, avoiding Tk's fragile
            # cross-parent `grid -in` stacking semantics.
            self.grid_columnconfigure(col * 3, weight=1, uniform="fields")
            self.grid_columnconfigure(col * 3 + 1, weight=0)
            self.grid_columnconfigure(col * 3 + 2, minsize=16, weight=0)

    def add(
        self,
        label: str,
        widget: tk.Widget,
        *,
        unit: str = "",
        hint: str = "",
        columnspan: int = 1,
    ) -> ttk.Frame:
        index = self._count
        row = index // self.columns
        col = index % self.columns
        if columnspan > 1 and col != 0:
            self._count += self.columns - col
            index = self._count
            row = index // self.columns
            col = 0
        start_column = col * 3
        base_row = row * 3
        value_span = max(1, columnspan * 3 - 2)
        label_span = max(2, columnspan * 3 - 1)
        field_label = ttk.Label(self, text=label, style="Field.TLabel", wraplength=280)
        field_label.grid(
            row=base_row,
            column=start_column,
            sticky="w",
            columnspan=label_span,
            pady=(0, 4),
        )
        self.bind("<Configure>", lambda event, item=field_label, span=columnspan:
                  item.configure(wraplength=max(80, event.width * span // self.columns - 20)), add="+")
        widget.grid(
            row=base_row + 1,
            column=start_column,
            columnspan=value_span,
            sticky="ew",
            pady=(0, 11 if not hint else 0),
        )
        if unit:
            unit_column = start_column + value_span
            ttk.Label(self, text=unit, style="Unit.TLabel").grid(
                row=base_row + 1,
                column=unit_column,
                padx=(7, 0),
                pady=(0, 11 if not hint else 0),
                sticky="w",
            )
        if hint:
            hint_label = ttk.Label(self, text=hint, style="Muted.TLabel", wraplength=360)
            hint_label.grid(
                row=base_row + 2,
                column=start_column,
                columnspan=label_span,
                sticky="w",
                pady=(3, 11),
            )
            self.bind(
                "<Configure>",
                lambda event, label_widget=hint_label, span=columnspan: label_widget.configure(
                    wraplength=max(120, event.width * span // self.columns - 28)
                ),
                add="+",
            )
        self._count += columnspan
        return self


class UnitEntry(ttk.Frame):
    """Entry with a compact unit suffix inside a common container."""

    def __init__(
        self,
        master: tk.Misc,
        variable: tk.Variable,
        unit: str,
        *,
        width: int = 12,
        state: str = "normal",
    ) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.grid_columnconfigure(0, weight=1)
        self.entry = ttk.Entry(self, textvariable=variable, width=width, state=state)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.unit_label = ttk.Label(self, text=unit, style="Muted.TLabel")
        self.unit_label.grid(row=0, column=1, padx=(7, 0))


class Switch(ttk.Checkbutton):
    """A checkbutton with button-like switch semantics."""

    def __init__(self, master: tk.Misc, text: str, variable: tk.Variable, command: Callable[[], None] | None = None):
        super().__init__(master, text=text, variable=variable, command=command, style="TCheckbutton")


class EmptyState(ttk.Frame):
    """Friendly placeholder for result panels before analysis."""

    def __init__(self, master: tk.Misc, title: str, message: str) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        box = ttk.Frame(self, style="Surface.TFrame")
        box.grid(row=0, column=0)
        ttk.Label(box, text="◈", style="Surface.TLabel", foreground=COLORS["accent"], font=(FONT_UI, 30)).pack()
        ttk.Label(box, text=title, style="Section.TLabel").pack(pady=(7, 3))
        ttk.Label(box, text=message, style="Muted.TLabel", justify="center").pack()


class Tooltip:
    """Small delayed tooltip with no third-party dependency."""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 550) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event: tk.Event) -> None:
        self._after = self.widget.after(self.delay_ms, self._show)

    def _show(self) -> None:
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self._tip,
            text=self.text,
            justify="left",
            background="#17222e",
            foreground="#ffffff",
            relief="solid",
            borderwidth=1,
            font=(FONT_UI, 9),
            padx=8,
            pady=5,
            wraplength=360,
        )
        label.pack()

    def _hide(self, _event: tk.Event | None = None) -> None:
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        if self._tip:
            self._tip.destroy()
            self._tip = None


def set_children_state(parent: tk.Misc, enabled: bool) -> None:
    """Recursively enable/disable ttk input controls."""

    state = "!disabled" if enabled else "disabled"
    for child in parent.winfo_children():
        if isinstance(child, (ttk.Entry, ttk.Combobox, ttk.Checkbutton, ttk.Radiobutton, ttk.Button)):
            try:
                child.state([state])
            except tk.TclError:
                pass
        set_children_state(child, enabled)


def configure_tree_columns(tree: ttk.Treeview, specifications: Iterable[tuple[str, int, str]]) -> None:
    for name, width, anchor in specifications:
        tree.heading(name, text=name)
        tree.column(name, width=width, minwidth=60, anchor=anchor, stretch=True)


def fit_tree_columns(tree: ttk.Treeview) -> None:
    """Keep headings readable at each DPI and provide horizontal access."""
    font = tkfont.Font(root=tree, font=ttk.Style(tree).lookup("Treeview.Heading", "font"))
    value_font = tkfont.Font(root=tree, font=ttk.Style(tree).lookup("Treeview", "font"))
    rows = [tree.item(item, "values") for item in tree.get_children()]
    for index, column in enumerate(tree.cget("columns")):
        content_width = max((value_font.measure(str(row[index])) for row in rows if index < len(row)), default=0)
        minimum = max(45, font.measure(str(tree.heading(column, "text"))) + 18, content_width + 14)
        tree.column(column, minwidth=minimum, width=max(minimum, int(tree.column(column, "width"))))
    parent = tree.master
    tree.pack_forget()
    vertical = []
    for child in parent.winfo_children():
        if isinstance(child, ttk.Scrollbar) and str(child.cget("orient")) == "vertical":
            child.pack_forget()
            vertical.append(child)
    if not vertical and len(rows) > int(tree.cget("height")):
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        vertical.append(scrollbar)
    tree.grid(row=0, column=0, sticky="nsew")
    parent.grid_columnconfigure(0, weight=1)
    parent.grid_rowconfigure(0, weight=1)
    for child in vertical:
        child.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    tree.configure(xscrollcommand=horizontal.set)
    def display_scrollbar(_event: tk.Event | None = None) -> None:
        total = sum(int(tree.column(column, "width")) for column in tree.cget("columns"))
        if total > tree.winfo_width() - 3:
            horizontal.grid()
        else:
            horizontal.grid_remove()
    tree.bind("<Configure>", display_scrollbar, add="+")
    tree.after_idle(display_scrollbar)
