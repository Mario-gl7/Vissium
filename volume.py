"""
Construye un volumen 3D (numpy) a partir de una serie DICOM y extrae
cortes en los tres planos ortogonales (axial, sagital, coronal),
respetando el espaciado físico real de cada eje (importante en CBCT,
donde el espaciado entre cortes suele ser mucho mayor que el espaciado
dentro del plano, y una vista sin corregir el aspecto sale "aplastada").
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pydicom


@dataclass
class Volume:
    array: np.ndarray          # shape (n_slices, rows, cols) -> (Z, Y, X)
    row_spacing: float         # mm entre filas (eje Y, dentro del plano)
    col_spacing: float         # mm entre columnas (eje X, dentro del plano)
    slice_spacing: float       # mm entre cortes (eje Z)
    file_paths: list[str]      # rutas de cada corte, en el mismo orden que el eje Z

    @property
    def shape(self):
        return self.array.shape  # (Z, Y, X)

    # -- Extracción de cortes MPR -------------------------------------
    def axial(self, z: int) -> np.ndarray:
        """Corte axial (plano XY) en la posición z. Tamaño físico: X*col x Y*row."""
        z = int(np.clip(z, 0, self.shape[0] - 1))
        return self.array[z, :, :]

    def sagittal(self, x: int) -> np.ndarray:
        """Corte sagital (plano YZ) en la posición x. Filas=Z, columnas=Y."""
        x = int(np.clip(x, 0, self.shape[2] - 1))
        return self.array[:, :, x]  # shape (Z, Y)

    def coronal(self, y: int) -> np.ndarray:
        """Corte coronal (plano XZ) en la posición y. Filas=Z, columnas=X."""
        y = int(np.clip(y, 0, self.shape[1] - 1))
        return self.array[:, y, :]  # shape (Z, X)

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


def load_volume(file_paths: list[str]) -> Volume | None:
    """
    Lee una lista de archivos DICOM (de la misma serie), los ordena
    espacialmente y construye un volumen 3D. Devuelve None si no hay
    suficientes cortes válidos o si sus dimensiones no son compatibles.
    """
    entries = []  # (position, array, path, row_spacing, col_spacing, slice_thickness)
    for path in file_paths:
        try:
            ds = pydicom.dcmread(path, force=True)
            if not hasattr(ds, "pixel_array"):
                continue
            arr = ds.pixel_array.astype(np.float32)
            slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
            intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
            arr = arr * slope + intercept

            row_sp, col_sp = 1.0, 1.0
            if hasattr(ds, "PixelSpacing"):
                try:
                    row_sp, col_sp = float(ds.PixelSpacing[0]), float(ds.PixelSpacing[1])
                except Exception:
                    pass

            position = None
            if hasattr(ds, "ImagePositionPatient"):
                try:
                    position = float(ds.ImagePositionPatient[2])
                except Exception:
                    position = None
            if position is None and hasattr(ds, "InstanceNumber"):
                try:
                    position = float(ds.InstanceNumber)
                except Exception:
                    position = None
            if position is None:
                position = float(len(entries))

            thickness = float(getattr(ds, "SliceThickness", 0.0) or 0.0)

            entries.append((position, arr, path, row_sp, col_sp, thickness))
        except Exception:
            continue

    if len(entries) < 1:
        return None

    entries.sort(key=lambda e: e[0])

    # Todas las imágenes deben tener las mismas dimensiones para apilarlas.
    base_shape = entries[0][1].shape
    entries = [e for e in entries if e[1].shape == base_shape]
    if not entries:
        return None

    positions = [e[0] for e in entries]
    arrays = [e[1] for e in entries]
    paths = [e[2] for e in entries]
    row_spacing = entries[0][3]
    col_spacing = entries[0][4]

    if len(entries) > 1:
        diffs = np.diff(positions)
        diffs = diffs[diffs > 1e-6]
        slice_spacing = float(np.median(diffs)) if len(diffs) else 1.0
    else:
        slice_spacing = entries[0][5] or 1.0
    if slice_spacing <= 0:
        slice_spacing = entries[0][5] or 1.0

    volume = np.stack(arrays, axis=0)  # (Z, Y, X)
    return Volume(
        array=volume,
        row_spacing=row_spacing or 1.0,
        col_spacing=col_spacing or 1.0,
        slice_spacing=slice_spacing or 1.0,
        file_paths=paths,
    )
