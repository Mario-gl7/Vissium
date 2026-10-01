"""
Visor 3D de mallas STL/PLY de Vissium (interfaz minimalista).

- Una sola vista: sólido con sombreado suave (normales calculadas, sin el
  aspecto "facetado" de un STL en bruto). Ya no hay modos alambre ni aristas.
- Fondo plano oscuro, sin barra de herramientas: el modelo ocupa toda la pestaña.
- Gizmo de ejes (orientación) en la esquina inferior izquierda.
- Estadísticas del modelo (vértices, triángulos, tamaño) superpuestas en la
  esquina inferior derecha, dibujadas dentro de la propia escena VTK.
- Restablecer cámara: `reset_view()`, que dispara la barra de iconos de la ventana.
"""
from __future__ import annotations

import os

import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

# Fondo plano (mismo tono que el resto de la interfaz, ligeramente más claro).
BG_COLOR = (0.102, 0.102, 0.110)
STATS_COLOR = (0.55, 0.55, 0.57)


def _reader_for(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".stl":
        return vtk.vtkSTLReader()
    if ext == ".ply":
        return vtk.vtkPLYReader()
    raise ValueError(f"Extensión de malla no soportada: {ext}")


def _fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


class MeshViewer(QWidget):
    """Widget de una pestaña: modelo 3D interactivo, a pantalla completa."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        try:
            reader = _reader_for(file_path)
            reader.SetFileName(file_path)
            reader.Update()
        except Exception as exc:
            outer.addWidget(QLabel(f"No se pudo cargar el modelo:\n{exc}", self))
            self.vtk_widget = None
            return

        polydata = reader.GetOutput()
        if polydata.GetNumberOfPoints() == 0:
            # VTK no lanza excepción con un archivo corrupto: devuelve una malla vacía.
            outer.addWidget(QLabel("El archivo no contiene una malla válida (0 vértices).", self))
            self.vtk_widget = None
            return

        # Normales suaves: evita el aspecto "facetado" de un STL en bruto.
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(polydata)
        normals.SetFeatureAngle(60.0)  # conserva aristas "duras" nítidas
        normals.ComputePointNormalsOn()
        normals.SplittingOn()
        normals.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())

        self.actor = vtk.vtkActor()
        self.actor.SetMapper(mapper)
        self.actor.GetProperty().SetColor(0.85, 0.85, 0.88)
        self.actor.GetProperty().SetSpecular(0.35)
        self.actor.GetProperty().SetSpecularPower(30)
        self.actor.GetProperty().SetDiffuse(0.85)

        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.vtk_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self.vtk_widget, stretch=1)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(*BG_COLOR)
        renderer.GradientBackgroundOff()
        renderer.AddActor(self.actor)

        # Estadísticas superpuestas (abajo a la derecha).
        n_points = polydata.GetNumberOfPoints()
        n_cells = polydata.GetNumberOfCells()
        bounds = polydata.GetBounds()  # xmin,xmax,ymin,ymax,zmin,zmax
        size = (bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
        stats = vtk.vtkTextActor()
        stats.SetInput(
            f"{_fmt_int(n_points)} vértices\n"
            f"{_fmt_int(n_cells)} triángulos\n"
            f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f}"
        )
        stats.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        stats.GetPositionCoordinate().SetValue(0.98, 0.03)
        prop = stats.GetTextProperty()
        prop.SetFontFamilyToCourier()
        prop.SetFontSize(13)
        prop.SetColor(*STATS_COLOR)
        prop.SetJustificationToRight()
        prop.SetVerticalJustificationToBottom()
        prop.SetLineSpacing(1.3)
        prop.ShadowOff()
        renderer.AddViewProp(stats)
        self.stats_actor = stats

        renderer.ResetCamera()
        self.renderer = renderer

        render_window = self.vtk_widget.GetRenderWindow()
        render_window.AddRenderer(renderer)

        interactor_style = vtk.vtkInteractorStyleTrackballCamera()
        self.vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(interactor_style)

        # Gizmo de ejes en la esquina inferior izquierda, como en Meshmixer/Slicer.
        axes = vtk.vtkAxesActor()
        self.axes_widget = vtk.vtkOrientationMarkerWidget()
        self.axes_widget.SetOrientationMarker(axes)
        self.axes_widget.SetViewport(0.0, 0.0, 0.18, 0.18)
        self.axes_widget.SetInteractor(self.vtk_widget.GetRenderWindow().GetInteractor())
        self.axes_widget.EnabledOn()
        self.axes_widget.InteractiveOff()

    # ------------------------------------------------------------------
    def reset_view(self):
        """Restablece la cámara (lo dispara el botón de la barra de iconos)."""
        if self.vtk_widget is not None:
            self.renderer.ResetCamera()
            self.vtk_widget.GetRenderWindow().Render()

    def start(self):
        """Debe llamarse una vez el widget está visible (tras añadirlo a la pestaña)."""
        if self.vtk_widget is not None:
            self.vtk_widget.Initialize()
            self.vtk_widget.Start()

    def shutdown(self):
        """Libera la ventana de render VTK al cerrar la pestaña (evita fugas de GPU/memoria)."""
        if self.vtk_widget is not None:
            try:
                self.axes_widget.EnabledOff()
                self.vtk_widget.Finalize()
            except Exception:
                pass
            self.vtk_widget = None

    def closeEvent(self, event):
        if self.vtk_widget is not None:
            self.vtk_widget.close()
        super().closeEvent(event)
