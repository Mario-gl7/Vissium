"""Reconstrucción superficial 3D a partir del volumen CBCT activo."""
from __future__ import annotations

import numpy as np
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.util.numpy_support import numpy_to_vtk
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)


class _PanZoomStyle(vtk.vtkInteractorStyleTrackballCamera):
    """Derecho desplaza, rueda acerca y el clic izquierdo no actúa."""

    def OnLeftButtonDown(self):
        pass

    def OnLeftButtonUp(self):
        pass

    def OnRightButtonDown(self):
        interactor = self.GetInteractor()
        if interactor is not None:
            self.FindPokedRenderer(*interactor.GetEventPosition())
        if self.GetCurrentRenderer() is not None:
            self.StartPan()

    def OnRightButtonUp(self):
        self.EndPan()


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
        outer.setSpacing(8)
        controls = QHBoxLayout()
        controls.setContentsMargins(4, 0, 4, 0)
        controls.setSpacing(10)
        self.threshold_button = QPushButton("Umbral", self)
        self.threshold_button.setObjectName("pill")
        self.threshold_button.setCheckable(True)
        self.threshold_button.setChecked(True)
        self.threshold_button.setToolTip("Mostrar u ocultar el ajuste de umbral óseo")
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.threshold_slider.setRange(0, 1000)
        self.threshold_slider.setToolTip("Ajusta el umbral de intensidad para reducir el ruido")
        self.threshold_value = QLabel(self)
        self.threshold_value.setMinimumWidth(56)
        self.threshold_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls.addWidget(self.threshold_button)
        controls.addWidget(self.threshold_slider, 1)
        controls.addWidget(self.threshold_value)
        outer.addLayout(controls)
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
        self._threshold_min = float(np.percentile(values, 1))
        self._threshold_max = float(np.percentile(values, 99.5))
        if self._threshold_max <= self._threshold_min:
            self._threshold_max = self._threshold_min + 1.0
        threshold = float(np.clip(threshold, self._threshold_min, self._threshold_max))
        surface = vtk.vtkFlyingEdges3D()
        surface.SetInputData(image)
        surface.SetValue(0, threshold)
        surface.ComputeGradientsOn()
        surface.ComputeNormalsOff()
        self._surface = surface
        self._threshold_current = threshold
        slider_value = int(round(1000 * (threshold - self._threshold_min)
                                 / (self._threshold_max - self._threshold_min)))
        self.threshold_slider.setValue(slider_value)
        self._update_threshold_label(slider_value)
        self.threshold_button.toggled.connect(self.threshold_slider.setVisible)
        self.threshold_slider.valueChanged.connect(self._queue_threshold_update)
        self._threshold_timer = QTimer(self)
        self._threshold_timer.setSingleShot(True)
        self._threshold_timer.setInterval(70)
        self._threshold_timer.timeout.connect(self._apply_threshold)

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
            self._style = _PanZoomStyle()
            interactor = self._vtk_widget.GetRenderWindow().GetInteractor()
            interactor.SetInteractorStyle(self._style)
            self._vtk_widget.Initialize()
            self._vtk_widget.Start()
            self._started = True

    def _update_threshold_label(self, slider_value: int):
        value = self._threshold_min + (self._threshold_max - self._threshold_min) * slider_value / 1000
        self.threshold_value.setText(f"{value:.0f}")

    def _queue_threshold_update(self, slider_value: int):
        self._update_threshold_label(slider_value)
        self._threshold_timer.start()

    def _apply_threshold(self):
        value = self._threshold_min + (self._threshold_max - self._threshold_min) * self.threshold_slider.value() / 1000
        if abs(value - self._threshold_current) < 1e-6:
            return
        self._threshold_current = value
        self._surface.SetValue(0, value)
        self._surface.Modified()
        if self._started:
            self._vtk_widget.GetRenderWindow().Render()

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
