"""
Detección de tipo de archivo/carpeta para decidir qué visor abrir.

Qué se detecta:
- DICOM (serie en carpeta, o archivo suelto), con CUALQUIER extensión o sin ella
  (IM0001, I10, 1.2.840...), con filtro rápido de 2 bytes + comprobación de
  Rows/Columns cuando falta la marca "DICM".
- Mallas 3D (.stl, .ply).
- Imágenes (png, jpg, bmp, gif, tif, webp, ico...).

Detección de series (por qué antes "a veces no se detectaban"):
- Antes solo se exploraban 3 niveles de subcarpetas y se paraba en el primer
  nivel donde aparecía algo. Las exportaciones tipo CD/PACS
  (DICOM/PAT/STD/SER/IMG) tienen los archivos a 4 o más niveles y no se
  encontraban.
- Antes, con subcarpetas, solo se devolvía la subcarpeta con MÁS archivos y el
  resto de series se perdía. Ahora se reúnen los DICOM de TODA la carpeta (y
  subcarpetas, hasta `_MAX_DEPTH` niveles) y `volume.load_volume` los agrupa por
  SeriesInstanceUID: el selector de series muestra todas.
- Antes, un DICOM suelto solo cargaba los de SU serie, así que el selector no
  ofrecía las demás series de la carpeta. Ahora se cargan todas las de la
  carpeta y se abre por defecto la serie del archivo elegido (`preferred_uid`).
- Los límites (carpetas, archivos, tiempo) avisan en `notes` cuando se alcanzan,
  en vez de cortar la búsqueda en silencio.

Prioridad al elegir una carpeta (igual que antes, ampliada con imágenes):
DICOM directos > mallas directas > DICOM en subcarpetas > mallas en
subcarpetas > imágenes (directas y, si no, de la primera subcarpeta con imágenes).

- Los archivos se ordenan de forma "natural" (IM2 antes que IM10).
- DICOMDIR se ignora (no contiene imagen).
- Un archivo de imagen suelto se abre junto a las demás imágenes de su carpeta
  (para poder pasar de una a otra con las flechas).
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto

import pydicom


class ContentType(Enum):
    DICOM_SERIES = auto()   # carpeta con uno o más archivos DICOM
    DICOM_FILE = auto()     # un archivo DICOM suelto (se amplía a las series de su carpeta)
    MESH = auto()           # .stl o .ply
    IMAGE = auto()          # foto/imagen: png, jpg...
    UNKNOWN = auto()
    EMPTY_FOLDER = auto()


MESH_EXTENSIONS = {".stl", ".ply"}
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".bmp", ".gif",
    ".tif", ".tiff", ".webp", ".ico",
}
# Extensiones en las que se intenta leer como DICOM aunque falte la marca "DICM".
_DICOM_EXTENSIONS = {"", ".dcm", ".dicom", ".dic", ".ima"}
# Extensiones que seguro NO son DICOM (se descartan sin abrir el archivo).
_NON_DICOM_EXTENSIONS = IMAGE_EXTENSIONS | MESH_EXTENSIONS | {
    ".obj", ".svg", ".txt", ".md", ".pdf", ".xml", ".json", ".csv", ".log",
    ".ini", ".cfg", ".exe", ".dll", ".zip", ".7z", ".rar", ".gz", ".tar", ".html",
    ".htm", ".py", ".bat", ".lnk", ".db", ".docx", ".xlsx", ".pptx", ".mp4", ".avi",
    ".mov", ".nii", ".mha", ".nrrd",
}
_SKIP_NAMES = {"dicomdir"}
_SKIP_DIRS = {"__macosx"}

# Los DICOM (con o sin preámbulo) empiezan por el grupo 0008 o 0002, en
# little o big endian. El grupo 0000 solo se admite con extensión DICOM típica.
_START_BYTES = {b"\x08\x00", b"\x02\x00", b"\x00\x08", b"\x00\x02"}

# Límites de la búsqueda en subcarpetas (evitan recorrer discos enteros).
_MAX_DEPTH = 8            # niveles de subcarpetas bajo la carpeta elegida
_MAX_SUBDIRS = 2000       # carpetas escaneadas
_MAX_DICOM_FILES = 30000  # archivos DICOM reunidos
_MAX_SCAN_SECONDS = 20.0  # tiempo máximo de búsqueda


@dataclass
class Classification:
    """Resultado de `classify_detailed`."""
    ctype: ContentType
    files: list[str] = field(default_factory=list)
    preferred_uid: str = ""      # DICOM suelto: serie del archivo elegido (abrir esa por defecto)
    index: int = 0               # IMAGE: posición del archivo elegido dentro de `files`
    notes: list[str] = field(default_factory=list)  # avisos (p. ej. búsqueda limitada)


@dataclass
class _Scan:
    dicoms: list[str] = field(default_factory=list)
    meshes: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    subdirs: list[str] = field(default_factory=list)
    n_files: int = 0


def _natural_key(path: str):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", os.path.basename(path))]


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def is_image_path(path: str) -> bool:
    """True si es un archivo (no carpeta) con extensión de imagen."""
    return _ext(path) in IMAGE_EXTENSIONS and os.path.isfile(path)


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
    ext = _ext(name)
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


def _scan(folder: str) -> _Scan:
    """DICOM, mallas, imágenes y subcarpetas de UNA carpeta (sin recursión)."""
    files: list[str] = []
    subdirs: list[str] = []
    try:
        with os.scandir(folder) as it:
            for entry in it:
                try:
                    if entry.is_file():
                        files.append(entry.path)
                    elif (entry.is_dir() and not entry.name.startswith((".", "$"))
                          and entry.name.lower() not in _SKIP_DIRS):
                        subdirs.append(entry.path)
                except OSError:
                    continue
    except OSError:
        return _Scan()
    files.sort(key=_natural_key)
    subdirs.sort(key=_natural_key)
    return _Scan(
        dicoms=[f for f in files if _is_dicom_file(f)],
        meshes=[f for f in files if _ext(f) in MESH_EXTENSIONS],
        images=[f for f in files if _ext(f) in IMAGE_EXTENSIONS],
        subdirs=subdirs,
        n_files=len(files),
    )


def _images_in(folder: str) -> list[str]:
    """Imágenes de una carpeta, sin comprobar DICOM (barato)."""
    try:
        with os.scandir(folder) as it:
            found = [e.path for e in it
                     if _ext(e.name) in IMAGE_EXTENSIONS and e.is_file()]
    except OSError:
        return []
    found.sort(key=_natural_key)
    return found


@dataclass
class _Walk:
    dicoms: list[str] = field(default_factory=list)   # TODOS los DICOM encontrados
    meshes: list[str] = field(default_factory=list)   # mallas de la carpeta menos profunda que tenga
    images: list[str] = field(default_factory=list)   # imágenes de la carpeta menos profunda que tenga
    notes: list[str] = field(default_factory=list)


def _walk_subfolders(subdirs: list[str]) -> _Walk:
    """
    Recorre las subcarpetas en anchura (hasta _MAX_DEPTH niveles) reuniendo los
    DICOM de TODAS ellas. Para mallas e imágenes se queda con las de la primera
    carpeta (la menos profunda) que las tenga.
    """
    walk = _Walk()
    started = time.monotonic()
    frontier = list(subdirs)
    scanned = 0
    stop_reason = ""
    for _depth in range(_MAX_DEPTH):
        if not frontier or stop_reason:
            break
        next_frontier: list[str] = []
        for sub in frontier:
            if scanned >= _MAX_SUBDIRS:
                stop_reason = f"se alcanzó el límite de {_MAX_SUBDIRS} carpetas"
                break
            if len(walk.dicoms) >= _MAX_DICOM_FILES:
                stop_reason = f"se alcanzó el límite de {_MAX_DICOM_FILES} archivos DICOM"
                break
            if time.monotonic() - started > _MAX_SCAN_SECONDS:
                stop_reason = f"la búsqueda superó {int(_MAX_SCAN_SECONDS)} s"
                break
            scanned += 1
            scan = _scan(sub)
            walk.dicoms.extend(scan.dicoms)
            if scan.meshes and not walk.meshes:
                walk.meshes = scan.meshes
            if scan.images and not walk.images:
                walk.images = scan.images
            next_frontier.extend(scan.subdirs)
        frontier = next_frontier
    if stop_reason:
        walk.notes.append(
            f"Búsqueda limitada ({stop_reason}): puede que falten series. "
            f"Selecciona una carpeta más concreta."
        )
    return walk


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


def classify_detailed(path: str) -> Classification:
    """
    Clasifica `path` (archivo o carpeta) y devuelve el tipo, los archivos
    relevantes y, según el caso, la serie preferida, la posición de la imagen
    elegida y avisos de la búsqueda.
    """
    if os.path.isdir(path):
        root = _scan(path)
        if root.dicoms:
            walk = _walk_subfolders(root.subdirs) if root.subdirs else _Walk()
            return Classification(ContentType.DICOM_SERIES, root.dicoms + walk.dicoms,
                                  notes=walk.notes)
        if root.meshes:
            return Classification(ContentType.MESH, root.meshes)
        if root.n_files == 0 and not root.subdirs:
            return Classification(ContentType.EMPTY_FOLDER)
        walk = _walk_subfolders(root.subdirs) if root.subdirs else _Walk()
        if walk.dicoms:
            return Classification(ContentType.DICOM_SERIES, walk.dicoms, notes=walk.notes)
        if walk.meshes:
            return Classification(ContentType.MESH, walk.meshes)
        if root.images:
            return Classification(ContentType.IMAGE, root.images)
        if walk.images:
            return Classification(ContentType.IMAGE, walk.images)
        return Classification(ContentType.UNKNOWN, notes=walk.notes)

    if os.path.isfile(path):
        ext = _ext(path)
        if ext in MESH_EXTENSIONS:
            return Classification(ContentType.MESH, [path])

        if ext in IMAGE_EXTENSIONS:
            siblings = _images_in(os.path.dirname(os.path.abspath(path))) or [path]
            index = next((i for i, f in enumerate(siblings) if _same(f, path)), None)
            if index is None:
                siblings.append(path)
                index = len(siblings) - 1
            return Classification(ContentType.IMAGE, siblings, index=index)

        if _is_dicom_file(path):
            uid = _series_uid(path)
            if not uid:
                return Classification(ContentType.DICOM_FILE, [path])
            # Todos los DICOM de la carpeta: el selector ofrece todas las series y se
            # abre por defecto la del archivo elegido.
            folder_files = _scan(os.path.dirname(os.path.abspath(path))).dicoms
            if not any(_same(f, path) for f in folder_files):
                folder_files.append(path)
            return Classification(ContentType.DICOM_FILE, folder_files, preferred_uid=uid)

        if _has_dicm_magic(path) and os.path.basename(path).lower() not in _SKIP_NAMES:
            # DICOM sin imagen (SR, RT...): el visor explicará por qué no hay nada que mostrar.
            return Classification(ContentType.DICOM_FILE, [path])
        return Classification(ContentType.UNKNOWN)

    return Classification(ContentType.UNKNOWN)


def classify_path(path: str) -> tuple[ContentType, list[str]]:
    """Versión corta de `classify_detailed`: (tipo, lista_de_archivos_relevantes)."""
    info = classify_detailed(path)
    return info.ctype, info.files
