"""
Ventana de previsualizaciones de Vissium.

No es la interfaz principal (la app vive en segundo plano, en la bandeja
del sistema): aparece automáticamente cuando se pulsa Espacio sobre un
archivo compatible en el Explorador de Windows, con una pestaña nueva por
cada previsualización. También se puede mostrar a mano desde el menú de la
bandeja, con el explorador de archivos propio como modo de respaldo.

Cambios respecto a la versión anterior:
- La clasificación y la lectura DICOM se hacen en un hilo (`_OpenWorker`);
  la interfaz no se congela y aparece una pestaña "Cargando…" al instante.
  Antes se bloqueaba el hilo de la interfaz y, además, se llamaba a
  `processEvents()` dentro del slot, lo que permitía reentradas: peticiones
  antiguas en cola se ejecutaban anidadas (los DICOM viejos "en bucle").
- Se ignoran peticiones idénticas repetidas en un intervalo corto, y no se
  abre una segunda pestaña de algo que ya se está cargando.
- Las pestañas se localizan por widget (no por índice) y se guarda una firma
  (fecha de modificación) del contenido: si la carpeta cambió desde que se
  abrió, se recarga en vez de mostrar la pestaña antigua.
- Varias selecciones del mismo estudio se abren como una sola serie.
- Carpetas con varias mallas abren cada una en su pestaña (máx. 5).
- Interfaz minimalista: tema oscuro (theme.py), pestañas de texto con
  subrayado y una barra de iconos a la izquierda (explorador manual, guías
  de cruce y restablecer vista, que actúan sobre la pestaña activa).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from file_browser import FileBrowser
from file_types import ContentType, classify_path
from foreground import bring_window_to_front
from theme import STYLESHEET, app_icon, apply_dark_titlebar, icon
from viewers.dicom_viewer import DicomViewer, wait_for_loaders
from viewers.mesh_viewer import MeshViewer
from volume import load_volume
from version import APP_NAME

log = logging.getLogger("vissium.preview")

MAX_MESHES_PER_FOLDER = 5
DUPLICATE_REQUEST_S = 0.8


def _signature(path: str) -> tuple:
    """Firma barata del contenido: cambia si se añaden/quitan/modifican archivos."""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size if os.path.isfile(path) else 0)
    except OSError:
        return (0, 0)


def _label_of(path: str) -> str:
    return os.path.basename(path.rstrip("\\/")) or path


@dataclass
class _Job:
    kind: str                       # "dicom" | "mesh" | "none" | "skip" | "error"
    key: str = ""
    label: str = ""
    files: list = field(default_factory=list)
    volume: object = None
    message: str = ""


class _Placeholder(QLabel):
    """Pestaña temporal mientras se lee el contenido."""

    def __init__(self, req_path: str, parent=None):
        super().__init__("Cargando…", parent)
        self.req_path = req_path
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class _OpenWorker(QThread):
    """Clasifica y lee el contenido fuera del hilo de la interfaz."""

    resultReady = Signal(str, object)  # (ruta_pedida, _Job)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.paths = list(paths)

    def run(self):
        seen: set[str] = set()
        for req in self.paths:
            try:
                for job in self._jobs_for(req, seen):
                    self.resultReady.emit(req, job)
            except Exception as exc:
                log.exception("Error abriendo %s", req)
                self.resultReady.emit(req, _Job(kind="error", message=str(exc)))

    @staticmethod
    def _jobs_for(req: str, seen: set[str]) -> list[_Job]:
        ctype, files = classify_path(req)

        if ctype in (ContentType.DICOM_SERIES, ContentType.DICOM_FILE):
            if ctype == ContentType.DICOM_FILE and len(files) > 1:
                key = os.path.dirname(os.path.abspath(files[0]))
            else:
                key = req
            norm = os.path.normcase(os.path.abspath(key))
            if norm in seen:  # p. ej. dos cortes de la misma serie seleccionados
                return [_Job(kind="skip", key=key)]
            seen.add(norm)
            t0 = time.monotonic()
            volume = load_volume(files)
            log.info("Serie DICOM %s: %d archivos en %.1f s", key, len(files), time.monotonic() - t0)
            return [_Job("dicom", key, _label_of(key), files, volume)]

        if ctype == ContentType.MESH:
            return [
                _Job("mesh", req if len(files) == 1 and files[0] == req else f,
                     _label_of(f), [f])
                for f in files[:MAX_MESHES_PER_FOLDER]
            ]

        if ctype == ContentType.EMPTY_FOLDER:
            return [_Job(kind="none", message="La carpeta está vacía")]
        return [_Job(kind="none",
                     message="No se reconoce contenido DICOM ni STL/PLY en esa selección")]


class PreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1200, 800)
        self.setStyleSheet(STYLESHEET)
        self._titlebar_done = False

        self.browser = FileBrowser(parent=self)
        self.browser.previewRequested.connect(self.open_preview)
        self.browser.statusMessage.connect(self.show_status)
        self.browser.hide()  # el flujo principal es el Explorador de Windows + Espacio

        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setIconSize(QSize(20, 20))
        self.tabs.tabCloseRequested.connect(self._close_tab)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self.browser)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        # Barra de iconos a la izquierda: actúa sobre la pestaña activa.
        self.rail = QWidget(self)
        self.rail.setObjectName("rail")
        self.rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.rail.setFixedWidth(46)
        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(5, 10, 5, 10)
        rail_layout.setSpacing(8)
        self.btn_browser = self._rail_button(
            "folder", "Explorador de archivos manual", checkable=True)
        self.btn_guides = self._rail_button(
            "crosshair", "Mostrar u ocultar las guías de cruce", checkable=True)
        self.btn_reset = self._rail_button("refresh", "Restablecer vista")
        self.btn_guides.setChecked(True)
        self.btn_guides.setEnabled(False)
        self.btn_reset.setEnabled(False)
        for button in (self.btn_browser, self.btn_guides, self.btn_reset):
            rail_layout.addWidget(button)
        rail_layout.addStretch(1)

        self.btn_browser.toggled.connect(self._set_browser_visible)
        self.btn_guides.toggled.connect(self._on_guides_toggled)
        self.btn_reset.clicked.connect(self._on_reset_clicked)

        central = QWidget(self)
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.rail)
        central_layout.addWidget(self.splitter, stretch=1)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))
        self.show_status(
            f"{APP_NAME} en segundo plano. Selecciona un archivo en el "
            "Explorador de Windows y pulsa Espacio para previsualizarlo."
        )

        # clave (ruta) -> (widget, firma). Varias claves pueden apuntar al mismo widget.
        self._tabs_by_key: dict[str, tuple[QWidget, tuple]] = {}
        self._pending: dict[str, _Placeholder] = {}   # ruta pedida -> pestaña "Cargando…"
        self._cancelled: set[str] = set()             # placeholders cerrados por el usuario
        self._workers: list[_OpenWorker] = []
        self._last_request: tuple[tuple, float] = ((), 0.0)

        self.tabs.currentChanged.connect(self._update_rail)

    # ------------------------------------------------------------------
    # Barra de iconos
    # ------------------------------------------------------------------
    def _rail_button(self, icon_name: str, tooltip: str, checkable: bool = False) -> QToolButton:
        button = QToolButton(self.rail)
        button.setIcon(icon(icon_name))
        button.setIconSize(QSize(20, 20))
        button.setFixedSize(36, 36)
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.setAutoRaise(True)
        return button

    def _set_browser_visible(self, visible: bool):
        self.btn_browser.blockSignals(True)
        self.btn_browser.setChecked(visible)
        self.btn_browser.blockSignals(False)
        self.browser.setVisible(visible)
        if visible:
            self.splitter.setSizes([320, max(880, self.width() - 320)])

    def _on_guides_toggled(self, checked: bool):
        widget = self.tabs.currentWidget()
        if hasattr(widget, "set_guides_visible"):
            widget.set_guides_visible(checked)

    def _on_reset_clicked(self):
        action = getattr(self.tabs.currentWidget(), "reset_view", None)
        if callable(action):
            action()

    def _update_rail(self, *_):
        """Habilita los botones según lo que sepa hacer la pestaña activa."""
        widget = self.tabs.currentWidget()
        can_guides = bool(getattr(widget, "supports_guides", False))
        self.btn_guides.setEnabled(can_guides)
        if can_guides:
            self.btn_guides.blockSignals(True)
            self.btn_guides.setChecked(bool(widget.guides_visible))
            self.btn_guides.blockSignals(False)
        self.btn_reset.setEnabled(callable(getattr(widget, "reset_view", None)))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._titlebar_done:
            self._titlebar_done = True
            apply_dark_titlebar(self)

    # ------------------------------------------------------------------
    def show_manual_browser(self):
        self._set_browser_visible(True)
        bring_window_to_front(self)

    def open_many_and_show(self, paths: list[str]):
        """Llamado desde el hook global de Espacio (una o varias rutas)."""
        key = tuple(paths)
        now = time.monotonic()
        if key == self._last_request[0] and now - self._last_request[1] < DUPLICATE_REQUEST_S:
            return
        self._last_request = (key, now)

        bring_window_to_front(self)
        self._start_request(paths)

    def open_preview(self, path: str):
        self._start_request([path])

    # ------------------------------------------------------------------
    def show_status(self, message: str):
        self.statusBar().showMessage(message, 5000)

    def _live_entry(self, key: str):
        """(widget, firma) de la pestaña abierta para `key`, o None si ya no existe."""
        entry = self._tabs_by_key.get(key)
        if entry is None:
            return None
        if self.tabs.indexOf(entry[0]) < 0:
            self._tabs_by_key.pop(key, None)
            return None
        return entry

    def _start_request(self, paths: list[str]):
        todo: list[str] = []
        for path in paths:
            if not os.path.exists(path):
                self.show_status(f"No existe: {path}")
                continue

            placeholder = self._pending.get(path)
            if placeholder is not None:  # ya se está cargando
                self.tabs.setCurrentWidget(placeholder)
                continue

            entry = self._live_entry(path)
            if entry is not None and entry[1] == _signature(path):
                self.tabs.setCurrentWidget(entry[0])
                continue

            ph = _Placeholder(path, self.tabs)
            idx = self.tabs.addTab(ph, f"⏳ {_label_of(path)}")
            self.tabs.setCurrentIndex(idx)
            self._pending[path] = ph
            todo.append(path)

        if not todo:
            return
        worker = _OpenWorker(todo, self)
        worker.resultReady.connect(self._on_result)
        worker.finished.connect(lambda w=worker: self._worker_finished(w))
        self._workers.append(worker)
        worker.start()

    def _worker_finished(self, worker: _OpenWorker):
        for p in worker.paths:
            self._cancelled.discard(p)
            leftover = self._pending.pop(p, None)  # por si no llegó ningún resultado
            if leftover is not None:
                self._remove_widget(leftover)
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def _remove_widget(self, widget):
        idx = self.tabs.indexOf(widget)
        if idx >= 0:
            self.tabs.removeTab(idx)
        widget.deleteLater()

    def _on_result(self, req_path: str, job: _Job):
        if req_path in self._cancelled:
            return  # el usuario cerró la pestaña "Cargando…"
        placeholder = self._pending.pop(req_path, None)

        if job.kind in ("none", "skip", "error"):
            if placeholder is not None:
                self._remove_widget(placeholder)
            if job.kind == "none":
                self.show_status(job.message)
            elif job.kind == "error":
                QMessageBox.warning(self, APP_NAME, f"No se pudo previsualizar:\n{job.message}")
            return

        sig = _signature(job.key)
        entry = self._live_entry(job.key)
        if entry is not None and entry[1] == sig:
            if placeholder is not None:
                self._remove_widget(placeholder)
            self.tabs.setCurrentWidget(entry[0])
            return
        if entry is not None:  # contenido cambiado: cerrar la pestaña antigua
            self._close_widget(entry[0])

        try:
            if job.kind == "dicom":
                if job.volume is None:
                    widget = QLabel(
                        "No se han podido leer imágenes DICOM válidas o compatibles "
                        "entre sí en esta selección.", self.tabs)
                    widget.setWordWrap(True)
                else:
                    widget = DicomViewer(job.files, parent=self.tabs, volume=job.volume)
                title = job.label
                tab_icon = app_icon()   # las pestañas DICOM llevan el icono de Vissium
                status = (f"DICOM cargado: {job.volume.shape[0]} cortes"
                          if job.volume is not None else "No se pudo leer el DICOM")
            else:
                widget = MeshViewer(job.files[0], parent=self.tabs)
                title = f"🧊 {job.label}"
                tab_icon = QIcon()
                status = f"Modelo 3D cargado: {job.label}"
        except Exception as exc:
            log.exception("Error creando el visor")
            if placeholder is not None:
                self._remove_widget(placeholder)
            QMessageBox.warning(self, APP_NAME, f"No se pudo previsualizar:\n{exc}")
            return

        if placeholder is not None and self.tabs.indexOf(placeholder) >= 0:
            idx = self.tabs.indexOf(placeholder)
            self.tabs.removeTab(idx)
            placeholder.deleteLater()
            self.tabs.insertTab(idx, widget, tab_icon, title)
        else:
            idx = self.tabs.addTab(widget, tab_icon, title)
        self.tabs.setCurrentIndex(idx)

        self._tabs_by_key[job.key] = (widget, sig)
        if req_path != job.key:
            self._tabs_by_key[req_path] = (widget, _signature(req_path))

        if job.kind == "mesh":
            widget.start()
        self.show_status(status)

    # ------------------------------------------------------------------
    def _close_widget(self, widget):
        self.tabs.removeTab(self.tabs.indexOf(widget))
        self._tabs_by_key = {k: v for k, v in self._tabs_by_key.items() if v[0] is not widget}
        if hasattr(widget, "shutdown"):
            try:
                widget.shutdown()
            except Exception:
                log.exception("Error liberando el visor")
        widget.deleteLater()

    def _close_tab(self, index: int):
        widget = self.tabs.widget(index)
        if widget is None:
            return
        if isinstance(widget, _Placeholder):
            self._pending.pop(widget.req_path, None)
            self._cancelled.add(widget.req_path)
            self.tabs.removeTab(index)
            widget.deleteLater()
            return
        self._close_widget(widget)

    def shutdown(self):
        """Espera a los hilos de carga antes de salir."""
        for worker in list(self._workers):
            worker.wait(3000)
        wait_for_loaders(3000)

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        # Cerrar la ventana no cierra Vissium: sigue activo en la
        # bandeja para seguir respondiendo a la barra espaciadora.
        event.ignore()
        self.hide()
