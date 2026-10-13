"""
Visor de imágenes (fotos, capturas, PNG, JPG, BMP, GIF, TIFF, WEBP, ICO) de Vissium.

- La imagen se ajusta a la ventana (nunca se amplía por encima de su tamaño real).
- Rueda del ratón: zoom hacia el cursor. Arrastrar con el botón izquierdo: desplazar.
  Doble clic: alternar entre "ajustar" y tamaño real (100 %).
- Teclado: ← / → (o AvPág / RePág) imagen anterior/siguiente de la carpeta,
  Inicio / Fin primera/última, `0` o `F` ajustar, `1` tamaño real, `+` / `-` zoom.
- Si se abre una imagen suelta, se pueden recorrer las demás imágenes de su carpeta
  con las flechas (si se seleccionan varias, solo esas).
- Respeta la orientación EXIF de las fotos de móvil/cámara.
- Muestra el nombre y la posición (3 / 12) arriba a la izquierda, y las dimensiones,
  el peso y el formato abajo a la derecha, sobre una franja translúcida.
- `reset_view()` (botón de la barra de iconos) vuelve a ajustar la imagen.
- La lectura de la imagen la puede hacer un hilo (`read_image`): QImage es seguro
  fuera del hilo de la interfaz; el QPixmap solo se crea aquí.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QImageReader,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from theme import CELL_BG, TEXT, TEXT_DIM

MAX_ZOOM = 32.0
ZOOM_STEP = 1.15
SMOOTH_UP_TO = 3.0   # por encima de este zoom se dibujan los píxeles "a saco" (para inspeccionar)


def read_image(path: str) -> tuple[QImage | None, str, str]:
    """
    Lee una imagen respetando su orientación EXIF.
    Devuelve (imagen | None, mensaje_de_error, formato) y se puede llamar desde un hilo.
    """
    try:
        QImageReader.setAllocationLimit(2048)  # Qt >= 6.8: por defecto limita a 256 MB
    except Exception:
        pass
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    fmt = bytes(reader.format()).decode("ascii", "ignore").upper()
    image = reader.read()
    if image.isNull():
        return None, reader.errorString() or "formato no compatible", fmt
    target = (QImage.Format.Format_ARGB32_Premultiplied if image.hasAlphaChannel()
              else QImage.Format.Format_RGB32)
    if image.format() != target:
        image = image.convertToFormat(target)
    return image, "", fmt


def _human_size(n_bytes: int) -> str:
    size = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n_bytes} B"


class _Canvas(QWidget):
    """Lienzo con zoom, desplazamiento y textos superpuestos."""

    def __init__(self, viewer: "ImageViewer"):
        super().__init__(viewer)
        self._viewer = viewer
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumSize(200, 200)

        self.image: QImage | None = None
        self.error = ""
        self.top_text = ""
        self.bottom_text = ""
        self._fit = True
        self._zoom = 1.0                      # solo si no está en modo ajustar
        self._offset = QPointF(0.0, 0.0)      # desplazamiento respecto a la imagen centrada
        self._drag_pos: QPointF | None = None
        self._cache_key: tuple | None = None
        self._cache: QPixmap | None = None

    # -- Contenido ---------------------------------------------------------
    def set_image(self, image: QImage | None, error: str = ""):
        self.image = image
        self.error = error
        self._cache_key = None
        self._cache = None
        self.fit()

    def fit(self):
        self._fit = True
        self._offset = QPointF(0.0, 0.0)
        self.update()

    # -- Geometría ---------------------------------------------------------
    def _fit_zoom(self) -> float:
        if self.image is None or self.image.width() <= 0 or self.image.height() <= 0:
            return 1.0
        return min(1.0, self.width() / self.image.width(), self.height() / self.image.height())

    def zoom_value(self) -> float:
        return self._fit_zoom() if self._fit else self._zoom

    def _clamp_offset(self, zoom: float):
        if self.image is None:
            return
        dw, dh = self.image.width() * zoom, self.image.height() * zoom
        max_x = max(0.0, (dw - self.width()) / 2)
        max_y = max(0.0, (dh - self.height()) / 2)
        self._offset = QPointF(
            max(-max_x, min(max_x, self._offset.x())),
            max(-max_y, min(max_y, self._offset.y())),
        )

    def _origin(self, zoom: float) -> QPointF:
        """Esquina superior izquierda de la imagen en el lienzo."""
        dw, dh = self.image.width() * zoom, self.image.height() * zoom
        return QPointF((self.width() - dw) / 2 + self._offset.x(),
                       (self.height() - dh) / 2 + self._offset.y())

    def zoom_to(self, new_zoom: float, anchor: QPointF | None = None):
        """Cambia el zoom manteniendo fijo el punto de la imagen que hay bajo `anchor`."""
        if self.image is None:
            return
        fit = self._fit_zoom()
        new_zoom = max(fit, min(MAX_ZOOM, new_zoom))
        old_zoom = self.zoom_value()
        if anchor is None:
            anchor = QPointF(self.width() / 2, self.height() / 2)
        origin = self._origin(old_zoom)
        img_x = (anchor.x() - origin.x()) / old_zoom
        img_y = (anchor.y() - origin.y()) / old_zoom

        if abs(new_zoom - fit) < 1e-6:
            self.fit()
            return
        self._fit = False
        self._zoom = new_zoom
        dw, dh = self.image.width() * new_zoom, self.image.height() * new_zoom
        new_origin_x = anchor.x() - img_x * new_zoom
        new_origin_y = anchor.y() - img_y * new_zoom
        self._offset = QPointF(new_origin_x - (self.width() - dw) / 2,
                               new_origin_y - (self.height() - dh) / 2)
        self._clamp_offset(new_zoom)
        self.update()

    # -- Pintado ------------------------------------------------------------
    def _scaled_pixmap(self, zoom: float) -> QPixmap:
        dpr = self.devicePixelRatioF() or 1.0
        key = (id(self.image), round(zoom, 5), dpr)
        if self._cache_key != key or self._cache is None:
            w = max(1, round(self.image.width() * zoom * dpr))
            h = max(1, round(self.image.height() * zoom * dpr))
            if zoom >= 0.9999 and dpr == 1.0:
                pixmap = QPixmap.fromImage(self.image)
            else:
                pixmap = QPixmap.fromImage(self.image.scaled(
                    w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            pixmap.setDevicePixelRatio(dpr)
            self._cache_key, self._cache = key, pixmap
        return self._cache

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(CELL_BG))

        if self.image is None:
            painter.setPen(QColor(TEXT_DIM))
            message = "No se pudo abrir la imagen"
            if self.error:
                message += f"\n{self.error}"
            painter.drawText(self.rect().adjusted(24, 24, -24, -24),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, message)
        else:
            zoom = self.zoom_value()
            origin = self._origin(zoom)
            dw, dh = self.image.width() * zoom, self.image.height() * zoom
            if zoom <= 1.0:
                painter.drawPixmap(origin, self._scaled_pixmap(zoom))
            else:
                # Ampliado: solo se dibuja la parte visible (si no, el pixmap sería enorme).
                target = QRectF(origin.x(), origin.y(), dw, dh).intersected(
                    QRectF(0, 0, self.width(), self.height()))
                if not target.isEmpty():
                    source = QRectF((target.x() - origin.x()) / zoom,
                                    (target.y() - origin.y()) / zoom,
                                    target.width() / zoom, target.height() / zoom)
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                                          zoom < SMOOTH_UP_TO)
                    painter.drawImage(target, self.image, source)

        self._paint_overlay(painter)
        painter.end()

    def _paint_overlay(self, painter: QPainter):
        font = QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        pad_x, pad_y, margin = 8, 4, 10
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        def pill(text: str, left: bool, top: bool):
            if not text:
                return
            max_w = max(60, self.width() - 2 * margin - 2 * pad_x)
            shown = metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, max_w)
            w = metrics.horizontalAdvance(shown) + 2 * pad_x
            h = metrics.height() + 2 * pad_y
            x = margin if left else self.width() - margin - w
            y = margin if top else self.height() - margin - h
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawRoundedRect(QRectF(x, y, w, h), 4, 4)
            painter.setPen(QColor(TEXT))
            painter.drawText(QRectF(x + pad_x, y + pad_y, w - 2 * pad_x, metrics.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, shown)

        pill(self.top_text, left=True, top=True)
        pill(self.bottom_text, left=False, top=False)

    # -- Ratón ---------------------------------------------------------------
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta != 0 and self.image is not None:
            factor = ZOOM_STEP ** (delta / 120.0)
            self.zoom_to(self.zoom_value() * factor, event.position())
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and self.image is not None:
            delta = event.position() - self._drag_pos
            self._drag_pos = event.position()
            self._offset += delta
            self._clamp_offset(self.zoom_value())
            self._fit = self._fit and self._offset == QPointF(0.0, 0.0)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image is not None:
            if self._fit and self._fit_zoom() < 1.0:
                self.zoom_to(1.0, event.position())   # ajustada -> tamaño real
            else:
                self.fit()                            # ampliada (o ya a 100 %) -> ajustar
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._fit:
            self._clamp_offset(self._zoom)

    # -- Teclado ---------------------------------------------------------------
    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self._viewer.step(-1)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            self._viewer.step(1)
        elif key == Qt.Key.Key_Home:
            self._viewer.go_to(0)
        elif key == Qt.Key.Key_End:
            self._viewer.go_to(-1)
        elif key in (Qt.Key.Key_0, Qt.Key.Key_F):
            self.fit()
        elif key == Qt.Key.Key_1:
            self.zoom_to(1.0)
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_to(self.zoom_value() * ZOOM_STEP * 1.3)
        elif key == Qt.Key.Key_Minus:
            self.zoom_to(self.zoom_value() / (ZOOM_STEP * 1.3))
        else:
            super().keyPressEvent(event)


class ImageViewer(QWidget):
    """Widget de una pestaña: una imagen (o una carpeta de imágenes) a pantalla completa."""

    supports_guides = False   # no hay guías de cruce (la barra de iconos desactiva ese botón)

    def __init__(self, files: list[str], index: int = 0, parent=None,
                 first: tuple | None = None):
        """
        `files`: imágenes recorribles con las flechas; `index`: la que se muestra primero.
        `first`: resultado de `read_image` de esa primera imagen, si ya se leyó en un hilo.
        """
        super().__init__(parent)
        self._files = list(files)
        self._index = max(0, min(index, len(self._files) - 1)) if self._files else 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.canvas = _Canvas(self)
        outer.addWidget(self.canvas)
        self.setFocusProxy(self.canvas)

        if self._files:
            self._show_file(first)

    # ------------------------------------------------------------------
    def _show_file(self, loaded: tuple | None = None):
        path = self._files[self._index]
        image, error, fmt = loaded if loaded is not None else read_image(path)
        self.canvas.set_image(image, error)

        name = os.path.basename(path)
        position = f"  ·  {self._index + 1} / {len(self._files)}" if len(self._files) > 1 else ""
        self.canvas.top_text = f"{name}{position}"
        if image is not None:
            try:
                weight = _human_size(os.path.getsize(path))
            except OSError:
                weight = ""
            parts = [f"{image.width()} × {image.height()} px", weight, fmt]
            self.canvas.bottom_text = "  ·  ".join(p for p in parts if p)
        else:
            self.canvas.bottom_text = ""
        self.canvas.update()

    def step(self, delta: int):
        """Imagen anterior (-1) o siguiente (+1); da la vuelta al llegar al final."""
        if len(self._files) > 1:
            self._index = (self._index + delta) % len(self._files)
            self._show_file()

    def go_to(self, index: int):
        """Salta a una imagen concreta (-1 = la última)."""
        if self._files:
            self._index = index % len(self._files)
            self._show_file()

    def reset_view(self):
        """Vuelve a ajustar la imagen a la ventana (botón de la barra de iconos)."""
        self.canvas.fit()

    def showEvent(self, event):
        super().showEvent(event)
        self.canvas.setFocus()
