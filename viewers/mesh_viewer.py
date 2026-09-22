"""
Visor 3D de mallas STL/PLY al estilo Meshmixer:

- Fondo con degradado suave (en vez de un negro plano).
- Sombreado suave con normales calculadas (evita el aspecto "facetado"
  típico de un STL sin procesar).
- Barra de herramientas: Sólido / Alambre / Sólido+Aristas, y
  restablecer cámara.
- Gizmo de ejes (orientación) en la esquina inferior izquierda.
- Panel con estadísticas del modelo: vértices, triángulos, tamaño
  (caja delimitadora).
"""
from __future__ import annotations

import os

import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QFormLayout,
    QSizePolicy,
)

PANEL_BG = "#2b2b2b"
BG_TOP = (0.62, 0.65, 0.72)
BG_BOTTOM = (0.24, 0.26, 0.32)

_STYLESHEET = f"""
QWidget {{ background-color: {PANEL_BG}; color: #dddddd; }}
QGroupBox {{
    border: 1px solid #444; border-radius: 4px; margin-top: 10px;
    font-weight: bold; color: #cccccc;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QPushButton {{
    background-color: #3a3a3a; border: 1px solid #555; border-radius: 4px;
    padding: 5px 10px;
}}
QPushButton:checked {{ background-color: #4a7fd6; border-color: #4a7fd6; }}
QPushButton:hover {{ background-color: #484848; }}
"""


def _reader_for(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".stl":
        return vtk.vtkSTLReader()
    if ext == ".ply":
        return vtk.vtkPLYReader()
    raise ValueError(f"Extensión de malla no soportada: {ext}")


class MeshViewer(QWidget):
    """Widget de una pestaña: modelo 3D interactivo al estilo Meshmixer."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_STYLESHEET)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        try:
            reader = _reader_for(file_path)
            reader.SetFileName(file_path)
            reader.Update()
        except Exception as exc:
            outer.addWidget(QLabel(f"No se pudo cargar el modelo:\n{exc}", self))
            self.vtk_widget = None
            return

        polydata = reader.GetOutput()

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

        # -- Barra de herramientas -------------------------------------
        toolbar = QHBoxLayout()
        self.btn_solid = QPushButton("Sólido", self)
        self.btn_wireframe = QPushButton("Alambre", self)
        self.btn_solid_edges = QPushButton("Sólido + Aristas", self)
        for btn in (self.btn_solid, self.btn_wireframe, self.btn_solid_edges):
            btn.setCheckable(True)
        self.btn_solid.setChecked(True)
        self.btn_solid.clicked.connect(lambda: self._set_render_mode("solid"))
        self.btn_wireframe.clicked.connect(lambda: self._set_render_mode("wireframe"))
        self.btn_solid_edges.clicked.connect(lambda: self._set_render_mode("solid_edges"))

        self.btn_reset = QPushButton("Restablecer cámara", self)
        self.btn_reset.clicked.connect(self._reset_camera)

        toolbar.addWidget(self.btn_solid)
        toolbar.addWidget(self.btn_wireframe)
        toolbar.addWidget(self.btn_solid_edges)
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_reset)

        # -- Vista 3D + panel de estadísticas ----------------------------
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.vtk_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        stats_box = QGroupBox("Modelo", self)
        stats_form = QFormLayout(stats_box)
        n_points = polydata.GetNumberOfPoints()
        n_cells = polydata.GetNumberOfCells()
        bounds = polydata.GetBounds()  # xmin,xmax,ymin,ymax,zmin,zmax
        size = (bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
        stats_form.addRow("Archivo:", QLabel(os.path.basename(file_path), self))
        stats_form.addRow("Vértices:", QLabel(f"{n_points:,}".replace(",", "."), self))
        stats_form.addRow("Triángulos:", QLabel(f"{n_cells:,}".replace(",", "."), self))
        stats_form.addRow(
            "Tamaño (X,Y,Z):",
            QLabel(f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f}", self),
        )
        stats_box.setMaximumWidth(220)

        body = QHBoxLayout()
        body.addWidget(self.vtk_widget, stretch=1)
        body.addWidget(stats_box)

        outer.addLayout(toolbar)
        outer.addLayout(body, stretch=1)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(*BG_BOTTOM)
        renderer.SetBackground2(*BG_TOP)
        renderer.GradientBackgroundOn()
        renderer.AddActor(self.actor)
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
    def _set_render_mode(self, mode: str):
        for btn in (self.btn_solid, self.btn_wireframe, self.btn_solid_edges):
            btn.setChecked(False)
        prop = self.actor.GetProperty()
        if mode == "solid":
            self.btn_solid.setChecked(True)
            prop.SetRepresentationToSurface()
            prop.EdgeVisibilityOff()
        elif mode == "wireframe":
            self.btn_wireframe.setChecked(True)
            prop.SetRepresentationToWireframe()
            prop.EdgeVisibilityOff()
        elif mode == "solid_edges":
            self.btn_solid_edges.setChecked(True)
            prop.SetRepresentationToSurface()
            prop.EdgeVisibilityOn()
            prop.SetEdgeColor(0.1, 0.1, 0.1)
        if self.vtk_widget is not None:
            self.vtk_widget.GetRenderWindow().Render()

    def _reset_camera(self):
        if self.vtk_widget is not None:
            self.renderer.ResetCamera()
            self.vtk_widget.GetRenderWindow().Render()

    def start(self):
        """Debe llamarse una vez el widget está visible (tras añadirlo a la pestaña)."""
        if self.vtk_widget is not None:
            self.vtk_widget.Initialize()
            self.vtk_widget.Start()

    def closeEvent(self, event):
        if self.vtk_widget is not None:
            self.vtk_widget.close()
        super().closeEvent(event)
