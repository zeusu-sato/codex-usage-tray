import json
import os
from pathlib import Path
import signal
import sys

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

from external_process import environment

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_COMMANDS = frozenset(("usage-check", "client-list", "client-select", "monitor-check", "monitor-notified"))


class BackendJob(QObject):
    completed = pyqtSignal(dict)

    def __init__(self, backend, folder, provider, command, arguments=(), parent=None, timeout_ms=45000):
        super().__init__(parent)
        if command not in ALLOWED_COMMANDS:
            raise ValueError("Unsupported Linux UI command")
        self.process = QProcess(self)
        parameters = QProcess.UnixProcessParameters()
        parameters.flags = QProcess.UnixProcessFlag.CreateNewSession
        self.process.setUnixProcessParameters(parameters)
        env = QProcessEnvironment()
        for key, value in environment().items():
            env.insert(key, value)
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(ROOT))
        self.process.setStandardErrorFile(QProcess.nullDevice())
        self.process.setProgram(sys.executable)
        self.process.setArguments([str(backend), command, "--data-dir", str(folder),
                                   "--provider", provider, *arguments])
        self.process.started.connect(self.started)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.failed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(timeout_ms)
        self.timer.timeout.connect(self.abort)
        self.output = bytearray()
        self.group = 0
        self.done = False
        self.aborting = False

    def start(self):
        self.timer.start()
        self.process.start()

    def started(self):
        self.group = int(self.process.processId())

    def read_output(self):
        self.output.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.output) > 1024 * 1024:
            self.abort()

    def kill_group(self):
        if self.group:
            try:
                os.killpg(self.group, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.group = 0

    def finish(self, reply):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        self.kill_group()
        self.completed.emit(reply)

    def finished(self, code, status):
        self.read_output()
        try:
            reply = json.loads(self.output) if code == 0 and status == QProcess.ExitStatus.NormalExit else None
            if not isinstance(reply, dict):
                raise ValueError("Invalid reply")
        except (ValueError, UnicodeError):
            reply = {"ok": False, "detail": "状態を取得できません。今すぐ確認で再試行できます。"}
        self.finish(reply)

    def failed(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.finish({"ok": False, "detail": "バックエンドを起動できません。Python と配置先を確認してください。"})

    def abort(self):
        if self.done or self.aborting:
            return
        self.aborting = True
        # The shared backend owns separate metadata sessions. SIGTERM allows
        # its finally blocks to clean up those groups before the wrapper exits.
        self.process.terminate()
        if not self.process.waitForFinished(4000):
            self.kill_group()
            self.process.kill()
            self.process.waitForFinished(1000)
        self.finish({"ok": False, "detail": "確認がタイムアウトしました。今すぐ確認で再試行できます。"})

