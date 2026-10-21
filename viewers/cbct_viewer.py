"""Reconstrucción superficial 3D a partir del volumen CBCT activo."""
from __future__ import annotations

import numpy as np
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.util.numpy_support import numpy_to_vtk
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget


class CBCTViewer(QWidget):
    """Isosuperficie ósea interactiva derivada del volumen DICOM activo."""

    def __init__(self, volume, parent=None):
        super().__init__(parent)
        self.setObjectName("cbctViewer")
        self._started = False
        self._vtk_widget = QVTKRenderWindowInteractor(self)
        frame = QFrame(self)
        frame.setObjectName("cbctFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._vtk_widget)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        data = np.asarray(volume.array)
        # Reduce muestras para que series CBCT grandes no bloqueen el visor.
        step = max(1, int(np.ceil(max(data.shape) / 256)))
        sample = np.ascontiguousarray(data[::step, ::step, ::step], dtype=np.float32)
        vtk_values = numpy_to_vtk(sample.ravel(order="C"), deep=True, array_type=vtk.VTK_FLOAT)
        image = vtk.vtkImageData()
        image.SetDimensions(sample.shape[2], sample.shape[1], sample.shape[0])
        image.SetSpacing(volume.col_spacing * step, volume.row_spacing * step,
                         volume.slice_spacing * step)
        image.GetPointData().SetScalars(vtk_values)

        # El umbral adaptativo funciona con CBCT exportados tanto en HU como en escala gris.
        values = sample.reshape(-1)
        low = float(np.percentile(values, 25))
        bone = values[values > low]
        threshold = float(np.percentile(bone, 72)) if bone.size else float(values.max())
        surface = vtk.vtkFlyingEdges3D()
        surface.SetInputData(image)
        surface.SetValue(0, threshold)
        surface.ComputeGradientsOn()
        surface.ComputeNormalsOff()

        smooth = vtk.vtkWindowedSincPolyDataFilter()
        smooth.SetInputConnection(surface.GetOutputPort())
        smooth.SetNumberOfIterations(12)
        smooth.SetPassBand(0.08)
        smooth.BoundarySmoothingOff()
        smooth.FeatureEdgeSmoothingOff()
        smooth.NonManifoldSmoothingOn()
        smooth.NormalizeCoordinatesOn()

        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(smooth.GetOutputPort())
        normals.SetFeatureAngle(60)
        normals.SplittingOff()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.82, 0.84, 0.88)
        actor.GetProperty().SetSpecular(0.24)
        actor.GetProperty().SetSpecularPower(22)
        actor.GetProperty().SetAmbient(0.18)
        actor.GetProperty().SetDiffuse(0.82)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0.035, 0.038, 0.045)
        renderer.AddActor(actor)
        renderer.ResetCamera()
        render_window = self._vtk_widget.GetRenderWindow()
        render_window.AddRenderer(renderer)
        renderer.ResetCamera()

    def start(self):
        if not self._started:
            self._vtk_widget.Initialize()
            self._vtk_widget.Start()
            self._started = True

    def reset_view(self):
        renderer = self._vtk_widget.GetRenderWindow().GetRenderers().GetFirstRenderer()
        if renderer and self._started:
            renderer.ResetCamera()
            self._vtk_widget.GetRenderWindow().Render()

    def shutdown(self):
        if self._started:
            try:
                self._vtk_widget.Finalize()
            except Exception:
                pass
            self._started = False
