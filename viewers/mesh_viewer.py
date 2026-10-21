"""
Visor 3D de mallas STL/PLY de Vissium (estilo Linear).

- Una vista sólida con sombreado suave (normales calculadas). Sin modos alambre.
- Cabecera con el nombre del modelo y el botón "Dos STL": permite poner un segundo
  STL/PLY en la MISMA escena (otra pestaña abierta o un archivo cualquiera) para ver
  cómo se relaciona uno con otro. Cada modelo tiene su color; se pueden ocultar y
  cambiar la opacidad del seleccionado. Se quita volviendo a pulsar el botón.
  Los modelos conservan sus coordenadas originales: si vienen del mismo escáner
  o del mismo estudio, quedan en su posición relativa real.
- Ratón:
    · clic izquierdo  = seleccionar el STL bajo el cursor (si hay dos en la vista);
      NO mueve ni gira nada.
    · clic derecho + arrastrar = GIRAR el modelo (la vista).
    · rueda = zoom. El botón central no hace nada: los modelos nunca se desplazan.
- Gizmo de ejes (orientación) en la esquina inferior izquierda y estadísticas del
  modelo seleccionado en la inferior derecha, dentro de la propia escena VTK.
- Restablecer cámara: `reset_view()`, que dispara el botón de la barra lateral.
- El widget de VTK es una ventana nativa: se recorta con esquinas redondeadas con
  `theme.rounded_mask` y el borde fino lo dibuja `_MeshFrame`.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable

import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from theme import LINE, RADIUS, icon, rounded_mask

log = logging.getLogger("vissium.mesh")

BG_COLOR = (0.0, 0.0, 0.0)           # mismo negro que las vistas DICOM
STATS_COLOR = (0.55, 0.55, 0.57)
OUTLINE_COLOR = (0.482, 0.525, 0.910)  # acento (#7b86e8): caja del modelo seleccionado
# Un color por modelo: gris claro (el primero) y verde azulado (el segundo).
MODEL_COLORS = [(0.85, 0.85, 0.88), (0.44, 0.77, 0.73)]
CLICK_TOLERANCE_PX = 4               # más movimiento que esto = arrastre, no clic
MAX_MODELS = 2


class _EmptyMesh(ValueError):
    """El archivo se leyó pero no tiene ninguna malla."""


def _reader_for(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".stl":
        return vtk.vtkSTLReader()
    if ext == ".ply":
        return vtk.vtkPLYReader()
    raise ValueError(f"Extensión de malla no soportada: {ext}")


def _load_polydata(path: str):
    reader = _reader_for(path)
    reader.SetFileName(path)
    reader.Update()
    polydata = reader.GetOutput()
    if polydata.GetNumberOfPoints() == 0:
        # VTK no lanza excepción con un archivo corrupto: devuelve una malla vacía.
        raise _EmptyMesh("El archivo no contiene una malla válida (0 vértices).")
    return polydata


def _fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _hex(color: tuple) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(round(c * 255)) for c in color))


def _dot_icon(color: tuple) -> QIcon:
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(_hex(color)))
    p.drawEllipse(QPointF(8, 8), 4.5, 4.5)
    p.end()
    return QIcon(pm)


@dataclass
class _Model:
    path: str
    label: str
    color: tuple
    polydata: object
    actor: object
    outline: object
    stats: str
    visible: bool = True
    opacity: float = 1.0


def _make_model(path: str, color: tuple) -> _Model:
    polydata = _load_polydata(path)

    # Normales suaves: evita el aspecto "facetado" de un STL en bruto.
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(polydata)
    normals.SetFeatureAngle(60.0)  # conserva aristas "duras" nítidas
    normals.ComputePointNormalsOn()
    normals.SplittingOn()
    normals.Update()

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(normals.GetOutputPort())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetColor(*color)
    prop.SetSpecular(0.35)
    prop.SetSpecularPower(30)
    prop.SetDiffuse(0.85)

    # Caja del modelo seleccionado (solo se ve cuando hay dos modelos en la vista).
    box = vtk.vtkOutlineFilter()
    box.SetInputData(polydata)
    box_mapper = vtk.vtkPolyDataMapper()
    box_mapper.SetInputConnection(box.GetOutputPort())
    outline = vtk.vtkActor()
    outline.SetMapper(box_mapper)
    outline.GetProperty().SetColor(*OUTLINE_COLOR)
    outline.GetProperty().SetLineWidth(2.0)
    outline.GetProperty().LightingOff()
    outline.PickableOff()
    outline.VisibilityOff()

    bounds = polydata.GetBounds()  # xmin,xmax,ymin,ymax,zmin,zmax
    size = (bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
    stats = (
        f"{_fmt_int(polydata.GetNumberOfPoints())} vértices\n"
        f"{_fmt_int(polydata.GetNumberOfCells())} triángulos\n"
        f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f}"
    )
    return _Model(path, os.path.basename(path), color, polydata, actor, outline, stats)


class _MeshStyle(vtk.vtkInteractorStyleTrackballCamera):
    """
    Navegación de Vissium para modelos 3D:
      clic izquierdo = seleccionar (sin arrastrar nada), clic derecho = girar,
      rueda = zoom, botón central = nada (los modelos nunca se desplazan).
    Al añadir observadores a un evento, VTK deja de ejecutar el comportamiento
    por defecto de ese evento: por eso aquí se redefine cada botón.
    """

    def __init__(self, on_click: Callable[[int, int], None]):
        super().__init__()
        self._on_click = on_click
        self._press: tuple[int, int] | None = None
        self._rotating = False
        self.AddObserver("LeftButtonPressEvent", self._left_down)
        self.AddObserver("LeftButtonReleaseEvent", self._left_up)
        self.AddObserver("RightButtonPressEvent", self._right_down)
        self.AddObserver("RightButtonReleaseEvent", self._right_up)
        self.AddObserver("MiddleButtonPressEvent", lambda *_: None)
        self.AddObserver("MiddleButtonReleaseEvent", lambda *_: None)
        # Sin atajos de VTK (w = alambre, s = superficie, p = selección, ...): solo vista sólida.
        self.AddObserver("CharEvent", lambda *_: None)

    # -- izquierdo: seleccionar ---------------------------------------------
    def _left_down(self, _obj, _event):
        self._press = tuple(self.GetInteractor().GetEventPosition())

    def _left_up(self, _obj, _event):
        press, self._press = self._press, None
        if press is None:
            return
        x, y = self.GetInteractor().GetEventPosition()
        if abs(x - press[0]) <= CLICK_TOLERANCE_PX and abs(y - press[1]) <= CLICK_TOLERANCE_PX:
            self._on_click(x, y)

    # -- derecho: girar la vista --------------------------------------------
    def _right_down(self, _obj, _event):
        x, y = self.GetInteractor().GetEventPosition()
        self.FindPokedRenderer(x, y)
        if self.GetCurrentRenderer() is None:
            return
        self._rotating = True
        self.StartRotate()

    def _right_up(self, _obj, _event):
        if not self._rotating:
            return
        self._rotating = False
        self.EndRotate()


class _MeshFrame(QWidget):
    """Marco con borde fino y esquinas redondeadas alrededor del widget de VTK."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(LINE), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        painter.end()


