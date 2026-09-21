"""
Detección de tipo de archivo/carpeta para decidir qué visor abrir.
"""
from __future__ import annotations

import os
from enum import Enum, auto

import pydicom


class ContentType(Enum):
    DICOM_SERIES = auto()   # carpeta con uno o más archivos DICOM
    DICOM_FILE = auto()     # un único archivo DICOM suelto
    MESH = auto()           # .stl o .ply
    UNKNOWN = auto()
    EMPTY_FOLDER = auto()


MESH_EXTENSIONS = {".stl", ".ply"}


def _is_dicom_file(path: str) -> bool:
    """Comprueba si un archivo es DICOM leyendo solo la cabecera (rápido)."""
    try:
        pydicom.dcmread(path, stop_before_pixels=True, force=False)
        return True
    except Exception:
        # force=True detecta también DICOM sin el preámbulo/"DICM" estándar
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            return hasattr(ds, "SOPClassUID") or hasattr(ds, "Rows")
        except Exception:
            return False


def classify_path(path: str) -> tuple[ContentType, list[str]]:
    """
    Devuelve (tipo, lista_de_archivos_relevantes).

    - Para una carpeta: busca archivos DICOM dentro (no recursivo por defecto).
    - Para un archivo: detecta si es DICOM, mesh, o desconocido.
    """
    if os.path.isdir(path):
        entries = sorted(
            os.path.join(path, f)
            for f in os.listdir(path)
            if os.path.isfile(os.path.join(path, f))
        )
        if not entries:
            return ContentType.EMPTY_FOLDER, []

        dicom_files = [f for f in entries if _is_dicom_file(f)]
        if dicom_files:
            return ContentType.DICOM_SERIES, dicom_files

        mesh_files = [f for f in entries if os.path.splitext(f)[1].lower() in MESH_EXTENSIONS]
        if mesh_files:
            # Una carpeta con mallas: se previsualiza la primera como pista;
            # normalmente el usuario seleccionará el archivo .stl/.ply directamente.
            return ContentType.MESH, mesh_files[:1]

        return ContentType.UNKNOWN, []

    if os.path.isfile(path):
        ext = os.path.splitext(path)[1].lower()
        if ext in MESH_EXTENSIONS:
            return ContentType.MESH, [path]
        if _is_dicom_file(path):
            return ContentType.DICOM_FILE, [path]
        return ContentType.UNKNOWN, []

    return ContentType.UNKNOWN, []
