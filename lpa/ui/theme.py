"""Visual theme and typography for the LPA desktop application."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


COLORS = {
    "window": "#f1f4f7",
    "surface": "#ffffff",
    "surface_alt": "#f7f9fb",
    "nav": "#17222e",
    "nav_hover": "#223243",
    "nav_active": "#0f6c8f",
    "accent": "#0f7fa6",
    "accent_hover": "#0b6c8e",
    "accent_soft": "#e3f2f7",
    "text": "#17212b",
    "muted": "#63717d",
    "border": "#d7dee5",
    "grid": "#dfe5ea",
    "success": "#18865a",
    "warning": "#b36a00",
    "danger": "#bd3e3e",
    "plot_hot": "#e5484d",
    "plot_wall": "#d42cff",
    "plot_cool": "#2667d8",
    "plot_contour": "#252a2f",
}

FONT_UI = "Segoe UI"
FONT_MONO = "Cascadia Mono"


def _install_combobox_wheel_guard(root: tk.Misc) -> None:
    """Keep the mouse wheel from silently changing combobox selections.

    Tk's native ``TCombobox`` class binding changes the selected item before a
    containing canvas receives the event.  Replace that class binding and, when
    the combobox lives in a scroll container, explicitly hand the event to the
    nearest container.  The marker is stored on the interpreter's root widget
    because ttk class bindings are interpreter-wide rather than toplevel-wide.
    """

    owner = root._root()  # type: ignore[attr-defined]
    if getattr(owner, "_lpa_combobox_wheel_guard", False):
        return

    def route_wheel(event: tk.Event) -> str:
        widget: tk.Misc | None = event.widget
        while widget is not None:
            handler = getattr(widget, "_lpa_handle_mousewheel", None)
            if callable(handler):
                handler(event)
                break
            widget = getattr(widget, "master", None)
        return "break"

    # Do not use add="+" here: the stock class script would already have
    # changed the value by the time an appended Python callback ran.
    owner.bind_class("TCombobox", "<MouseWheel>", route_wheel)
    owner.bind_class("TCombobox", "<Button-4>", route_wheel)
    owner.bind_class("TCombobox", "<Button-5>", route_wheel)
    setattr(owner, "_lpa_combobox_wheel_guard", True)


def _paint_box(image: tk.PhotoImage, color: str, x1: int, y1: int, x2: int, y2: int) -> None:
    """Fill an inclusive pixel rectangle in a small ttk indicator image."""

    image.put(color, to=(x1, y1, x2 + 1, y2 + 1))


def _checkbox_image(root: tk.Misc, *, selected: bool, disabled: bool = False) -> tk.PhotoImage:
    image = tk.PhotoImage(master=root, width=18, height=18)
    border = "#b8c2ca" if disabled else COLORS["border"]
    fill = "#d8e1e5" if disabled and selected else (COLORS["accent"] if selected else COLORS["surface"])
    _paint_box(image, border, 1, 1, 16, 16)
    _paint_box(image, fill, 2, 2, 15, 15)
    if selected:
        mark = "#f7fafb" if not disabled else "#81919a"
        # A compact, unmistakable tick.  Drawing it ourselves avoids the X
        # indicator used by some platform/theme combinations.
        for x, y in ((4, 8), (5, 9), (6, 10), (7, 11), (8, 10), (9, 9), (10, 8), (11, 7), (12, 6), (13, 5)):
            _paint_box(image, mark, x, y, min(x + 1, 16), min(y + 1, 16))
    return image


def _radio_image(root: tk.Misc, *, selected: bool, disabled: bool = False) -> tk.PhotoImage:
    image = tk.PhotoImage(master=root, width=18, height=18)
    border = "#b8c2ca" if disabled else COLORS["border"]
    fill = "#eef2f4" if disabled else COLORS["surface"]
    # Pixel-rounded outer ring.
    for y, span in enumerate((0, 0, 5, 3, 2, 2, 1, 1, 1, 1, 1, 1, 2, 2, 3, 5, 0, 0)):
        if span:
            _paint_box(image, border, span, y, 17 - span, y)
    for y, span in enumerate((0, 0, 0, 5, 4, 3, 3, 2, 2, 2, 2, 3, 3, 4, 5, 0, 0, 0)):
        if span:
            _paint_box(image, fill, span, y, 17 - span, y)
    if selected:
        dot = "#81919a" if disabled else COLORS["accent"]
        for y, span in ((6, 7), (7, 6), (8, 6), (9, 6), (10, 6), (11, 7)):
            _paint_box(image, dot, span, y, 17 - span, y)
    return image


def _replace_indicator(
    layout: list[tuple[str, dict[str, object]]],
    suffix: str,
    replacement: str,
) -> list[tuple[str, dict[str, object]]]:
    """Return a ttk layout with only its indicator element replaced."""

    result: list[tuple[str, dict[str, object]]] = []
    for element, options in layout:
        copied = dict(options)
        children = copied.get("children")
        if isinstance(children, list):
            copied["children"] = _replace_indicator(children, suffix, replacement)
        result.append((replacement if element.endswith(suffix) else element, copied))
    return result


def _install_selection_indicators(root: tk.Misc, style: ttk.Style) -> None:
    """Install stable, high-contrast check and radio indicators for clam."""

    owner = root._root()  # type: ignore[attr-defined]
    if getattr(owner, "_lpa_selection_indicator_images", None):
        return

    images = {
        "check_off": _checkbox_image(owner, selected=False),
        "check_on": _checkbox_image(owner, selected=True),
        "check_off_disabled": _checkbox_image(owner, selected=False, disabled=True),
        "check_on_disabled": _checkbox_image(owner, selected=True, disabled=True),
        "radio_off": _radio_image(owner, selected=False),
        "radio_on": _radio_image(owner, selected=True),
        "radio_off_disabled": _radio_image(owner, selected=False, disabled=True),
        "radio_on_disabled": _radio_image(owner, selected=True, disabled=True),
    }
    try:
        style.element_create(
            "LPA.Check.indicator",
            "image",
            images["check_off"],
            ("disabled", "selected", images["check_on_disabled"]),
            ("disabled", images["check_off_disabled"]),
            ("selected", images["check_on"]),
            border=0,
            sticky="",
        )
        style.element_create(
            "LPA.Radio.indicator",
            "image",
            images["radio_off"],
            ("disabled", "selected", images["radio_on_disabled"]),
            ("disabled", images["radio_off_disabled"]),
            ("selected", images["radio_on"]),
            border=0,
            sticky="",
        )
        style.layout(
            "TCheckbutton",
            _replace_indicator(style.layout("TCheckbutton"), "Checkbutton.indicator", "LPA.Check.indicator"),
        )
        style.layout(
            "TRadiobutton",
            _replace_indicator(style.layout("TRadiobutton"), "Radiobutton.indicator", "LPA.Radio.indicator"),
        )
    except tk.TclError:
        # A second style object for the same interpreter may find the elements
        # already registered.  The retained images still keep them alive.
        pass
    setattr(owner, "_lpa_selection_indicator_images", images)


def apply_theme(root: tk.Misc) -> ttk.Style:
    """Install LPA's compact, high-contrast engineering theme."""

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.option_add("*Font", (FONT_UI, 10))
    root.option_add("*tearOff", False)
    root.option_add("*Menu.Font", (FONT_UI, 10))
    root.option_add("*Menu.background", COLORS["nav"])
    root.option_add("*Menu.foreground", "#dbe4ec")
    root.option_add("*Menu.activeBackground", COLORS["nav_hover"])
    root.option_add("*Menu.activeForeground", "#ffffff")
    root.option_add("*Menu.selectColor", COLORS["accent"])
    root.option_add("*Menu.borderWidth", 0)
    root.option_add("*Menu.activeBorderWidth", 0)
    root.option_add("*Text.Font", (FONT_UI, 10))
    root.option_add("*Listbox.Font", (FONT_UI, 10))

    style.configure(".", font=(FONT_UI, 10), foreground=COLORS["text"])
    style.configure("TFrame", background=COLORS["window"])
    style.configure("Surface.TFrame", background=COLORS["surface"])
    style.configure("Alt.TFrame", background=COLORS["surface_alt"])
    style.configure("Nav.TFrame", background=COLORS["nav"])
    style.configure("Header.TFrame", background=COLORS["surface"])
    style.configure("Card.TFrame", background=COLORS["surface"], relief="flat")

    style.configure("TLabel", background=COLORS["window"], foreground=COLORS["text"])
    style.configure("Surface.TLabel", background=COLORS["surface"])
    style.configure("Muted.TLabel", background=COLORS["surface"], foreground=COLORS["muted"])
    style.configure(
        "Title.TLabel",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        font=(FONT_UI, 18, "bold"),
    )
    style.configure(
        "Subtitle.TLabel",
        background=COLORS["surface"],
        foreground=COLORS["muted"],
        font=(FONT_UI, 9),
    )
    style.configure(
        "PageTitle.TLabel",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        font=(FONT_UI, 15, "bold"),
    )
    style.configure(
        "Section.TLabel",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        font=(FONT_UI, 12, "bold"),
    )
    style.configure(
        "Field.TLabel",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        font=(FONT_UI, 10, "bold"),
    )
    style.configure(
        "Unit.TLabel",
        background=COLORS["surface"],
        foreground=COLORS["muted"],
        font=(FONT_UI, 9),
    )
    style.configure(
        "NavGroup.TLabel",
        background=COLORS["nav"],
        foreground="#90a1b2",
        font=(FONT_UI, 8, "bold"),
    )
    style.configure(
        "NavBrand.TLabel",
        background=COLORS["nav"],
        foreground="#ffffff",
        font=(FONT_UI, 17, "bold"),
    )
    style.configure(
        "NavCaption.TLabel",
        background=COLORS["nav"],
        foreground="#a9b8c6",
        font=(FONT_UI, 8),
    )
    style.configure(
        "Badge.TLabel",
        background=COLORS["accent_soft"],
        foreground=COLORS["accent"],
        font=(FONT_UI, 9, "bold"),
        padding=(8, 3),
    )
    style.configure(
        "Warning.TLabel",
        background="#fff3df",
        foreground=COLORS["warning"],
        padding=(10, 7),
    )
    style.configure(
        "Error.TLabel",
        background="#fdebec",
        foreground=COLORS["danger"],
        padding=(10, 7),
    )

    style.configure(
        "TButton",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        focusthickness=1,
        focuscolor=COLORS["accent"],
        padding=(12, 7),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[("active", COLORS["surface_alt"]), ("pressed", COLORS["accent_soft"])],
        bordercolor=[("focus", COLORS["accent"])],
    )
    style.configure(
        "Primary.TButton",
        background=COLORS["accent"],
        foreground="#ffffff",
        bordercolor=COLORS["accent"],
        font=(FONT_UI, 10, "bold"),
        padding=(15, 8),
    )
    style.map(
        "Primary.TButton",
        background=[("active", COLORS["accent_hover"]), ("disabled", "#9eb8c2")],
        foreground=[("disabled", "#eef4f6")],
    )
    style.configure(
        "Danger.TButton",
        foreground=COLORS["danger"],
        bordercolor="#e8c6c6",
    )
    style.configure(
        "Nav.TButton",
        background=COLORS["nav"],
        foreground="#dbe4ec",
        borderwidth=0,
        anchor="w",
        padding=(17, 10),
        font=(FONT_UI, 10),
    )
    style.map(
        "Nav.TButton",
        background=[("active", COLORS["nav_hover"]), ("pressed", COLORS["nav_active"])],
        foreground=[("active", "#ffffff")],
    )
    style.configure(
        "NavActive.TButton",
        background=COLORS["nav_active"],
        foreground="#ffffff",
        borderwidth=0,
        anchor="w",
        padding=(17, 10),
        font=(FONT_UI, 10, "bold"),
    )
    style.map(
        "NavActive.TButton",
        background=[("pressed", COLORS["accent_hover"]), ("active", COLORS["nav_active"])],
        foreground=[("disabled", "#b8c5cf"), ("active", "#ffffff"), ("pressed", "#ffffff")],
    )

    field_options = dict(
        fieldbackground=COLORS["surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        insertcolor=COLORS["text"],
        padding=(7, 6),
    )
    style.configure("TEntry", **field_options)
    style.configure("TCombobox", **field_options, arrowcolor=COLORS["muted"])
    style.map(
        "TEntry",
        bordercolor=[("focus", COLORS["accent"]), ("invalid", COLORS["danger"])],
        fieldbackground=[("disabled", "#edf0f2")],
    )
    style.map(
        "TCombobox",
        bordercolor=[("focus", COLORS["accent"])],
        fieldbackground=[("readonly", COLORS["surface"]), ("disabled", "#edf0f2")],
        foreground=[("disabled", "#89949e")],
    )
    style.configure("TCheckbutton", background=COLORS["surface"], padding=(0, 3))
    style.configure("TRadiobutton", background=COLORS["surface"], padding=(0, 3))
    style.map(
        "TCheckbutton",
        background=[("active", COLORS["surface"])],
        foreground=[("disabled", COLORS["muted"])],
    )
    style.map(
        "TRadiobutton",
        background=[("active", COLORS["surface"])],
        foreground=[("disabled", COLORS["muted"])],
    )

    style.configure(
        "Treeview",
        background=COLORS["surface"],
        fieldbackground=COLORS["surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        rowheight=28,
        font=(FONT_UI, 9),
    )
    style.configure(
        "Treeview.Heading",
        background="#e9eef2",
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        font=(FONT_UI, 9, "bold"),
        padding=(6, 6),
    )
    style.map("Treeview", background=[("selected", COLORS["accent_soft"])], foreground=[("selected", COLORS["text"])])

    style.configure("TNotebook", background=COLORS["window"], borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=COLORS["window"],
        foreground=COLORS["muted"],
        borderwidth=0,
        padding=(16, 9),
        font=(FONT_UI, 9, "bold"),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", COLORS["surface"])],
        foreground=[("selected", COLORS["accent"])],
    )
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor="#e2e8ed",
        background=COLORS["accent"],
        bordercolor="#e2e8ed",
        lightcolor=COLORS["accent"],
        darkcolor=COLORS["accent"],
    )
    style.configure("TSeparator", background=COLORS["border"])
    scrollbar_options = dict(
        background=COLORS["accent"],
        troughcolor="#e2e8ed",
        bordercolor="#e2e8ed",
        lightcolor=COLORS["accent"],
        darkcolor=COLORS["accent"],
        arrowcolor="#ffffff",
        relief="flat",
        borderwidth=0,
        gripcount=0,
        width=14,
        arrowsize=11,
    )
    for scrollbar_style in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(scrollbar_style, **scrollbar_options)
        style.map(
            scrollbar_style,
            background=[("pressed", COLORS["nav_active"]), ("active", COLORS["accent_hover"])],
            arrowcolor=[("disabled", "#aab5bd"), ("active", "#ffffff")],
            lightcolor=[("pressed", COLORS["nav_active"]), ("active", COLORS["accent_hover"])],
            darkcolor=[("pressed", COLORS["nav_active"]), ("active", COLORS["accent_hover"])],
        )
    style.configure(
        "TLabelframe",
        background=COLORS["surface"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        font=(FONT_UI, 12, "bold"),
    )
    _install_combobox_wheel_guard(root)
    _install_selection_indicators(root, style)
    return style
