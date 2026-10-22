"""
Studio: botón flotante (estilo botón de chat de una web) y su panel con los datos
del paciente. Ambos flotan sobre el visor DICOM cuando está activo el CBCT 3D.

- `StudioLauncher`: botón circular de 52 px con el icono de paciente. Es el estado
  "minimizado" del panel.
- `StudioPanel`: ventana con el mismo diseño que las celdas del visor (fondo de
  tarjeta, línea fina, esquinas redondeadas, cabecera con título y botones de
  minimizar / maximizar / volver a la vista del paciente) y un hueco (`body_layout`)
  donde el visor DICOM coloca el panel de información.

Ambos son ventanas nativas hijas (WA_NativeWindow): la vista 3D es un widget nativo
de VTK y un widget normal quedaría por detrás o con restos de pintura. Al ser
nativos se recortan con una máscara (círculo / esquinas redondeadas) y se pintan a
mano; el margen que deja la máscara es del negro de las vistas.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRegion
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QToolButton,
                               QVBoxLayout, QWidget)

from theme import (ACCENT, ACCENT_TEXT, CARD, CELL_BG, LINE, LINE_STRONG, RADIUS_CARD,
                   TEXT, TEXT_DIM, icon, icon_pixmap, rounded_mask)


class StudioLauncher(QAbstractButton):
    """Botón circular flotante (como el de un chat de ayuda en una página web)."""

    SIZE = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioLauncher")
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Studio: información del paciente")
        self.setAccessibleName("Abrir Studio, información del paciente")
        self._hover = False
        self._pix = icon_pixmap("patient", TEXT_DIM, 48)
        self._pix_hover = icon_pixmap("patient", TEXT, 48)

    def sizeHint(self) -> QSize:
        return QSize(self.SIZE, self.SIZE)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMask(QRegion(0, 0, self.width(), self.height(), QRegion.RegionType.Ellipse))

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(CELL_BG))   # borde de la máscara: mismo negro que la escena
        disc = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        gradient = QLinearGradient(disc.topLeft(), disc.bottomLeft())
        if self.isDown():
            gradient.setColorAt(0, QColor("#17181b"))
            gradient.setColorAt(1, QColor("#1d1e22"))
        else:
            gradient.setColorAt(0, QColor("#2c2e34" if self._hover else "#25272c"))
            gradient.setColorAt(1, QColor("#17181b"))
        border = QColor(ACCENT) if (self._hover or self.hasFocus()) else QColor(LINE_STRONG)
        p.setPen(QPen(border, 1.4 if self.hasFocus() else 1.0))
        p.setBrush(gradient)
        p.drawEllipse(disc)
        # Brillo fino en el borde superior: da volumen sin sombras.
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawArc(disc.adjusted(2, 2, -2, -2), 35 * 16, 110 * 16)
        side = 24.0
        target = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        pix = self._pix_hover if self._hover else self._pix
        p.drawPixmap(target, pix, QRectF(pix.rect()))
        p.end()


class StudioPanel(QFrame):
    """Ventana flotante con el diseño de las celdas del visor."""

    minimizeRequested = Signal()
    maximizeRequested = Signal()
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)   # deja ver el borde redondeado
        outer.setSpacing(0)

        header = QWidget(self)
        head = QHBoxLayout(header)
        head.setContentsMargins(14, 10, 8, 10)
        head.setSpacing(8)
        badge = QLabel(header)
        badge.setPixmap(icon_pixmap("patient", ACCENT_TEXT, 20))
        badge.setFixedSize(20, 20)
        head.addWidget(badge)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(0)
        self.title = QLabel("Studio", header)
        self.title.setObjectName("studioTitle")
        self.subtitle = QLabel("", header)
        self.subtitle.setObjectName("studioSubtitle")
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        head.addLayout(texts, 1)
        self.btn_minimize = self._button(header, "minimize", "Minimizar Studio")
        self.btn_maximize = self._button(header, "maximize", "Maximizar Studio")
        self.btn_close = self._button(header, "switch", "Cambiar a la vista del paciente")
        for button in (self.btn_minimize, self.btn_maximize, self.btn_close):
            head.addWidget(button)
        outer.addWidget(header)

        rule = QFrame(self)
        rule.setObjectName("studioRule")
        rule.setFixedHeight(1)
        outer.addWidget(rule)

        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 6)
        self.body_layout.setSpacing(0)
        outer.addLayout(self.body_layout, 1)

        self.btn_minimize.clicked.connect(self.minimizeRequested)
        self.btn_maximize.clicked.connect(self.maximizeRequested)
        self.btn_close.clicked.connect(self.closeRequested)

    def _button(self, parent, icon_name: str, tip: str) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("studioBtn")
        button.setIcon(icon(icon_name))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(28, 28)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def set_subtitle(self, text: str):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def set_maximized(self, maximized: bool):
        self.btn_maximize.setIcon(icon("restore" if maximized else "maximize"))
        tip = "Restaurar Studio" if maximized else "Maximizar Studio"
        self.btn_maximize.setToolTip(tip)
        self.btn_maximize.setAccessibleName(tip)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rounded_mask(self, RADIUS_CARD)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(CARD))
        p.setPen(QPen(QColor(LINE_STRONG), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                          RADIUS_CARD, RADIUS_CARD)
        p.end()
