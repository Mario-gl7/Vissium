"""Recorrido de la ventana de previsualización: abrir cada tipo de contenido y cerrar pestañas."""
import re
import time

import pytest
from PySide6.QtWidgets import QApplication

from preview_window import PreviewWindow

# Emojis y símbolos decorativos que no deben aparecer en la interfaz.
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u23F3]")


@pytest.fixture
def window(qtbot):
    w = PreviewWindow()
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    yield w
    w.shutdown()


def _wait_loaded(qtbot, w, expected_tabs, timeout=20000):
    def ready():
        return w.tabs.count() == expected_tabs and not w._pending
    qtbot.waitUntil(ready, timeout=timeout)
    QApplication.processEvents()
    time.sleep(0.2)


def test_empty_state_visible_without_tabs(window):
    assert window.tabs.count() == 0
    assert window.stack.currentIndex() == 0


@pytest.mark.parametrize("name,viewer", [
    ("dicom_flat", "DicomViewer"),
    ("modelo.stl", "MeshViewer"),
    ("foto.png", "ImageViewer"),
])
def test_open_each_type(qtbot, window, fixtures, name, viewer):
    window.open_preview(str(fixtures / name))
    _wait_loaded(qtbot, window, 1)
    assert type(window.tabs.currentWidget()).__name__ == viewer
    assert window.stack.currentIndex() == 1
    assert not EMOJI.search(window.tabs.tabText(0))


def test_cd_with_two_series_opens_one_tab(qtbot, window, fixtures):
    window.open_preview(str(fixtures / "cd"))
    _wait_loaded(qtbot, window, 1)
    assert len(window.tabs.currentWidget().volume.series) == 2


def test_close_tab_returns_to_empty_state(qtbot, window, fixtures):
    window.open_preview(str(fixtures / "foto.png"))
    _wait_loaded(qtbot, window, 1)
    button = window.tabs.tabBar().tabButton(0, window.tabs.tabBar().ButtonPosition.RightSide)
    assert button is not None and button.accessibleName() == "Cerrar pestaña"
    button.click()
    assert window.tabs.count() == 0
    assert window.stack.currentIndex() == 0


def test_rail_buttons_have_accessible_names(window):
    for b in (window.btn_browser, window.btn_guides, window.btn_reset):
        assert b.accessibleName()


def test_update_environment_drops_pyinstaller_vars():
    from updater import clean_environment
    env = clean_environment({"PATH": "x", "_MEIPASS2": r"C:\Temp\_MEI123",
                             "_PYI_APPLICATION_HOME_DIR": r"C:\Temp\_MEI123"})
    assert env["PATH"] == "x"
    assert "_MEIPASS2" not in env and "_PYI_APPLICATION_HOME_DIR" not in env
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


# -- Visor STL: dos modelos y navegación con el ratón (2026-10-21) ---------------
def _sphere_stl(path, cx):
    import vtk
    s = vtk.vtkSphereSource()
    s.SetCenter(cx, 0, 0)
    s.SetThetaResolution(24)
    s.SetPhiResolution(24)
    s.Update()
    w = vtk.vtkSTLWriter()
    w.SetFileName(str(path))
    w.SetInputData(s.GetOutput())
    w.Write()


@pytest.fixture
def two_meshes(tmp_path):
    a, b = tmp_path / "a.stl", tmp_path / "b.stl"
    _sphere_stl(a, 0.0)
    _sphere_stl(b, 1.4)
    return a, b


def _open_mesh(qtbot, window, path):
    window.open_preview(str(path))
    qtbot.waitUntil(lambda: not window._pending, timeout=20000)
    QApplication.processEvents()
    return window.tabs.currentWidget()


def test_two_stl_in_same_view_and_title(qtbot, window, two_meshes):
    a, b = two_meshes
    viewer = _open_mesh(qtbot, window, a)
    assert type(viewer).__name__ == "MeshViewer"
    assert viewer.compare_button.accessibleName()
    assert not viewer.models_panel.isVisibleTo(viewer)
    assert viewer.add_model(str(b))
    assert len(viewer._models) == 2
    assert viewer.models_panel.isVisibleTo(viewer)
    assert window.tabs.tabText(window.tabs.currentIndex()) == "a.stl + b.stl"
    viewer.remove_second_model()
    assert len(viewer._models) == 1
    assert window.tabs.tabText(window.tabs.currentIndex()) == "a.stl"


def test_other_open_stl_offered_for_comparison(qtbot, window, two_meshes):
    a, b = two_meshes
    _open_mesh(qtbot, window, a)
    viewer_b = _open_mesh(qtbot, window, b)
    assert [n for n, _p in viewer_b._sources_provider()] == ["a.stl"]


def test_stl_mouse_left_selects_right_rotates_never_moves(qtbot, window, two_meshes):
    a, b = two_meshes
    viewer = _open_mesh(qtbot, window, a)
    viewer.add_model(str(b))
    QApplication.processEvents()
    iren = viewer.vtk_widget.GetRenderWindow().GetInteractor()
    ren, cam = viewer.renderer, viewer.renderer.GetActiveCamera()

    def px(x):
        ren.SetWorldPoint(x, 0, 0, 1)
        ren.WorldToDisplay()
        p = ren.GetDisplayPoint()
        return int(p[0]), int(p[1])

    def state():
        return cam.GetPosition(), cam.GetFocalPoint(), cam.GetViewUp()

    def drag(button, p0, p1):
        iren.SetEventInformation(*p0)
        getattr(iren, f"{button}ButtonPressEvent")()
        for t in range(1, 6):
            iren.SetEventInformation(p0[0] + (p1[0] - p0[0]) * t // 5, p0[1] + (p1[1] - p0[1]) * t // 5)
            iren.MouseMoveEvent()
        getattr(iren, f"{button}ButtonReleaseEvent")()

    first, second = px(0.0), px(1.4)
    before = state()
    for target, expected in ((first, 0), (second, 1)):  # clic izquierdo = seleccionar
        iren.SetEventInformation(*target)
        iren.LeftButtonPressEvent()
        iren.LeftButtonReleaseEvent()
        assert viewer._selected == expected
    assert state() == before
    drag("Left", first, (first[0] + 60, first[1] + 30))     # arrastrar con el izquierdo: nada
    drag("Middle", first, (first[0] + 60, first[1] + 30))   # botón central: nada
    assert state() == before
    drag("Right", first, (first[0] + 80, first[1] + 40))    # derecho: gira, no desplaza
    after = state()
    assert after != before
    assert after[1] == pytest.approx(before[1])


def test_theme_colors_are_valid_for_qcolor():
    from PySide6.QtGui import QColor
    import theme
    for name in ("BG", "CARD", "LINE", "LINE_STRONG", "ACCENT", "CELL_BG"):
        assert QColor(getattr(theme, name)).isValid(), name
