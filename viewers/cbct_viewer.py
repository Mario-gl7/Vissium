"""Reconstrucción superficial 3D a partir del volumen CBCT activo.

La ventana tiene el mismo diseño que las vistas MPR (caja negra con borde fino y
esquinas redondeadas, cabecera con el título) y se puede maximizar igual: doble
clic sobre el modelo o el botón de la cabecera. El umbral óseo es una cápsula en la
cabecera: el botón (iconos de regletas) la abre o la recoge.
"""
from __future__ import annotations

import numpy as np
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.util.numpy_support import numpy_to_vtk
from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QSlider,
                               QToolButton, QVBoxLayout, QWidget)

from theme import RADIUS, icon

CAPSULE_OPEN_MAX = 460     # ancho máximo de la cápsula con el deslizador visible
SMOOTH_FULL = 12            # suavizado de la superficie en reposo
SMOOTH_DRAG = 2             # suavizado ligero mientras se arrastra el umbral (más fluido)
SLIDER_STEPS = 10000       # pasos del deslizador (antes 1000): ajuste fino del umbral
CAPSULE_CLOSED = 28        # ancho de la cápsula recogida (solo el botón)


class _RotateZoomStyle(vtk.vtkInteractorStyleTrackballCamera):
    """Igual que los STL: clic derecho = girar, rueda = zoom; el modelo nunca se desplaza.

    Izquierdo y central no hacen nada. Sin atajos de teclado de VTK.
    """

    def __init__(self):
        super().__init__()
        self._rotating = False
        for event in ("LeftButtonPressEvent", "LeftButtonReleaseEvent",
                      "MiddleButtonPressEvent", "MiddleButtonReleaseEvent", "CharEvent"):
            self.AddObserver(event, lambda *_: None)
        self.AddObserver("RightButtonPressEvent", self._right_down)
        self.AddObserver("RightButtonReleaseEvent", self._right_up)

    def _right_down(self, _obj, _event):
        x, y = self.GetInteractor().GetEventPosition()
        self.FindPokedRenderer(x, y)
        if self.GetCurrentRenderer() is None:
            return
        self._rotating = True
        self.StartRotate()

    def _right_up(self, _obj, _event):
        if self._rotating:
            self._rotating = False
            self.EndRotate()


