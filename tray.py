"""
Icono en la bandeja del sistema (system tray) para FastLook.

Genera el icono en tiempo real (sin necesitar un archivo .ico externo)
y monta el menú contextual: mostrar la ventana, abrir el explorador
manual de respaldo, y salir.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from foreground import bring_window_to_front


def _build_icon() -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2f6fed"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 14, 14)

    painter.setPen(QColor("white"))
    font = QFont("Arial", 22, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "FL")
    painter.end()

    return QIcon(pixmap)


def build_tray_icon(window, qapp: QApplication) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_build_icon(), parent=qapp)
    tray.setToolTip("FastLook — en segundo plano")

    menu = QMenu()

    show_action = menu.addAction("Mostrar ventana de previsualizaciones")
    show_action.triggered.connect(lambda: bring_window_to_front(window))

    browser_action = menu.addAction("Abrir explorador manual (modo respaldo)")
    browser_action.triggered.connect(window.show_manual_browser)

    menu.addSeparator()
    quit_action = menu.addAction("Salir de FastLook")
    quit_action.triggered.connect(qapp.quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: bring_window_to_front(window)
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()
    return tray
