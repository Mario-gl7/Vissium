"""
Hook de teclado global para la barra espaciadora.

Se dispara en CUALQUIER ventana (hook a nivel de sistema), pero solo
actúa si la ventana activa es el Explorador de Windows (ver
`explorer_integration.py`); si no, Espacio sigue funcionando con normalidad.

SOLO funciona en Windows y requiere el paquete `keyboard`. En algunos
equipos requiere ejecutar la aplicación como administrador (y no ve las
teclas pulsadas sobre ventanas que se ejecutan como administrador).

Cambios respecto a la versión anterior:
- El callback del hook ya NO consulta el Explorador (COM es lento y estaba
  en el hilo del hook): solo encola una petición. Un hilo trabajador propio,
  con COM inicializado, hace la consulta.
- Se ignoran las repeticiones automáticas de tecla (mantener Espacio
  generaba decenas de eventos, cada uno abriendo previsualizaciones).
- Antirrebote y coalescencia: si se acumulan peticiones mientras se procesa
  una, solo se atiende una. Antes se acumulaban y se reproducían después
  con selecciones ya antiguas (los "DICOM viejos en bucle").
- Ctrl/Alt/Shift/Win + Espacio no dispara la vista previa.
"""
from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from typing import Callable

log = logging.getLogger("vissium.hotkey")

IS_WINDOWS = sys.platform.startswith("win")

DEBOUNCE_S = 0.35        # tiempo mínimo entre dos previsualizaciones
STALE_KEY_STATE_S = 1.5  # si no hay eventos en este tiempo, se olvida "tecla pulsada"


class HotkeyHandle:
    """Permite detener la escucha (se usa al cerrar la aplicación)."""

    def __init__(self, stop_fn: Callable[[], None]):
        self._stop_fn = stop_fn

    def stop(self):
        self._stop_fn()


def start_hotkey_listener(on_trigger: Callable[[list[str]], None]) -> HotkeyHandle | None:
    """
    Registra el hook global de la barra espaciadora.

    `on_trigger` se llama con la lista de rutas seleccionadas desde un hilo
    trabajador (NO el de la interfaz): en main.py se envía a través de una
    señal Qt para tocar la ventana con seguridad.

    Devuelve None si no estamos en Windows o si `keyboard` no está disponible.
    """
    if not IS_WINDOWS:
        return None

    try:
        import keyboard
    except ImportError:
        log.warning("Paquete 'keyboard' no disponible")
        return None

    import explorer_integration

    requests: queue.SimpleQueue = queue.SimpleQueue()
    key_state = {"down": False, "last_event": 0.0}

    def _worker():
        last_trigger = 0.0
        while True:
            if requests.get() is None:
                return
            # Coalescer: descartar peticiones acumuladas mientras esperábamos.
            stop = False
            while True:
                try:
                    if requests.get_nowait() is None:
                        stop = True
                except queue.Empty:
                    break
            if stop:
                return

            if time.monotonic() - last_trigger < DEBOUNCE_S:
                continue

            t0 = time.monotonic()
            try:
                paths = explorer_integration.get_selected_paths()
            except Exception:
                log.exception("Fallo al obtener la selección del Explorador")
                continue
            log.info("Espacio -> %s (%.0f ms)", paths, (time.monotonic() - t0) * 1000)

            if paths:
                last_trigger = time.monotonic()
                try:
                    on_trigger(paths)
                except Exception:
                    log.exception("Fallo en el callback de previsualización")

    worker = threading.Thread(target=_worker, name="vissium-hotkey-worker", daemon=True)
    worker.start()

    def _on_space(event):
        now = time.monotonic()
        if event.event_type == keyboard.KEY_UP:
            key_state["down"] = False
            return
        # Repetición automática de tecla: ignorar (salvo estado obsoleto).
        if key_state["down"] and now - key_state["last_event"] < STALE_KEY_STATE_S:
            key_state["last_event"] = now
            return
        key_state["down"] = True
        key_state["last_event"] = now
        try:
            for modifier in ("ctrl", "alt", "shift", "windows"):
                if keyboard.is_pressed(modifier):
                    return
        except Exception:
            pass
        requests.put(True)

    keyboard.hook_key("space", _on_space, suppress=False)
    log.info("Hook de la barra espaciadora activo")

    def _stop():
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        requests.put(None)

    return HotkeyHandle(_stop)
