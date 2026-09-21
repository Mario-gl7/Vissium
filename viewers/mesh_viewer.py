"""
Visor 3D para archivos STL y PLY, usando VTK embebido en un QWidget.
"""
from __future__ import annotations

import os

import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


def _reader_for(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".stl":
        return vtk.vtkSTLReader()
    if ext == ".ply":
        return vtk.vtkPLYReader()
    raise ValueError(f"Extensión de malla no soportada: {ext}")


class MeshViewer(QWidget):
    """Widget de una pestaña: muestra un modelo 3D (STL/PLY) interactivo."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            reader = _reader_for(file_path)
            reader.SetFileName(file_path)
            reader.Update()
        except Exception as exc:
            layout.addWidget(QLabel(f"No se pudo cargar el modelo:\n{exc}", self))
            self.vtk_widget = None
            return

        self.vtk_widget = QVTKRenderWindowInteractor(self)
        layout.addWidget(self.vtk_widget)

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(reader.GetOutputPort())

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.82, 0.82, 0.85)
        actor.GetProperty().SetSpecular(0.3)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0.12, 0.12, 0.14)
        renderer.AddActor(actor)
        renderer.ResetCamera()

        render_window = self.vtk_widget.GetRenderWindow()
        render_window.AddRenderer(renderer)

        interactor_style = vtk.vtkInteractorStyleTrackballCamera()
        self.vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(interactor_style)

        self.renderer = renderer

    def start(self):
        """Debe llamarse una vez el widget está visible (tras añadirlo a la pestaña)."""
        if self.vtk_widget is not None:
            self.vtk_widget.Initialize()
            self.vtk_widget.Start()

    def closeEvent(self, event):
        if self.vtk_widget is not None:
            self.vtk_widget.close()
        super().closeEvent(event)
