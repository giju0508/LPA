from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import pytest

from lpa.ui.theme import COLORS, apply_theme
from lpa.ui.widgets import ScrollableFrame


@pytest.fixture(scope="module")
def themed_root() -> tk.Tk:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk is unavailable: {exc}")
    root.geometry("420x320+0+0")
    apply_theme(root)
    root.update()
    try:
        yield root
    finally:
        if root.winfo_exists():
            root.destroy()


def test_short_scrollable_frame_stays_at_top_with_full_thumb(themed_root: tk.Tk) -> None:
    frame = ScrollableFrame(themed_root, padding=8)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame.body, text="Short form", style="Surface.TLabel").pack()
    themed_root.update()

    assert frame._scrollable is False
    assert frame.canvas.yview() == pytest.approx((0.0, 1.0))
    assert frame.scrollbar.get() == pytest.approx((0.0, 1.0))

    before = frame.canvas.yview()
    assert frame._on_mousewheel(SimpleNamespace(delta=120, num=0)) == "break"
    assert frame.canvas.yview() == pytest.approx(before)
    frame.destroy()
    themed_root.update()


def test_scrollable_frame_preserves_unrelated_global_wheel_binding(themed_root: tk.Tk) -> None:
    marker = themed_root.bind_all("<MouseWheel>", lambda _event: None, add="+")
    before = themed_root.bind_class("all", "<MouseWheel>")
    frame = ScrollableFrame(themed_root)
    frame.pack(fill="both", expand=True)
    themed_root.update()
    frame.destroy()
    themed_root.update()

    after = themed_root.bind_class("all", "<MouseWheel>")
    assert marker
    assert marker in before
    assert marker in after


def test_combobox_wheel_keeps_value_and_scrolls_form(themed_root: tk.Tk) -> None:
    frame = ScrollableFrame(themed_root, padding=8)
    frame.pack(fill="both", expand=True)
    combo = ttk.Combobox(frame.body, values=("LOX", "GOX", "N2O"), state="readonly")
    combo.current(1)
    combo.pack(fill="x")
    for index in range(45):
        ttk.Label(frame.body, text=f"Field {index}", style="Surface.TLabel").pack(fill="x", pady=3)
    themed_root.update()

    before = frame.canvas.yview()[0]
    combo.event_generate("<MouseWheel>", delta=-120)
    themed_root.update()

    assert combo.current() == 1
    assert frame.canvas.yview()[0] > before
    frame.destroy()
    themed_root.update()


def test_navigation_hover_and_menu_colors_remain_readable(themed_root: tk.Tk) -> None:
    style = ttk.Style(themed_root)
    assert style.lookup("Nav.TButton", "background", ("active",)) == COLORS["nav_hover"]
    assert style.lookup("Nav.TButton", "foreground", ("active",)) == "#ffffff"
    assert style.lookup("NavActive.TButton", "background", ("active",)) == COLORS["nav_active"]
    assert style.lookup("NavActive.TButton", "foreground", ("active",)) == "#ffffff"

    menu = tk.Menu(themed_root, tearoff=False)
    assert str(menu.cget("activebackground")) == COLORS["nav_hover"]
    assert str(menu.cget("activeforeground")) == "#ffffff"
    menu.destroy()


def test_scrollbar_and_selection_indicators_use_lpa_theme(themed_root: tk.Tk) -> None:
    style = ttk.Style(themed_root)
    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        assert style.lookup(name, "troughcolor") == "#e2e8ed"
        assert style.lookup(name, "background") == COLORS["accent"]
        assert int(style.lookup(name, "width")) == 14
        assert int(style.lookup(name, "arrowsize")) == 11

    check_layout = repr(style.layout("TCheckbutton"))
    radio_layout = repr(style.layout("TRadiobutton"))
    assert "LPA.Check.indicator" in check_layout
    assert "LPA.Radio.indicator" in radio_layout
    assert hasattr(themed_root, "_lpa_selection_indicator_images")
