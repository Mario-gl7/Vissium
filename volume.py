"""
Construye un volumen 3D (numpy) a partir de una serie DICOM, con la
misma tolerancia que 3D Slicer ante metadatos incompletos y
estructuras no estándar. En concreto:

- Agrupa los archivos por SeriesInstanceUID (nunca se mezclan series en
  un volumen). Los DICOM que no son imagen (SR, RT Struct, PR, DICOMDIR...)
  se descartan al agrupar. Por defecto se carga la serie con más imágenes
  (ignorando localizadores si hay otra opción).
- Decodificación con cadena de respaldos: decodificador por defecto de
  pydicom, y después GDCM, pylibjpeg, Pillow, pyjpegls..., y como último
  recurso una lectura "en crudo" para datos sin comprimir (también con
  píxeles truncados, que se rellenan con ceros y se avisa).
- Archivos sin cabecera Part-10 / sin TransferSyntaxUID: se deduce la
  sintaxis de transferencia a partir de lo que detectó pydicom.
- Soporta Float Pixel Data / Double Float Pixel Data (mapas paramétricos).
- Multi-frame clásico y Enhanced (CT/MR/CBCT): espaciado, orientación,
  posición y reescalado (pendiente/intercepto) se leen también de los
  grupos funcionales compartidos y por frame.
- MONOCHROME1 se invierte; PALETTE COLOR y color (RGB/YBR) se pasan a gris.
- Orientación: posición de cada corte proyectando ImagePositionPatient
  sobre la normal del plano. Si hay cortes con orientaciones distintas
  (localizadores mezclados) se queda el grupo mayoritario.
- Series 4D / multifase (varios cortes en la misma posición): se muestra
  la primera fase y se avisa, en vez de apilar posiciones repetidas.
- Si falta información de posición/espaciado, se usa un fallback
  razonable (SliceLocation, nº de instancia, orden de archivo, grosor) y
  se deja constancia en `Volume.warnings`.
- Si no se puede extraer ninguna imagen se lanza `DicomLoadError` con un
  mensaje que explica el motivo (en vez de devolver None sin más).
- Se extraen ventana/nivel por defecto de las etiquetas DICOM.

Detección de series:
- Los archivos repetidos (mismo SOPInstanceUID, p. ej. una copia de seguridad
  en una subcarpeta) se descartan: antes se confundían con una serie 4D.
- Los archivos sin SeriesInstanceUID se agrupan por nº de serie y tamaño de
  imagen (antes se mezclaban todos en una única serie).
- `SeriesInfo` guarda también paciente, estudio y cabecera: el selector
  distingue series de estudios/pacientes distintos y los metadatos se leen sin
  volver a abrir el archivo.
- Metadatos ampliados: nº de serie, UID de serie/estudio, nº de acceso, ID de
  estudio, equipo, kVp, mA, protocolo, etc. (`Volume.metadata`).
- `Volume.scan_warnings`: avisos de la búsqueda de archivos, que se conservan al
  cambiar de serie.
"""
from __future__ import annotations

import logging
import os
import warnings as _warnings
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pydicom
from pydicom.dataset import FileMetaDataset
from pydicom.multival import MultiValue
from pydicom.uid import (
    ExplicitVRBigEndian,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
)

log = logging.getLogger("vissium.volume")


class DicomLoadError(Exception):
    """No se pudo extraer ninguna imagen; el mensaje explica el motivo."""


@dataclass
class SeriesInfo:
    """Una serie DICOM dentro de la selección (para el selector de series)."""
    uid: str
    number: str                # SeriesNumber como texto ("" si falta)
    description: str
    modality: str
    paths: list[str]           # archivos de la serie, en el orden de la selección
    n_images: int = 0          # imágenes/frames totales (un multi-frame cuenta todos)
    localizer: bool = False    # ImageType contiene LOCALIZER
    study_uid: str = ""
    patient: str = ""          # PatientName tal cual (con "^")
    study_date: str = ""       # StudyDate (YYYYMMDD)
    header: object = field(default=None, repr=False, compare=False)  # cabecera del 1.er archivo

    @property
    def label(self) -> str:
        head = f"{self.number} · " if self.number else ""
        count = self.n_images or len(self.paths)
        return f"{head}{self.description or 'Sin descripción'} ({count})"


