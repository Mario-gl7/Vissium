"""
Tema visual de Vissium: colores, hoja de estilos global e iconos.

Estilo "Linear" (referencia: linear.app / awesome-design-md): barra lateral sin
bordes, contenido dentro de una tarjeta redondeada con línea fina clara, cada
apartado en su propia caja con borde de 1 px y esquinas de 10-12 px, botones en
forma de píldora y un único color de acento. Los colores son los de siempre
(fondo casi negro, acento índigo, colores de plano rojo/amarillo/verde).

Los iconos se dibujan con QPainter, así que no hace falta empaquetar imágenes ni
depender de fuentes de iconos del sistema.

- `STYLESHEET`: se aplica una sola vez, en la ventana de previsualizaciones;
  los visores heredan el estilo. Los widgets son transparentes por defecto: el
  fondo lo ponen la ventana (`BG`), la tarjeta (`#card`) y cada celda.
- `icon(nombre)`: icono de línea fina ("folder", "crosshair", "refresh", "close",
  "image", "cube", "loading", "warning", "layers", "eye", "eye-off",
  "skull", "minimize", "maximize", "restore", "switch") con
  estados apagado / activo / deshabilitado.
- `rounded_mask(widget, radio)`: recorta con esquinas redondeadas un widget con
  ventana nativa (el de VTK), que de otro modo se vería con esquinas cuadradas.
- `apply_dark_titlebar(ventana)`: en Windows 10/11 pone oscura la barra de
  título nativa para que case con el resto de la interfaz.
"""
from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion

from paths import resource_path

IS_WINDOWS = sys.platform.startswith("win")

# -- Paleta ---------------------------------------------------------------
# Mismos colores que antes; se añade la tarjeta (`CARD`) y las líneas pasan a ser
# más claras para delimitar cada apartado. Todo en hexadecimal (se usa también
# con QColor).
BG = "#0e0f10"            # ventana y barra lateral
CARD = "#131416"          # tarjeta principal y paneles
CELL_BG = "#000000"       # vistas de imagen / modelo
PANEL_BG = CARD
LINE = "#2f3035"          # línea fina (separadores, bordes de cajas)
LINE_STRONG = "#45464c"   # borde de botones, menús y paneles flotantes
FIELD_BG = "#17181b"
HOVER_BG = "#1b1c1f"
TEXT = "#ededee"
TEXT_DIM = "#a0a3aa"
TEXT_MUTED = "#6f737b"
ICON_DISABLED = "#3a3c42"
ACCENT = "#7b86e8"
ACCENT_SOFT = "#1a1c2e"   # fondo de lo activo (píldora "Dos STL", selección)
ACCENT_TEXT = "#aab1f2"
CROSSHAIR = "#4fc3f7"
WARNING = "#e3c34c"
RADIUS = 10               # esquinas de cajas y vistas
RADIUS_CARD = 12          # esquinas de la tarjeta principal
FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", Arial, sans-serif'

PLANE_COLORS = {
    "axial": "#e34c4c",
    "sagittal": "#e3d34c",
    "coronal": "#4ce35c",
}

