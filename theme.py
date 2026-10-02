"""
Tema visual de Vissium: colores, hoja de estilos global e iconos.

Interfaz minimalista y neutra (gris casi negro, líneas de 1 px, un único
color de acento). Los iconos se dibujan con QPainter, así que no hace falta
empaquetar imágenes ni depender de fuentes de iconos del sistema.

- `STYLESHEET`: se aplica una sola vez, en la ventana de previsualizaciones;
  los visores heredan el estilo.
- `icon(nombre)`: icono de línea fina ("folder", "crosshair", "refresh") con
  estados apagado / activo / deshabilitado.
- `apply_dark_titlebar(ventana)`: en Windows 10/11 pone oscura la barra de
  título nativa para que case con el resto de la interfaz.
"""
from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from paths import resource_path

IS_WINDOWS = sys.platform.startswith("win")

# -- Paleta ---------------------------------------------------------------
BG = "#141414"
CELL_BG = "#000000"
PANEL_BG = "#0c0c0c"
LINE = "#2a2a2a"
FIELD_BG = "#1c1c1c"
TEXT = "#e8e8e8"
TEXT_DIM = "#9a9a9a"
TEXT_MUTED = "#6a6a6a"
ICON_DISABLED = "#3a3a3a"
CROSSHAIR = "#4fc3f7"
WARNING = "#e3c34c"

PLANE_COLORS = {
    "axial": "#e34c4c",
    "sagittal": "#e3d34c",
    "coronal": "#4ce35c",
}

STYLESHEET = f"""
QWidget {{ background-color: {BG}; color: {TEXT}; }}
QLabel {{ background: transparent; }}
QToolTip {{
    background-color: #232323; color: {TEXT};
    border: 1px solid #3a3a3a; padding: 3px 6px;
}}

QSplitter::handle {{ background-color: {LINE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}

QTabWidget::pane {{ border: 0; border-top: 1px solid {LINE}; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_MUTED};
    padding: 7px 14px; border: 0; border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: #c8c8c8; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {TEXT}; }}

QStatusBar {{ color: {TEXT_MUTED}; border-top: 1px solid {LINE}; }}
QStatusBar::item {{ border: 0; }}

QToolButton {{
    background: transparent; border: 0; border-radius: 4px; padding: 6px;
}}
QToolButton:hover {{ background-color: #232323; }}
QToolButton:checked {{ background-color: {LINE}; }}

QPushButton {{
    background-color: #232323; border: 1px solid #3a3a3a;
    border-radius: 4px; padding: 5px 14px;
}}
QPushButton:hover {{ background-color: #2c2c2c; }}

QLineEdit {{
    background-color: {FIELD_BG}; border: 1px solid {LINE};
    border-radius: 4px; padding: 4px 6px;
}}
QTreeView {{ background-color: {BG}; border: 0; }}
QTreeView::item:selected {{ background-color: {LINE}; color: {TEXT}; }}

QComboBox {{
    background-color: {FIELD_BG}; border: 1px solid {LINE};
    border-radius: 4px; padding: 4px 8px; color: {TEXT};
}}
QComboBox:disabled {{ color: {TEXT_MUTED}; }}
QComboBox QAbstractItemView {{
    background-color: {FIELD_BG}; color: {TEXT}; border: 1px solid {LINE};
    selection-background-color: {LINE}; selection-color: {TEXT}; outline: 0;
}}

QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{ background: {LINE}; height: 2px; }}
QSlider::sub-page:horizontal {{ background: {TEXT}; height: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 10px; height: 10px;
    margin: -4px 0; border-radius: 5px;
}}

QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #333333; border-radius: 5px; min-height: 24px;
}}
QScrollBar:horizontal {{ background: {BG}; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: #333333; border-radius: 5px; min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

#rail {{ border-right: 1px solid {LINE}; }}
#dicomRoot {{ background-color: {LINE}; }}
#planeCell {{ background-color: {CELL_BG}; }}
#infoCell {{ background-color: {PANEL_BG}; }}
"""


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
    p.end()
    return pm


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
