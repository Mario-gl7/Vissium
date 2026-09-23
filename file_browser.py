"""
Explorador de archivos propio de Vissium.

Muestra el árbol de carpetas/archivos del sistema y emite una señal
`previewRequested(str)` con la ruta seleccionada cuando el usuario
pulsa la barra espaciadora sobre un elemento (archivo o carpeta).
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, QDir
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeView,
    QFileSystemModel,
    QPushButton,
    QLineEdit,
    QLabel,
    QFileDialog,
)

# Extensiones que Vissium sabe previsualizar.
DICOM_EXTENSIONS = {".dcm", ".dicom", ""}  # los DICOM a veces no tienen extensión
MESH_EXTENSIONS = {".stl", ".ply"}
SUPPORTED_EXTENSIONS = DICOM_EXTENSIONS | MESH_EXTENSIONS


class FileBrowser(QWidget):
    """Panel izquierdo: árbol de carpetas + campo de ruta."""

    previewRequested = Signal(str)  # ruta de archivo o carpeta
    statusMessage = Signal(str)

    def __init__(self, root_path: str | None = None, parent=None):
        super().__init__(parent)

        self.model = QFileSystemModel(self)
        self.model.setRootPath(QDir.rootPath())
        # No filtramos por extensión en el árbol: el usuario debe poder
        # navegar por carpetas normales y ver también los .dcm sin extensión.
        self.model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)

        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setColumnWidth(0, 260)
        # Ocultamos columnas de tamaño/tipo/fecha para dejar más sitio al nombre.
        for col in (1, 2, 3):
            self.tree.setColumnHidden(col, True)
        self.tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self.tree.installEventFilter(self)

        start_dir = root_path or QDir.homePath()
        self.tree.setRootIndex(self.model.index(start_dir))

        self.path_edit = QLineEdit(start_dir, self)
        self.path_edit.returnPressed.connect(self._go_to_path)

        browse_btn = QPushButton("...", self)
        browse_btn.setFixedWidth(32)
        browse_btn.clicked.connect(self._browse_folder)

        hint = QLabel(
            "Selecciona un archivo o carpeta y pulsa "
            "<b>Espacio</b> para previsualizar", self
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; padding: 4px;")

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(path_row)
        layout.addWidget(self.tree)
        layout.addWidget(hint)
        layout.setContentsMargins(4, 4, 4, 4)

    # ------------------------------------------------------------------
    # Navegación
    # ------------------------------------------------------------------
    def _go_to_path(self):
        path = self.path_edit.text().strip()
        if os.path.isdir(path):
            self.tree.setRootIndex(self.model.index(path))
        elif os.path.isfile(path):
            index = self.model.index(path)
            self.tree.setRootIndex(self.model.index(os.path.dirname(path)))
            self.tree.setCurrentIndex(index)
        else:
            self.statusMessage.emit(f"Ruta no encontrada: {path}")

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Elegir carpeta", self.path_edit.text())
        if path:
            self.path_edit.setText(path)
            self._go_to_path()

    # ------------------------------------------------------------------
    # Barra espaciadora -> previsualizar
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self.tree and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Space:
                self._trigger_preview()
                return True  # evita que la barra espaciadora expanda/colapse el árbol
        return super().eventFilter(obj, event)

    def _trigger_preview(self):
        index = self.tree.currentIndex()
        if not index.isValid():
            self.statusMessage.emit("No hay ningún archivo o carpeta seleccionado")
            return
        path = self.model.filePath(index)
        self.previewRequested.emit(path)
