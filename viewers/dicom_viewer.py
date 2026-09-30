"""
Visor MPR de DICOM al estilo 3D Slicer.

- Tres vistas ortogonales con los colores estándar de Slicer:
  Axial = rojo, Sagital = amarillo, Coronal = verde. Las tres tienen
  el mismo tamaño y un ancho mínimo cómodo por defecto.
- Retícula de referencia cruzada: cada vista muestra dónde están
  posicionadas las otras dos, y se puede hacer clic (o arrastrar con
  el botón izquierdo) en cualquier vista para mover las otras dos a
  ese punto.
- Rueda del ratón: avanza/retrocede los cortes de la vista bajo el
  cursor. Botón derecho + arrastrar: zoom de esa vista.
- Doble clic sobre una vista: la pone a pantalla completa dentro del
  visor (doble clic otra vez para restaurar las tres).
- Panel de información de paciente/estudio/serie, más ancho para que
  quepa todo el texto.
- Respeta el espaciado físico real de cada eje (importante en CBCT).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
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
    QPushButton,
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

# Tamaño mínimo cómodo por vista, y ancho fijo del panel de información.
MIN_VIEW_SIZE = 280
INFO_PANEL_WIDTH = 340

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
    """
    Panel de imagen de un plano.

    - Clic/arrastre con botón izquierdo: emite un punto normalizado
      (0..1, 0..1) para la navegación cruzada.
    - Rueda del ratón: emite +1/-1 para avanzar/retroceder de corte.
    - Botón derecho + arrastrar (vertical): emite un factor de zoom.
    - Botón central (rueda) + arrastrar: desplaza (pan) la imagen
      dentro de la vista -- imprescindible para poder moverse por la
      zona deseada una vez se ha hecho zoom, ya que el clic izquierdo
      está reservado para la navegación cruzada.
    - Doble clic: pide poner esta vista a pantalla completa.
    """

    pointClicked = Signal(float, float)
    wheelScrolled = Signal(int)
    zoomRequested = Signal(float)
    doubleClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(MIN_VIEW_SIZE, MIN_VIEW_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background-color: {DARK_BG};")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._pixmap = None  # pixmap ya escalado, sin el desplazamiento aplicado
        self._pixmap_rect = None  # (x, y, w, h) del pixmap dentro del label, con pan aplicado
        self._right_drag_y = None
        self._pan_offset = [0.0, 0.0]  # desplazamiento manual (botón central) en píxeles
        self._middle_drag_pos = None

    def set_display_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._update_pixmap_rect()
        self.update()

    def reset_pan(self):
        self._pan_offset = [0.0, 0.0]
        self._update_pixmap_rect()
        self.update()

    def _update_pixmap_rect(self):
        if self._pixmap is None:
            self._pixmap_rect = None
            return
        # OJO: QPixmap.width()/height() devuelven píxeles FÍSICOS (de
        # dispositivo); para el centrado/pan hay que usar el tamaño
        # LÓGICO (dividido por su devicePixelRatio), que es el tamaño
        # con el que Qt lo va a dibujar realmente en pantalla.
        dpr = self._pixmap.devicePixelRatio() or 1.0
        logical_w = self._pixmap.width() / dpr
        logical_h = self._pixmap.height() / dpr
        x = (self.width() - logical_w) / 2 + self._pan_offset[0]
        y = (self.height() - logical_h) / 2 + self._pan_offset[1]
        self._pixmap_rect = (x, y, logical_w, logical_h)

    def paintEvent(self, event):
        # Pintado manual (en vez de dejar que QLabel centre el pixmap
        # automáticamente) para poder aplicar el desplazamiento del pan.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(DARK_BG))
        if self._pixmap is not None and self._pixmap_rect is not None:
            x, y, _w, _h = self._pixmap_rect
            painter.drawPixmap(QPointF(x, y), self._pixmap)
        painter.end()

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

    # -- Navegación con clic izquierdo / zoom / pan --------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._emit_from_pos(event.position())
        elif event.button() == Qt.MouseButton.RightButton:
            self._right_drag_y = event.position().y()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._middle_drag_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._emit_from_pos(event.position())
        elif event.buttons() & Qt.MouseButton.RightButton and self._right_drag_y is not None:
            current_y = event.position().y()
            dy = self._right_drag_y - current_y  # arriba = acercar
            if abs(dy) >= 1:
                factor = 1.0 + (dy * 0.01)
                factor = max(0.5, min(factor, 1.5))
                self.zoomRequested.emit(factor)
                self._right_drag_y = current_y
        elif event.buttons() & Qt.MouseButton.MiddleButton and self._middle_drag_pos is not None:
            current_pos = event.position()
            delta = current_pos - self._middle_drag_pos
            self._pan_offset[0] += delta.x()
            self._pan_offset[1] += delta.y()
            self._middle_drag_pos = current_pos
            self._update_pixmap_rect()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._right_drag_y = None
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._middle_drag_pos = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event):
        # Si cambia el tamaño del panel (p. ej. al maximizar una vista),
        # recalculamos la posición del pixmap ya cargado con el pan actual.
        self._update_pixmap_rect()
        super().resizeEvent(event)

    # -- Rueda del ratón: avanzar/retroceder cortes ---------------------
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta != 0:
            self.wheelScrolled.emit(1 if delta > 0 else -1)
        event.accept()


class _PlaneView(QWidget):
    """Un panel MPR completo: cabecera de color, imagen, slider e info."""

    pointClicked = Signal(float, float)
    zoomChanged = Signal()
    doubleClicked = Signal()

    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self.zoom = 1.0

        header = QLabel(title, self)
        header.setStyleSheet(
            f"background-color: {color}; color: #1a1a1a; font-weight: bold; "
            f"padding: 2px 6px; border-radius: 2px;"
        )

        self.image_view = _ImageView(self)
        self.image_view.pointClicked.connect(self.pointClicked)
        self.image_view.wheelScrolled.connect(self._on_wheel)
        self.image_view.zoomRequested.connect(self._on_zoom)
        self.image_view.doubleClicked.connect(self.doubleClicked)

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

    def _on_wheel(self, direction: int):
        self.slider.setValue(self.slider.value() + direction)

    def _on_zoom(self, factor: float):
        self.zoom = max(0.2, min(self.zoom * factor, 8.0))
        self.zoomChanged.emit()

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

        # Relación de píxeles físicos/lógicos de la pantalla actual (>1 en
        # HiDPI/Retina o con el escalado de Windows por encima del 100%).
        # Sin esto, se escala siempre al tamaño LÓGICO del panel, que en
        # una pantalla así es más pequeño que los píxeles físicos reales
        # disponibles -> la imagen sale borrosa/con menos detalle del que
        # la pantalla podría mostrar. Generamos el pixmap ya a resolución
        # física y le indicamos su devicePixelRatio para que Qt lo pinte
        # nítido al tamaño lógico correcto.
        dpr = self.image_view.devicePixelRatioF() or 1.0

        box_w, box_h = self.image_view.width(), self.image_view.height()
        if box_w <= 0 or box_h <= 0 or phys_w <= 0 or phys_h <= 0:
            fallback_size = self.image_view.size()
            scaled = pixmap.scaled(
                max(1, round(fallback_size.width() * dpr)),
                max(1, round(fallback_size.height() * dpr)),
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
            target_w = max(1, int(target_w * self.zoom))
            target_h = max(1, int(target_h * self.zoom))
            scaled = pixmap.scaled(
                max(1, round(target_w * dpr)),
                max(1, round(target_h * dpr)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        scaled.setDevicePixelRatio(dpr)

        if cross_u is not None and cross_v is not None:
            scaled = QPixmap(scaled)  # copia independiente para poder pintar encima
            scaled.setDevicePixelRatio(dpr)
            painter = QPainter(scaled)
            pen = QPen(QColor(CROSSHAIR_COLOR))
            pen.setWidth(max(1, round(dpr)))
            painter.setPen(pen)
            # Coordenadas en píxeles lógicos: al haber fijado
            # setDevicePixelRatio, QPainter ya trabaja en ese espacio.
            logical_w = scaled.width() / dpr
            logical_h = scaled.height() / dpr
            x = int(max(0, min(cross_u, 1.0)) * logical_w)
            y = int(max(0, min(cross_v, 1.0)) * logical_h)
            painter.drawLine(x, 0, x, int(logical_h))
            painter.drawLine(0, y, int(logical_w), y)
            painter.end()

        self.image_view.set_display_pixmap(scaled)


class DicomViewer(QWidget):
    """Widget de una pestaña: vista MPR completa al estilo Slicer."""

    def __init__(self, file_paths: list[str], parent=None, volume: Volume | None = None):
        super().__init__(parent)
        self.setStyleSheet(_DARK_STYLESHEET)
        # `volume` ya leído (en un hilo, desde preview_window) evita bloquear la interfaz.
        self.volume: Volume | None = volume if volume is not None else load_volume(file_paths)

        if self.volume is None:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(
                "No se han podido leer imágenes DICOM válidas o compatibles "
                "entre sí (dimensiones distintas) en esta selección.", self
            ))
            return

        # Ancho por defecto suficiente para ver las tres vistas + el
        # panel de información con comodidad.
        self.setMinimumSize(MIN_VIEW_SIZE * 2 + INFO_PANEL_WIDTH + 40, MIN_VIEW_SIZE * 2 + 80)

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

        self.axial_view.zoomChanged.connect(self._render_axial)
        self.sagittal_view.zoomChanged.connect(self._render_sagittal)
        self.coronal_view.zoomChanged.connect(self._render_coronal)

        self.axial_view.doubleClicked.connect(lambda: self._toggle_maximize("axial"))
        self.sagittal_view.doubleClicked.connect(lambda: self._toggle_maximize("sagittal"))
        self.coronal_view.doubleClicked.connect(lambda: self._toggle_maximize("coronal"))

        # -- Barra de herramientas: restablecer zoom/pan y mostrar/ocultar
        # la retícula de referencia cruzada -------------------------------
        self._show_guides = True

        self.btn_reset_view = QPushButton("Restablecer vista", self)
        self.btn_reset_view.setToolTip("Vuelve el zoom y el desplazamiento (pan) de las tres vistas a su estado original")
        self.btn_reset_view.clicked.connect(self._reset_views)

        self.btn_toggle_guides = QPushButton("Ocultar guías", self)
        self.btn_toggle_guides.setCheckable(True)
        self.btn_toggle_guides.setToolTip("Muestra u oculta la retícula de referencia cruzada")
        self.btn_toggle_guides.toggled.connect(self._on_toggle_guides)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addWidget(self.btn_reset_view)
        toolbar.addWidget(self.btn_toggle_guides)
        toolbar.addStretch(1)
        self._toolbar = toolbar

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
        info_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
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
        side_widget.setFixedWidth(INFO_PANEL_WIDTH)
        self.side_widget = side_widget

        # Las tres vistas ocupan una rejilla 2x2 con celdas del mismo
        # tamaño (una celda queda vacía); el panel lateral es
        # independiente, con ancho fijo propio.
        self.views_grid = QGridLayout()
        self.views_grid.setContentsMargins(0, 0, 0, 0)
        self.views_grid.setSpacing(4)
        self.views_grid.setRowStretch(0, 1)
        self.views_grid.setRowStretch(1, 1)
        self.views_grid.setColumnStretch(0, 1)
        self.views_grid.setColumnStretch(1, 1)

        self._plane_positions = {
            "axial": (self.axial_view, 0, 0, 1, 1),
            "coronal": (self.coronal_view, 0, 1, 1, 1),
            "sagittal": (self.sagittal_view, 1, 0, 1, 1),
        }
        for widget, row, col, rspan, cspan in self._plane_positions.values():
            self.views_grid.addWidget(widget, row, col, rspan, cspan)
        self._maximized: str | None = None

        views_widget = QWidget(self)
        views_widget.setLayout(self.views_grid)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)
        content.addWidget(views_widget, stretch=1)
        content.addWidget(side_widget)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        root.addLayout(self._toolbar)
        root.addLayout(content, stretch=1)

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
    # Barra de herramientas: restablecer vista y guías
    # ------------------------------------------------------------------
    def _reset_views(self):
        """Vuelve el zoom y el pan de las tres vistas a su estado original."""
        for view in (self.axial_view, self.sagittal_view, self.coronal_view):
            view.zoom = 1.0
            view.image_view.reset_pan()
        self._render_all()

    def _on_toggle_guides(self, checked: bool):
        self._show_guides = not checked
        self.btn_toggle_guides.setText("Mostrar guías" if checked else "Ocultar guías")
        self._render_all()

    # ------------------------------------------------------------------
    # Pantalla completa de una vista dentro del visor
    # ------------------------------------------------------------------
    def _toggle_maximize(self, name: str):
        # Quitar todo de la rejilla antes de recolocar.
        for widget, *_ in self._plane_positions.values():
            self.views_grid.removeWidget(widget)

        if self._maximized == name:
            for widget, row, col, rspan, cspan in self._plane_positions.values():
                self.views_grid.addWidget(widget, row, col, rspan, cspan)
                widget.show()
            self._maximized = None
        else:
            target_widget = self._plane_positions[name][0]
            self.views_grid.addWidget(target_widget, 0, 0, 2, 2)
            target_widget.show()
            for key, (widget, *_rest) in self._plane_positions.items():
                if key != name:
                    widget.hide()
            self._maximized = name

        # El tamaño de las vistas cambia drásticamente al maximizar o
        # restaurar; reiniciamos el pan para que la imagen no quede
        # descentrada fuera de la vista.
        for view in (self.axial_view, self.sagittal_view, self.coronal_view):
            view.image_view.reset_pan()

        self._render_all()

    # ------------------------------------------------------------------
    # Navegación por clic: mover las OTRAS dos vistas al punto pulsado.
    # Los planos sagital/coronal muestran el eje Z invertido (superior
    # arriba), así que su coordenada vertical se traduce al revés.
    # ------------------------------------------------------------------
    def _on_axial_clicked(self, u: float, v: float):
        n_z, n_y, n_x = self.volume.shape
        self.sagittal_view.slider.setValue(int(np.clip(round(u * (n_x - 1)), 0, n_x - 1)))
        self.coronal_view.slider.setValue(int(np.clip(round(v * (n_y - 1)), 0, n_y - 1)))

    def _on_sagittal_clicked(self, u: float, v: float):
        n_z, n_y, n_x = self.volume.shape
        self.coronal_view.slider.setValue(int(np.clip(round(u * (n_y - 1)), 0, n_y - 1)))
        z_idx = round((1.0 - v) * (n_z - 1))
        self.axial_view.slider.setValue(int(np.clip(z_idx, 0, n_z - 1)))

    def _on_coronal_clicked(self, u: float, v: float):
        n_z, n_y, n_x = self.volume.shape
        self.sagittal_view.slider.setValue(int(np.clip(round(u * (n_x - 1)), 0, n_x - 1)))
        z_idx = round((1.0 - v) * (n_z - 1))
        self.axial_view.slider.setValue(int(np.clip(z_idx, 0, n_z - 1)))

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
        cross_u = self.sagittal_view.slider.value() / max(n_x - 1, 1) if self._show_guides else None
        cross_v = self.coronal_view.slider.value() / max(n_y - 1, 1) if self._show_guides else None
        self.axial_view.set_pixmap_from_array(arr, low, high, w, h, cross_u, cross_v)
        self.axial_view.info_label.setText(f"Z: {z + 1} / {n_z}")

    def _render_sagittal(self):
        n_z, n_y, n_x = self.volume.shape
        x = self.sagittal_view.slider.value()
        arr = self.volume.sagittal(x)
        low, high = self._window_bounds()
        w, h = self.volume.sagittal_physical_size()
        if self._show_guides:
            cross_u = self.coronal_view.slider.value() / max(n_y - 1, 1)
            # eje Z invertido en esta vista -> la posición vertical va al revés
            cross_v = 1.0 - (self.axial_view.slider.value() / max(n_z - 1, 1))
        else:
            cross_u = cross_v = None
        self.sagittal_view.set_pixmap_from_array(arr, low, high, w, h, cross_u, cross_v)
        self.sagittal_view.info_label.setText(f"X: {x + 1} / {n_x}")

    def _render_coronal(self):
        n_z, n_y, n_x = self.volume.shape
        y = self.coronal_view.slider.value()
        arr = self.volume.coronal(y)
        low, high = self._window_bounds()
        w, h = self.volume.coronal_physical_size()
        if self._show_guides:
            cross_u = self.sagittal_view.slider.value() / max(n_x - 1, 1)
            cross_v = 1.0 - (self.axial_view.slider.value() / max(n_z - 1, 1))
        else:
            cross_u = cross_v = None
        self.coronal_view.set_pixmap_from_array(arr, low, high, w, h, cross_u, cross_v)
        self.coronal_view.info_label.setText(f"Y: {y + 1} / {n_y}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.volume is not None:
            self._render_all()
