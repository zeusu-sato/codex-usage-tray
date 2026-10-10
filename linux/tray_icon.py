import math

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

COLORS = {"comfortable": "#46b982", "tight": "#dba82e", "at_risk": "#ee625f"}


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

