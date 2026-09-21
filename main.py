"""
FastLook — se ejecuta en segundo plano (icono en la bandeja del
sistema) y se integra con el Explorador de Windows: selecciona un
archivo o carpeta compatible (DICOM, STL, PLY) y pulsa la barra
espaciadora para abrir una vista previa, sin necesidad de tener la
ventana de FastLook abierta.

Ejecutar:
    python main.py
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from preview_window import PreviewWindow
from tray import build_tray_icon
from hotkey_listener import start_hotkey_listener, IS_WINDOWS


class _HotkeyBridge(QObject):
    """
    El hook de teclado llama desde su propio hilo; esta señal Qt lleva
    el aviso de vuelta al hilo de la interfaz de forma segura.
    """
    triggered = Signal(list)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FastLook")
    # Cerrar la ventana de previsualizaciones NO debe cerrar la app:
    # sigue viva en la bandeja, esperando la barra espaciadora.
    app.setQuitOnLastWindowClosed(False)

    window = PreviewWindow()
    tray = build_tray_icon(window, app)

    bridge = _HotkeyBridge()
    bridge.triggered.connect(window.open_many_and_show)

    listener = start_hotkey_listener(lambda paths: bridge.triggered.emit(paths))

    if IS_WINDOWS and listener is None:
        tray.showMessage(
            "FastLook",
            "No se pudo activar la integración con el Explorador de Windows "
            "(¿está instalado el paquete 'keyboard'?). Puedes usar el "
            "explorador manual desde el menú de la bandeja.",
        )
    elif not IS_WINDOWS:
        tray.showMessage(
            "FastLook",
            "La integración con el Explorador de Windows solo está "
            "disponible en Windows. Usa el explorador manual desde el "
            "menú de la bandeja.",
        )

    exit_code = app.exec()
    if listener is not None:
        listener.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
