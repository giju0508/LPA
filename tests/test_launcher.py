from __future__ import annotations

import lpa.app as app_module


class _FakeApplication:
    def __init__(self, *, interrupt: bool) -> None:
        self.interrupt = interrupt
        self.mainloop_calls = 0
        self.shutdown_calls = 0

    def mainloop(self) -> None:
        self.mainloop_calls += 1
        if self.interrupt:
            raise KeyboardInterrupt

    def _shutdown_immediately(self) -> None:
        self.shutdown_calls += 1


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, bool]] = []

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self.calls.append((wait, cancel_futures))


class _ShutdownTarget:
    def __init__(self) -> None:
        self._shutdown_started = False
        self._executor = _FakeExecutor()
        self.destroy_calls = 0

    def winfo_exists(self) -> bool:
        return True

    def destroy(self) -> None:
        self.destroy_calls += 1


def test_run_treats_keyboard_interrupt_as_orderly_shutdown(monkeypatch) -> None:
    application = _FakeApplication(interrupt=True)
    monkeypatch.setattr(app_module, "LPAApplication", lambda: application)

    app_module.run()

    assert application.mainloop_calls == 1
    assert application.shutdown_calls == 1


def test_run_also_cleans_up_after_normal_mainloop_return(monkeypatch) -> None:
    application = _FakeApplication(interrupt=False)
    monkeypatch.setattr(app_module, "LPAApplication", lambda: application)

    app_module.run()

    assert application.mainloop_calls == 1
    assert application.shutdown_calls == 1


def test_immediate_shutdown_is_idempotent() -> None:
    target = _ShutdownTarget()

    app_module.LPAApplication._shutdown_immediately(target)
    app_module.LPAApplication._shutdown_immediately(target)

    assert target._executor.calls == [(False, True)]
    assert target.destroy_calls == 1