STYLESHEET = f"""
QWidget {{ background: transparent; color: {TEXT}; font-family: {FONT_STACK}; font-size: 12px; }}
QMainWindow, QDialog, QMessageBox {{ background-color: {BG}; }}
QLabel {{ background: transparent; }}
QToolTip {{
    background-color: {HOVER_BG}; color: {TEXT};
    border: 1px solid {LINE_STRONG}; border-radius: 6px; padding: 4px 8px;
}}

QSplitter::handle {{ background-color: {LINE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}

/* Tarjeta principal: contiene las pestañas y las vistas. */
#card {{ background-color: {CARD}; border: 1px solid {LINE}; border-radius: {RADIUS_CARD}px; }}

/* Pestañas en la cabecera de la tarjeta, con la activa en píldora. */
QTabWidget::pane {{ border: 0; border-top: 1px solid {LINE}; padding: 10px; }}
QTabWidget::tab-bar {{ left: 8px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_MUTED};
    padding: 5px 10px; margin: 7px 3px 7px 0;
    border: 1px solid transparent; border-radius: 8px;
}}
QTabBar::tab:hover {{ color: {TEXT_DIM}; background-color: {HOVER_BG}; }}
QTabBar::tab:selected {{ color: {TEXT}; background-color: {HOVER_BG}; border: 1px solid {LINE}; }}

QStatusBar {{ color: {TEXT_MUTED}; }}
QStatusBar::item {{ border: 0; }}

QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px;
}}
QToolButton:hover {{ background-color: {HOVER_BG}; }}
QToolButton:checked {{ background-color: {LINE}; }}
QToolButton:focus {{ border: 1px solid {ACCENT}; }}
QToolButton#tabClose {{ padding: 2px; border-radius: 4px; }}
QToolButton#tabClose:hover {{ background-color: {LINE_STRONG}; }}

QPushButton {{
    background-color: {HOVER_BG}; border: 1px solid {LINE_STRONG};
    border-radius: 8px; padding: 5px 14px;
}}
QPushButton:hover {{ background-color: {LINE}; }}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}

/* Barra lateral: botones de texto sin borde; el activo, en caja gris. */
#rail {{ background: transparent; }}
#railBrand {{ font-size: 13px; font-weight: 600; color: {TEXT}; padding: 4px 6px; }}
QPushButton#railBtn {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 6px 10px; text-align: left; color: {TEXT_DIM};
}}
QPushButton#railBtn:hover {{ background-color: {HOVER_BG}; color: {TEXT}; }}
QPushButton#railBtn:checked {{ background-color: {HOVER_BG}; color: {TEXT}; }}
QPushButton#railBtn:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#railBtn:disabled {{ color: {ICON_DISABLED}; background: transparent; }}

/* Botones en forma de píldora (cabecera del visor STL). */
QPushButton#pill {{
    background-color: {FIELD_BG}; border: 1px solid {LINE_STRONG}; border-radius: 14px;
    padding: 4px 12px; color: {TEXT_DIM};
}}
QPushButton#pill:hover {{ background-color: {HOVER_BG}; color: {TEXT}; }}
QPushButton#pill:checked {{ background-color: {ACCENT_SOFT}; border: 1px solid {ACCENT}; color: {ACCENT_TEXT}; }}
QPushButton#pill:focus {{ border: 1px solid {ACCENT}; }}

QMenu {{
    background-color: {FIELD_BG}; border: 1px solid {LINE_STRONG}; border-radius: 10px; padding: 4px;
}}
QMenu::item {{ padding: 6px 16px; border-radius: 6px; color: {TEXT}; background: transparent; }}
QMenu::item:selected {{ background-color: {HOVER_BG}; }}
QMenu::item:disabled {{ color: {TEXT_MUTED}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}

QLineEdit {{
    background-color: {FIELD_BG}; border: 1px solid {LINE};
    border-radius: 8px; padding: 4px 8px;
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
QTreeView {{ background-color: {CARD}; border: 0; }}
QTreeView::item {{ padding: 2px 0; border-radius: 6px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {TEXT_MUTED}; border: 0; padding: 4px 6px; }}
QTreeView::item:selected {{ background-color: {HOVER_BG}; color: {TEXT}; }}

QComboBox {{
    background-color: {FIELD_BG}; border: 1px solid {LINE};
    border-radius: 8px; padding: 4px 8px; color: {TEXT};
}}
QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox:disabled {{ color: {TEXT_MUTED}; }}
QComboBox QAbstractItemView {{
    background-color: {FIELD_BG}; color: {TEXT}; border: 1px solid {LINE_STRONG};
    border-radius: 8px; selection-background-color: {HOVER_BG}; selection-color: {TEXT}; outline: 0;
}}

QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{ background: {LINE}; height: 2px; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {TEXT_DIM}; height: 2px; border-radius: 1px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 10px; height: 10px;
    margin: -4px 0; border-radius: 5px;
}}
QSlider::handle:horizontal:focus {{ background: {ACCENT}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {LINE_STRONG}; border-radius: 5px; min-height: 24px;
}}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {LINE_STRONG}; border-radius: 5px; min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Visor DICOM: cada vista es una caja con borde fino y esquinas redondeadas. */
#dicomRoot {{ background: transparent; }}
#planeCell {{ background-color: {CELL_BG}; border: 1px solid {LINE}; border-radius: {RADIUS}px; }}
#infoCell {{ background-color: {PANEL_BG}; border: 1px solid {LINE}; border-radius: {RADIUS}px; }}

/* Visor STL: cabecera, marco del modelo y panel de modelos. */
#meshHeader {{ background: transparent; }}
#meshTitle {{ font-weight: 600; color: {TEXT}; }}
#meshHint {{ color: {TEXT_MUTED}; font-size: 11px; }}
#modelsPanel {{ background-color: {PANEL_BG}; border: 1px solid {LINE}; border-radius: {RADIUS}px; }}
#modelsHeading {{ color: {TEXT_MUTED}; font-size: 11px; }}
QPushButton#modelRow {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 6px 8px; text-align: left; color: {TEXT_DIM};
}}
QPushButton#modelRow:hover {{ background-color: {HOVER_BG}; }}
QPushButton#modelRow:checked {{ background-color: {HOVER_BG}; border: 1px solid {LINE}; color: {TEXT}; }}
QToolButton#modelEye {{ padding: 4px; border-radius: 6px; }}

#emptyState {{ background: transparent; }}
#emptyTitle {{ font-size: 22px; font-weight: 600; color: {TEXT}; }}
#emptyHint {{ font-size: 13px; color: {TEXT_DIM}; }}
#emptyFormats {{ font-size: 11px; color: {TEXT_MUTED}; letter-spacing: 1px; }}
#kbd {{
    background-color: {FIELD_BG}; border: 1px solid {LINE_STRONG}; border-radius: 5px;
    padding: 1px 7px; font-family: "Cascadia Mono", Consolas, monospace; color: {TEXT};
}}
"""


