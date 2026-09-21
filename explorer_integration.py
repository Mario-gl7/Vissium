"""
Integración con el Explorador de Windows.

Averigua qué archivos/carpetas están seleccionados en la ventana del
Explorador que tiene el foco en este momento, usando el objeto COM
`Shell.Application` (el mismo mecanismo que usan utilidades como
QuickLook o Seer).

SOLO funciona en Windows y requiere el paquete `pywin32`. En cualquier
otro sistema, `get_selected_paths()` devuelve siempre None.
"""
from __future__ import annotations

import sys

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    import win32com.client
    import win32gui

# Clases de ventana de una carpeta abierta en el Explorador de Windows.
EXPLORER_WINDOW_CLASSES = ("CabinetWClass", "ExploreWClass")


def get_selected_paths() -> list[str] | None:
    """
    Devuelve las rutas seleccionadas en la ventana de Explorador que
    tiene el foco ahora mismo, o None si:
      - no estamos en Windows,
      - la ventana activa no es una ventana de carpeta del Explorador,
      - o no se ha podido consultar la selección (p. ej. la ventana se
        cerró justo entre medias).

    Devuelve una lista vacía (no None) si la ventana es del Explorador
    pero no hay nada seleccionado.
    """
    if not IS_WINDOWS:
        return None

    hwnd = win32gui.GetForegroundWindow()
    try:
        class_name = win32gui.GetClassName(hwnd)
    except Exception:
        return None

    if class_name not in EXPLORER_WINDOW_CLASSES:
        return None

    try:
        shell = win32com.client.Dispatch("Shell.Application")
    except Exception:
        return None

    try:
        for window in shell.Windows():
            try:
                if window.HWND != hwnd:
                    continue
                selected_items = window.Document.SelectedItems()
                paths = [item.Path for item in selected_items]
                return paths
            except Exception:
                continue
    except Exception:
        return None

    return None
