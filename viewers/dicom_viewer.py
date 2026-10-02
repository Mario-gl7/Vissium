"""
Visor MPR de DICOM de Vissium (interfaz minimalista).

- Rejilla 2x2 con líneas de 1 px: axial, coronal, sagital y, en la cuarta
  celda, el panel de información. Cada vista lleva su nombre (con el color
  estándar de Slicer: axial rojo, sagital amarillo, coronal verde), el
  número de corte y una barra de desplazamiento fina debajo.
- Panel de información: selector de serie, ventana/nivel y solo los datos
  esenciales (paciente, fecha, tamaño, espaciado, nº de cortes).
- Selector de series: si la selección contiene varias series DICOM se puede
  elegir cuál ver; la nueva serie se lee en un hilo, sin congelar la interfaz.
- Retícula de referencia cruzada: clic (o arrastrar con el botón izquierdo)
  en cualquier vista mueve las otras dos a ese punto.
- Rueda del ratón: avanza/retrocede cortes. Botón derecho + arrastrar: zoom.
  Botón central + arrastrar: desplazar (pan). Doble clic: maximizar la vista.
- Respeta el espaciado físico real de cada eje (importante en CBCT).
- Imágenes 2D (radiografía, panorámica, ecografía): se muestra solo la vista
  principal, grande, junto al panel de información (sin sagital/coronal vacíos).
- Ventana/nivel inicial tomada de las etiquetas DICOM cuando son coherentes
  con los datos; si no, de los percentiles de la imagen.
- Las acciones globales (guías, restablecer vista) las dispara la barra de
  iconos de la ventana mediante `set_guides_visible()` y `reset_view()`.
"""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt, Signal, QPointF, QThread
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from theme import (
    CELL_BG,
    CROSSHAIR,
    PLANE_COLORS,
    TEXT,
    TEXT_DIM,
    TEXT_MUTED,
    WARNING,
)
from volume import DicomLoadError, SeriesInfo, Volume, load_volume

log = logging.getLogger("vissium.dicom")

# Tamaño mínimo cómodo de la zona de imagen de cada vista.
MIN_VIEW_SIZE = 220


# ----------------------------------------------------------------------
# Lectura de otra serie en un hilo
# ----------------------------------------------------------------------
# Los hilos en marcha se guardan aquí (sin padre) para que no se destruyan
# mientras leen si el usuario cierra la pestaña a mitad de carga.
_running_loaders: set = set()


class _SeriesLoader(QThread):
    loaded = Signal(int, object, str)  # (id_de_petición, Volume | None, motivo del fallo)

    def __init__(self, request_id: int, file_paths: list[str], series_uid: str,
                 available: list[SeriesInfo]):
        super().__init__()
        self.request_id = request_id
        self._file_paths = file_paths
        self._series_uid = series_uid
        self._available = available

    def run(self):
        error = ""
        try:
            volume = load_volume(self._file_paths, self._series_uid, self._available)
        except DicomLoadError as exc:
            volume, error = None, str(exc)
        except Exception as exc:
            log.exception("Error leyendo la serie %s", self._series_uid)
            volume, error = None, str(exc)
        self.loaded.emit(self.request_id, volume, error)


def _loader_done(loader: _SeriesLoader):
    _running_loaders.discard(loader)
    loader.deleteLater()


def wait_for_loaders(timeout_ms: int = 3000):
    """Espera a las lecturas de series en curso (se usa al cerrar la aplicación)."""
    for loader in list(_running_loaders):
        loader.wait(timeout_ms)


# ----------------------------------------------------------------------
# Formato de los datos del panel
# ----------------------------------------------------------------------
def _format_patient(value: str) -> str:
    # DICOM separa apellidos y nombre con "^".
    text = " ".join(value.replace("^", " ").split())
    return text if text and text != "—" else "—"


def _format_date(value: str) -> str:
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return value or "—"