def rounded_mask(widget, radius: int) -> None:
    """Recorta `widget` con esquinas redondeadas (útil para el widget nativo de VTK)."""
    rect = QRectF(0, 0, widget.width(), widget.height())
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


# -- Iconos -------------------------------------------------------------
def _draw_icon(name: str, color: str) -> QPixmap:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(4.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    if name == "folder":
        path = QPainterPath()
        path.moveTo(8, 18)
        path.lineTo(26, 18)
        path.lineTo(31, 25)
        path.lineTo(56, 25)
        path.lineTo(56, 50)
        path.lineTo(8, 50)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "crosshair":
        p.drawEllipse(QPointF(32, 32), 14, 14)
        p.drawLine(QPointF(32, 6), QPointF(32, 20))
        p.drawLine(QPointF(32, 44), QPointF(32, 58))
        p.drawLine(QPointF(6, 32), QPointF(20, 32))
        p.drawLine(QPointF(44, 32), QPointF(58, 32))
    elif name == "refresh":
        # Arco de 280° con una punta de flecha en su extremo.
        p.drawArc(12, 12, 40, 40, 40 * 16, 280 * 16)
        tip = QPointF(47.3, 44.9)
        p.drawLine(tip, QPointF(35.7, 48.0))
        p.drawLine(tip, QPointF(46.3, 56.9))
    elif name == "close":
        p.drawLine(QPointF(18, 18), QPointF(46, 46))
        p.drawLine(QPointF(46, 18), QPointF(18, 46))
    elif name == "image":
        p.drawRoundedRect(8, 12, 48, 40, 5, 5)
        p.drawEllipse(QPointF(22, 26), 4, 4)
        path = QPainterPath()
        path.moveTo(10, 46)
        path.lineTo(26, 32)
        path.lineTo(36, 42)
        path.lineTo(42, 36)
        path.lineTo(54, 48)
        p.drawPath(path)
    elif name == "cube":
        path = QPainterPath()
        path.moveTo(32, 8)
        path.lineTo(54, 20)
        path.lineTo(54, 44)
        path.lineTo(32, 56)
        path.lineTo(10, 44)
        path.lineTo(10, 20)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(10, 20), QPointF(32, 32))
        p.drawLine(QPointF(54, 20), QPointF(32, 32))
        p.drawLine(QPointF(32, 32), QPointF(32, 56))
    elif name == "skull":
        # Perfil frontal simplificado de cráneo, legible también a 16 px.
        path = QPainterPath()
        path.moveTo(18, 49)
        path.lineTo(16, 43)
        path.lineTo(11, 39)
        path.lineTo(9, 31)
        path.lineTo(11, 21)
        path.lineTo(17, 13)
        path.lineTo(25, 9)
        path.lineTo(39, 9)
        path.lineTo(47, 13)
        path.lineTo(53, 21)
        path.lineTo(55, 31)
        path.lineTo(53, 39)
        path.lineTo(48, 43)
        path.lineTo(46, 49)
        path.lineTo(40, 49)
        path.lineTo(40, 44)
        path.lineTo(24, 44)
        path.lineTo(24, 49)
        path.closeSubpath()
        p.drawPath(path)
        p.drawEllipse(QPointF(22, 29), 4, 5)
        p.drawEllipse(QPointF(42, 29), 4, 5)
        p.drawLine(QPointF(32, 33), QPointF(29, 39))
        p.drawLine(QPointF(35, 39), QPointF(29, 39))
        p.drawLine(QPointF(28, 46), QPointF(28, 51))
        p.drawLine(QPointF(36, 46), QPointF(36, 51))
    elif name == "minimize":
        p.drawLine(QPointF(16, 44), QPointF(48, 44))
    elif name == "maximize":
        p.drawLine(QPointF(25, 11), QPointF(11, 11))
        p.drawLine(QPointF(11, 11), QPointF(11, 25))
        p.drawLine(QPointF(39, 11), QPointF(53, 11))
        p.drawLine(QPointF(53, 11), QPointF(53, 25))
        p.drawLine(QPointF(11, 39), QPointF(11, 53))
        p.drawLine(QPointF(11, 53), QPointF(25, 53))
        p.drawLine(QPointF(53, 39), QPointF(53, 53))
        p.drawLine(QPointF(53, 53), QPointF(39, 53))
    elif name == "restore":
        p.drawRoundedRect(12, 20, 32, 32, 4, 4)
        p.drawLine(QPointF(25, 12), QPointF(48, 12))
        p.drawLine(QPointF(48, 12), QPointF(48, 35))
        p.drawLine(QPointF(48, 35), QPointF(44, 35))
    elif name == "switch":
        p.drawLine(QPointF(10, 22), QPointF(49, 22))
        p.drawLine(QPointF(49, 22), QPointF(40, 13))
        p.drawLine(QPointF(49, 22), QPointF(40, 31))
        p.drawLine(QPointF(54, 42), QPointF(15, 42))
        p.drawLine(QPointF(15, 42), QPointF(24, 33))
        p.drawLine(QPointF(15, 42), QPointF(24, 51))
    elif name == "loading":
        p.drawArc(14, 14, 36, 36, 60 * 16, 240 * 16)
    elif name == "warning":
        path = QPainterPath()
        path.moveTo(32, 10)
        path.lineTo(56, 52)
        path.lineTo(8, 52)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(32, 25), QPointF(32, 38))
        p.drawPoint(QPointF(32, 45))
    elif name == "layers":
        # Dos rombos apilados: "varios modelos en la misma vista".
        top = QPainterPath()
        top.moveTo(32, 10)
        top.lineTo(56, 24)
        top.lineTo(32, 38)
        top.lineTo(8, 24)
        top.closeSubpath()
        p.drawPath(top)
        low = QPainterPath()
        low.moveTo(8, 36)
        low.lineTo(32, 50)
        low.lineTo(56, 36)
        p.drawPath(low)
    elif name in ("eye", "eye-off"):
        eye = QPainterPath()
        eye.moveTo(6, 32)
        eye.quadTo(32, 6, 58, 32)
        eye.quadTo(32, 58, 6, 32)
        p.drawPath(eye)
        p.drawEllipse(QPointF(32, 32), 8, 8)
        if name == "eye-off":
            p.drawLine(QPointF(12, 54), QPointF(54, 10))
    p.end()
    return pm


