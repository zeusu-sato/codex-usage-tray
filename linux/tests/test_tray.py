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
