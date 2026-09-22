"""
Ventana de previsualizaciones de FastLook.

No es la interfaz principal (la app vive en segundo plano, en la
bandeja del sistema): esta ventana aparece automáticamente cuando se
pulsa Espacio sobre un archivo compatible en el Explorador de Windows,
con una pestaña nueva por cada previsualización. También se puede
mostrar a mano desde el menú de la bandeja, con el explorador de
archivos propio como modo de respaldo (por ejemplo, si la integración
con el Explorador de Windows no está disponible en este equipo).
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QTabWidget,
    QStatusBar,
    QMessageBox,
    QApplication,
)

from file_browser import FileBrowser
from file_types import ContentType, classify_path
from foreground import bring_window_to_front
from viewers.dicom_viewer import DicomViewer
from viewers.mesh_viewer import MeshViewer


class PreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FastLook")
        self.resize(1200, 800)

        self.browser = FileBrowser(parent=self)
        self.browser.previewRequested.connect(self.open_preview)
        self.browser.statusMessage.connect(self.show_status)
        self.browser.hide()  # el flujo principal es el Explorador de Windows + Espacio

        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self.browser)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        self.setCentralWidget(self.splitter)
        self.setStatusBar(QStatusBar(self))
        self.show_status(
            "FastLook en segundo plano. Selecciona un archivo en el "
            "Explorador de Windows y pulsa Espacio para previsualizarlo."
        )

        self._open_tabs: dict[str, int] = {}  # ruta -> índice de pestaña

    # ------------------------------------------------------------------
    def show_manual_browser(self):
        self.browser.show()
        self.splitter.setSizes([320, max(880, self.width() - 320)])
        bring_window_to_front(self)

    def open_many_and_show(self, paths: list[str]):
        """Llamado desde el hook global de Espacio (una o varias rutas)."""
        # Primero se muestra y se sube al frente la ventana, y se fuerza
        # un repintado inmediato -- así se percibe como instantánea
        # aunque la carga del contenido (DICOM/STL) tarde un poco más.
        bring_window_to_front(self)
        QApplication.processEvents()

        for path in paths:
            self.open_preview(path)

        # La carga puede haber tardado lo suyo; nos aseguramos de que
        # seguimos en primer plano al terminar.
        bring_window_to_front(self)

    # ------------------------------------------------------------------
    def show_status(self, message: str):
        self.statusBar().showMessage(message, 5000)

    def open_preview(self, path: str):
        if not os.path.exists(path):
            self.show_status(f"No existe: {path}")
            return

        existing = self._open_tabs.get(path)
        if existing is not None and existing < self.tabs.count():
            self.tabs.setCurrentIndex(existing)
            return

        content_type, files = classify_path(path)
        label = os.path.basename(path.rstrip(os.sep)) or path

        try:
            if content_type in (ContentType.DICOM_SERIES, ContentType.DICOM_FILE):
                widget = DicomViewer(files, parent=self.tabs)
                self._add_tab(widget, f"🩻 {label}", path)
                n = len(files)
                self.show_status(f"DICOM cargado: {n} corte{'s' if n != 1 else ''}")

            elif content_type == ContentType.MESH:
                widget = MeshViewer(files[0], parent=self.tabs)
                self._add_tab(widget, f"🧊 {os.path.basename(files[0])}", path)
                widget.start()
                self.show_status(f"Modelo 3D cargado: {os.path.basename(files[0])}")

            elif content_type == ContentType.EMPTY_FOLDER:
                self.show_status("La carpeta está vacía")

            else:
                self.show_status(
                    "No se reconoce contenido DICOM ni STL/PLY en esa selección"
                )
        except Exception as exc:
            QMessageBox.warning(self, "FastLook", f"No se pudo previsualizar:\n{exc}")

    def _add_tab(self, widget, title: str, path: str):
        index = self.tabs.addTab(widget, title)
        self.tabs.setCurrentIndex(index)
        self._open_tabs[path] = index

    def _close_tab(self, index: int):
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        self._open_tabs = {
            p: (i if i < index else i - 1)
            for p, i in self._open_tabs.items()
            if i != index
        }

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        # Cerrar la ventana no cierra FastLook: sigue activo en la
        # bandeja para seguir respondiendo a la barra espaciadora.
        event.ignore()
        self.hide()