@dataclass
class Volume:
    array: np.ndarray          # shape (n_slices, rows, cols) -> (Z, Y, X)
    row_spacing: float         # mm entre filas (eje Y, dentro del plano)
    col_spacing: float         # mm entre columnas (eje X, dentro del plano)
    slice_spacing: float       # mm entre cortes (eje Z)
    file_paths: list[str]      # rutas de cada corte, en el mismo orden que el eje Z
    metadata: dict[str, str]   # info de paciente/estudio/serie, al estilo Slicer
    warnings: list[str] = field(default_factory=list)  # avisos no bloqueantes
    series_uid: str = ""                                 # serie que contiene este volumen
    series: list[SeriesInfo] = field(default_factory=list)  # todas las series de la selección
    modality: str = ""
    window_center: float | None = None   # ventana por defecto según las etiquetas DICOM
    window_width: float | None = None
    scan_warnings: list[str] = field(default_factory=list)  # avisos de la búsqueda (no de la serie)

    @property
    def shape(self):
        return self.array.shape  # (Z, Y, X)

    @property
    def is_single_image(self) -> bool:
        """Imagen 2D (radiografía, panorámica, ecografía...): sin sagital/coronal útiles."""
        return self.array.shape[0] == 1

    # -- Extracción de cortes MPR -------------------------------------
    def axial(self, z: int) -> np.ndarray:
        """Corte axial (plano XY) en la posición z. Tamaño físico: X*col x Y*row."""
        z = int(np.clip(z, 0, self.shape[0] - 1))
        return self.array[z, :, :]

    def sagittal(self, x: int) -> np.ndarray:
        """
        Corte sagital (plano YZ) en la posición x. Filas=Z, columnas=Y.
        Se voltea verticalmente el eje Z: el índice más alto (más
        superior, según la convención LPS de DICOM) queda arriba en la
        imagen, como en un visor radiológico normal.
        """
        x = int(np.clip(x, 0, self.shape[2] - 1))
        return self.array[::-1, :, x]  # shape (Z, Y), Z invertido

    def coronal(self, y: int) -> np.ndarray:
        """Corte coronal (plano XZ) en la posición y. Filas=Z, columnas=X (Z invertido)."""
        y = int(np.clip(y, 0, self.shape[1] - 1))
        return self.array[::-1, y, :]  # shape (Z, X), Z invertido

    # -- Tamaño físico (mm) de cada vista, para corregir el aspecto ---
    def axial_physical_size(self) -> tuple[float, float]:
        """(ancho_mm, alto_mm) de la vista axial."""
        n_cols, n_rows = self.shape[2], self.shape[1]
        return n_cols * self.col_spacing, n_rows * self.row_spacing

    def sagittal_physical_size(self) -> tuple[float, float]:
        n_rows_img, n_z = self.shape[1], self.shape[0]
        return n_rows_img * self.row_spacing, n_z * self.slice_spacing

    def coronal_physical_size(self) -> tuple[float, float]:
        n_cols_img, n_z = self.shape[2], self.shape[0]
        return n_cols_img * self.col_spacing, n_z * self.slice_spacing


