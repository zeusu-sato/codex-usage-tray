import math
import re

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap

COLORS = {"comfortable": "#46b982", "tight": "#dba82e", "at_risk": "#ee625f"}


CREDIT_COLOR = "#A68CFF"


def credit_value(reply):
    credit = reply.get("credit")
    if (not isinstance(credit, dict)
            or credit.get("kind") not in ("codex_credits", "claude_extra_usage")
            or not isinstance(credit.get("tray_text"), str)
            or not re.fullmatch(r"(?:[0-9]{1,3}|[1-9][0-9]?[kMG]|\.[1-9][MG]|\u221e|\u00a4)", credit["tray_text"])
            or not isinstance(credit.get("amount_known"), bool)
            or not isinstance(credit.get("title"), str)
            or not isinstance(credit.get("summary"), str)):
        return None
    return credit


def text_font(text, size):
    font = QFont("sans-serif")
    font.setBold(True)
    font.setPixelSize(round(size * (.52 if len(text) == 3 else .62)))
    while font.pixelSize() > 1:
        metrics = QFontMetrics(font)
        if max(metrics.horizontalAdvance(text), metrics.boundingRect(text).width()) <= size:
            break
        font.setPixelSize(font.pixelSize() - 1)
    return font


def remaining_value(reply):
    value = reply.get("remaining_percent")
    if (reply.get("ok") is not True or reply.get("stale") or reply.get("blocked")
            or (reply.get("credit") is not None and credit_value(reply) is None)
            or isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 100):
        return None
    return value



def value_color(value, forecast):
    return "#ee625f" if value == 0 else COLORS.get(forecast, "#88939e") if value is not None else "#88939e"



def usage_icon(provider, reply):
    value = remaining_value(reply)
    credit = credit_value(reply) if value is not None else None
    text = credit["tray_text"] if credit else "?" if value is None else str(math.floor(value))
    color = QColor(CREDIT_COLOR if credit else value_color(value, reply.get("forecast", {}).get("status")))
    icon = QIcon()
    for size in (16, 22, 32, 48, 64):
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
        if credit:
            font = text_font(text, size)
        else:
            font.setPixelSize(round(size * (.52 if len(text) == 3 else .62)))
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(QRectF(0, size * .16, size, size * .74), Qt.AlignmentFlag.AlignCenter, text)
        painter.fillRect(QRectF(1, size * .92, size - 2, size * .07), QColor("#68727a"))
        if value is not None and credit is None:
            painter.fillRect(QRectF(1, size * .92, (size - 2) * value / 100, size * .07), color)
        painter.end()
        icon.addPixmap(pixmap)
    return icon

