"""Run with QT_QPA_PLATFORM=offscreen; all backends are synthetic."""
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QProcess
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
from tray import BackendJob, ROOT, TrayWindow, remaining_value, usage_icon

APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


def wait_until(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(20)
    if not condition():
        raise AssertionError("Timed out waiting for the fixture backend")


class TrayTests(unittest.TestCase):
    def test_credit_icons_validation_and_font_fit(self):
        from PyQt6.QtGui import QColor, QFontMetrics
        from tray_icon import CREDIT_COLOR, credit_value, text_font, value_color
        credit = dict(kind="codex_credits", tray_text="61k", amount_known=True,
                      title="Credit 利用中", summary="残り61,794クレジット")
        reply = dict(ok=True, remaining_percent=0, credit=credit)
        self.assertEqual(credit_value(reply), credit)
        self.assertEqual(remaining_value(reply), 0)
        for value in (0, 50, None):
            for status in ("comfortable", "tight", "at_risk", "unavailable"):
                self.assertNotEqual(CREDIT_COLOR.lower(), value_color(value, status).lower())
        for text in ("0", "999", "1k", "99k", ".9M", "1M", "99M", ".1G", ".9G", "1G", "99G", "812", "61k", ".1M", "∞", "¤", "688"):
            self.assertNotEqual(text, "C")
            reply["credit"] = dict(credit, tray_text=text)
            for size in (16, 22):
                metrics = QFontMetrics(text_font(text, size))
                self.assertLessEqual(max(metrics.horizontalAdvance(text), metrics.boundingRect(text).width()), size)
                image = usage_icon("codex", reply).pixmap(size, size).toImage()
                self.assertFalse(image.isNull())
            with patch("tray_icon.QPainter") as painter_class:
                usage_icon("codex", reply)
                painter = painter_class.return_value
                self.assertIn(QColor(CREDIT_COLOR), [call.args[0] for call in painter.setPen.call_args_list])
                self.assertEqual([call.args[-1] for call in painter.drawText.call_args_list], ["C", text] * 5)
                self.assertEqual(painter.fillRect.call_count, 5)
        for field, bad in (("tray_text", ""), ("tray_text", "123456"), ("tray_text", "$688"), ("tray_text", "$1.2k"),
                         ("tray_text", "999k"), ("tray_text", "1.2M"), ("tray_text", "1000"), ("tray_text", "1B"), ("tray_text", 12),
                           ("title", None), ("summary", []), ("amount_known", 1), ("kind", "other")):
            reply["credit"] = dict(credit, **{field: bad})
            self.assertIsNone(credit_value(reply))
            self.assertIsNone(remaining_value(reply))
        for bad in (True, [], "credit", 1):
            reply["credit"] = bad
            self.assertIsNone(remaining_value(reply))
        reply["credit"] = None
        self.assertEqual(remaining_value(reply), 0)
        del reply["credit"]
        self.assertEqual(remaining_value(reply), 0)

    def test_credit_window_text_color_and_invalid_reply(self):
        from types import SimpleNamespace
        from PyQt6.QtWidgets import QLabel, QMenu
        from provider_view import ProviderView
        from tray_icon import CREDIT_COLOR
        view = SimpleNamespace(job=SimpleNamespace(deleteLater=lambda: None), exiting=False,
                               provider="codex", value=QLabel(), detail=QLabel(), forecast=QLabel(),
                               checked=QLabel(), tray=QSystemTrayIcon(), menu=QMenu(), next_job=lambda: None)
        view.menu.addAction("Open")
        credit = dict(kind="claude_extra_usage", tray_text="688", amount_known=True,
                      title="追加利用中", summary="追加利用：残り $688.00")
        reply = dict(ok=True, remaining_percent=0, credit=credit, tooltip="追加利用中",
                     forecast=dict(title="見通しなし", detail="pending"))
        for current, expected in ((credit, credit["title"]), (dict(credit, tray_text=""), "?"), (None, "0%")):
            view.job = SimpleNamespace(deleteLater=lambda: None)
            reply["credit"] = current
            ProviderView.received(view, "usage-check", reply)
            self.assertEqual(view.value.text(), expected)
            if current is credit:
                self.assertIn(CREDIT_COLOR, view.value.styleSheet())
                self.assertEqual(view.detail.text(), credit["summary"])
                self.assertIn(credit["title"], view.menu.actions()[0].text())
                self.assertEqual(view.menu.actions()[0].toolTip(), credit["summary"])
                self.assertEqual(view.forecast.text(), "見通しなし\npending")
                self.assertIn(reply["tooltip"], view.tray.toolTip())
            elif expected == "?":
                self.assertIn("#88939e", view.value.styleSheet())

    def test_periodic_refresh_updates_both_trays_after_window_is_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "changing_fixture.py"
            script.write_text(
                "import contextlib,io,json,runpy,sys\nfrom pathlib import Path\n"
                "output=io.StringIO()\n"
                "with contextlib.redirect_stdout(output):\n"
                f"    runpy.run_path({str(ROOT / 'linux/fixture_backend.py')!r},run_name='__main__')\n"
                "reply=json.loads(output.getvalue())\n"
                "if sys.argv[1]=='usage-check':\n"
                "    folder=Path(sys.argv[sys.argv.index('--data-dir')+1])\n"
                "    provider=sys.argv[sys.argv.index('--provider')+1]\n"
                "    counter=folder/(provider+'-count')\n"
                "    count=int(counter.read_text())+1 if counter.exists() else 1\n"
                "    counter.write_text(str(count))\n"
                "    reply['remaining_percent']=80-count\n"
                "    reply['tooltip']='fixture update '+str(count)\n"
                "print(json.dumps(reply))\n")
            window = TrayWindow(root, script, demo=True)
            try:
                window.show()
                wait_until(lambda: all(view.reply for view in window.views.values()), seconds=30)
                icons = {name: view.tray.icon().cacheKey() for name, view in window.views.items()}
                for view in window.views.values():
                    self.assertEqual(view.value.text(), "79%")
                    self.assertEqual(view.usage_timer.interval(), 5 * 60 * 1000)
                with patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
                    window.close()
                for view in window.views.values():
                    # Accelerate the actual recurring Qt timer; do not invoke refresh manually.
                    view.usage_timer.setInterval(500)
                wait_until(lambda: all(0 < view.reply.get("remaining_percent", 100) <= 77
                                       for view in window.views.values()), seconds=30)
                for view in window.views.values():
                    view.usage_timer.stop()
                wait_until(lambda: all(view.job is None and not view.queue for view in window.views.values()), seconds=30)
                self.assertFalse(window.isVisible())
                for name, view in window.views.items():
                    self.assertTrue(view.tray.isVisible())
                    self.assertGreaterEqual(int((root / (name + "-count")).read_text()), 3)
                    self.assertNotEqual(view.tray.icon().cacheKey(), icons[name])
                    self.assertNotIn("fixture update 1", view.tray.toolTip())
            finally:
                window.stop()
                window.deleteLater()
                QTest.qWait(20)

    def test_both_providers_refresh_without_real_clients_and_close_hides(self):
        with tempfile.TemporaryDirectory() as directory:
            window = TrayWindow(directory, ROOT / "linux/fixture_backend.py", demo=True)
            try:
                window.show()
                wait_until(lambda: all(view.reply for view in window.views.values()))
                self.assertEqual(window.views["codex"].value.text(), "48%")
                self.assertEqual(window.views["claude"].value.text(), "62%")
                window.open_provider("claude")
                self.assertEqual(window.tabs.currentIndex(), 1)
                with patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
                    window.close()
                self.assertFalse(window.isVisible())
                self.assertTrue(all(view.tray.isVisible() for view in window.views.values()))
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally:
                window.stop()
                window.deleteLater()
                QTest.qWait(20)

    def test_unknown_blocked_and_stale_values_are_never_displayed_as_current(self):
        for reply in ({"ok": True, "remaining_percent": 0},
                      {"ok": True, "remaining_percent": 100}):
            self.assertEqual(remaining_value(reply), reply["remaining_percent"])
            self.assertFalse(usage_icon("codex", reply).isNull())
        for reply in ({}, {"ok": False, "remaining_percent": 75},
                      {"ok": True, "stale": True, "remaining_percent": 75},
                      {"ok": True, "blocked": True, "remaining_percent": 75},
                      {"ok": True, "remaining_percent": float("nan")},
                      {"ok": True, "remaining_percent": True}):
            self.assertIsNone(remaining_value(reply))
            self.assertFalse(usage_icon("claude", reply).isNull())

    def test_ai_and_instruction_writes_are_not_linux_background_commands(self):
        for command in ("review-run", "review-decide", "ui-enable", "ui-disable"):
            with self.assertRaises(ValueError):
                BackendJob(ROOT / "src/backend.py", Path("/unused"), "codex", command)

    def test_timeout_kills_backend_and_its_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "child.pid"
            script = root / "hung.py"
            script.write_text("import subprocess,sys,time,pathlib\n"
                              "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
                              f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                              "time.sleep(60)\n")
            job = BackendJob(script, root, "codex", "usage-check", timeout_ms=1500)
            results = []
            job.completed.connect(results.append)
            job.start()
            try:
                wait_until(lambda: bool(results))
                self.assertFalse(results[0]["ok"])
                self.assertEqual(job.process.state(), QProcess.ProcessState.NotRunning)
                child = int(pid_file.read_text())
                def child_stopped():
                    try:
                        return Path(f"/proc/{child}/stat").read_text().split(") ", 1)[1].startswith("Z")
                    except FileNotFoundError:
                        return True
                wait_until(child_stopped)
                self.assertEqual(len(results), 1)
            finally:
                job.abort()
                job.deleteLater()

    def test_timeout_allows_shared_backend_to_clean_separate_metadata_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "metadata.pid"
            script = root / "metadata_owner.py"
            script.write_text(
                "import subprocess,sys,time\nfrom pathlib import Path\n"
                f"sys.path.insert(0,{str(ROOT / 'src')!r})\n"
                "from external_process import install_termination_handlers,metadata_process_options\n"
                "from quota_monitor import kill_children_on_exit\n"
                "install_termination_handlers()\n"
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],**metadata_process_options())\n"
                "try:\n"
                "    with kill_children_on_exit(child):\n"
                f"        Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                "        time.sleep(60)\n"
                "finally:\n"
                "    child.wait(timeout=3)\n")
            job = BackendJob(script, root, "codex", "usage-check", timeout_ms=30000)
            results = []
            job.completed.connect(results.append)
            job.start()
            try:
                wait_until(pid_file.exists, seconds=20)
                child = int(pid_file.read_text())
                self.assertEqual(os.getpgid(child), child)
                job.timer.start(1)
                wait_until(lambda: bool(results))
                self.assertFalse(results[0]["ok"])
                self.assertEqual(len(results), 1)
                wait_until(lambda: not Path(f"/proc/{child}").exists())
            finally:
                job.abort()
                if pid_file.exists():
                    try:
                        os.kill(int(pid_file.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                job.deleteLater()


if __name__ == "__main__":
    unittest.main()
