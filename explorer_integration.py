"""
Integración con el Explorador de Windows.

Averigua qué archivos/carpetas están seleccionados en la ventana del
Explorador que tiene el foco, usando el objeto COM `Shell.Application`.

SOLO funciona en Windows y requiere `pywin32`. En otros sistemas,
`get_selected_paths()` devuelve siempre None.

Correcciones importantes respecto a la versión anterior:
- COM se inicializa (`CoInitialize`) en el hilo que hace la consulta. Antes
  se llamaba desde el hilo del hook de teclado SIN inicializar COM: el
  Dispatch fallaba y el `except` lo silenciaba -> "la barra espaciadora no
  hace nada".
- El objeto Shell.Application se crea una vez por hilo y se reutiliza.
- Windows 11 con pestañas: varias pestañas comparten el mismo HWND, así que
  antes se podía devolver la selección de OTRA pestaña (archivos viejos).
  Ahora se elige la pestaña cuyo nombre coincide con el título de la ventana.
- Se ignora Espacio si el foco está en un cuadro de texto (renombrar,
  buscar, barra de direcciones) en vez de en la lista de archivos.
- Los errores se registran en el log en vez de tragarse.
"""
from __future__ import annotations

import logging
import sys
import threading

log = logging.getLogger("vissium.explorer")

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    import pythoncom
    import win32com.client
    import win32gui
    import win32process

    class _GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

# Clases de ventana de una carpeta abierta en el Explorador de Windows.
EXPLORER_WINDOW_CLASSES = ("CabinetWClass", "ExploreWClass")
# Clases del control con foco que corresponden a la lista de archivos.
FILE_LIST_CLASSES = {"DirectUIHWND", "SysListView32", "SHELLDLL_DefView"}

_local = threading.local()


def _shell():
    """Shell.Application del hilo actual (con COM inicializado)."""
    shell = getattr(_local, "shell", None)
    if shell is None:
        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("Shell.Application")
        _local.shell = shell
    return shell


def _focused_class(top_hwnd: int) -> str | None:
    """Clase del control con foco dentro de la ventana (None si no se sabe)."""
    try:
        thread_id = win32process.GetWindowThreadProcessId(top_hwnd)[0]
        info = _GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return None
        if not info.hwndFocus:
            return None
        return win32gui.GetClassName(info.hwndFocus)
    except Exception:
        return None


def _selection_of(window) -> list[str]:
    items = window.Document.SelectedItems()
    return [items.Item(i).Path for i in range(items.Count)]


def get_selected_paths() -> list[str] | None:
    """
    Rutas seleccionadas en la ventana del Explorador con el foco, o None si:
      - no estamos en Windows,
      - la ventana activa no es una carpeta del Explorador,
      - el foco no está en la lista de archivos (p. ej. renombrando),
      - o falló la consulta (queda registrado en el log).
    Lista vacía si es el Explorador pero no hay nada seleccionado.
    """
    if not IS_WINDOWS:
        return None

    try:
        hwnd = win32gui.GetForegroundWindow()
        class_name = win32gui.GetClassName(hwnd)
    except Exception:
        return None

    if class_name not in EXPLORER_WINDOW_CLASSES:
        return None

    focus = _focused_class(hwnd)
    if focus is not None and focus not in FILE_LIST_CLASSES:
        log.info("Espacio ignorado: el foco está en '%s', no en la lista de archivos", focus)
        return None

    try:
        shell = _shell()
        candidates = []
        for window in shell.Windows():
            try:
                if window.HWND == hwnd:
                    candidates.append(window)
            except Exception:
                continue

        if not candidates:
            log.warning("No se encontró la ventana del Explorador (HWND %s) en Shell.Windows()", hwnd)
            return None

        if len(candidates) > 1:
            # Varias pestañas en la misma ventana: se elige la activa por título.
            title = win32gui.GetWindowText(hwnd)
            by_title = []
            for window in candidates:
                try:
                    if window.LocationName == title:
                        by_title.append(window)
                except Exception:
                    continue
            if by_title:
                candidates = by_title

        for window in candidates:
            try:
                paths = _selection_of(window)
            except Exception:
                log.exception("No se pudo leer la selección de una pestaña")
                continue
            if paths:
                return paths
        return []
    except Exception:
        # Si el Explorador se reinició, el objeto COM cacheado queda obsoleto.
        _local.shell = None
        log.exception("Error consultando el Explorador de Windows")
        return None
