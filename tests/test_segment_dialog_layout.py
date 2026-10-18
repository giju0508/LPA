from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from tkinter import ttk

import pytest

from lpa.ui.input_views import SegmentDialog, default_segment
from lpa.ui.widgets import Card


def _walk(widget: tk.Misc) -> Iterator[tk.Misc]:
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _label(dialog: SegmentDialog, text: str) -> ttk.Label:
    return next(
        widget
        for widget in _walk(dialog)
        if isinstance(widget, ttk.Label) and str(widget.cget("text")) == text
    )


@pytest.fixture(scope="module")
def root() -> Iterator[tk.Tk]:
    window = tk.Tk()
    window.withdraw()
    try:
        yield window
    finally:
        if window.winfo_exists():
            window.destroy()


def test_regen_dialog_uses_compact_requested_field_order(root: tk.Tk) -> None:
    dialog = SegmentDialog(root, default_segment("Regen", 1), [])
    try:
        dialog.update()

        identity_rows = {
            int(_label(dialog, name).grid_info()["row"])
            for name in ("Name", "Start", "End")
        }
        assert identity_rows == {0}
        assert not any(
            isinstance(widget, ttk.Label)
            and "Temperature-dependent conductivity" in str(widget.cget("text"))
            for widget in _walk(dialog)
        )

        width_row = int(_label(dialog, "Width definition").grid_info()["row"])
        assert {
            int(_label(dialog, name).grid_info()["row"])
            for name in ("Occupied angle per channel", "Number of channels")
        } == {width_row}
        channel_width_row = int(_label(dialog, "Channel width a1").grid_info()["row"])
        assert {
            int(_label(dialog, name).grid_info()["row"])
            for name in ("Channel width a min", "Channel width a2")
        } == {channel_width_row}
        rib_width_row = int(_label(dialog, "Rib width b1").grid_info()["row"])
        assert {
            int(_label(dialog, name).grid_info()["row"])
            for name in ("Rib width b min", "Rib width b2")
        } == {rib_width_row}
        assert width_row < channel_width_row < rib_width_row

        cards = [widget for widget in dialog.form.winfo_children() if isinstance(widget, Card)]
        roughness_card = next(
            card
            for card in cards
            if any(
                isinstance(widget, ttk.Label) and str(widget.cget("text")) == "Surface roughness"
                for widget in _walk(card)
            )
        )
        assert cards[-1] is roughness_card
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_regen_optional_detail_fields_are_hidden_until_enabled(root: tk.Tk) -> None:
    dialog = SegmentDialog(root, default_segment("Regen", 1), [])
    try:
        dialog.update()
        assert dialog.rough_frame.winfo_manager() == ""
        assert dialog.tbc_frame.winfo_manager() == ""

        dialog.vars["roughness_enabled"].set(True)
        dialog.vars["tbc_enabled"].set(True)
        dialog._refresh()
        assert dialog.rough_frame.winfo_manager() == "pack"
        assert dialog.tbc_frame.winfo_manager() == "pack"
        assert dialog.roughness_height_entry.instate(["!disabled"])
        assert dialog.roughness_step_entry.instate(["disabled"])
        assert _label(dialog, "Spacing not used by this model").winfo_exists()
        assert _label(dialog, "Equivalent sand-grain height").winfo_exists()

        dialog.vars["roughness_enabled"].set(False)
        dialog.vars["tbc_enabled"].set(False)
        dialog._refresh()
        assert dialog.rough_frame.winfo_manager() == ""
        assert dialog.tbc_frame.winfo_manager() == ""
        dialog.vars["roughness_enabled"].set(True)
        dialog._refresh()
        assert dialog.roughness_step_entry.instate(["disabled"])
        assert dialog.vars["roughness_step_mm"].get() == "0.10"
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_film_identity_fields_share_one_row_and_default_to_injector_face(root: tk.Tk) -> None:
    segment = default_segment("Film", 1)
    assert segment["position_mode"] == "Injector Face"
    assert segment["position_mm"] == "0"

    dialog = SegmentDialog(root, segment, [])
    try:
        dialog.update()
        identity_rows = {
            int(_label(dialog, name).grid_info()["row"])
            for name in ("Name", "Injection position", "Specified location")
        }
        assert identity_rows == {0}
        assert not any(
            isinstance(widget, ttk.Label) and str(widget.cget("text")) == "Specified x"
            for widget in _walk(dialog)
        )
        assert dialog.vars["position_mode"].get() == "Injector Face"
        assert dialog.position_entry.instate(["disabled"])
    finally:
        if dialog.winfo_exists():
            dialog.destroy()