def _format_mm(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


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
        painter.fillRect(self.rect(), QColor(CELL_BG))
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
    """Una celda MPR: nombre y nº de corte arriba, imagen, y barra de desplazamiento abajo."""

    pointClicked = Signal(float, float)
    zoomChanged = Signal()
    doubleClicked = Signal()

    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("planeCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.color = color
        self.zoom = 1.0

        self.title_label = QLabel(title, self)
        self.title_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.count_label = QLabel(self)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.count_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        header = QHBoxLayout()
        header.setContentsMargins(8, 6, 8, 0)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.count_label)

        self.image_view = _ImageView(self)
        self.image_view.pointClicked.connect(self.pointClicked)
        self.image_view.wheelScrolled.connect(self._on_wheel)
        self.image_view.zoomRequested.connect(self._on_zoom)
        self.image_view.doubleClicked.connect(self.doubleClicked)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.image_view, stretch=1)
        layout.addSpacing(4)
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(10, 0, 10, 8)
        slider_row.addWidget(self.slider)
        layout.addLayout(slider_row)

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
            pen = QPen(QColor(CROSSHAIR))
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


class _InfoPanel(QWidget):
    """
    Cuarta celda de la rejilla: selector de serie, ventana/nivel y datos
    esenciales del estudio (paciente, fecha, tamaño, espaciado, nº de cortes).
    """

    seriesSelected = Signal(int)  # índice elegido por el usuario en el selector

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("infoCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # El contenido no debe forzar la altura de la fila: las cuatro celdas
        # se reparten el espacio por igual.
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # -- Serie ------------------------------------------------------
        self.series_heading = self._heading("Serie")
        layout.addWidget(self.series_heading)
        self.series_combo = QComboBox(self)
        self.series_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.series_combo.setMinimumContentsLength(12)
        self.series_combo.activated.connect(self.seriesSelected)
        layout.addWidget(self.series_combo)
        layout.addSpacing(8)

        # -- Ventana / nivel --------------------------------------------
        layout.addWidget(self._heading("Ventana / nivel"))
        self.level_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.width_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.level_value = self._value_label()
        self.width_value = self._value_label()
        layout.addLayout(self._row("Nivel", self.level_value))
        layout.addWidget(self.level_slider)
        layout.addLayout(self._row("Ventana", self.width_value))
        layout.addWidget(self.width_slider)
        layout.addSpacing(8)

        # -- Información ------------------------------------------------
        layout.addWidget(self._heading("Información"))
        self._values: dict[str, QLabel] = {}
        for key in ("Paciente", "Fecha", "Tamaño", "Espaciado", "Cortes"):
            label = self._value_label()
            label.setWordWrap(True)
            self._values[key] = label
            layout.addLayout(self._row(key, label))

        self.warn_label = QLabel(self)
        self.warn_label.setStyleSheet(f"color: {WARNING}; font-size: 11px;")
        self.warn_label.hide()
        layout.addWidget(self.warn_label)
        layout.addStretch(1)

    # -- Construcción -----------------------------------------------------
    def _heading(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        return label

    def _value_label(self) -> QLabel:
        label = QLabel("—", self)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet(f"color: {TEXT}; font-size: 12px;")
        return label

    def _row(self, key: str, value_label: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        key_label = QLabel(key, self)
        key_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        row.addWidget(key_label)
        row.addWidget(value_label, stretch=1)
        return row

    # -- Datos --------------------------------------------------------------
    def set_series(self, labels: list[str], current: int):
        self.series_combo.blockSignals(True)
        self.series_combo.clear()
        for i, text in enumerate(labels):
            self.series_combo.addItem(text)
            self.series_combo.setItemData(i, text, Qt.ItemDataRole.ToolTipRole)
        self.series_combo.setCurrentIndex(max(0, current))
        self.series_combo.blockSignals(False)
        self.series_combo.setEnabled(len(labels) > 1)

    def select_series(self, index: int):
        self.series_combo.blockSignals(True)
        self.series_combo.setCurrentIndex(max(0, index))
        self.series_combo.blockSignals(False)

    def set_loading(self, loading: bool):
        self.series_heading.setText("Serie · cargando…" if loading else "Serie")
        self.series_combo.setEnabled(not loading and self.series_combo.count() > 1)

    def set_metadata(self, patient: str, date: str, size: str, spacing: str, slices: str):
        self._values["Paciente"].setText(patient)
        self._values["Fecha"].setText(date)
        self._values["Tamaño"].setText(size)
        self._values["Espaciado"].setText(spacing)
        self._values["Cortes"].setText(slices)

    def set_warnings(self, warnings: list[str]):
        if warnings:
            count = len(warnings)
            self.warn_label.setText(f"⚠ {count} aviso" + ("s" if count > 1 else ""))
            self.warn_label.setToolTip("\n".join(warnings))
            self.warn_label.show()
        else:
            self.warn_label.hide()


class DicomViewer(QWidget):
    """Widget de una pestaña: vista MPR completa con panel de información y series."""

    def __init__(self, file_paths: list[str], parent=None, volume: Volume | None = None):
        super().__init__(parent)
        self._show_guides = True
        self._maximized: str | None = None
        self._request_id = 0
        self._all_paths = list(file_paths)
        # `volume` ya leído (en un hilo, desde preview_window) evita bloquear la interfaz.
        self._single_mode: bool | None = None   # diseño actual: imagen 2D o MPR
        reason = ""
        if volume is None:
            try:
                volume = load_volume(file_paths)
            except Exception as exc:
                log.exception("Error leyendo el DICOM")
                reason = str(exc)
        self.volume: Volume | None = volume

        if self.volume is None:
            layout = QVBoxLayout(self)
            message = QLabel(reason or "No se han podido leer imágenes DICOM válidas en esta selección.", self)
            message.setWordWrap(True)
            layout.addWidget(message)
            return

        self._series: list[SeriesInfo] = list(self.volume.series)

        self.setObjectName("dicomRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(MIN_VIEW_SIZE * 2 + 3, MIN_VIEW_SIZE * 2 + 100)

        self.axial_view = _PlaneView("Axial", PLANE_COLORS["axial"], self)
        self.sagittal_view = _PlaneView("Sagital", PLANE_COLORS["sagittal"], self)
        self.coronal_view = _PlaneView("Coronal", PLANE_COLORS["coronal"], self)
        self.info_panel = _InfoPanel(self)

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

        # Ventana / nivel compartida entre las tres vistas.
        self._wl_center = 0.0
        self._wl_width = 1.0
        self.info_panel.level_slider.valueChanged.connect(self._on_wl_changed)
        self.info_panel.width_slider.valueChanged.connect(self._on_wl_changed)
        self.info_panel.seriesSelected.connect(self._on_series_selected)

        # Rejilla 2x2 con celdas del mismo tamaño; el fondo del propio visor
        # (color de línea) asoma en el hueco de 1 px entre celdas.
        self.views_grid = QGridLayout(self)
        self.views_grid.setContentsMargins(0, 0, 0, 0)
        self.views_grid.setSpacing(1)
        self.views_grid.setRowStretch(0, 1)
        self.views_grid.setRowStretch(1, 1)
        self.views_grid.setColumnStretch(0, 1)
        self.views_grid.setColumnStretch(1, 1)

        self._plane_positions = {
            "axial": (self.axial_view, 0, 0, 1, 1),
            "coronal": (self.coronal_view, 0, 1, 1, 1),
            "sagittal": (self.sagittal_view, 1, 0, 1, 1),
            "info": (self.info_panel, 1, 1, 1, 1),
        }
        for widget, row, col, rspan, cspan in self._plane_positions.values():
            self.views_grid.addWidget(widget, row, col, rspan, cspan)

        self._apply_volume(self.volume)
        self._refresh_series_selector()

    # ------------------------------------------------------------------
    # Acciones globales (las dispara la barra de iconos de la ventana)
    # ------------------------------------------------------------------
    @property
    def supports_guides(self) -> bool:
        return self.volume is not None and not self.volume.is_single_image

    @property
    def guides_visible(self) -> bool:
        return self._show_guides

    def set_guides_visible(self, visible: bool):
        """Muestra u oculta la retícula de referencia cruzada."""
        if self.volume is None:
            return
        self._show_guides = bool(visible)
        self._render_all()

    def reset_view(self):
        """Vuelve el zoom y el pan de las tres vistas a su estado original."""
        if self.volume is None:
            return
        for view in (self.axial_view, self.sagittal_view, self.coronal_view):
            view.zoom = 1.0
            view.image_view.reset_pan()
        self._render_all()

    def shutdown(self):
        """Ignora cualquier lectura de serie que siga en curso al cerrar la pestaña."""
        self._request_id += 1

    # ------------------------------------------------------------------
    # Volumen actual y selector de series
    # ------------------------------------------------------------------
    def _apply_volume(self, volume: Volume):
        """Pone `volume` en las tres vistas (alta inicial o cambio de serie)."""
        self.volume = volume
        n_z, n_y, n_x = volume.shape
        self._relayout()
        for view, count in (
            (self.axial_view, n_z),
            (self.sagittal_view, n_x),
            (self.coronal_view, n_y),
        ):
            view.slider.blockSignals(True)
            view.slider.setRange(0, max(0, count - 1))
            view.slider.setValue(count // 2)
            view.slider.blockSignals(False)
            view.zoom = 1.0
            view.image_view.reset_pan()

        self._setup_window_level_defaults()

        metadata = volume.metadata
        self.info_panel.set_metadata(
            patient=_format_patient(metadata.get("Paciente", "")),
            date=_format_date(metadata.get("Fecha estudio", "")),
            size=f"{n_x} × {n_y} px",
            spacing=(f"{_format_mm(volume.col_spacing)} × {_format_mm(volume.row_spacing)} "
                     f"× {_format_mm(volume.slice_spacing)} mm"),
            slices=str(n_z),
        )
        self.info_panel.set_warnings(volume.warnings)
        self._render_all()

    def _current_series_index(self) -> int:
        for i, info in enumerate(self._series):
            if info.uid == self.volume.series_uid:
                return i
        return 0

    def _refresh_series_selector(self):
        self.info_panel.set_series([s.label for s in self._series], self._current_series_index())

    def _on_series_selected(self, index: int):
        if index < 0 or index >= len(self._series):
            return
        uid = self._series[index].uid
        if uid == self.volume.series_uid:
            return
        self._request_id += 1
        self.info_panel.set_loading(True)
        loader = _SeriesLoader(self._request_id, self._all_paths, uid, self._series)
        loader.loaded.connect(self._on_series_loaded)
        loader.finished.connect(lambda l=loader: _loader_done(l))
        _running_loaders.add(loader)
        loader.start()

    def _on_series_loaded(self, request_id: int, volume, error: str = ""):
        if request_id != self._request_id:
            return  # petición antigua o pestaña cerrada
        self.info_panel.set_loading(False)
        if volume is None:
            self.info_panel.select_series(self._current_series_index())
            self.info_panel.set_warnings([error or "No se pudo leer esa serie."])
            return
        self._apply_volume(volume)
        self.info_panel.select_series(self._current_series_index())

    # ------------------------------------------------------------------
    def _setup_window_level_defaults(self):
        sample = self.volume.axial(self.volume.shape[0] // 2)
        p_low, p_high = np.percentile(sample, [1, 99])
        self._wl_center = float((p_low + p_high) / 2)
        self._wl_width = float(max(p_high - p_low, 1))

        # Si las etiquetas DICOM traen una ventana y es coherente con los datos
        # (se solapa con el rango real de la imagen), se usa; si no, percentiles.
        tag_c, tag_w = self.volume.window_center, self.volume.window_width
        if tag_c is not None and tag_w is not None and tag_w >= 1:
            if tag_c + tag_w / 2 > p_low and tag_c - tag_w / 2 < p_high:
                self._wl_center, self._wl_width = float(tag_c), float(tag_w)

        level_slider = self.info_panel.level_slider
        width_slider = self.info_panel.width_slider
        level_slider.blockSignals(True)
        width_slider.blockSignals(True)

        spread = max(abs(self._wl_center) * 4, self._wl_width * 4, 100)
        level_slider.setMinimum(int(self._wl_center - spread))
        level_slider.setMaximum(int(self._wl_center + spread))
        level_slider.setValue(int(self._wl_center))

        width_slider.setMinimum(1)
        width_slider.setMaximum(int(self._wl_width * 6) + 10)
        width_slider.setValue(int(self._wl_width))

        level_slider.blockSignals(False)
        width_slider.blockSignals(False)
        self._update_wl_labels()

    def _update_wl_labels(self):
        self.info_panel.level_value.setText(str(int(self._wl_center)))
        self.info_panel.width_value.setText(str(int(self._wl_width)))

    def _on_wl_changed(self):
        self._wl_center = float(self.info_panel.level_slider.value())
        self._wl_width = float(max(self.info_panel.width_slider.value(), 1))
        self._update_wl_labels()
        self._render_all()

    def _window_bounds(self):
        return self._wl_center - self._wl_width / 2, self._wl_center + self._wl_width / 2

    # ------------------------------------------------------------------
    # Pantalla completa de una vista dentro del visor
    # ------------------------------------------------------------------
    def _toggle_maximize(self, name: str):
        if self._single_mode:
            return  # imagen 2D: ya ocupa todo el espacio
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
    def _is_single(self) -> bool:
        return self.volume is not None and self.volume.is_single_image

    def _relayout(self):
        """Diseño según el contenido: MPR 2x2, o una sola imagen 2D con el panel al lado."""
        single = self._is_single()
        if single == self._single_mode:
            return
        self._single_mode = single
        self._maximized = None
        for widget, *_ in self._plane_positions.values():
            self.views_grid.removeWidget(widget)
        if single:
            self.sagittal_view.hide()
            self.coronal_view.hide()
            self.axial_view.show()
            self.info_panel.show()
            self.views_grid.addWidget(self.axial_view, 0, 0, 2, 1)
            self.views_grid.addWidget(self.info_panel, 0, 1, 2, 1)
            self.views_grid.setColumnStretch(0, 3)
            self.views_grid.setColumnStretch(1, 1)
        else:
            for widget, row, col, rspan, cspan in self._plane_positions.values():
                self.views_grid.addWidget(widget, row, col, rspan, cspan)
                widget.show()
            self.views_grid.setColumnStretch(0, 1)
            self.views_grid.setColumnStretch(1, 1)
        self.axial_view.slider.setVisible(not single)

    def _render_all(self):
        self._render_axial()
        if self._is_single():
            return
        self._render_sagittal()
        self._render_coronal()

    def _render_axial(self):
        n_z, n_y, n_x = self.volume.shape
        z = self.axial_view.slider.value()
        arr = self.volume.axial(z)
        low, high = self._window_bounds()
        w, h = self.volume.axial_physical_size()
        guides = self._show_guides and not self._is_single()
        cross_u = self.sagittal_view.slider.value() / max(n_x - 1, 1) if guides else None
        cross_v = self.coronal_view.slider.value() / max(n_y - 1, 1) if guides else None
        self.axial_view.set_pixmap_from_array(arr, low, high, w, h, cross_u, cross_v)
        self.axial_view.count_label.setText(f"{z + 1} / {n_z}")

    def _render_sagittal(self):
        if self._is_single():
            return
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
        self.sagittal_view.count_label.setText(f"{x + 1} / {n_x}")

    def _render_coronal(self):
        if self._is_single():
            return
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
        self.coronal_view.count_label.setText(f"{y + 1} / {n_y}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.volume is not None:
            self._render_all()
