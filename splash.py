"""
Pantalla de inicio (splash) de Vissium.

Composición a pantalla completa: a la izquierda la marca, la etiqueta de formatos
y la barra de progreso; a la derecha, el cráneo en rayos X con su retícula de
planos (`assets/splash_art.png`, reescalado x4 con superresolución).

Todo el texto y la barra se dibujan en vectores con QPainter (nítido a cualquier
escala de pantalla); solo el cráneo es una imagen. Así el estado ("Inicializando…")
y el progreso pueden cambiar mientras se cargan VTK, pydicom, etc.

Las coordenadas están en un espacio de referencia de 715 x 667 (`REF_W`, `REF_H`)
y se escalan con `SPLASH_SCALE`, de modo que el diseño no depende de la resolución.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication,
    QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import QSplashScreen

from paths import resource_path

REF_W, REF_H = 715, 667          # espacio de referencia del diseño
SPLASH_SCALE = 0.9               # tamaño real = referencia x escala (644 x 600)
ART_X = 380                      # donde empieza el cráneo (referencia)

# Paleta del splash: mismo azul frío que el cráneo, sin colores nuevos.
C_BG_TOP = QColor("#0c1016")
C_BG_BOTTOM = QColor("#090c11")
C_FRAME = QColor("#1b222c")
C_TAG = QColor("#7d8794")
C_TITLE = QColor("#f1f3f6")
C_SUBTITLE = QColor("#d9dee6")
C_STATUS = QColor("#c5ccd6")
C_DETAIL = QColor("#8a94a3")
C_TRACK = QColor("#1a2230")
C_FILL_A = QColor("#5f8fc9")
C_FILL_B = QColor("#9cc3ee")

TAGS = ("CT", "CBCT", "STL", "DICOM")

_fonts_loaded = False
_FAMILY_LIGHT = ""
_FAMILY_REGULAR = ""


def _load_fonts() -> tuple[str, str]:
    """Registra Montserrat (incluida en assets/fonts) y devuelve (ligera, regular)."""
    global _fonts_loaded, _FAMILY_LIGHT, _FAMILY_REGULAR
    if _fonts_loaded:
        return _FAMILY_LIGHT, _FAMILY_REGULAR
    _fonts_loaded = True
    fallback = "Segoe UI"
    families = []
    for name in ("Montserrat-Light.ttf", "Montserrat-Regular.ttf"):
        font_id = QFontDatabase.addApplicationFont(resource_path("assets", "fonts", name))
        found = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        families.append(found[0] if found else fallback)
    _FAMILY_LIGHT, _FAMILY_REGULAR = families
    return _FAMILY_LIGHT, _FAMILY_REGULAR


def _font(family: str, pixel_size: float, weight: QFont.Weight, spacing: float = 0.0) -> QFont:
    font = QFont(family)
    font.setPixelSize(round(pixel_size))
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def _draw_text(p: QPainter, x: float, baseline: float, text: str, font: QFont, color: QColor):
    p.setFont(font)
    p.setPen(color)
    p.drawText(QPointF(x, baseline), text)


def _title_font(family: str, target_width: float, text: str, size: float = 40) -> QFont:
    """Ajusta el tracking para que el título ocupe exactamente `target_width`."""
    base = QFontMetricsF(_font(family, size, QFont.Weight.Light)).horizontalAdvance(text)
    spacing = (target_width - base) / max(1, len(text) - 1)
    return _font(family, size, QFont.Weight.Light, spacing)


def _draw_art(p: QPainter, ratio: float):
    """
    Dibuja el cráneo con el borde izquierdo desvanecido (alfa), de modo que se
    funde con el degradado de fondo a cualquier altura, sin costura.
    """
    art = QPixmap(resource_path("assets", "splash_art.png"))
    if art.isNull():
        return
    w, h = REF_W - ART_X, REF_H
    layer = QPixmap(round(w * SPLASH_SCALE * ratio), round(h * SPLASH_SCALE * ratio))
    layer.setDevicePixelRatio(ratio)
    layer.fill(Qt.GlobalColor.transparent)

    lp = QPainter(layer)
    lp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    lp.scale(SPLASH_SCALE, SPLASH_SCALE)
    lp.drawPixmap(QRectF(0, 0, w, h), art, QRectF(art.rect()))
    lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    mask = QLinearGradient(0, 0, 54, 0)
    mask.setColorAt(0.0, QColor(0, 0, 0, 0))
    mask.setColorAt(1.0, QColor(0, 0, 0, 255))
    lp.fillRect(QRectF(0, 0, w, h), mask)
    lp.end()

    p.save()
    p.scale(1 / SPLASH_SCALE, 1 / SPLASH_SCALE)  # la capa ya está en píxeles lógicos finales
    p.drawPixmap(QPointF(ART_X * SPLASH_SCALE, 0), layer)
    p.restore()


def _draw_progress(p: QPainter, value: float):
    x, y, w, h = 61.0, 578.0, 294.0, 5.0
    radius = h / 2
    track = QPainterPath()
    track.addRoundedRect(QRectF(x, y, w, h), radius, radius)
    p.fillPath(track, C_TRACK)
    value = max(0.0, min(1.0, value))
    if value <= 0:
        return
    fill_w = max(h, w * value)
    grad = QLinearGradient(x, 0, x + w, 0)
    grad.setColorAt(0.0, C_FILL_A)
    grad.setColorAt(1.0, C_FILL_B)
    fill = QPainterPath()
    fill.addRoundedRect(QRectF(x, y, fill_w, h), radius, radius)
    p.fillPath(fill, grad)


def render_splash(
    progress: float = 0.3,
    status: str = "Inicializando…",
    detail: str = "Cargando volúmenes DICOM",
    pixel_ratio: float = 2.0,
) -> QPixmap:
    """
    Dibuja el splash completo. `pixel_ratio` es la densidad de píxeles del
    lienzo (2 = nítido en pantallas HiDPI; 4 para exportar una imagen grande).
    """
    light, regular = _load_fonts()
    logical_w, logical_h = REF_W * SPLASH_SCALE, REF_H * SPLASH_SCALE
    pixmap = QPixmap(round(logical_w * pixel_ratio), round(logical_h * pixel_ratio))
    pixmap.setDevicePixelRatio(pixel_ratio)

    p = QPainter(pixmap)
    p.setRenderHints(
        QPainter.RenderHint.Antialiasing
        | QPainter.RenderHint.TextAntialiasing
        | QPainter.RenderHint.SmoothPixmapTransform
    )
    p.scale(SPLASH_SCALE, SPLASH_SCALE)

    bg = QLinearGradient(0, 0, 0, REF_H)
    bg.setColorAt(0.0, C_BG_TOP)
    bg.setColorAt(1.0, C_BG_BOTTOM)
    p.fillRect(QRectF(0, 0, REF_W, REF_H), bg)

    _draw_art(p, pixel_ratio)

    tag_font = _font(regular, 11, QFont.Weight.Normal, 1.4)
    for i, tag in enumerate(TAGS):
        _draw_text(p, 59, 60 + i * 24.5, tag, tag_font, C_TAG)

    _draw_text(p, 62, 347, "VISSIUM", _title_font(light, 290, "VISSIUM"), C_TITLE)
    _draw_text(p, 62, 402, "Visualización médica en 3D…",
               _font(regular, 17, QFont.Weight.Normal), C_SUBTITLE)

    _draw_text(p, 61, 558, status, _font(regular, 13.5, QFont.Weight.Normal), C_STATUS)
    _draw_progress(p, progress)
    _draw_text(p, 61, 621, detail, _font(regular, 11.5, QFont.Weight.Normal, 0.2), C_DETAIL)

    p.setPen(QPen(C_FRAME, 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(0.5, 0.5, REF_W - 1, REF_H - 1))
    p.end()
    return pixmap


class VissiumSplash(QSplashScreen):
    """Splash con progreso: cada `advance()` repinta estado y barra al instante."""

    def __init__(self):
        screen = QGuiApplication.primaryScreen()
        ratio = max(2.0, screen.devicePixelRatio() if screen else 2.0)
        self._ratio = ratio
        super().__init__(render_splash(0.0, pixel_ratio=ratio),
                         Qt.WindowType.WindowStaysOnTopHint)

    def advance(self, progress: float, status: str, detail: str = ""):
        self.setPixmap(render_splash(progress, status, detail, pixel_ratio=self._ratio))
        self.repaint()