def tab_icon(name: str) -> QIcon:
    """Icono pequeño y fijo (sin estados) para las pestañas."""
    return QIcon(_draw_icon(name, TEXT_DIM))


def make_close_button(callback, parent=None):
    """Botón de cierre de pestaña dibujado por nosotros (el nativo se ve como un cuadrado blanco)."""
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QToolButton
    button = QToolButton(parent)
    button.setObjectName("tabClose")
    button.setIcon(icon("close"))
    button.setIconSize(QSize(12, 12))
    button.setAutoRaise(True)
    button.setToolTip("Cerrar pestaña")
    button.setAccessibleName("Cerrar pestaña")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(callback)
    return button


def icon(name: str) -> QIcon:
    """Icono de línea: gris apagado, claro al pasar el ratón o al estar activo."""
    dim = _draw_icon(name, TEXT_MUTED)
    bright = _draw_icon(name, TEXT)
    off = _draw_icon(name, ICON_DISABLED)
    qicon = QIcon()
    qicon.addPixmap(dim, QIcon.Mode.Normal, QIcon.State.Off)
    qicon.addPixmap(bright, QIcon.Mode.Normal, QIcon.State.On)
    qicon.addPixmap(bright, QIcon.Mode.Active, QIcon.State.Off)
    qicon.addPixmap(bright, QIcon.Mode.Active, QIcon.State.On)
    qicon.addPixmap(off, QIcon.Mode.Disabled, QIcon.State.Off)
    qicon.addPixmap(off, QIcon.Mode.Disabled, QIcon.State.On)
    return qicon


