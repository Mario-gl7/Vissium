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
