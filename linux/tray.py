#!/usr/bin/env python3
"""Native Qt tray for Linux. Background commands never invoke AI."""
import argparse
import hashlib
import os
from pathlib import Path
import signal
import sys
import tempfile

from PyQt6.QtCore import QLockFile, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QMainWindow, QMessageBox, QScrollArea,
                            QSystemTrayIcon, QTabWidget)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from storage import default_data_dir
from backend_job import BackendJob, ROOT
from provider_view import PROVIDERS, ProviderView
from tray_icon import remaining_value, usage_icon


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
