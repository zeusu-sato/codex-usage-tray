from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton,
                            QSystemTrayIcon, QVBoxLayout, QWidget)

from claude_adapter import MINIMUM_VERSION
from backend_job import BackendJob
from tray_icon import remaining_value, value_color, usage_icon

PROVIDERS = {"codex": "Codex / GPT", "claude": "Claude Code"}


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

