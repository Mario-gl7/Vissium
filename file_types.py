"""
Detección de tipo de archivo/carpeta para decidir qué visor abrir.

Cambios respecto a la versión anterior:
- La detección de DICOM comprueba primero la marca "DICM" (bytes 128-132),
  que es una lectura mínima, en vez de parsear la cabecera con pydicom en
  cada archivo (antes se hacían hasta DOS lecturas por archivo).
- Los archivos se ordenan de forma "natural" (IM2 antes que IM10).
- Si una carpeta no contiene nada directamente (típico de exportaciones
  CBCT: carpeta/DICOM/*.dcm), se busca en subcarpetas (2 niveles).
- Una carpeta con varias mallas devuelve todas (antes solo la primera).
- Un DICOM suelto se amplía a su serie completa (los archivos hermanos con
  el mismo SeriesInstanceUID), porque un único corte apenas sirve de vista
  previa.
- DICOMDIR se ignora (no contiene imagen).
"""
from __future__ import annotations

import os
import re
from enum import Enum, auto

import pydicom


class ContentType(Enum):
    DICOM_SERIES = auto()   # carpeta con uno o más archivos DICOM
    DICOM_FILE = auto()     # un archivo DICOM suelto (se amplía a su serie)
    MESH = auto()           # .stl o .ply
    UNKNOWN = auto()
    EMPTY_FOLDER = auto()


MESH_EXTENSIONS = {".stl", ".ply"}
# Extensiones en las que se intenta leer como DICOM aunque falte la marca "DICM".
_DICOM_EXTENSIONS = {"", ".dcm", ".dicom", ".dic", ".ima"}
_SKIP_NAMES = {"dicomdir"}

_MAX_DEPTH = 2        # niveles de subcarpetas a explorar
_MAX_SUBDIRS = 300    # tope de subcarpetas escaneadas (evita recorrer discos enteros)


def _natural_key(path: str):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", os.path.basename(path))]


def _has_dicm_magic(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            fh.seek(128)
            return fh.read(4) == b"DICM"
    except OSError:
        return False


def _is_dicom_file(path: str) -> bool:
    """Rápido: marca DICM; si falta, solo se prueba en extensiones típicas."""
    name = os.path.basename(path)
    if name.lower() in _SKIP_NAMES:
        return False
    if _has_dicm_magic(path):
        return True
    if os.path.splitext(name)[1].lower() not in _DICOM_EXTENSIONS:
        return False
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    except Exception:
        return False
    return "Rows" in ds and "Columns" in ds


def _scan(folder: str):
    """(dicoms, mallas, subcarpetas, nº_de_archivos) de una carpeta, sin recursión."""
    files: list[str] = []
    subdirs: list[str] = []
    try:
        with os.scandir(folder) as it:
            for entry in it:
                try:
                    if entry.is_file():
                        files.append(entry.path)
                    elif entry.is_dir() and not entry.name.startswith((".", "$")):
                        subdirs.append(entry.path)
                except OSError:
                    continue
    except OSError:
        return [], [], [], 0
    files.sort(key=_natural_key)
    subdirs.sort(key=_natural_key)
    dicoms = [f for f in files if _is_dicom_file(f)]
    meshes = [f for f in files if os.path.splitext(f)[1].lower() in MESH_EXTENSIONS]
    return dicoms, meshes, subdirs, len(files)


def _find_in_subfolders(root: str, root_subdirs: list[str]):
    """Busca (BFS, hasta _MAX_DEPTH) la subcarpeta con más DICOM, o con mallas."""
    best_dicom: list[str] = []
    best_mesh: list[str] = []
    frontier = root_subdirs
    scanned = 0
    for _depth in range(_MAX_DEPTH):
        next_frontier: list[str] = []
        for sub in frontier:
            if scanned >= _MAX_SUBDIRS:
                break
            scanned += 1
            dicoms, meshes, subs, _n = _scan(sub)
            if len(dicoms) > len(best_dicom):
                best_dicom = dicoms
            if meshes and not best_mesh:
                best_mesh = meshes
            next_frontier.extend(subs)
        if best_dicom or scanned >= _MAX_SUBDIRS:
            break
        frontier = next_frontier
    return best_dicom, best_mesh


def _series_uid(path: str) -> str | None:
    try:
        ds = pydicom.dcmread(
            path, stop_before_pixels=True, force=True,
            specific_tags=["SeriesInstanceUID"],
        )
        return str(ds.SeriesInstanceUID) if "SeriesInstanceUID" in ds else None
    except Exception:
        return None


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _series_files(path: str) -> list[str]:
    """Archivos de la misma carpeta que pertenecen a la misma serie que `path`."""
    uid = _series_uid(path)
    if not uid:
        return [path]
    folder = os.path.dirname(os.path.abspath(path))
    dicoms, _meshes, _subs, _n = _scan(folder)
    same = [f for f in dicoms if _same(f, path) or _series_uid(f) == uid]
    return same or [path]


def classify_path(path: str) -> tuple[ContentType, list[str]]:
    """
    Devuelve (tipo, lista_de_archivos_relevantes).

    - Carpeta: DICOM directos > mallas directas > (subcarpetas) DICOM > mallas.
    - Archivo: malla, DICOM (ampliado a su serie) o desconocido.
    """
    if os.path.isdir(path):
        dicoms, meshes, subdirs, n_files = _scan(path)
        if dicoms:
            return ContentType.DICOM_SERIES, dicoms
        if meshes:
            return ContentType.MESH, meshes
        if n_files == 0 and not subdirs:
            return ContentType.EMPTY_FOLDER, []
        if subdirs:
            sub_dicoms, sub_meshes = _find_in_subfolders(path, subdirs)
            if sub_dicoms:
                return ContentType.DICOM_SERIES, sub_dicoms
            if sub_meshes:
                return ContentType.MESH, sub_meshes
        return ContentType.UNKNOWN, []

    if os.path.isfile(path):
        if os.path.splitext(path)[1].lower() in MESH_EXTENSIONS:
            return ContentType.MESH, [path]
        if _is_dicom_file(path):
            return ContentType.DICOM_FILE, _series_files(path)
        return ContentType.UNKNOWN, []

    return ContentType.UNKNOWN, []
