from __future__ import annotations

import pytest

import lpa.app as app_module


@pytest.mark.parametrize("scaling", [1.3333333333, 1.6666666667, 2.0])
@pytest.mark.parametrize("size", ["1080x700", "1280x860"])
def test_auto_of_single_line_fits_beside_chamber_pressure_at_each_dpi(monkeypatch, scaling, size):
    original_theme = app_module.apply_theme
    original_scaling = None

    def scaled_theme(window):
        nonlocal original_scaling
        # Apply scaling before constructing any page widgets or theme fonts.
        original_scaling = float(window.tk.call("tk", "scaling"))
        window.tk.call("tk", "scaling", scaling)
        return original_theme(window)

    monkeypatch.setattr(app_module, "apply_theme", scaled_theme)
    app = app_module.LPAApplication()
    try:
        app.geometry(size)
        app.deiconify()
        app.show_page("engine")
        app.update()
        page = app.pages["engine"]
        checkbox = page.automatic_mixture_ratio_checkbox
        assert checkbox.cget("text") == "Auto O/F: maximum theoretical vacuum Isp"
        assert checkbox.winfo_reqwidth() <= checkbox.winfo_width()
        assert checkbox.winfo_reqwidth() <= checkbox.master.winfo_width()
        assert checkbox.winfo_rootx() >= page.canvas.winfo_rootx()
        assert checkbox.winfo_rootx() + checkbox.winfo_reqwidth() <= page.canvas.winfo_rootx() + page.canvas.winfo_width()
        assert int(checkbox.master.grid_info()["columnspan"]) == 5
        ratio_box = page.mixture_ratio_entry.master
        pressure = page.chamber_pressure_entry
        assert ratio_box.master is pressure.master
        assert int(ratio_box.grid_info()["row"]) == int(pressure.grid_info()["row"])
        assert int(ratio_box.grid_info()["column"]) > int(pressure.grid_info()["column"])
        assert int(ratio_box.grid_info()["columnspan"]) == 1
        assert abs(page.mixture_ratio_entry.winfo_rooty()-pressure.winfo_rooty()) <= 1
        assert abs(page.oxidizer_combo.winfo_rooty()-page.fuel_combo.winfo_rooty()) <= 1
    finally:
        # Tk display scaling survives a root window on Windows. Restore it
        # before destroying this app so later GUI tests use the original DPI.
        if original_scaling is not None:
            app.tk.call("tk", "scaling", original_scaling)
        app._shutdown_immediately()