class CBCTViewer(QWidget):
    """Isosuperficie ósea interactiva derivada del volumen DICOM activo."""

    maximizeRequested = Signal()   # doble clic o botón de la cabecera

    def __init__(self, volume, parent=None):
        super().__init__(parent)
        self.setObjectName("cbctView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._started = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)   # deja ver el borde redondeado de la caja
        outer.setSpacing(0)

        # -- Cabecera: título, cápsula del umbral y botón de maximizar ---------
        header = QHBoxLayout()
        header.setContentsMargins(8, 5, 6, 4)
        header.setSpacing(8)
        title = QLabel("3D", self)
        title.setObjectName("cbctTitle")
        header.addWidget(title)

        self.threshold_capsule = QFrame(self)
        self.threshold_capsule.setObjectName("thresholdCapsule")
        self.threshold_capsule.setProperty("open", True)
        self.threshold_capsule.setFixedHeight(28)
        self.threshold_capsule.setMaximumWidth(CAPSULE_OPEN_MAX)
        capsule = QHBoxLayout(self.threshold_capsule)
        capsule.setContentsMargins(3, 0, 8, 0)
        capsule.setSpacing(8)
        self.threshold_button = QToolButton(self.threshold_capsule)
        self.threshold_button.setObjectName("thresholdToggle")
        self.threshold_button.setIcon(icon("sliders"))
        self.threshold_button.setIconSize(QSize(14, 14))
        self.threshold_button.setFixedSize(22, 22)
        self.threshold_button.setCheckable(True)
        self.threshold_button.setChecked(False)   # recogida por defecto
        self.threshold_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.threshold_button.setToolTip("Mostrar u ocultar el ajuste de umbral óseo")
        self.threshold_button.setAccessibleName("Mostrar u ocultar el ajuste de umbral")
        self.threshold_label = QLabel("UMBRAL", self.threshold_capsule)
        self.threshold_label.setObjectName("thresholdLabel")
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal, self.threshold_capsule)
        self.threshold_slider.setObjectName("thresholdSlider")
        self.threshold_slider.setRange(0, SLIDER_STEPS)
        self.threshold_slider.setMinimumWidth(60)
        self.threshold_slider.setPageStep(SLIDER_STEPS // 50)
        self.threshold_slider.setSingleStep(SLIDER_STEPS // 500)
        self.threshold_slider.setToolTip("Ajusta el umbral de intensidad para reducir el ruido")
        self.threshold_slider.setAccessibleName("Umbral de intensidad")
        self.threshold_value = QLabel(self.threshold_capsule)
        self.threshold_value.setObjectName("thresholdValue")
        self.threshold_value.setMinimumWidth(58)
        self.threshold_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        capsule.addWidget(self.threshold_button)
        capsule.addWidget(self.threshold_label)
        capsule.addWidget(self.threshold_slider, 1)
        capsule.addWidget(self.threshold_value)
        header.addWidget(self.threshold_capsule, 1, Qt.AlignmentFlag.AlignRight)

        self.maximize_button = QToolButton(self)
        self.maximize_button.setObjectName("cbctMax")
        self.maximize_button.setIcon(icon("maximize"))
        self.maximize_button.setIconSize(QSize(14, 14))
        self.maximize_button.setAutoRaise(True)
        self.maximize_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.maximize_button.setToolTip("Maximizar la vista 3D (o doble clic sobre el modelo)")
        self.maximize_button.setAccessibleName("Maximizar la vista 3D")
        self.maximize_button.clicked.connect(self.maximizeRequested)
        header.addWidget(self.maximize_button)
        outer.addLayout(header)

        # -- Escena VTK (widget nativo): se recorta con esquinas inferiores redondeadas --
        self._vtk_widget = QVTKRenderWindowInteractor(self)
        self._vtk_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._vtk_widget.installEventFilter(self)
        outer.addWidget(self._vtk_widget, 1)

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

        # Versión de media resolución: se usa solo mientras se arrastra el umbral, para que
        # la superficie (cientos de miles de triángulos) siga al deslizador sin tirones.
        fast_step = 2 if min(sample.shape) >= 64 else 1
        fast_sample = np.ascontiguousarray(sample[::fast_step, ::fast_step, ::fast_step])
        fast_image = vtk.vtkImageData()
        fast_image.SetDimensions(fast_sample.shape[2], fast_sample.shape[1], fast_sample.shape[0])
        fast_image.SetSpacing(volume.col_spacing * step * fast_step, volume.row_spacing * step * fast_step,
                              volume.slice_spacing * step * fast_step)
        fast_image.GetPointData().SetScalars(
            numpy_to_vtk(fast_sample.ravel(order="C"), deep=True, array_type=vtk.VTK_FLOAT))
        self._image_full = image
        self._image_fast = fast_image

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
        surface.ComputeGradientsOff()   # las normales se calculan después del suavizado
        surface.ComputeNormalsOff()
        self._surface = surface
        self._threshold_current = threshold
        slider_value = int(round(SLIDER_STEPS * (threshold - self._threshold_min)
                                 / (self._threshold_max - self._threshold_min)))
        self.threshold_slider.setValue(slider_value)
        self._update_threshold_label(slider_value)
        self.threshold_button.toggled.connect(self._on_threshold_toggled)
        self._on_threshold_toggled(False)
        self.threshold_slider.valueChanged.connect(self._queue_threshold_update)
        self.threshold_slider.sliderPressed.connect(self._queue_threshold_update)
        self.threshold_slider.sliderReleased.connect(self._on_threshold_released)
        # Intervalo 0: se aplica en cuanto el bucle de eventos queda libre, así la vista
        # sigue al deslizador sin esperar a que se pare (antes 70 ms de espera = tirones).
        self._threshold_timer = QTimer(self)
        self._threshold_timer.setSingleShot(True)
        self._threshold_timer.setInterval(0)
        self._threshold_timer.timeout.connect(self._apply_threshold)

        smooth = vtk.vtkWindowedSincPolyDataFilter()
        smooth.SetInputConnection(surface.GetOutputPort())
        smooth.SetNumberOfIterations(12)
        smooth.SetPassBand(0.08)
        smooth.BoundarySmoothingOff()
        smooth.FeatureEdgeSmoothingOff()
        smooth.NonManifoldSmoothingOn()
        smooth.NormalizeCoordinatesOn()
        self._smooth = smooth
        self._fast_mode = False

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
        renderer.SetBackground(0.0, 0.0, 0.0)   # como las vistas DICOM
        renderer.AddActor(actor)
        renderer.ResetCamera()
        render_window = self._vtk_widget.GetRenderWindow()
        render_window.AddRenderer(renderer)
        renderer.ResetCamera()

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self._vtk_widget:
            kind = event.type()
            if kind == QEvent.Type.Resize:
                self._round_bottom_corners()
            elif kind == QEvent.Type.MouseButtonDblClick and \
                    event.button() == Qt.MouseButton.LeftButton:
                # Fuera del evento: maximizar recoloca widgets y no debe ocurrir dentro de VTK.
                QTimer.singleShot(0, self.maximizeRequested.emit)
                return True
        return super().eventFilter(obj, event)

    def _round_bottom_corners(self):
        """El widget nativo de VTK cuelga de la cabecera: solo se redondean las esquinas de abajo."""
        w, h = self._vtk_widget.width(), self._vtk_widget.height()
        radius = RADIUS - 1
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        # Se une una franja recta arriba (sin coordenadas negativas: el recorte de un
        # widget nativo debe quedarse dentro de su ventana).
        region = QRegion(path.toFillPolygon().toPolygon()).united(QRegion(0, 0, w, radius * 2))
        self._vtk_widget.setMask(region)

    def _on_threshold_toggled(self, open_: bool):
        self.threshold_label.setVisible(open_)
        self.threshold_slider.setVisible(open_)
        self.threshold_value.setVisible(open_)
        self.threshold_capsule.setMaximumWidth(CAPSULE_OPEN_MAX if open_ else CAPSULE_CLOSED)
        self.threshold_capsule.setProperty("open", open_)
        style = self.threshold_capsule.style()
        style.unpolish(self.threshold_capsule)
        style.polish(self.threshold_capsule)

    def set_maximized(self, maximized: bool):
        """Cambia el icono y el texto del botón de la cabecera (lo llama el visor DICOM)."""
        self.maximize_button.setIcon(icon("restore" if maximized else "maximize"))
        tip = "Restaurar la vista 3D" if maximized else "Maximizar la vista 3D (o doble clic sobre el modelo)"
        self.maximize_button.setToolTip(tip)
        self.maximize_button.setAccessibleName(tip)

    def start(self):
        if not self._started:
            self._style = _RotateZoomStyle()
            interactor = self._vtk_widget.GetRenderWindow().GetInteractor()
            interactor.SetInteractorStyle(self._style)
            self._vtk_widget.Initialize()
            self._vtk_widget.Start()
            self._started = True

    def _update_threshold_label(self, slider_value: int):
        value = self._threshold_min + (self._threshold_max - self._threshold_min) * slider_value / SLIDER_STEPS
        self.threshold_value.setText(f"{value:.1f}")

    def _queue_threshold_update(self, *_):
        self._update_threshold_label(self.threshold_slider.value())
        if not self._threshold_timer.isActive():
            self._threshold_timer.start()

    def _on_threshold_released(self):
        """Al soltar el deslizador se recalcula la superficie con el suavizado completo."""
        self._apply_threshold(force=True)

    def _apply_threshold(self, force: bool = False):
        value = self._threshold_min + (self._threshold_max - self._threshold_min) * self.threshold_slider.value() / SLIDER_STEPS
        fast = self.threshold_slider.isSliderDown()
        if not force and fast == self._fast_mode and abs(value - self._threshold_current) < 1e-6:
            return
        self._threshold_current = value
        if fast != self._fast_mode:
            # Arrastrando: media resolución y suavizado ligero. Al soltar: resolución completa.
            self._fast_mode = fast
            self._surface.SetInputData(self._image_fast if fast else self._image_full)
            self._smooth.SetNumberOfIterations(SMOOTH_DRAG if fast else SMOOTH_FULL)
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
