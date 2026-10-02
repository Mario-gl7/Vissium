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

Ampliado para leer "cualquier DICOM":
- Se reconocen archivos DICOM con CUALQUIER extensión (o sin ella: IM0001,
  I10, 1.2.840...). Para no leer miles de archivos enteros, se filtra antes
  con una comprobación de 2 bytes (los DICOM empiezan por el grupo 0008 o
  0002) y solo entonces se parsea la cabecera.
- Se descartan por extensión los formatos que seguro no son DICOM
  (imágenes, documentos, comprimidos...).
- Se explora hasta 3 niveles de subcarpetas (antes 2), hasta 500 carpetas.
- Un archivo suelto con marca DICM se acepta aunque no tenga imagen (el
  visor explicará el motivo en vez de decir "no se reconoce").
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
# Extensiones que seguro NO son DICOM (se descartan sin abrir el archivo).
_NON_DICOM_EXTENSIONS = {
    ".stl", ".ply", ".obj", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff",
    ".webp", ".svg", ".ico", ".txt", ".md", ".pdf", ".xml", ".json", ".csv", ".log",
    ".ini", ".cfg", ".exe", ".dll", ".zip", ".7z", ".rar", ".gz", ".tar", ".html",
    ".htm", ".py", ".bat", ".lnk", ".db", ".docx", ".xlsx", ".pptx", ".mp4", ".avi",
    ".mov", ".nii", ".mha", ".nrrd",
}
_SKIP_NAMES = {"dicomdir"}

# Los DICOM (con o sin preámbulo) empiezan por el grupo 0008 o 0002, en
# little o big endian. El grupo 0000 solo se admite con extensión DICOM típica.
_START_BYTES = {b"\x08\x00", b"\x02\x00", b"\x00\x08", b"\x00\x02"}

_MAX_DEPTH = 3        # niveles de subcarpetas a explorar
_MAX_SUBDIRS = 500    # tope de subcarpetas escaneadas (evita recorrer discos enteros)


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


def _looks_like_dicom_start(path: str, ext: str) -> bool:
    """Filtro barato (2 bytes) para archivos sin marca DICM."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(2)
    except OSError:
        return False
    if head in _START_BYTES:
        return True
    return head == b"\x00\x00" and ext in _DICOM_EXTENSIONS


def _is_dicom_file(path: str) -> bool:
    """
    Rápido: marca DICM. Si falta (DICOM sin preámbulo), se admite cualquier
    extensión que no sea claramente de otro formato, previo filtro de 2 bytes
    y comprobación de que la cabecera tiene imagen (Rows/Columns).
    """
    name = os.path.basename(path)
    if name.lower() in _SKIP_NAMES:
        return False
    ext = os.path.splitext(name)[1].lower()
    if ext in _NON_DICOM_EXTENSIONS:
        return False
    if _has_dicm_magic(path):
        return True
    # Extensiones DICOM explícitas se intentan siempre; el resto pasan el filtro de bytes.
    if ext not in (".dcm", ".dicom", ".dic", ".ima") and not _looks_like_dicom_start(path, ext):
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
        if _has_dicm_magic(path) and os.path.basename(path).lower() not in _SKIP_NAMES:
            # DICOM sin imagen (SR, RT...): el visor explicará por qué no hay nada que mostrar.
            return ContentType.DICOM_FILE, [path]
        return ContentType.UNKNOWN, []

    return ContentType.UNKNOWN, []
