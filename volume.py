"""
Construye un volumen 3D (numpy) a partir de una serie DICOM, con la
misma tolerancia que 3D Slicer ante metadatos incompletos y
estructuras no estándar. En concreto, esto incluye:

- Agrupar los archivos por SeriesInstanceUID: si la selección mezcla
  varias series (p. ej. una carpeta con más de un estudio), se usa la
  más numerosa y se avisa de las demás, en vez de mezclarlas o fallar.
- Separar correctamente imágenes en color (RGB) y archivos
  "multi-frame" (un único archivo con varios cortes dentro) -- esto es
  precisamente lo que causaba el error "too many values to unpack
  (expected 3, got 4)": un array de píxeles con una dimensión extra
  (color o frames) que se apilaba tal cual, sin separarlo primero.
- Calcular la posición real de cada corte proyectando
  ImagePositionPatient sobre la normal del plano de corte (derivada de
  ImageOrientationPatient), en vez de asumir que el eje Z del paciente
  coincide siempre con el orden de los archivos -- así también
  funciona con series oblicuas, sagitales o coronales de origen.
- Si falta información de posición/espaciado, no se descarta el
  archivo: se usa un fallback razonable (número de instancia, orden de
  archivo, grosor de corte) y se deja constancia en `Volume.warnings`.
- Soporte de paleta de color (PALETTE COLOR) y aviso claro (en vez de
  una excepción críptica) cuando un archivo usa una sintaxis de
  transferencia comprimida para la que falta un decodificador
  (pylibjpeg / gdcm).
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np
import pydicom


@dataclass
class Volume:
    array: np.ndarray          # shape (n_slices, rows, cols) -> (Z, Y, X)
    row_spacing: float         # mm entre filas (eje Y, dentro del plano)
    col_spacing: float         # mm entre columnas (eje X, dentro del plano)
    slice_spacing: float       # mm entre cortes (eje Z)
    file_paths: list[str]      # rutas de cada corte, en el mismo orden que el eje Z
    metadata: dict[str, str]   # info de paciente/estudio/serie, al estilo Slicer
    warnings: list[str] = field(default_factory=list)  # avisos no bloqueantes

    @property
    def shape(self):
        return self.array.shape  # (Z, Y, X)

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
        imagen, como en un visor radiológico normal -- si no, la vista
        sale boca abajo.
        """
        x = int(np.clip(x, 0, self.shape[2] - 1))
        return self.array[::-1, :, x]  # shape (Z, Y), Z invertido

    def coronal(self, y: int) -> np.ndarray:
        """
        Corte coronal (plano XZ) en la posición y. Filas=Z, columnas=X.
        Igual que en `sagittal`, se voltea el eje Z para que lo
        superior quede arriba.
        """
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
def _slice_normal(iop) -> np.ndarray:
    """
    Vector normal al plano de corte, a partir de ImageOrientationPatient
    (los dos vectores fila/columna del plano). Con esto la posición de
    cada corte se calcula correctamente aunque la serie no sea axial
    pura (oblicua, sagital o coronal de origen) -- así es como Slicer
    ordena los cortes internamente, en vez de asumir el eje Z.
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


def _pixel_spacing_of(ds) -> tuple[float, float] | None:
    """PixelSpacing, o ImagerPixelSpacing como alternativa habitual en CR/DX."""
    for tag in ("PixelSpacing", "ImagerPixelSpacing"):
        value = getattr(ds, tag, None)
        if value is not None and len(value) >= 2:
            try:
                return float(value[0]), float(value[1])
            except Exception:
                continue
    return None


def _maybe_apply_palette(ds, frame: np.ndarray) -> np.ndarray:
    """Si la imagen usa PALETTE COLOR (frecuente en algunos equipos), la
    convierte a RGB real antes de pasar a escala de grises."""
    photometric = str(getattr(ds, "PhotometricInterpretation", "")).upper()
    if photometric != "PALETTE COLOR":
        return frame
    try:
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


def _split_frames(pixels: np.ndarray) -> list[np.ndarray]:
    """
    Separa el array de píxeles de un dataset en una lista de frames 2D
    (o 2D+color, que luego se pasan a gris). Se basa en la FORMA real
    del array, no en la etiqueta NumberOfFrames (que puede faltar o no
    coincidir), evitando así apilar por error una dimensión de color o
    de multi-frame como si fuera parte de la imagen.
    """
    pixels = np.asarray(pixels)
    if pixels.ndim == 2:
        return [pixels]
    if pixels.ndim == 3:
        if pixels.shape[-1] in (3, 4):
            return [pixels]  # una sola imagen en color
        return [pixels[i] for i in range(pixels.shape[0])]  # pila de frames en gris
    if pixels.ndim == 4:
        return [pixels[i] for i in range(pixels.shape[0])]  # pila de frames en color
    return []  # forma no reconocida (poco común) -> se omite con aviso


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
    slice_thickness: float
    path: str


def _header_only(path: str):
    try:
        return pydicom.dcmread(path, stop_before_pixels=True, force=True)
    except Exception:
        return None


def _group_by_series(file_paths: list[str]):
    """Agrupa por SeriesInstanceUID sin decodificar los píxeles (rápido)."""
    groups: dict[str, list[str]] = defaultdict(list)
    headers: dict[str, "pydicom.Dataset"] = {}
    for path in file_paths:
        ds = _header_only(path)
        if ds is None:
            continue
        series_uid = getattr(ds, "SeriesInstanceUID", None) or "__sin_serie__"
        groups[series_uid].append(path)
        headers[path] = ds
    return groups, headers


def _frames_from_dataset(ds, path: str, warnings: list[str], base_order: int) -> list[_FrameRecord]:
    try:
        pixels = ds.pixel_array
    except Exception as exc:
        warnings.append(
            f"{os.path.basename(path)}: no se pudo decodificar la imagen ({exc}). "
            f"Si el archivo usa compresión JPEG2000/JPEG-LS/RLE, instala "
            f"'pylibjpeg' o 'python-gdcm' (ver requirements.txt)."
        )
        return []

    slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)

    spacing = _pixel_spacing_of(ds)
    if spacing is None:
        row_sp, col_sp = 1.0, 1.0
        warnings.append(
            f"{os.path.basename(path)}: sin PixelSpacing/ImagerPixelSpacing; se asume 1 mm."
        )
    else:
        row_sp, col_sp = spacing

    thickness = float(getattr(ds, "SliceThickness", 0.0) or 0.0)

    iop = getattr(ds, "ImageOrientationPatient", None)
    normal = _slice_normal(iop) if iop is not None and len(iop) == 6 else np.array([0.0, 0.0, 1.0])

    raw_frames = _split_frames(pixels)
    if not raw_frames:
        warnings.append(
            f"{os.path.basename(path)}: forma de píxel no reconocida {getattr(pixels, 'shape', '?')}; se omite."
        )
        return []

    per_frame_groups = getattr(ds, "PerFrameFunctionalGroupsSequence", None)
    base_ipp = getattr(ds, "ImagePositionPatient", None)

    inst = getattr(ds, "InstanceNumber", None)
    try:
        base_key = float(inst) * 100000 if inst is not None else float(base_order) * 100000
    except Exception:
        base_key = float(base_order) * 100000

    records: list[_FrameRecord] = []
    for idx, frame in enumerate(raw_frames):
        frame = _maybe_apply_palette(ds, frame)
        frame = _to_grayscale(frame)
        if frame.ndim != 2:
            warnings.append(
                f"{os.path.basename(path)} (frame {idx}): forma de píxel no soportada "
                f"{frame.shape}; se omite."
            )
            continue
        frame = frame.astype(np.float32) * slope + intercept

        ipp = None
        if per_frame_groups is not None and idx < len(per_frame_groups):
            try:
                plane_seq = per_frame_groups[idx].PlanePositionSequence
                ipp = [float(v) for v in plane_seq[0].ImagePositionPatient]
            except Exception:
                ipp = None
        if ipp is None and base_ipp is not None:
            try:
                ipp = [float(v) for v in base_ipp]
            except Exception:
                ipp = None

        position = None
        if ipp is not None and len(ipp) == 3:
            position = float(np.dot(normal, np.array(ipp, dtype=float)))

        records.append(_FrameRecord(
            array=frame,
            position=position,
            fallback_order=base_key + idx,
            row_spacing=row_sp,
            col_spacing=col_sp,
            slice_thickness=thickness,
            path=path,
        ))
    return records


def load_volume(file_paths: list[str]) -> Volume | None:
    """
    Lee una lista de archivos DICOM, los agrupa por serie, ordena los
    cortes espacialmente (o con el mejor fallback disponible) y
    construye un volumen 3D. Devuelve None solo si no se ha podido
    extraer ni un solo corte válido.
    """
    warnings: list[str] = []

    groups, headers = _group_by_series(file_paths)
    if not groups:
        return None

    if len(groups) > 1:
        chosen_uid, chosen_paths = max(groups.items(), key=lambda kv: len(kv[1]))
        omitted = sum(len(v) for k, v in groups.items() if k != chosen_uid)
        warnings.append(
            f"Se han detectado {len(groups)} series DICOM distintas en esta selección; "
            f"se muestra la más numerosa ({len(chosen_paths)} archivos) y se omiten "
            f"{omitted} archivo(s) de otra(s) serie(s)."
        )
    else:
        chosen_paths = next(iter(groups.values()))

    # Mantener el orden original de aparición como primer criterio estable.
    chosen_set = set(chosen_paths)
    chosen_paths = [p for p in file_paths if p in chosen_set]

    records: list[_FrameRecord] = []
    for i, path in enumerate(chosen_paths):
        try:
            ds_full = pydicom.dcmread(path, force=True)
        except Exception as exc:
            warnings.append(f"{os.path.basename(path)}: no se pudo leer ({exc}); se omite.")
            continue
        records.extend(_frames_from_dataset(ds_full, path, warnings, base_order=i))

    if not records:
        return None

    # Si hay cortes con dimensiones distintas al resto (recortes,
    # cambios de FOV a mitad de serie...), nos quedamos con el grupo
    # mayoritario en vez de fallar al apilar.
    shape_counts = Counter(r.array.shape for r in records)
    majority_shape, _ = shape_counts.most_common(1)[0]
    filtered = [r for r in records if r.array.shape == majority_shape]
    if len(filtered) < len(records):
        warnings.append(
            f"{len(records) - len(filtered)} corte(s) con dimensiones distintas al "
            f"resto de la serie se han omitido."
        )
    records = filtered
    if not records:
        return None

    has_all_positions = all(r.position is not None for r in records)
    if has_all_positions and len(records) > 1:
        records.sort(key=lambda r: r.position)
        diffs = np.diff([r.position for r in records])
        diffs = diffs[np.abs(diffs) > 1e-6]
        slice_spacing = float(np.median(np.abs(diffs))) if len(diffs) else (records[0].slice_thickness or 1.0)
    else:
        records.sort(key=lambda r: r.fallback_order)
        slice_spacing = records[0].slice_thickness or 1.0
        if not has_all_positions and len(records) > 1:
            warnings.append(
                "No se ha podido determinar la posición física de todos los cortes "
                "(falta ImagePositionPatient); se han ordenado por número de "
                "instancia/orden de archivo y se ha usado el grosor de corte como "
                "espaciado entre cortes."
            )
    if slice_spacing <= 0:
        slice_spacing = 1.0

    row_spacing = records[0].row_spacing or 1.0
    col_spacing = records[0].col_spacing or 1.0

    volume = np.stack([r.array for r in records], axis=0)  # (Z, Y, X), siempre 3D
    paths = [r.path for r in records]

    first_header = headers.get(chosen_paths[0]) if chosen_paths else None
    metadata = _extract_metadata(first_header, n_slices=volume.shape[0])

    return Volume(
        array=volume,
        row_spacing=row_spacing,
        col_spacing=col_spacing,
        slice_spacing=slice_spacing,
        file_paths=paths,
        metadata=metadata,
        warnings=warnings,
    )


# ----------------------------------------------------------------------
# Metadatos
# ----------------------------------------------------------------------
def _tag(ds, name: str, default: str = "—") -> str:
    try:
        value = getattr(ds, name, None)
        if value is None or value == "":
            return default
        return str(value)
    except Exception:
        return default


def _extract_metadata(ds, n_slices: int) -> dict[str, str]:
    """
    Recoge los campos que Slicer suele mostrar en su panel de
    información: identificación del paciente, del estudio y de la
    serie, y parámetros de adquisición.
    """
    if ds is None:
        return {"Nº de cortes": str(n_slices)}
    return {
        "Paciente": _tag(ds, "PatientName"),
        "ID paciente": _tag(ds, "PatientID"),
        "Sexo": _tag(ds, "PatientSex"),
        "Fecha nacimiento": _tag(ds, "PatientBirthDate"),
        "Fecha estudio": _tag(ds, "StudyDate"),
        "Descripción estudio": _tag(ds, "StudyDescription"),
        "Descripción serie": _tag(ds, "SeriesDescription"),
        "Nº serie": _tag(ds, "SeriesNumber"),
        "Modalidad": _tag(ds, "Modality"),
        "Fabricante": _tag(ds, "Manufacturer"),
        "Modelo": _tag(ds, "ManufacturerModelName"),
        "KVP": _tag(ds, "KVP"),
        "Nº de cortes": str(n_slices),
        "Institución": _tag(ds, "InstitutionName"),
    }
