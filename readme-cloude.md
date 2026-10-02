# readme-cloude

Registro de cambios hechos con Claude en Vissium. Se amplía cada vez que se
modifica cualquier archivo del proyecto (lo más reciente, arriba).

## Estructura del proyecto (resumen)

Ver `README.md`. Rutas relevantes: raíz (`main.py`, `volume.py`, `file_types.py`,
`preview_window.py`, ...) y `viewers/` (`dicom_viewer.py`, `mesh_viewer.py`).

## 2026-10-01 — Lector DICOM mucho más potente ("leer cualquier DICOM")

Archivos modificados: `volume.py`, `file_types.py`, `viewers/dicom_viewer.py`,
`requirements.txt`, `vissium.spec`, `readme-cloude.md` (nuevo).

### volume.py
- Decodificación con cadena de respaldos: decodificador por defecto, GDCM,
  pylibjpeg, Pillow, pyjpegls, openjpeg, libjpeg, RLE. Para datos sin
  comprimir, lectura directa como último recurso (rellena con ceros si los
  píxeles están truncados y avisa).
- Archivos sin cabecera Part-10 / sin TransferSyntaxUID: se deduce la sintaxis.
- Float Pixel Data y Double Float Pixel Data (mapas paramétricos).
- Multi-frame Enhanced: PixelSpacing, orientación, posición, grosor y
  RescaleSlope/Intercept también desde grupos funcionales compartidos/por frame.
  Un multi-frame sin posición por frame ya no pierde cortes.
- MONOCHROME1 invertido; PALETTE COLOR y color a gris; Modality LUT Sequence.
- Enmascarado de bits no usados (BitsStored < BitsAllocated).
- Se ignoran DICOM sin imagen (SR, RT, PR...). La serie por defecto es la que
  más imágenes tiene (cuenta los frames) y evita localizadores.
- Cortes con orientación distinta: se queda el grupo mayoritario (aviso).
- Series 4D/multifase: se muestra la primera fase (aviso) en vez de apilar
  posiciones repetidas. Aviso si el espaciado entre cortes no es uniforme.
- Fallback de posición con SliceLocation; SpacingBetweenSlices antes que el grosor.
- Lectura de cabeceras en paralelo. Enteros de 32 bits se reducen a 16 si caben.
- Ventana/nivel por defecto desde las etiquetas (`Volume.window_center/width`).
- NUEVO: `load_volume` lanza `DicomLoadError` con el motivo cuando no hay nada
  que mostrar (antes devolvía `None`). `Volume.is_single_image`, `Volume.modality`.
  `SeriesInfo.n_images`, `SeriesInfo.localizer`.

### file_types.py
- DICOM con cualquier extensión o sin ella (IM0001, I10...), con filtro rápido
  de 2 bytes + comprobación de Rows/Columns; descarte por extensión de formatos
  que no son DICOM.
- Búsqueda en subcarpetas: 3 niveles y hasta 500 carpetas (antes 2 y 300).
- Archivo suelto con marca DICM sin imagen: se acepta y el visor explica el motivo.

### viewers/dicom_viewer.py
- Imágenes 2D (radiografía, panorámica, ecografía): vista única grande + panel
  de información (sin sagital/coronal vacíos, sin barra de cortes ni guías).
- Ventana/nivel inicial desde las etiquetas DICOM si son coherentes con los datos.
- Si falla la lectura se muestra el motivo real (también al cambiar de serie).
- La señal `_SeriesLoader.loaded` ahora lleva un tercer argumento (mensaje de error).

### requirements.txt / vissium.spec
- Añadido `pylibjpeg-rle` (RLE).
- El .exe incluye todos los submódulos de `pydicom` (en pydicom 3 los
  decodificadores se cargan dinámicamente y PyInstaller no los detectaba).

### Notas
- Probado con datos sintéticos: serie CT sin extensión con reescalado, MONOCHROME1,
  DICOM sin preámbulo, RLE comprimido, Enhanced multi-frame, SR sin imagen,
  píxeles truncados, serie bifásica y el visor en modo 2D/MPR (Qt offscreen).
- No probado: JPEG2000/JPEG-LS reales, ni el .exe empaquetado (reconstruir con `build.bat`).
- Sin cambios de versión: sube `version.py` al publicar.
