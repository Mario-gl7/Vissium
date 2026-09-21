"""
Visor MPR (multiplanar) de DICOM: muestra simultáneamente los tres
planos ortogonales -- axial, sagital y coronal -- cada uno con su
propio slider, y respetando el espaciado físico real de cada eje
(fundamental en CBCT, donde el espaciado entre cortes suele ser mucho
mayor que el espaciado dentro del plano).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSizePolicy,
    QGroupBox,
    QFormLayout,
)

from volume import Volume, load_volume


class _PlaneView(QWidget):
    """Un único panel: imagen + slider para recorrer ese plano."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(160, 160)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setStyleSheet("background-color: black;")

        self.title_label = QLabel(title, self)
        self.title_label.setStyleSheet("color: #ccc; font-weight: bold;")

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.info_label = QLabel(self)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("color: #999;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.title_label)
        layout.addWidget(self.image_label, stretch=1)
        layout.addWidget(self.slider)
        layout.addWidget(self.info_label)

    def set_pixmap_from_array(self, arr: np.ndarray, low: float, high: float,
                               phys_w: float, phys_h: float):
        clipped = np.clip(arr, low, high)
        if high > low:
            normalized = (clipped - low) / (high - low) * 255.0
        else:
            normalized = np.zeros_like(clipped)
        img8 = np.ascontiguousarray(normalized.astype(np.uint8))

        h, w = img8.shape[:2]
        qimage = QImage(img8.data, w, h, w, QImage.Format.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimage.copy())

        # Tamaño destino que respeta el aspecto físico real (mm), no solo
        # el aspecto en píxeles -- clave con voxels anisotrópicos.
        box_w, box_h = self.image_label.width(), self.image_label.height()
        if box_w <= 0 or box_h <= 0 or phys_w <= 0 or phys_h <= 0:
            scaled = pixmap.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            phys_aspect = phys_w / phys_h
            box_aspect = box_w / box_h
            if phys_aspect > box_aspect:
                target_w = box_w
                target_h = max(1, int(box_w / phys_aspect))
            else:
                target_h = box_h
                target_w = max(1, int(box_h * phys_aspect))
            scaled = pixmap.scaled(
                target_w, target_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.image_label.setPixmap(scaled)


class DicomViewer(QWidget):
    """Widget de una pestaña: vista MPR completa (axial + sagital + coronal)."""

    def __init__(self, file_paths: list[str], parent=None):
        super().__init__(parent)
        self.volume: Volume | None = load_volume(file_paths)

        if self.volume is None:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(
                "No se han podido leer imágenes DICOM válidas o compatibles "
                "entre sí (dimensiones distintas) en esta selección.", self
            ))
            return

        n_z, n_y, n_x = self.volume.shape

        self.axial_view = _PlaneView("Axial", self)
        self.sagittal_view = _PlaneView("Sagital", self)
        self.coronal_view = _PlaneView("Coronal", self)

        self.axial_view.slider.setRange(0, max(0, n_z - 1))
        self.axial_view.slider.setValue(n_z // 2)
        self.sagittal_view.slider.setRange(0, max(0, n_x - 1))
        self.sagittal_view.slider.setValue(n_x // 2)
        self.coronal_view.slider.setRange(0, max(0, n_y - 1))
        self.coronal_view.slider.setValue(n_y // 2)

        self.axial_view.slider.valueChanged.connect(self._render_axial)
        self.sagittal_view.slider.valueChanged.connect(self._render_sagittal)
        self.coronal_view.slider.valueChanged.connect(self._render_coronal)

        # Ventana/nivel compartida entre las tres vistas.
        self._wl_center = 0.0
        self._wl_width = 1.0
        self.level_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.width_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._setup_window_level_defaults()
        self.level_slider.valueChanged.connect(self._on_wl_changed)
        self.width_slider.valueChanged.connect(self._on_wl_changed)

        wl_box = QGroupBox("Ventana / Nivel", self)
        wl_form = QFormLayout(wl_box)
        wl_form.addRow("Nivel", self.level_slider)
        wl_form.addRow("Ventana", self.width_slider)

        info_box = QGroupBox("Serie", self)
        info_form = QFormLayout(info_box)
        info_form.addRow("Cortes", QLabel(str(n_z), self))
        info_form.addRow("Tamaño", QLabel(f"{n_x} x {n_y} px", self))
        info_form.addRow(
            "Espaciado",
            QLabel(
                f"{self.volume.col_spacing:.3f} x {self.volume.row_spacing:.3f} "
                f"x {self.volume.slice_spacing:.3f} mm",
                self,
            ),
        )

        side_panel = QVBoxLayout()
        side_panel.addWidget(wl_box)
        side_panel.addWidget(info_box)
        side_panel.addStretch(1)
        side_widget = QWidget(self)
        side_widget.setLayout(side_panel)
        side_widget.setMaximumWidth(220)

        grid = QGridLayout()
        grid.addWidget(self.axial_view, 0, 0)
        grid.addWidget(self.coronal_view, 0, 1)
        grid.addWidget(self.sagittal_view, 1, 0)
        grid.addWidget(side_widget, 1, 1)

        outer = QHBoxLayout(self)
        outer.addLayout(grid)

        self._render_axial()
        self._render_sagittal()
        self._render_coronal()

    # ------------------------------------------------------------------
    def _setup_window_level_defaults(self):
        sample = self.volume.axial(self.volume.shape[0] // 2)
        p_low, p_high = np.percentile(sample, [1, 99])
        self._wl_center = float((p_low + p_high) / 2)
        self._wl_width = float(max(p_high - p_low, 1))

        spread = max(abs(self._wl_center) * 4, self._wl_width * 4, 100)
        self.level_slider.setMinimum(int(self._wl_center - spread))
        self.level_slider.setMaximum(int(self._wl_center + spread))
        self.level_slider.setValue(int(self._wl_center))

        self.width_slider.setMinimum(1)
        self.width_slider.setMaximum(int(self._wl_width * 6) + 10)
        self.width_slider.setValue(int(self._wl_width))

    def _on_wl_changed(self):
        self._wl_center = float(self.level_slider.value())
        self._wl_width = float(max(self.width_slider.value(), 1))
        self._render_axial()
        self._render_sagittal()
        self._render_coronal()

    def _window_bounds(self):
        return self._wl_center - self._wl_width / 2, self._wl_center + self._wl_width / 2

    # ------------------------------------------------------------------
    def _render_axial(self):
        z = self.axial_view.slider.value()
        arr = self.volume.axial(z)
        low, high = self._window_bounds()
        w, h = self.volume.axial_physical_size()
        self.axial_view.set_pixmap_from_array(arr, low, high, w, h)
        self.axial_view.info_label.setText(f"Z: {z + 1} / {self.volume.shape[0]}")

    def _render_sagittal(self):
        x = self.sagittal_view.slider.value()
        arr = self.volume.sagittal(x)
        low, high = self._window_bounds()
        w, h = self.volume.sagittal_physical_size()
        self.sagittal_view.set_pixmap_from_array(arr, low, high, w, h)
        self.sagittal_view.info_label.setText(f"X: {x + 1} / {self.volume.shape[2]}")

    def _render_coronal(self):
        y = self.coronal_view.slider.value()
        arr = self.volume.coronal(y)
        low, high = self._window_bounds()
        w, h = self.volume.coronal_physical_size()
        self.coronal_view.set_pixmap_from_array(arr, low, high, w, h)
        self.coronal_view.info_label.setText(f"Y: {y + 1} / {self.volume.shape[1]}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.volume is not None:
            self._render_axial()
            self._render_sagittal()
            self._render_coronal()