# -- Icono de la aplicación -------------------------------------------
_app_icon_cache: QIcon | None = None


def app_icon() -> QIcon:
    """
    Icono NUEVO de Vissium (assets/vissium_icon.ico|png) para el interior de la app:
    icono de la ventana y pestañas de los DICOM. El splash, la bandeja y el .exe
    siguen usando el icono anterior (assets/icon.ico|png). Si falta el nuevo, se
    usa el anterior; si no hay ninguno, devuelve un QIcon vacío.
    """
    global _app_icon_cache
    if _app_icon_cache is None:
        _app_icon_cache = QIcon()
        for name in ("vissium_icon.ico", "vissium_icon.png", "icon.ico", "icon.png"):
            path = resource_path("assets", name)
            if os.path.exists(path):
                candidate = QIcon(path)
                if not candidate.isNull():
                    _app_icon_cache = candidate
                    break
    return _app_icon_cache


# -- Barra de título oscura (Windows) -----------------------------------
def apply_dark_titlebar(widget) -> None:
    """Best-effort: si falla, se queda la barra de título normal del sistema."""
    if not IS_WINDOWS:
        return
    try:
        hwnd = ctypes.c_void_p(int(widget.winId()))
        value = ctypes.c_int(1)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+ / Win11); 19 en builds antiguas.
        for attr in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
    except Exception:
        pass