# ----------------------------------------------------------------------
# Utilidades de bajo nivel
# ----------------------------------------------------------------------
def _short(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return (text[0] if text else type(exc).__name__)[:200]


def _nth(seq, i: int):
    try:
        return seq[i] if seq else None
    except Exception:
        return None


def _fg_value(ds, frame_idx: int, seq_name: str, attr: str):
    """
    Busca `attr` dentro de `seq_name[0]` en los grupos funcionales de un
    objeto Enhanced / multi-frame: primero los del frame, luego los compartidos.
    """
    containers = (
        _nth(getattr(ds, "PerFrameFunctionalGroupsSequence", None), frame_idx),
        _nth(getattr(ds, "SharedFunctionalGroupsSequence", None), 0),
    )
    for container in containers:
        if container is None:
            continue
        seq = getattr(container, seq_name, None)
        if seq:
            value = getattr(seq[0], attr, None)
            if value is not None:
                return value
    return None


def _num(value) -> float | None:
    """Número a partir de un valor DICOM (DS/IS/MultiValue); None si no se puede."""
    if value is None:
        return None
    try:
        if not isinstance(value, (str, bytes)) and hasattr(value, "__len__"):
            value = value[0]
        return float(value)
    except Exception:
        return None


def _slice_normal(iop) -> np.ndarray:
    """
    Vector normal al plano de corte, a partir de ImageOrientationPatient.
    Con esto la posición de cada corte se calcula bien aunque la serie no
    sea axial pura (oblicua, sagital o coronal de origen).
    """
    try:
        row_cosines = np.array(iop[0:3], dtype=float)
        col_cosines = np.array(iop[3:6], dtype=float)
        normal = np.cross(row_cosines, col_cosines)
        norm = np.linalg.norm(normal)
        if norm < 1e-6:
            return np.array([0.0, 0.0, 1.0])
        return normal / norm
    except Exception:
        return np.array([0.0, 0.0, 1.0])


def _iop_of(ds, idx: int):
    """ImageOrientationPatient (6 valores) del frame, o None."""
    for value in (
        getattr(ds, "ImageOrientationPatient", None),
        _fg_value(ds, idx, "PlaneOrientationSequence", "ImageOrientationPatient"),
    ):
        if value is not None and len(value) == 6:
            try:
                return [float(v) for v in value]
            except Exception:
                continue
    return None


def _pixel_spacing_of(ds, idx: int) -> tuple[float, float] | None:
    """PixelSpacing, o alternativas habituales (CR/DX, Enhanced, digitalizadores)."""
    candidates = (
        getattr(ds, "PixelSpacing", None),
        getattr(ds, "ImagerPixelSpacing", None),
        _fg_value(ds, idx, "PixelMeasuresSequence", "PixelSpacing"),
        getattr(ds, "NominalScannedPixelSpacing", None),
    )
    for value in candidates:
        if value is not None and len(value) >= 2:
            try:
                row_sp, col_sp = float(value[0]), float(value[1])
                if row_sp > 0 and col_sp > 0:
                    return row_sp, col_sp
            except Exception:
                continue
    return None


def _spacing_hint_of(ds, idx: int) -> float:
    """Espaciado entre cortes declarado (SpacingBetweenSlices) o, si no, el grosor."""
    for owner, attr in (
        (ds, "SpacingBetweenSlices"),
        (None, "SpacingBetweenSlices"),
        (ds, "SliceThickness"),
        (None, "SliceThickness"),
    ):
        if owner is not None:
            value = _num(getattr(owner, attr, None))
        else:
            value = _num(_fg_value(ds, idx, "PixelMeasuresSequence", attr))
        if value and value > 0:
            return value
    return 0.0


def _rescale_of(ds, idx: int) -> tuple[float, float]:
    slope = _num(getattr(ds, "RescaleSlope", None))
    intercept = _num(getattr(ds, "RescaleIntercept", None))
    if slope is None:
        slope = _num(_fg_value(ds, idx, "PixelValueTransformationSequence", "RescaleSlope"))
    if intercept is None:
        intercept = _num(_fg_value(ds, idx, "PixelValueTransformationSequence", "RescaleIntercept"))
    return (slope if slope else 1.0), (intercept if intercept is not None else 0.0)


def _maybe_apply_palette(ds, frame: np.ndarray) -> np.ndarray:
    """Si la imagen usa PALETTE COLOR, la convierte a RGB real antes de pasar a gris."""
    photometric = str(getattr(ds, "PhotometricInterpretation", "")).upper()
    if photometric != "PALETTE COLOR":
        return frame
    try:
        try:
            from pydicom.pixels import apply_color_lut  # pydicom >= 3.0
        except ImportError:
            from pydicom.pixel_data_handlers.util import apply_color_lut
        return apply_color_lut(frame, ds)
    except Exception:
        return frame


def _to_grayscale(frame: np.ndarray) -> np.ndarray:
    """Convierte a escala de grises si el frame viene en color (RGB/RGBA)."""
    frame = np.asarray(frame)
    if frame.ndim == 3 and frame.shape[-1] in (3, 4):
        rgb = frame[..., :3].astype(np.float32)
        return rgb[..., 0] * 0.2989 + rgb[..., 1] * 0.5870 + rgb[..., 2] * 0.1140
    return frame


def _split_frames(pixels: np.ndarray, ds) -> list[np.ndarray]:
    """
    Separa el array de píxeles en una lista de frames (2D, o 2D+color que
    luego se pasa a gris). Usa SamplesPerPixel para distinguir "color" de
    "multi-frame" y, si falta, recurre a la forma del array.
    """
    pixels = np.asarray(pixels)
    spp = _num(getattr(ds, "SamplesPerPixel", None))
    if pixels.ndim == 2:
        return [pixels]
    if pixels.ndim == 3:
        if spp is not None:
            color = spp > 1
        else:
            color = pixels.shape[-1] in (3, 4)
        return [pixels] if color else [pixels[i] for i in range(pixels.shape[0])]
    if pixels.ndim == 4:
        return [pixels[i] for i in range(pixels.shape[0])]
    return []  # forma no reconocida


# ----------------------------------------------------------------------
# Decodificación de píxeles (con respaldos)
# ----------------------------------------------------------------------
# Nombres de decodificadores: pydicom 3.x (decoding_plugin) y 2.x (handler_name).
_PLUGINS = ("", "gdcm", "pylibjpeg", "pillow", "pyjpegls", "jpeg_ls", "openjpeg", "libjpeg", "rle")


def _ensure_transfer_syntax(ds) -> None:
    """Si el archivo no declara TransferSyntaxUID, se deduce de lo que detectó pydicom."""
    meta = getattr(ds, "file_meta", None)
    if meta is not None and getattr(meta, "TransferSyntaxUID", None):
        return
    if meta is None:
        ds.file_meta = FileMetaDataset()
        meta = ds.file_meta
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        implicit = getattr(ds, "is_implicit_VR", True)
        little = getattr(ds, "is_little_endian", True)
    if implicit:
        meta.TransferSyntaxUID = ImplicitVRLittleEndian
    elif little:
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
    else:
        meta.TransferSyntaxUID = ExplicitVRBigEndian


def _transfer_syntax(ds):
    return getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)


def _is_compressed(ds) -> bool:
    ts = _transfer_syntax(ds)
    return bool(ts is not None and getattr(ts, "is_compressed", False))


