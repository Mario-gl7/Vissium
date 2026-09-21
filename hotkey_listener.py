"""
Hook de teclado global para la barra espaciadora.

Se dispara en CUALQUIER ventana (es un hook a nivel de sistema), pero el
callback comprueba primero si la ventana activa es el Explorador de
Windows (ver `explorer_integration.py`) antes de hacer nada; si no lo
es, no pasa nada y la tecla Espacio sigue funcionando con normalidad en
la aplicación en la que estuvieras escribiendo.

SOLO funciona en Windows y requiere el paquete `keyboard`. En algunos
equipos, instalar un hook de teclado a nivel de sistema requiere
ejecutar la aplicación como administrador.
"""
from __future__ import annotations

import sys
from typing import Callable

IS_WINDOWS = sys.platform.startswith("win")


class HotkeyHandle:
    """Permite detener la escucha (se usa al cerrar la aplicación)."""

    def __init__(self, stop_fn: Callable[[], None]):
        self._stop_fn = stop_fn

    def stop(self):
        self._stop_fn()


def start_hotkey_listener(on_trigger: Callable[[list[str]], None]) -> HotkeyHandle | None:
    """
    Registra el hook global de la barra espaciadora.

    `on_trigger` se llama con la lista de rutas seleccionadas cada vez
    que se pulsa Espacio mientras el Explorador de Windows tiene el
    foco y hay algo seleccionado. OJO: se llama desde el hilo del hook
    de teclado, NO desde el hilo de la interfaz -- en main.py se envía
    a través de una señal Qt para poder tocar la ventana con seguridad.

    Devuelve None si no estamos en Windows o si `keyboard` no está
    disponible (por ejemplo, durante desarrollo/pruebas en otro SO).
    """
    if not IS_WINDOWS:
        return None

    try:
        import keyboard
    except ImportError:
        return None

    from explorer_integration import get_selected_paths

    def _on_space_pressed(event):
        paths = get_selected_paths()
        if paths:
            on_trigger(paths)

    keyboard.on_press_key("space", _on_space_pressed, suppress=False)

    def _stop():
        try:
            keyboard.unhook_all()
        except Exception:
            pass

    return HotkeyHandle(_stop)
