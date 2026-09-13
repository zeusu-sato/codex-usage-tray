#!/usr/bin/env python3
"""Native Qt tray for Linux. Background commands never invoke AI."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import tempfile

from PyQt6.QtCore import QLockFile, QObject, QProcess, QProcessEnvironment, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QMainWindow,
                            QMenu, QMessageBox, QPushButton, QScrollArea, QSystemTrayIcon,
                            QTabWidget, QVBoxLayout, QWidget)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from external_process import environment
from storage import default_data_dir
from claude_adapter import MINIMUM_VERSION

COLORS = {"comfortable": "#46b982", "tight": "#dba82e", "at_risk": "#ee625f"}
PROVIDERS = {"codex": "Codex / GPT", "claude": "Claude Code"}
ALLOWED_COMMANDS = frozenset(("usage-check", "client-list", "client-select", "monitor-check", "monitor-notified"))


def remaining_value(reply):
    value = reply.get("remaining_percent")
    if (reply.get("ok") is not True or reply.get("stale") or reply.get("blocked")
            or isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 100):
        return None
    return value


def value_color(value, forecast):
    return "#ee625f" if value == 0 else COLORS.get(forecast, "#88939e") if value is not None else "#88939e"


def usage_icon(provider, reply):
    value = remaining_value(reply)
    text = "?" if value is None else str(math.floor(value))
    color = QColor(value_color(value, reply.get("forecast", {}).get("status")))
    icon = QIcon()
    for size in (22, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # A small product marker distinguishes icons without bundling brand artwork.
        painter.setPen(QColor("#879db2" if provider == "codex" else "#cd997e"))
        font = QFont("sans-serif")
        font.setBold(True)
        font.setPixelSize(max(6, round(size * .24)))
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, size, size * .25), Qt.AlignmentFlag.AlignCenter,
                         "C" if provider == "codex" else "A")
        font.setPixelSize(round(size * (.52 if len(text) == 3 else .62)))
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(QRectF(0, size * .16, size, size * .74), Qt.AlignmentFlag.AlignCenter, text)
        painter.fillRect(QRectF(1, size * .92, size - 2, size * .07), QColor("#68727a"))
        if value is not None:
            painter.fillRect(QRectF(1, size * .92, (size - 2) * value / 100, size * .07), color)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


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


def text_label(text=""):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class ProviderView(QWidget):
    def __init__(self, host, provider):
        super().__init__()
        self.host, self.provider = host, provider
        self.job = None
        self.queue = []
        self.reply = {}
        self.exiting = False
        self.clients = QComboBox()
        self.clients.setMinimumContentsLength(18)
        self.clients.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.clients.activated.connect(self.select_client)
        self.refresh = QPushButton("今すぐ確認")
        self.refresh.clicked.connect(self.refresh_all)
        row = QHBoxLayout()
        row.addWidget(self.clients, 1)
        row.addWidget(self.refresh)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        layout.addLayout(row)
        self.value = text_label("?")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value.setStyleSheet("font-size: 56px; font-weight: bold; color: #88939e")
        layout.addWidget(self.value)
        self.detail = text_label("残量を確認しています…")
        self.forecast = text_label()
        self.checked = text_label()
        self.monitor = text_label()
        for label in (self.detail, self.forecast, self.checked, self.monitor):
            layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(text_label("残量は5分ごと、バージョンは15分ごとに確認します。\n"
                                    "通常の確認でAI推論は使いません。時刻はJSTです。"))
        if provider == "claude":
            layout.addWidget(text_label("Claude Code " + ".".join(map(str, MINIMUM_VERSION))
                                        + " 以降の安定版で試験対応。全体の5時間枠・週間枠を表示します。"))
        self.tray = QSystemTrayIcon(usage_icon(provider, {}), self)
        self.tray.setToolTip(PROVIDERS[provider] + " — 確認中")
        self.menu = QMenu(host)
        self.menu.addAction(PROVIDERS[provider] + " を開く", lambda: host.open_provider(provider))
        self.refresh_action = self.menu.addAction("今すぐ確認", self.refresh_all)
        self.menu.addAction("監視対象を選ぶ…", lambda: host.open_provider(provider))
        self.menu.addSeparator()
        self.menu.addAction("終了", host.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.activated)
        self.tray.show()
        self.usage_timer = QTimer(self)
        self.usage_timer.setInterval(5 * 60 * 1000)
        self.usage_timer.timeout.connect(lambda: self.enqueue("usage-check"))
        self.usage_timer.start()
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(15 * 60 * 1000)
        self.monitor_timer.timeout.connect(lambda: self.enqueue("monitor-check"))
        self.monitor_timer.start()
        QTimer.singleShot(0, self.refresh_all)

    def activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.host.open_provider(self.provider)

    def refresh_all(self):
        if self.job or self.queue or self.exiting:
            return
        self.queue.extend((command, ()) for command in ("client-list", "monitor-check", "usage-check"))
        self.next_job()

    def enqueue(self, command, arguments=()):
        if self.exiting:
            return
        if not any(item[0] == command for item in self.queue):
            self.queue.append((command, arguments))
        self.next_job()

    def next_job(self):
        if self.job or self.exiting:
            return
        busy = bool(self.queue)
        self.refresh.setEnabled(not busy)
        self.refresh_action.setEnabled(not busy)
        self.clients.setEnabled(not busy and self.clients.count() > 1)
        if not busy:
            return
        command, arguments = self.queue.pop(0)
        self.job = BackendJob(self.host.backend, self.host.folder, self.provider, command, arguments, self)
        self.job.completed.connect(lambda reply: self.received(command, reply))
        self.job.start()

    def received(self, command, reply):
        job, self.job = self.job, None
        job.deleteLater()
        if self.exiting:
            return
        if command == "usage-check":
            self.reply = reply
            value = remaining_value(reply)
            self.value.setText("?" if value is None else f"{value:g}%")
            status = reply.get("forecast", {})
            self.value.setStyleSheet("font-size: 56px; font-weight: bold; color: " + value_color(value, status.get("status")))
            self.detail.setText(reply.get("detail", "現在値を確認できません。"))
            self.forecast.setText("\n".join(str(status[key]) for key in ("title", "detail") if status.get(key)))
            self.checked.setText(reply.get("checked_label", ""))
            self.tray.setIcon(usage_icon(self.provider, reply))
            self.tray.setToolTip(PROVIDERS[self.provider] + "\n" + reply.get("tooltip", "Usage 未確認"))
        elif command == "client-list" and reply.get("ok"):
            self.clients.clear()
            entries = reply.get("clients", [])
            selected = reply.get("selected_id")
            if (len(entries) > 1 and not selected) or (entries and selected and selected not in [c["id"] for c in entries]):
                self.clients.addItem("監視対象を選択してください", "")
            for client in entries:
                self.clients.addItem(client["label"], client["id"])
            index = self.clients.findData(reply.get("selected_id"))
            if index >= 0:
                self.clients.setCurrentIndex(index)
            if not entries:
                self.clients.addItem("対応するクライアントが見つかりません", "")
        elif command == "monitor-check":
            self.monitor.setText("\n".join(reply.get(key, "") for key in ("title", "baseline_label", "current_label", "checked_label"))
                                 + ("\n" + reply.get("detail", "") if not reply.get("ok") else ""))
            if reply.get("alert"):
                self.tray.showMessage(PROVIDERS[self.provider], reply.get("title", "クライアントの変更を検知しました"))
                self.queue.append(("monitor-notified", ("--signature", reply["signature"])))
        elif not reply.get("ok"):
            self.monitor.setText(reply.get("detail", "操作を完了できませんでした。"))
        self.next_job()

    def select_client(self, index):
        client_id = self.clients.itemData(index)
        if not client_id or self.job or self.queue:
            return
        self.reply = {}
        self.value.setText("?")
        self.detail.setText("監視対象を切り替えています…")
        self.forecast.clear()
        self.checked.clear()
        self.tray.setIcon(usage_icon(self.provider, {}))
        self.tray.setToolTip(PROVIDERS[self.provider] + " — 切り替え中")
        self.queue.extend((("client-select", ("--client-id", client_id)), ("client-list", ()),
                           ("monitor-check", ()), ("usage-check", ())))
        self.next_job()

    def stop(self):
        self.exiting = True
        self.usage_timer.stop()
        self.monitor_timer.stop()
        self.queue.clear()
        if self.job:
            self.job.abort()
        self.tray.hide()


class TrayWindow(QMainWindow):
    def __init__(self, folder, backend, demo=False):
        super().__init__()
        self.folder, self.backend = Path(folder), Path(backend)
        self.setWindowTitle("Codex + Claude Usage — Linux" + (" [デモ]" if demo else ""))
        font = self.font()
        font.setPointSizeF(11)
        self.setFont(font)
        self.resize(580, 660)
        self.setMinimumSize(420, 360)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.views = {}
        for provider, title in PROVIDERS.items():
            view = ProviderView(self, provider)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(view)
            self.tabs.addTab(scroll, title)
            self.views[provider] = view
        self.setWindowIcon(usage_icon("codex", {}))
        self.statusBar().showMessage("Linux試作版：残量表示・バージョン監視に対応")
        QApplication.instance().aboutToQuit.connect(self.stop)

    def open_provider(self, provider=None):
        if provider in self.views:
            self.tabs.setCurrentIndex(list(self.views).index(provider))
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            event.accept()
            self.quit()

    def stop(self):
        for view in self.views.values():
            view.stop()

    def quit(self):
        QApplication.instance().quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tray", action="store_true", help="Start with the window hidden")
    parser.add_argument("--demo", action="store_true", help="Use synthetic data without installed clients or network")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    temporary = tempfile.TemporaryDirectory(prefix="usage-tray-demo-") if args.demo and args.data_dir is None else None
    folder = (args.data_dir or (Path(temporary.name) if temporary else default_data_dir())).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("CodexUsageTray")
    app.setDesktopFileName("codex-usage-tray")
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(folder / "linux-ui.lock"))
    # Runtime IPC contains only a request to show the existing window.
    name = "codex-usage-tray-" + hashlib.sha256(f"{os.getuid()}:{folder}".encode()).hexdigest()[:24]
    if not lock.tryLock(0):
        socket = QLocalSocket()
        socket.connectToServer(name)
        if socket.waitForConnected(1500):
            socket.write(b"show\n")
            socket.waitForBytesWritten(1500)
            return 0
        QMessageBox.warning(None, "Codex Usage Tray", "同じ保存先のアプリが起動中です。トレイから開いてください。")
        return 1
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(name)
    if not server.listen(name):
        QMessageBox.critical(None, "Codex Usage Tray", "既存ウィンドウを開くための通信を開始できません。")
        return 1
    window = TrayWindow(folder, Path(__file__).with_name("fixture_backend.py") if args.demo else ROOT / "src/backend.py", args.demo)

    def connection():
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            window.open_provider()
            socket.disconnectFromServer()
            socket.deleteLater()

    server.newConnection.connect(connection)
    if not args.tray or not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(500)
    result = app.exec()
    server.close()
    lock.unlock()
    if temporary:
        temporary.cleanup()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