def _codec_hint(ds) -> str:
    ts = _transfer_syntax(ds)
    if ts is not None and getattr(ts, "is_compressed", False):
        return (f"Sintaxis de transferencia: {getattr(ts, 'name', ts)}. "
                f"Instala 'pylibjpeg' y 'python-gdcm' (ver requirements.txt).")
    return ""


def _try_decode(ds, plugin: str) -> np.ndarray:
    if not plugin:
        return ds.pixel_array
    try:
        from pydicom.pixels import pixel_array as _pixel_array  # pydicom >= 3.0
    except ImportError:
        ds.convert_pixel_data(handler_name=plugin)           # pydicom 2.x
        return ds.pixel_array
    return _pixel_array(ds, decoding_plugin=plugin)


def _raw_decode(ds, warnings: list[str], name: str) -> np.ndarray:
    """Último recurso para datos SIN comprimir: lectura directa, tolerando píxeles truncados."""
    rows, cols = int(ds.Rows), int(ds.Columns)
    bits = int(getattr(ds, "BitsAllocated", 16))
    spp = int(_num(getattr(ds, "SamplesPerPixel", 1)) or 1)
    nframes = int(_num(getattr(ds, "NumberOfFrames", 1)) or 1)
    signed = int(_num(getattr(ds, "PixelRepresentation", 0)) or 0) == 1
    if bits not in (8, 16, 32):
        raise ValueError(f"BitsAllocated={bits} no soportado en lectura directa")
    big = _transfer_syntax(ds) == ExplicitVRBigEndian
    dtype = np.dtype(f"{'i' if signed else 'u'}{bits // 8}").newbyteorder(">" if big else "<")

    buffer = bytes(ds.PixelData)
    expected = rows * cols * spp * nframes
    available = len(buffer) // dtype.itemsize
    arr = np.frombuffer(buffer, dtype=dtype, count=min(expected, available))
    if arr.size < expected:
        warnings.append(
            f"{name}: datos de imagen truncados ({arr.size} de {expected} valores); "
            f"se rellena con ceros."
        )
        arr = np.concatenate([arr, np.zeros(expected - arr.size, dtype=dtype)])

    planar = int(_num(getattr(ds, "PlanarConfiguration", 0)) or 0)
    if spp > 1:
        if planar == 1:
            arr = arr.reshape(nframes, spp, rows, cols).transpose(0, 2, 3, 1)
        else:
            arr = arr.reshape(nframes, rows, cols, spp)
        photometric = str(getattr(ds, "PhotometricInterpretation", "")).upper()
        if photometric.startswith("YBR") and spp == 3:
            try:
                try:
                    from pydicom.pixels import convert_color_space
                except ImportError:
                    from pydicom.pixel_data_handlers.util import convert_color_space
                arr = np.stack([convert_color_space(f, photometric, "RGB") for f in arr])
            except Exception:
                pass
    else:
        arr = arr.reshape(nframes, rows, cols)
    return arr.astype(dtype.newbyteorder("="), copy=False)


def _decode_pixels(ds, warnings: list[str], name: str) -> np.ndarray:
    rows, cols = int(ds.Rows), int(ds.Columns)

    if "PixelData" not in ds:
        for tag, dtype in (("FloatPixelData", "<f4"), ("DoubleFloatPixelData", "<f8")):
            raw = ds.get(tag)
            if raw is not None:
                return np.frombuffer(bytes(raw.value), dtype=dtype).reshape(-1, rows, cols)
        raise ValueError("el archivo no contiene datos de imagen (PixelData)")

    compressed = _is_compressed(ds)
    errors: list[str] = []
    arr = None
    for plugin in (_PLUGINS if compressed else ("",)):
        try:
            arr = _try_decode(ds, plugin)
            break
        except Exception as exc:
            errors.append(f"{plugin or 'auto'}: {_short(exc)}")
    if arr is None and not compressed:
        try:
            arr = _raw_decode(ds, warnings, name)
        except Exception as exc:
            errors.append(f"directo: {_short(exc)}")
    if arr is None:
        raise RuntimeError("; ".join(errors[:3]) or "decodificación fallida")

    # Bits sin usar (p. ej. 12 bits en 16): se enmascaran los altos si son basura/overlay.
    try:
        stored = int(_num(getattr(ds, "BitsStored", 0)) or 0)
        allocated = int(_num(getattr(ds, "BitsAllocated", 0)) or 0)
        if arr.dtype.kind == "u" and 0 < stored < allocated:
            arr = arr & np.array((1 << stored) - 1, dtype=arr.dtype)
    except Exception:
        pass
    return arr