class MeshViewer(QWidget):
    """Widget de una pestaña: modelo 3D interactivo, con opción de comparar dos."""

    titleChanged = Signal(str)   # nuevo texto de la pestaña (uno o dos nombres)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.primary_path = file_path
        self.vtk_widget = None
        self._models: list[_Model] = []
        self._selected = 0
        self._sources_provider: Callable[[], list[tuple[str, str]]] | None = None
        self._syncing = False
        self._started = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        try:
            primary = _make_model(file_path, MODEL_COLORS[0])
        except _EmptyMesh as exc:
            outer.addWidget(QLabel(str(exc), self))
            return
        except Exception as exc:
            outer.addWidget(QLabel(f"No se pudo cargar el modelo:\n{exc}", self))
            return
        self._models.append(primary)
        self.actor = primary.actor  # compatibilidad: actor del primer modelo

        # -- Cabecera: nombre, ayuda de ratón y botón "Dos STL" ---------------
        header = QWidget(self)
        header.setObjectName("meshHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(2, 0, 2, 0)
        header_layout.setSpacing(10)
        self.title_label = QLabel(header)
        self.title_label.setObjectName("meshTitle")
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        self.hint_label = QLabel(header)
        self.hint_label.setObjectName("meshHint")
        self.compare_button = QPushButton("Dos STL", header)
        self.compare_button.setObjectName("pill")
        self.compare_button.setIcon(icon("layers"))
        self.compare_button.setCheckable(True)
        self.compare_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.compare_button.setToolTip("Ver dos STL a la vez en la misma vista")
        self.compare_button.setAccessibleName("Ver dos STL a la vez en la misma vista")
        self.compare_button.clicked.connect(self._on_compare_clicked)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.hint_label)
        header_layout.addWidget(self.compare_button)
        outer.addWidget(header)

        # -- Escena VTK dentro de su marco redondeado -------------------------
        body = QHBoxLayout()
        body.setSpacing(8)
        outer.addLayout(body, stretch=1)

        self.frame = _MeshFrame(self)
        self.vtk_widget = QVTKRenderWindowInteractor(self.frame)
        self.vtk_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.vtk_widget.installEventFilter(self)
        self.frame.layout().addWidget(self.vtk_widget)
        body.addWidget(self.frame, stretch=1)

        self.models_panel = self._build_models_panel()
        self.models_panel.hide()
        body.addWidget(self.models_panel)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(*BG_COLOR)
        renderer.GradientBackgroundOff()
        self.renderer = renderer
        renderer.AddActor(primary.actor)
        renderer.AddActor(primary.outline)

        # Estadísticas superpuestas (abajo a la derecha), del modelo seleccionado.
        stats = vtk.vtkTextActor()
        stats.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        stats.GetPositionCoordinate().SetValue(0.98, 0.03)
        prop = stats.GetTextProperty()
        prop.SetFontFamilyToCourier()
        prop.SetFontSize(13)
        prop.SetColor(*STATS_COLOR)
        prop.SetJustificationToRight()
        prop.SetVerticalJustificationToBottom()
        prop.SetLineSpacing(1.3)
        prop.ShadowOff()
        renderer.AddViewProp(stats)
        self.stats_actor = stats

        renderer.ResetCamera()
        render_window = self.vtk_widget.GetRenderWindow()
        render_window.AddRenderer(renderer)

        self._picker = vtk.vtkPropPicker()
        self._style = _MeshStyle(self._on_scene_click)
        interactor = render_window.GetInteractor()
        interactor.SetInteractorStyle(self._style)

        # Gizmo de ejes en la esquina inferior izquierda, como en Meshmixer/Slicer.
        axes = vtk.vtkAxesActor()
        self.axes_widget = vtk.vtkOrientationMarkerWidget()
        self.axes_widget.SetOrientationMarker(axes)
        self.axes_widget.SetViewport(0.0, 0.0, 0.18, 0.18)
        self.axes_widget.SetInteractor(interactor)
        self.axes_widget.EnabledOn()
        self.axes_widget.InteractiveOff()

        self._refresh_ui()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def set_sources_provider(self, provider: Callable[[], list[tuple[str, str]]]):
        """Función que devuelve [(nombre, ruta)] de otros STL abiertos, para ofrecerlos en "Dos STL"."""
        self._sources_provider = provider

    def tab_title(self) -> str:
        return " + ".join(m.label for m in self._models)

    def add_model(self, path: str) -> bool:
        """Añade un segundo modelo a la escena. Devuelve False (y avisa) si no se puede."""
        if self.vtk_widget is None or len(self._models) >= MAX_MODELS:
            return False
        try:
            model = _make_model(path, MODEL_COLORS[len(self._models) % len(MODEL_COLORS)])
        except Exception as exc:
            QMessageBox.warning(self, "Vissium", f"No se pudo cargar el modelo:\n{exc}")
            return False
        self._models.append(model)
        self.renderer.AddActor(model.actor)
        self.renderer.AddActor(model.outline)
        self._selected = len(self._models) - 1
        self.renderer.ResetCamera()
        self._refresh_ui()
        self.titleChanged.emit(self.tab_title())
        return True

    def remove_second_model(self):
        if self.vtk_widget is None or len(self._models) < 2:
            return
        model = self._models.pop()
        self.renderer.RemoveActor(model.actor)
        self.renderer.RemoveActor(model.outline)
        self._selected = 0
        self.renderer.ResetCamera()
        self._refresh_ui()
        self.titleChanged.emit(self.tab_title())

    def reset_view(self):
        """Restablece la cámara (lo dispara el botón de la barra lateral)."""
        if self.vtk_widget is not None:
            self.renderer.ResetCamera()
            self._render()

    def start(self):
        """Debe llamarse una vez el widget está visible (tras añadirlo a la pestaña)."""
        if self.vtk_widget is not None:
            self.vtk_widget.Initialize()
            self.vtk_widget.Start()
            self._started = True
            rounded_mask(self.vtk_widget, RADIUS - 1)

    def shutdown(self):
        """Libera la ventana de render VTK al cerrar la pestaña (evita fugas de GPU/memoria)."""
        if self.vtk_widget is not None:
            try:
                self._style.RemoveAllObservers()
                self.axes_widget.EnabledOff()
                self.vtk_widget.Finalize()
            except Exception:
                pass
            self.vtk_widget = None

    def closeEvent(self, event):
        if self.vtk_widget is not None:
            self.vtk_widget.close()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        # El widget de VTK es una ventana nativa: se recorta con esquinas redondeadas.
        if obj is self.vtk_widget and event.type() == QEvent.Type.Resize:
            rounded_mask(self.vtk_widget, RADIUS - 1)
        return super().eventFilter(obj, event)

    def _build_models_panel(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("modelsPanel")
        panel.setFixedWidth(196)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(4)
        heading = QLabel("Modelos", panel)
        heading.setObjectName("modelsHeading")
        heading.setContentsMargins(6, 0, 0, 4)
        layout.addWidget(heading)
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(2)
        layout.addLayout(self._rows_layout)
        layout.addSpacing(8)
        opacity_label = QLabel("Opacidad del seleccionado", panel)
        opacity_label.setObjectName("modelsHeading")
        opacity_label.setContentsMargins(6, 0, 0, 0)
        layout.addWidget(opacity_label)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, panel)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setAccessibleName("Opacidad del modelo seleccionado")
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(6, 0, 6, 0)
        slider_row.addWidget(self.opacity_slider)
        layout.addLayout(slider_row)
        layout.addStretch(1)
        return panel

    def _clear_rows(self):
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            row = item.layout()
            if row is not None:
                while row.count():
                    child = row.takeAt(0).widget()
                    if child is not None:
                        child.deleteLater()
            elif item.widget() is not None:
                item.widget().deleteLater()

    def _refresh_ui(self):
        """Sincroniza cabecera, panel de modelos, caja de selección y estadísticas con `self._models`."""
        compare = len(self._models) > 1
        self._syncing = True
        self.compare_button.setChecked(compare)
        self.compare_button.setText("Quitar el segundo" if compare else "Dos STL")
        self._syncing = False

        names = [m.label for m in self._models]
        title = f"<b>{names[0]}</b>"
        if compare:
            title += f" <span style='color:#6f737b'>+ {names[1]}</span>"
        self.title_label.setText(title)
        self.hint_label.setText(
            "Clic izq. seleccionar  ·  Clic der. girar  ·  Rueda zoom" if compare
            else "Clic der. girar  ·  Rueda zoom")

        self.models_panel.setVisible(compare)
        self._clear_rows()
        if compare:
            for i, model in enumerate(self._models):
                row = QHBoxLayout()
                row.setSpacing(2)
                button = QPushButton(model.label, self.models_panel)
                button.setObjectName("modelRow")
                button.setIcon(_dot_icon(model.color))
                button.setCheckable(True)
                button.setChecked(i == self._selected)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setToolTip(model.path)
                button.setAccessibleName(f"Seleccionar {model.label}")
                button.clicked.connect(lambda _=False, idx=i: self._select(idx))
                eye = QToolButton(self.models_panel)
                eye.setObjectName("modelEye")
                eye.setIcon(icon("eye" if model.visible else "eye-off"))
                eye.setAutoRaise(True)
                eye.setToolTip("Mostrar u ocultar este modelo")
                eye.setAccessibleName(f"Mostrar u ocultar {model.label}")
                eye.clicked.connect(lambda _=False, idx=i: self._toggle_visible(idx))
                row.addWidget(button, stretch=1)
                row.addWidget(eye)
                self._rows_layout.addLayout(row)
        self._apply_selection()

    def _apply_selection(self):
        compare = len(self._models) > 1
        for i, model in enumerate(self._models):
            model.outline.SetVisibility(bool(compare and i == self._selected and model.visible))
            model.actor.SetVisibility(model.visible)
            model.actor.SetPickable(model.visible)
        selected = self._models[self._selected]
        label = f"{selected.label}\n" if compare else ""
        self.stats_actor.SetInput(label + selected.stats)
        self._syncing = True
        self.opacity_slider.setValue(int(round(selected.opacity * 100)))
        self._syncing = False
        self._render()

    def _render(self):
        if self.vtk_widget is not None and self._started:
            self.vtk_widget.GetRenderWindow().Render()

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def _select(self, index: int):
        if 0 <= index < len(self._models) and index != self._selected:
            self._selected = index
            self._refresh_ui()

    def _toggle_visible(self, index: int):
        model = self._models[index]
        model.visible = not model.visible
        if not any(m.visible for m in self._models):  # nunca dejar la escena vacía
            model.visible = True
        self._refresh_ui()

    def _on_opacity_changed(self, value: int):
        if self._syncing or not self._models:
            return
        model = self._models[self._selected]
        model.opacity = value / 100.0
        model.actor.GetProperty().SetOpacity(model.opacity)
        self._render()

    def _on_scene_click(self, x: int, y: int):
        """Clic izquierdo en la escena: selecciona el STL que haya bajo el cursor."""
        if len(self._models) < 2:
            return
        if not self._picker.Pick(x, y, 0, self.renderer):
            return
        actor = self._picker.GetActor()
        for i, model in enumerate(self._models):
            if model.actor is actor:
                self._select(i)
                return

    def _on_compare_clicked(self, checked: bool):
        if self._syncing or self.vtk_widget is None:
            return
        if len(self._models) > 1:
            self.remove_second_model()
            return
        # Se quiere añadir un segundo modelo: ofrecer los STL abiertos y "Examinar…".
        menu = QMenu(self)
        others = []
        if self._sources_provider is not None:
            try:
                others = [(n, p) for n, p in self._sources_provider() if p != self.primary_path]
            except Exception:
                log.exception("No se pudo obtener la lista de STL abiertos")
        for name, path in others:
            action = menu.addAction(icon("cube"), name)
            action.setData(path)
        if others:
            menu.addSeparator()
        browse = menu.addAction(icon("folder"), "Examinar archivo…")
        picked = menu.exec(self.compare_button.mapToGlobal(
            self.compare_button.rect().bottomLeft()))
        path = ""
        if picked is browse:
            start_dir = os.path.dirname(self.primary_path)
            path, _ = QFileDialog.getOpenFileName(
                self, "Segundo modelo", start_dir, "Mallas 3D (*.stl *.ply)")
        elif picked is not None:
            path = str(picked.data() or "")
        if path:
            self.add_model(path)
        self._refresh_ui()  # si no se añadió nada, el botón vuelve a "Dos STL"
