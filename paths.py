"""
Resolución de rutas a recursos empaquetados (iconos, etc.).

Cuando Vissium corre desde el código fuente, los recursos están junto
a este archivo. Cuando corre como .exe generado por PyInstaller (modo
--onefile), los recursos se descomprimen en una carpeta temporal cuya
ruta expone PyInstaller en `sys._MEIPASS`. Esta función funciona en
ambos casos.
"""
from __future__ import annotations

import os
import sys


def resource_path(*parts: str) -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def app_dir() -> str:
    """
    Carpeta donde vive el ejecutable/script principal (para escribir
    archivos junto a él, p. ej. durante una actualización).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))
