"""
Visor MPR de DICOM al estilo 3D Slicer.

- Tres vistas ortogonales con los colores estándar de Slicer:
  Axial = rojo, Sagital = amarillo, Coronal = verde.
- Retícula de referencia cruzada: cada vista muestra dónde están
  posicionadas las otras dos, y se puede hacer clic (o arrastrar) en
  cualquier vista para mover las otras dos a ese punto.
- Panel de información de paciente/estudio/serie, como el panel de
  información de Slicer.
- Respeta el espaciado físico real de cada eje (importante en CBCT).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QWidget,
    QGridLayout,
    QVBoxLayout,
    QLabel,
    QSlider,
    QSizePolicy,
    QGroupBox,
    QFormLayout,
)

from volume import Volume, load_volume

PLANE_COLORS = {
    "axial": "#e34c4c",
    "sagittal": "#e3d34c",
    "coronal": "#4ce35c",
}
CROSSHAIR_COLOR = "#22d3ff"
DARK_BG = "#1e1e1e"
PANEL_BG = "#2b2b2b"

_DARK_STYLESHEET = f"""
QWidget {{ background-color: {PANEL_BG}; color: #dddddd; }}
QGroupBox {{
    border: 1px solid #444; border-radius: 4px; margin-top: 10px;
    font-weight: bold; color: #cccccc;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QLabel {{ color: #dddddd; }}
QSlider::groove:horizontal {{ background: #444; height: 4px; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: #8ab4f8; width: 12px; margin: -5px 0; border-radius: 6px;
}}
"""


class _ImageView(QLabel):
    """Panel de imagen: emite un punto normalizado (0..1, 0..1) al clicar/arrastrar."""

    pointClicked = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background-color: {DARK_BG};")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._pixmap_rect = None  # (x, y, w, h) del pixmap dentro del label

    def set_display_pixmap(self, pixmap: QPixmap):
        self.setPixmap(pixmap)
        x = (self.width() - pixmap.width()) / 2
        y = (self.height() - pixmap.height()) / 2
        self._pixmap_rect = (x, y, pixmap.width(), pixmap.height())

    def _emit_from_pos(self, pos):
        if not self._pixmap_rect:
            return
        px, py, pw, ph = self._pixmap_rect
        if pw <= 0 or ph <= 0:
            return
        u = (pos.x() - px) / pw
        v = (pos.y() - py) / ph
        if 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0:
            self.pointClicked.emit(u, v)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._emit_from_pos(event.position())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._emit_from_pos(event.position())
        super().mouseMoveEvent(event)


class _PlaneView(QWidget):
    """Un panel MPR completo: cabecera de color, imagen, slider e info."""

    pointClicked = Signal(float, float)

    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        self.color = color

        header = QLabel(title, self)
        header.setStyleSheet(
            f"background-color: {color}; color: #1a1a1a; font-weight: bold; "
            f"padding: 2px 6px; border-radius: 2px;"
        )

        self.image_view = _ImageView(self)
        self.image_view.pointClicked.connect(self.pointClicked)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)

        self.info_label = QLabel(self)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("color: #999999; font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(2)
        layout.addWidget(header)
        layout.addWidget(self.image_view, stretch=1)
        layout.addWidget(self.slider)
        layout.addWidget(self.info_label)

    def set_pixmap_from_array(
        self,
        arr: np.ndarray,
        low: float,
        high: float,
        phys_w: float,
        phys_h: float,
        cross_u: float | None = None,
        cross_v: float | None = None,
    ):
        clipped = np.clip(arr, low, high)
        if high > low:
            normalized = (clipped - low) / (high - low) * 255.0
        else:
            normalized = np.zeros_like(clipped)
        img8 = np.ascontiguousarray(normalized.astype(np.uint8))

        h, w = img8.shape[:2]
        gray_image = QImage(img8.data, w, h, w, QImage.Format.Format_Grayscale8)
        rgb_image = gray_image.convertToFormat(QImage.Format.Format_RGB32)
        pixmap = QPixmap.fromImage(rgb_image)

        box_w, box_h = self.image_view.width(), self.image_view.height()
        if box_w <= 0 or box_h <= 0 or phys_w <= 0 or phys_h <= 0:
            scaled = pixmap.scaled(
                self.image_view.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            phys_aspect = phys_w / phys_h
            box_aspect = box_w / box_h
            if phys_aspect > box_aspect:
                target_w, target_h = box_w, max(1, int(box_w / phys_aspect))
            else:
                target_h, target_w = box_h, max(1, int(box_h * phys_aspect))
            scaled = pixmap.scaled(
                target_w, target_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        if cross_u is not None and cross_v is not None:
            scaled = QPixmap(scaled)  # copia independiente para poder pintar encima
            painter = QPainter(scaled)
            pen = QPen(QColor(CROSSHAIR_COLOR))
            pen.setWidth(1)
            painter.setPen(pen)
            x = int(max(0, min(cross_u, 1.0)) * scaled.width())
            y = int(max(0, min(cross_v, 1.0)) * scaled.height())
            painter.drawLine(x, 0, x, scaled.height())
            painter.drawLine(0, y, scaled.width(), y)
            painter.end()

        self.image_view.set_display_pixmap(scaled)


class DicomViewer(QWidget):
    """Widget de una pestaña: vista MPR completa al estilo Slicer."""

    def __init__(self, file_paths: list[str], parent=None):
        super().__init__(parent)
        self.setStyleSheet(_DARK_STYLESHEET)
        self.volume: Volume | None = load_volume(file_paths)

        if self.volume is None:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(
                "No se han podido leer imágenes DICOM válidas o compatibles "
                "entre sí (dimensiones distintas) en esta selección.", self
            ))
            return

        n_z, n_y, n_x = self.volume.shape

        self.axial_view = _PlaneView("AXIAL", PLANE_COLORS["axial"], self)
        self.sagittal_view = _PlaneView("SAGITAL", PLANE_COLORS["sagittal"], self)
        self.coronal_view = _PlaneView("CORONAL", PLANE_COLORS["coronal"], self)

        self.axial_view.slider.setRange(0, max(0, n_z - 1))
        self.axial_view.slider.setValue(n_z // 2)
        self.sagittal_view.slider.setRange(0, max(0, n_x - 1))
        self.sagittal_view.slider.setValue(n_x // 2)
        self.coronal_view.slider.setRange(0, max(0, n_y - 1))
        self.coronal_view.slider.setValue(n_y // 2)

        for view in (self.axial_view, self.sagittal_view, self.coronal_view):
            view.slider.valueChanged.connect(self._render_all)

        self.axial_view.pointClicked.connect(self._on_axial_clicked)
        self.sagittal_view.pointClicked.connect(self._on_sagittal_clicked)
        self.coronal_view.pointClicked.connect(self._on_coronal_clicked)

        # Ventana / nivel compartida entre las tres vistas.
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

        info_box = QGroupBox("Información", self)
        info_form = QFormLayout(info_box)
        info_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for key, value in self.volume.metadata.items():
            value_label = QLabel(value, self)
            value_label.setWordWrap(True)
            info_form.addRow(f"{key}:", value_label)
        info_form.addRow("Tamaño:", QLabel(f"{n_x} x {n_y} px", self))
        info_form.addRow(
            "Espaciado:",
            QLabel(
                f"{self.volume.col_spacing:.3f} x {self.volume.row_spacing:.3f} "
                f"x {self.volume.slice_spacing:.3f} mm",
                self,
            ),
        )

        side_layout = QVBoxLayout()
        side_layout.addWidget(wl_box)
        side_layout.addWidget(info_box)
        if self.volume.warnings:
            warn_box = QGroupBox("Avisos de lectura", self)
            warn_layout = QVBoxLayout(warn_box)
            for msg in self.volume.warnings:
                label = QLabel(f"⚠ {msg}", self)
                label.setWordWrap(True)
                label.setStyleSheet("color: #e3c34c; font-size: 11px;")
                warn_layout.addWidget(label)
            side_layout.addWidget(warn_box)
        side_layout.addStretch(1)
        side_widget = QWidget(self)
        side_widget.setLayout(side_layout)
        side_widget.setMaximumWidth(240)

        grid = QGridLayout(self)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setSpacing(4)
        grid.addWidget(self.axial_view, 0, 0)
        grid.addWidget(self.coronal_view, 0, 1)
        grid.addWidget(self.sagittal_view, 1, 0)
        grid.addWidget(side_widget, 1, 1)

        self._render_all()

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
        self._render_all()

    def _window_bounds(self):
        return self._wl_center - self._wl_width / 2, self._wl_center + self._wl_width / 2

    # ------------------------------------------------------------------
    # Navegación por clic: mover las OTRAS dos vistas al punto pulsado.
    # ------------------------------------------------------------------
    def _on_axial_clicked(self, u: float, v: float):
        n_z, n_y, n_x = self.volume.shape
        self.sagittal_view.slider.setValue(int(np.clip(u * n_x, 0, n_x - 1)))
        self.coronal_view.slider.setValue(int(np.clip(v * n_y, 0, n_y - 1)))

    def _on_sagittal_clicked(self, u: float, v: float):
        n_z, n_y, n_x = self.volume.shape
        self.coronal_view.slider.setValue(int(np.clip(u * n_y, 0, n_y - 1)))
        self.axial_view.slider.setValue(int(np.clip(v * n_z, 0, n_z - 1)))

    def _on_coronal_clicked(self, u: float, v: float):
        n_z, n_y, n_x = self.volume.shape
        self.sagittal_view.slider.setValue(int(np.clip(u * n_x, 0, n_x - 1)))
        self.axial_view.slider.setValue(int(np.clip(v * n_z, 0, n_z - 1)))

    # ------------------------------------------------------------------
    def _render_all(self):
        self._render_axial()
        self._render_sagittal()
        self._render_coronal()

    def _render_axial(self):
        n_z, n_y, n_x = self.volume.shape
        z = self.axial_view.slider.value()
        arr = self.volume.axial(z)
        low, high = self._window_bounds()
        w, h = self.volume.axial_physical_size()
        cross_u = self.sagittal_view.slider.value() / max(n_x - 1, 1)
        cross_v = self.coronal_view.slider.value() / max(n_y - 1, 1)
        self.axial_view.set_pixmap_from_array(arr, low, high, w, h, cross_u, cross_v)
        self.axial_view.info_label.setText(f"Z: {z + 1} / {n_z}")

    def _render_sagittal(self):
        n_z, n_y, n_x = self.volume.shape
        x = self.sagittal_view.slider.value()
        arr = self.volume.sagittal(x)
        low, high = self._window_bounds()
        w, h = self.volume.sagittal_physical_size()
        cross_u = self.coronal_view.slider.value() / max(n_y - 1, 1)
        cross_v = self.axial_view.slider.value() / max(n_z - 1, 1)
        self.sagittal_view.set_pixmap_from_array(arr, low, high, w, h, cross_u, cross_v)
        self.sagittal_view.info_label.setText(f"X: {x + 1} / {n_x}")

    def _render_coronal(self):
        n_z, n_y, n_x = self.volume.shape
        y = self.coronal_view.slider.value()
        arr = self.volume.coronal(y)
        low, high = self._window_bounds()
        w, h = self.volume.coronal_physical_size()
        cross_u = self.sagittal_view.slider.value() / max(n_x - 1, 1)
        cross_v = self.axial_view.slider.value() / max(n_z - 1, 1)
        self.coronal_view.set_pixmap_from_array(arr, low, high, w, h, cross_u, cross_v)
        self.coronal_view.info_label.setText(f"Y: {y + 1} / {n_y}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.volume is not None:
            self._render_all()
