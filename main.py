"""
Vissium — se ejecuta en segundo plano (icono en la bandeja del
sistema) y se integra con el Explorador de Windows: selecciona un
archivo o carpeta compatible (DICOM, STL, PLY) y pulsa la barra
espaciadora para abrir una vista previa, sin necesidad de tener la
ventana de Vissium abierta.

Ejecutar:
    python main.py
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal, QThread
from PySide6.QtWidgets import QApplication, QMessageBox

from preview_window import PreviewWindow
from tray import build_tray_icon
from hotkey_listener import start_hotkey_listener, IS_WINDOWS
from updater import check_for_update, apply_update, UpdateInfo
from version import APP_NAME, __version__


class _HotkeyBridge(QObject):
    """
    El hook de teclado llama desde su propio hilo; esta señal Qt lleva
    el aviso de vuelta al hilo de la interfaz de forma segura.
    """
    triggered = Signal(list)


class _UpdateCheckWorker(QThread):
    """Consulta GitHub en un hilo aparte para no bloquear la interfaz."""
    found = Signal(object)  # UpdateInfo | None

    def run(self):
        self.found.emit(check_for_update())


class UpdateController(QObject):
    """
    Coordina la comprobación de actualizaciones (silenciosa al
    arrancar, o manual desde el menú de la bandeja) y el diálogo para
    aplicarlas.
    """

    def __init__(self, parent_widget, tray, app: QApplication):
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._tray = tray
        self._app = app
        self._worker: _UpdateCheckWorker | None = None
        self._manual = False

    def check(self, manual: bool = False):
        if self._worker is not None and self._worker.isRunning():
            return
        self._manual = manual
        self._worker = _UpdateCheckWorker()
        self._worker.found.connect(self._on_result)
        self._worker.start()

    def _on_result(self, info: UpdateInfo | None):
        if info is None:
            if self._manual:
                QMessageBox.information(
                    self._parent,
                    APP_NAME,
                    f"Ya tienes la última versión instalada ({__version__}).",
                )
            return

        self._offer_update(info)

    def _offer_update(self, info: UpdateInfo):
        notes = f"\n\n{info.notes}" if info.notes else ""
        answer = QMessageBox.question(
            self._parent,
            APP_NAME,
            f"Hay una nueva versión disponible: {info.version} "
            f"(tienes {__version__}).{notes}\n\n"
            "¿Actualizar ahora? La aplicación se reiniciará.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if apply_update(info):
            self._app.quit()
        else:
            QMessageBox.warning(
                self._parent,
                APP_NAME,
                "No se ha podido aplicar la actualización automáticamente "
                "(solo funciona desde el .exe instalado en Windows). "
                "Descárgala manualmente desde la página de Releases de GitHub.",
            )


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Cerrar la ventana de previsualizaciones NO debe cerrar la app:
    # sigue viva en la bandeja, esperando la barra espaciadora.
    app.setQuitOnLastWindowClosed(False)

    window = PreviewWindow()

    update_controller = UpdateController(window, None, app)
    tray = build_tray_icon(
        window, app, on_check_updates=lambda: update_controller.check(manual=True)
    )
    update_controller._tray = tray

    bridge = _HotkeyBridge()
    bridge.triggered.connect(window.open_many_and_show)

    listener = start_hotkey_listener(lambda paths: bridge.triggered.emit(paths))

    if IS_WINDOWS and listener is None:
        tray.showMessage(
            APP_NAME,
            "No se pudo activar la integración con el Explorador de Windows "
            "(¿está instalado el paquete 'keyboard'?). Puedes usar el "
            "explorador manual desde el menú de la bandeja.",
        )
    elif not IS_WINDOWS:
        tray.showMessage(
            APP_NAME,
            "La integración con el Explorador de Windows solo está "
            "disponible en Windows. Usa el explorador manual desde el "
            "menú de la bandeja.",
        )

    # Comprobación silenciosa al arrancar: si no hay nada nuevo, no se
    # molesta al usuario con ningún aviso.
    update_controller.check(manual=False)

    exit_code = app.exec()
    if listener is not None:
        listener.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
