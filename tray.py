"""
Icono en la bandeja del sistema (system tray) para Vissium.

Usa el icono de la app (assets/icon.ico/png) si está disponible, y si
no monta el menú contextual: mostrar la ventana, abrir el explorador
manual de respaldo, buscar actualizaciones, y salir.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from foreground import bring_window_to_front
from paths import resource_path
from version import APP_NAME


def _fallback_icon() -> QIcon:
    """Icono generado en tiempo real, por si no se encuentra assets/icon.*."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2f6fed"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 14, 14)

    painter.setPen(QColor("white"))
    font = QFont("Arial", 20, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "VS")
    painter.end()

    return QIcon(pixmap)


def _build_icon() -> QIcon:
    for name in ("icon.ico", "icon.png"):
        path = resource_path("assets", name)
        if os.path.exists(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    return _fallback_icon()


def build_tray_icon(
    window,
    qapp: QApplication,
    on_check_updates=None,
) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_build_icon(), parent=qapp)
    tray.setToolTip(f"{APP_NAME} — en segundo plano")

    menu = QMenu()

    show_action = menu.addAction("Mostrar ventana de previsualizaciones")
    show_action.triggered.connect(lambda: bring_window_to_front(window))

    browser_action = menu.addAction("Abrir explorador manual (modo respaldo)")
    browser_action.triggered.connect(window.show_manual_browser)

    menu.addSeparator()
    if on_check_updates is not None:
        update_action = menu.addAction("Buscar actualizaciones…")
        update_action.triggered.connect(on_check_updates)
        menu.addSeparator()

    quit_action = menu.addAction(f"Salir de {APP_NAME}")
    quit_action.triggered.connect(qapp.quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: bring_window_to_front(window)
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()
    return tray
