"""
Trae una ventana Qt al primer plano, por encima de cualquier otra
aplicación abierta -- no solo dentro del propio proceso, que es lo que
garantiza `raise_()`/`activateWindow()` por sí solos.

En Windows existe una restricción del sistema que impide a un proceso
en segundo plano robarle el foco a la ventana activa
("foreground lock"). El truco habitual para saltarla es alternar
brevemente la ventana a HWND_TOPMOST y volver a HWND_NOTOPMOST antes
de pedir el foco -- es lo que hace `_force_windows_foreground`.
"""
from __future__ import annotations

import sys

IS_WINDOWS = sys.platform.startswith("win")


def bring_window_to_front(window):
    """Muestra, sube y enfoca la ventana, superponiéndola a otras apps."""
    # show() por sí solo no restaura una ventana minimizada en Windows.
    # showNormal() restaura su tamaño/estado normal y showMaximized() fuerza
    # el resultado esperado para la hotkey de Vissium.
    window.showNormal()
    window.showMaximized()
    window.show()
    window.raise_()
    window.activateWindow()
    if IS_WINDOWS:
        _force_windows_foreground(window)


def _force_windows_foreground(window):
    try:
        import win32con
        import win32gui
    except ImportError:
        return

    try:
        hwnd = int(window.winId())
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        # Alternar a topmost y quitarlo fuerza a Windows a subir la
        # ventana por encima de lo que haya en primer plano ahora
        # mismo, sin dejarla fija por encima de todo para siempre.
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
        )
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
        )
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass  # best-effort: si algo falla, se queda el show()/raise_() normal