# ----------------------------------------------------------------------
# Lectura de series
# ----------------------------------------------------------------------
@dataclass
class _FrameRecord:
    array: np.ndarray
    position: float | None   # posición física proyectada (None si no se pudo calcular)
    fallback_order: float    # orden de respaldo: nº de instancia / orden de archivo
    row_spacing: float
    col_spacing: float
    spacing_hint: float      # SpacingBetweenSlices o SliceThickness (0 si no hay)
    path: str
    iop_key: tuple | None    # orientación redondeada (para agrupar cortes coplanares)
    invert: bool             # MONOCHROME1


def _header_only(path: str):
    try:
        return pydicom.dcmread(path, stop_before_pixels=True, force=True)
    except Exception:
        return None


def _is_image_header(ds) -> bool:
    try:
        return int(ds.Rows) > 0 and int(ds.Columns) > 0
    except Exception:
        return False


def _group_by_series(file_paths: list[str]):
    """
    Agrupa por SeriesInstanceUID sin decodificar los píxeles. Los archivos que
    no son imagen o no se pueden leer se descartan (y se cuentan en `stats`);
    los repetidos (mismo SOPInstanceUID) también.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    headers: dict[str, "pydicom.Dataset"] = {}
    seen_instances: set[tuple] = set()
    stats = {"total": len(file_paths), "non_image": 0, "unreadable": 0, "duplicates": 0}

    workers = max(1, min(8, os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_header_only, file_paths))  # conserva el orden

    for path, ds in zip(file_paths, results):
        if ds is None:
            stats["unreadable"] += 1
            continue
        if not _is_image_header(ds):
            stats["non_image"] += 1
            continue
        series_uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
        if not series_uid:
            # Sin UID de serie: se agrupa por nº de serie y tamaño para no mezclar series distintas.
            series_uid = (f"__sin_serie__{_tag(ds, 'SeriesNumber', '')}|"
                          f"{getattr(ds, 'Rows', '')}x{getattr(ds, 'Columns', '')}")
        sop_uid = str(getattr(ds, "SOPInstanceUID", "") or "")
        if sop_uid:
            instance_key = (series_uid, sop_uid)
            if instance_key in seen_instances:
                stats["duplicates"] += 1
                continue
            seen_instances.add(instance_key)
        groups[series_uid].append(path)
        headers[path] = ds
    return groups, headers, stats


def _no_images_message(stats: dict) -> str:
    parts = []
    if stats["non_image"]:
        parts.append(f"{stats['non_image']} archivo(s) DICOM no contienen imagen "
                     f"(informes SR, RT Struct, presentaciones, DICOMDIR...)")
    if stats["unreadable"]:
        parts.append(f"{stats['unreadable']} archivo(s) no se han podido leer como DICOM")
    detail = "; ".join(parts) or "la selección está vacía"
    return f"No hay imágenes DICOM que mostrar: {detail}."


def _series_sort_key(info: SeriesInfo):
    try:
        number = int(float(info.number))
    except ValueError:
        number = 10**9
    return (number, info.description.lower(), info.uid)


def _series_list(groups: dict[str, list[str]], headers: dict) -> list[SeriesInfo]:
    """Resumen de cada serie (nº, descripción, modalidad, nº de imágenes), ordenado por nº de serie."""
    items: list[SeriesInfo] = []
    for uid, paths in groups.items():
        ds = headers.get(paths[0])
        n_images = 0
        for p in paths:
            n_images += int(_num(getattr(headers.get(p), "NumberOfFrames", 1)) or 1)
        image_type = [str(v).upper() for v in (getattr(ds, "ImageType", None) or [])]
        items.append(SeriesInfo(
            uid=uid,
            number=_tag(ds, "SeriesNumber", ""),
            description=_tag(ds, "SeriesDescription", ""),
            modality=_tag(ds, "Modality", ""),
            paths=list(paths),
            n_images=n_images,
            localizer="LOCALIZER" in image_type,
            study_uid=_tag(ds, "StudyInstanceUID", ""),
            patient=_tag(ds, "PatientName", ""),
            study_date=_tag(ds, "StudyDate", ""),
            header=ds,
        ))
    items.sort(key=_series_sort_key)
    return items


def _frames_from_dataset(ds, path: str, warnings: list[str], base_order: int) -> list[_FrameRecord]:
    name = os.path.basename(path)
    _ensure_transfer_syntax(ds)
    try:
        pixels = _decode_pixels(ds, warnings, name)
    except Exception as exc:
        hint = _codec_hint(ds)
        warnings.append(f"{name}: no se pudo decodificar la imagen ({_short(exc)}). {hint}".strip())
        return []

    raw_frames = _split_frames(pixels, ds)
    if not raw_frames:
        warnings.append(
            f"{name}: forma de píxel no reconocida {getattr(pixels, 'shape', '?')}; se omite."
        )
        return []

    n_frames = len(raw_frames)
    photometric = str(getattr(ds, "PhotometricInterpretation", "")).upper()
    invert = photometric == "MONOCHROME1"
    top_ipp = getattr(ds, "ImagePositionPatient", None)
    slice_location = _num(getattr(ds, "SliceLocation", None))
    warned_spacing = False

    inst = _num(getattr(ds, "InstanceNumber", None))
    base_key = (inst if inst is not None else float(base_order)) * 100000

    records: list[_FrameRecord] = []
    for idx, frame in enumerate(raw_frames):
        frame = _maybe_apply_palette(ds, frame)
        frame = _to_grayscale(frame)
        if frame.ndim != 2:
            warnings.append(f"{name} (frame {idx}): forma de píxel no soportada {frame.shape}; se omite.")
            continue

        slope, intercept = _rescale_of(ds, idx)
        if "ModalityLUTSequence" in ds and "RescaleSlope" not in ds:
            try:
                try:
                    from pydicom.pixels import apply_modality_lut
                except ImportError:
                    from pydicom.pixel_data_handlers.util import apply_modality_lut
                frame = np.asarray(apply_modality_lut(frame, ds))
                slope, intercept = 1.0, 0.0
            except Exception:
                pass
        # Se conserva el tipo entero cuando el reescalado es entero (mucha menos
        # memoria que float32 en un CBCT de cientos de cortes).
        if slope == 1.0 and float(intercept).is_integer() and frame.dtype.kind in "iu":
            if intercept != 0.0:
                frame = frame.astype(np.int32) + int(intercept)
        elif slope != 1.0 or intercept != 0.0 or frame.dtype.kind not in "iu":
            frame = frame.astype(np.float32) * slope + intercept

        spacing = _pixel_spacing_of(ds, idx)
        if spacing is None:
            row_sp, col_sp = 1.0, 1.0
            if not warned_spacing:
                warnings.append(f"{name}: sin PixelSpacing; se asume 1 mm.")
                warned_spacing = True
        else:
            row_sp, col_sp = spacing

        iop = _iop_of(ds, idx)
        normal = _slice_normal(iop) if iop is not None else np.array([0.0, 0.0, 1.0])

        ipp = None
        per_frame = _fg_value(ds, idx, "PlanePositionSequence", "ImagePositionPatient")
        if per_frame is not None:
            ipp = per_frame
        elif top_ipp is not None and n_frames == 1:
            # Con varios frames, una única posición superior no distingue los cortes.
            ipp = top_ipp
        position = None
        if ipp is not None:
            try:
                coords = [float(v) for v in ipp]
                if len(coords) == 3:
                    position = float(np.dot(normal, np.array(coords)))
            except Exception:
                position = None
        if position is None and slice_location is not None and n_frames == 1:
            position = slice_location

        records.append(_FrameRecord(
            array=frame,
            position=position,
            fallback_order=base_key + idx,
            row_spacing=row_sp,
            col_spacing=col_sp,
            spacing_hint=_spacing_hint_of(ds, idx),
            path=path,
            iop_key=tuple(round(v, 2) for v in iop) if iop is not None else None,
            invert=invert,
        ))
    return records


def _window_from_header(ds) -> tuple[float | None, float | None]:
    if ds is None:
        return None, None
    center = _num(getattr(ds, "WindowCenter", None))
    width = _num(getattr(ds, "WindowWidth", None))
    if center is None or width is None:
        center = _num(_fg_value(ds, 0, "FrameVOILUTSequence", "WindowCenter"))
        width = _num(_fg_value(ds, 0, "FrameVOILUTSequence", "WindowWidth"))
    if center is None or width is None or width <= 0:
        return None, None
    return center, width


def _compact_dtype(volume: np.ndarray) -> np.ndarray:
    """Reduce enteros de 32 bits a 16 si el rango lo permite (memoria)."""
    if volume.dtype.kind in "iu" and volume.dtype.itemsize > 2:
        lo, hi = int(volume.min()), int(volume.max())
        if -32768 <= lo and hi <= 32767:
            return volume.astype(np.int16)
        if 0 <= lo and hi <= 65535:
            return volume.astype(np.uint16)
    return volume


def load_volume(
    file_paths: list[str],
    series_uid: str | None = None,
    available: list[SeriesInfo] | None = None,
    scan_warnings: list[str] | None = None,
) -> Volume:
    """
    Lee una lista de archivos DICOM, los agrupa por serie, ordena los
    cortes espacialmente (o con el mejor fallback disponible) y construye
    un volumen 3D. Lanza `DicomLoadError` si no se puede extraer ni un
    solo corte válido (el mensaje explica el motivo).

    - `series_uid`: serie a cargar. Si no se indica (o no existe), la que
      tenga más imágenes (ignorando localizadores si hay alternativa).
    - `available`: lista de series ya calculada (de un `Volume.series`
      anterior). Evita volver a leer las cabeceras al cambiar de serie.
    - `scan_warnings`: avisos previos de la búsqueda de archivos (de
      `classify_detailed` o de un `Volume.scan_warnings` anterior).
    """
    warnings: list[str] = list(scan_warnings or [])

    if available is None:
        groups, headers, stats = _group_by_series(file_paths)
        if not groups:
            raise DicomLoadError(_no_images_message(stats))
        available = _series_list(groups, headers)
        if stats["non_image"]:
            warnings.append(f"{stats['non_image']} archivo(s) DICOM sin imagen omitidos.")
        if stats["duplicates"]:
            warnings.append(f"{stats['duplicates']} archivo(s) repetidos (mismo SOPInstanceUID) omitidos.")
        if stats["unreadable"]:
            warnings.append(f"{stats['unreadable']} archivo(s) no se han podido leer como DICOM.")
    if not available:
        raise DicomLoadError("No hay imágenes DICOM que mostrar.")
    scan_warnings_out = list(warnings)

    chosen = next((s for s in available if s.uid == series_uid), None)
    if chosen is None:
        chosen = max(available, key=lambda s: (not s.localizer, s.n_images or len(s.paths)))
    chosen_paths = list(chosen.paths)

    def _read_one(item):
        i, path = item
        local: list[str] = []
        try:
            ds_full = pydicom.dcmread(path, force=True)
        except Exception as exc:
            local.append(f"{os.path.basename(path)}: no se pudo leer ({_short(exc)}); se omite.")
            return [], local
        return _frames_from_dataset(ds_full, path, local, base_order=i), local

    # Lectura/descompresión en paralelo (pool.map conserva el orden).
    records: list[_FrameRecord] = []
    decode_warnings: list[str] = []
    workers = max(1, min(8, os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for recs, local in pool.map(_read_one, enumerate(chosen_paths)):
            records.extend(recs)
            decode_warnings.extend(local)
    warnings.extend(decode_warnings)

    if not records:
        detail = " ".join(decode_warnings[:3]) or "no se encontró ninguna imagen en la serie."
        raise DicomLoadError(f"No se pudo leer ninguna imagen de la serie. {detail}")

    # Cortes con dimensiones distintas: se queda el grupo mayoritario.
    majority_shape, _ = Counter(r.array.shape for r in records).most_common(1)[0]
    filtered = [r for r in records if r.array.shape == majority_shape]
    if len(filtered) < len(records):
        warnings.append(
            f"{len(records) - len(filtered)} corte(s) con dimensiones distintas al "
            f"resto de la serie se han omitido."
        )
    records = filtered

    # Cortes con orientaciones distintas (p. ej. localizadores mezclados).
    orient_counts = Counter(r.iop_key for r in records)
    if len(orient_counts) > 1:
        majority_iop, _ = orient_counts.most_common(1)[0]
        filtered = [r for r in records if r.iop_key == majority_iop]
        warnings.append(
            f"{len(records) - len(filtered)} corte(s) con orientación distinta al "
            f"resto de la serie se han omitido."
        )
        records = filtered

    has_all_positions = all(r.position is not None for r in records)
    if has_all_positions and len(records) > 1:
        records.sort(key=lambda r: (r.position, r.fallback_order))
        unique: list[_FrameRecord] = []
        for r in records:
            if unique and abs(r.position - unique[-1].position) < 1e-3:
                continue  # misma posición: otra fase/eco/repetición
            unique.append(r)
        if len(unique) < len(records):
            phases = len(records) // max(len(unique), 1)
            warnings.append(
                f"{len(records) - len(unique)} corte(s) repetidos en la misma posición "
                f"(serie 4D / multifase / varios ecos, ~{phases} fases): se muestra solo la primera."
            )
            records = unique
        diffs = np.abs(np.diff([r.position for r in records])) if len(records) > 1 else np.array([])
        diffs = diffs[diffs > 1e-6]
        if len(diffs):
            slice_spacing = float(np.median(diffs))
            if diffs.max() > 1.5 * diffs.min():
                warnings.append(
                    "Espaciado entre cortes no uniforme (huecos o inclinación del gantry): "
                    "las vistas sagital/coronal pueden verse deformadas."
                )
        else:
            slice_spacing = records[0].spacing_hint or 1.0
    else:
        records.sort(key=lambda r: r.fallback_order)
        slice_spacing = records[0].spacing_hint or 1.0
        if not has_all_positions and len(records) > 1:
            warnings.append(
                "No se ha podido determinar la posición física de todos los cortes; se han "
                "ordenado por número de instancia/orden de archivo y se ha usado el "
                "espaciado/grosor de corte declarado."
            )
    if slice_spacing <= 0:
        slice_spacing = 1.0

    row_spacing = records[0].row_spacing or 1.0
    col_spacing = records[0].col_spacing or 1.0

    volume = np.stack([r.array for r in records], axis=0)  # (Z, Y, X), siempre 3D
    invert = any(r.invert for r in records)
    if invert:
        vmin, vmax = volume.min(), volume.max()
        if volume.dtype.kind == "f":
            volume = (vmax + vmin) - volume
        else:
            inverted = (int(vmax) + int(vmin)) - volume.astype(np.int64)
            volume = inverted.astype(volume.dtype)
    volume = _compact_dtype(volume)
    paths = [r.path for r in records]

    first_header = chosen.header
    if first_header is None and chosen_paths:
        first_header = _header_only(chosen_paths[0])
    metadata = _extract_metadata(first_header, n_slices=volume.shape[0])
    win_center, win_width = (None, None) if invert else _window_from_header(first_header)

    # Evita cientos de etiquetas de aviso en la interfaz (una por archivo).
    if len(warnings) > 10:
        extra = len(warnings) - 10
        warnings = warnings[:10] + [f"… y {extra} aviso(s) más del mismo tipo."]

    return Volume(
        array=volume,
        row_spacing=row_spacing,
        col_spacing=col_spacing,
        slice_spacing=slice_spacing,
        file_paths=paths,
        metadata=metadata,
        warnings=warnings,
        series_uid=chosen.uid,
        series=available,
        modality=chosen.modality,
        window_center=win_center,
        window_width=win_width,
        scan_warnings=scan_warnings_out,
    )


# ----------------------------------------------------------------------
# Metadatos
# ----------------------------------------------------------------------
def _tag(ds, name: str, default: str = "—") -> str:
    try:
        value = getattr(ds, name, None)
        if value is None or value == "":
            return default
        if isinstance(value, MultiValue):
            text = " / ".join(str(v) for v in value if str(v) != "")
            return text or default
        return str(value)
    except Exception:
        return default


def _first_tag(ds, names: tuple[str, ...], default: str = "—") -> str:
    """Primer valor no vacío entre varias etiquetas equivalentes."""
    for name in names:
        value = _tag(ds, name, "")
        if value:
            return value
    return default


def _transfer_syntax_name(ds) -> str:
    ts = _transfer_syntax(ds)
    if ts is None:
        return "—"
    return str(getattr(ts, "name", None) or ts)


def series_labels(series: list[SeriesInfo]) -> list[str]:
    """
    Textos del selector de series. Si la selección mezcla estudios o pacientes
    distintos, cada texto lleva delante el paciente y la fecha del estudio.
    """
    multi = len({(s.patient, s.study_uid) for s in series}) > 1
    labels: list[str] = []
    for info in series:
        text = info.label
        if multi:
            who = " ".join(info.patient.replace("^", " ").split()) or "Sin nombre"
            d = info.study_date.strip()
            date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d
            text = f"{who} · {date} · {text}" if date else f"{who} · {text}"
        labels.append(text)
    return labels


def _extract_metadata(ds, n_slices: int) -> dict[str, str]:
    """
    Recoge los campos que Slicer suele mostrar en su panel de información:
    identificación del paciente, del estudio y de la serie (con su número y
    UID de referencia), y parámetros de adquisición. Los valores que faltan
    quedan como "—".
    """
    if ds is None:
        return {"Nº de cortes": str(n_slices)}
    return {
        # Paciente
        "Paciente": _tag(ds, "PatientName"),
        "ID paciente": _tag(ds, "PatientID"),
        "Sexo": _tag(ds, "PatientSex"),
        "Fecha nacimiento": _tag(ds, "PatientBirthDate"),
        "Edad": _tag(ds, "PatientAge"),
        # Estudio
        "Fecha estudio": _tag(ds, "StudyDate"),
        "Hora estudio": _tag(ds, "StudyTime"),
        "Descripción estudio": _tag(ds, "StudyDescription"),
        "ID estudio": _tag(ds, "StudyID"),
        "Nº de acceso": _tag(ds, "AccessionNumber"),
        "UID estudio": _tag(ds, "StudyInstanceUID"),
        "Institución": _tag(ds, "InstitutionName"),
        # Serie
        "Nº serie": _tag(ds, "SeriesNumber"),
        "Descripción serie": _tag(ds, "SeriesDescription"),
        "UID serie": _tag(ds, "SeriesInstanceUID"),
        "Modalidad": _tag(ds, "Modality"),
        "Parte del cuerpo": _tag(ds, "BodyPartExamined"),
        "Protocolo": _tag(ds, "ProtocolName"),
        "Tipo de imagen": _tag(ds, "ImageType"),
        # Imagen
        "Nº de cortes": str(n_slices),
        "Grosor de corte": _tag(ds, "SliceThickness"),
        "Bits": _first_tag(ds, ("BitsStored", "BitsAllocated")),
        "Compresión": _transfer_syntax_name(ds),
        # Equipo y adquisición
        "Fabricante": _tag(ds, "Manufacturer"),
        "Modelo": _tag(ds, "ManufacturerModelName"),
        "Software": _tag(ds, "SoftwareVersions"),
        "Estación": _tag(ds, "StationName"),
        "KVP": _tag(ds, "KVP"),
        "mA": _first_tag(ds, ("XRayTubeCurrent", "XRayTubeCurrentInmA")),
        "Exposición (mAs)": _tag(ds, "Exposure"),
        "Tiempo exposición (ms)": _tag(ds, "ExposureTime"),
    }
