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

import logging
import logging.handlers
import os
import sys
import tempfile
import time

from PySide6.QtCore import QLockFile, QObject, Signal, QThread, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from splash import VissiumSplash
from theme import app_icon
from tray import build_tray_icon
from hotkey_listener import start_hotkey_listener, IS_WINDOWS
from updater import check_for_update, apply_update, UpdateInfo
from version import APP_NAME, __version__

# Tiempo mínimo que se mantiene visible la pantalla de carga al arrancar,
# como confirmación visual de que la app se ha abierto (Vissium no
# muestra ninguna otra ventana al iniciar: se queda en la bandeja).
# Se cuenta desde que el splash aparece, no desde que termina la carga.
SPLASH_MIN_MS = 1500


def _setup_logging():
    """
    Log en %LOCALAPPDATA%\\Vissium\\vissium.log. Con el .exe sin consola no hay
    otro sitio donde ver los errores (antes se silenciaban con `except: pass`).
    """
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    folder = os.path.join(base, "Vissium")
    try:
        os.makedirs(folder, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(folder, "vissium.log"), maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def _excepthook(exc_type, exc, tb):
        logging.getLogger("vissium").critical("Excepción no controlada", exc_info=(exc_type, exc, tb))

    sys.excepthook = _excepthook


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
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Estilo Fusion: hace que la hoja de estilos oscura (theme.py) se vea igual
    # en cualquier versión de Windows.
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())

    # Instancia única: dos copias = dos hooks de teclado = cada Espacio abre todo dos veces.
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "vissium.lock"))
    if not lock.tryLock(1000):
        QMessageBox.information(
            None, APP_NAME,
            f"{APP_NAME} ya está en ejecución (busca su icono junto al reloj).",
        )
        sys.exit(0)
    # Cerrar la ventana de previsualizaciones NO debe cerrar la app:
    # sigue viva en la bandeja, esperando la barra espaciadora.
    app.setQuitOnLastWindowClosed(False)

    # Pantalla de carga: confirma visualmente que la app se ha abierto,
    # ya que al arrancar no se muestra ninguna otra ventana (se queda
    # en la bandeja). Se muestra ANTES de importar los módulos pesados
    # (VTK, pydicom...): antes se importaban al principio del archivo y el
    # splash aparecía tarde, o ya cerrado, o no llegaba a verse.
    splash = VissiumSplash()
    splash.setAccessibleName(f"{APP_NAME}: iniciando")
    splash.show()
    splash.raise_()
    splash.advance(0.12, "Inicializando…", "Cargando volúmenes DICOM")
    app.processEvents()  # pinta el splash ya, antes de seguir con el arranque
    splash_shown_at = time.monotonic()

    from preview_window import PreviewWindow  # importa VTK/pydicom: tarda

    splash.advance(0.55, "Preparando visores…", "Motor 3D (VTK) y lector DICOM listos")
    app.processEvents()
    window = PreviewWindow()
    splash.advance(0.78, "Preparando bandeja…", "Icono del sistema y buscador de actualizaciones")
    app.processEvents()

    update_controller = UpdateController(window, None, app)
    tray = build_tray_icon(
        window, app, on_check_updates=lambda: update_controller.check(manual=True)
    )
    update_controller._tray = tray

    bridge = _HotkeyBridge()
    bridge.triggered.connect(window.open_many_and_show)

    listener = start_hotkey_listener(lambda paths: bridge.triggered.emit(paths))
    splash.advance(1.0, "Listo", "Pulsa la barra espaciadora en el Explorador")
    app.processEvents()

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

    elapsed_ms = int((time.monotonic() - splash_shown_at) * 1000)
    QTimer.singleShot(max(0, SPLASH_MIN_MS - elapsed_ms), splash.close)

    # Comprobación silenciosa al arrancar: si no hay nada nuevo, no se
    # molesta al usuario con ningún aviso; si hay una versión nueva, se
    # pregunta si se quiere actualizar (ver UpdateController._offer_update).
    update_controller.check(manual=False)

    exit_code = app.exec()
    if listener is not None:
        listener.stop()
    window.shutdown()
    lock.unlock()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
