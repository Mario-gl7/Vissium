# readme-cloude

Registro de cambios hechos con Claude en Vissium. Se amplía cada vez que se
modifica cualquier archivo del proyecto (lo más reciente, arriba).

## Estructura del proyecto (resumen)

Ver `README.md`. Rutas relevantes: raíz (`main.py`, `volume.py`, `file_types.py`,
`preview_window.py`, ...) y `viewers/` (`dicom_viewer.py`, `mesh_viewer.py`,
`image_viewer.py`).

## 2026-10-13 — Series que no se detectaban, avisos junto a la info, más datos del CBCT e imágenes

Archivos modificados: `file_types.py`, `volume.py`, `viewers/dicom_viewer.py`,
`preview_window.py`, `viewers/image_viewer.py` (nuevo), `README.md`,
`readme-cloude.md`.

### Por qué a veces no se detectaban series (file_types.py / volume.py)
- Solo se exploraban 3 niveles de subcarpetas y se paraba en el primer nivel con
  algo. Las exportaciones tipo CD/PACS (`DICOM/PAT/STD/SER/IMG`) tienen los
  archivos a 4+ niveles: el código antiguo devolvía "no se reconoce" (comprobado
  con datos sintéticos). Ahora hasta 8 niveles.
- Con subcarpetas solo se usaba la subcarpeta con MÁS archivos y se perdía el
  resto de series. Ahora se reúnen los DICOM de toda la carpeta y subcarpetas, y
  `load_volume` los agrupa por SeriesInstanceUID: el selector muestra todas.
- Un DICOM suelto solo cargaba los de su misma serie. Ahora carga todos los de su
  carpeta y abre la suya (`Classification.preferred_uid`). Si esa carpeta ya está
  abierta en una pestaña, se cambia a esa serie en la misma pestaña
  (`DicomViewer.select_series_uid`).
- Archivos repetidos (mismo SOPInstanceUID, p. ej. copia en `backup/`) se
  descartan y se avisa; antes se tomaban por una serie 4D.
- Archivos sin SeriesInstanceUID: se agrupan por nº de serie y tamaño (antes todos
  en una única serie).
- Series de estudios/pacientes distintos: el selector antepone paciente y fecha.
- La firma de carpeta de `preview_window._signature` mira ahora nº de elementos y
  fecha más reciente del contenido directo (antes solo la fecha de la carpeta, y
  podía enseñar una pestaña con series antiguas).
- Límites de búsqueda (2000 carpetas, 30000 archivos, 20 s): si se alcanzan, se
  avisa en el panel en vez de cortar en silencio.
- Nuevo `file_types.classify_detailed()` (devuelve `Classification`);
  `classify_path()` se conserva como envoltorio.
- `load_volume(..., scan_warnings=...)`; nuevo `Volume.scan_warnings`;
  `SeriesInfo` guarda paciente, estudio y cabecera.

### Panel de información del visor DICOM (viewers/dicom_viewer.py)
- Los avisos ya se ven dentro del panel (bajo el selector de serie), no solo en
  un tooltip.
- Más datos, agrupados y con scroll: Paciente (nombre, ID, sexo, nacimiento,
  edad), Estudio (fecha/hora, descripción, ID, nº de acceso, UID, institución),
  Serie (nº de serie, descripción, UID de serie, modalidad, parte del cuerpo,
  protocolo, tipo de imagen), Imagen (tamaño, espaciado, campo de visión
  calculado, cortes, grosor, bits, compresión) y Equipo (fabricante, modelo,
  software, estación, kVp, mA, exposición). Los campos vacíos se ocultan.
- Doble clic sobre un valor lo copia al portapapeles (útil para los UID).
- Esto amplía la decisión del 2026-10-01 ("solo paciente, fecha, tamaño,
  espaciado y cortes"), a petición de Mario.

### Imágenes (viewers/image_viewer.py, file_types.py, preview_window.py)
- Nuevo visor para png, jpg/jpeg/jpe/jfif, bmp, gif (1.er fotograma), tif/tiff,
  webp e ico, con orientación EXIF.
- Rueda = zoom hacia el cursor; arrastrar = desplazar; doble clic = ajustar /
  100 %; flechas = imagen anterior/siguiente de la carpeta; `0`/`F` ajustar, `1`
  100 %, `+`/`-` zoom. Botón "restablecer vista" de la barra = ajustar.
- Una imagen suelta se abre con las demás de su carpeta; varias imágenes
  seleccionadas a la vez → una sola pestaña. Una carpeta solo con imágenes también
  abre el visor. Prioridad de carpeta: DICOM > mallas > imágenes.
- La primera imagen se lee en el hilo de carga (no congela la interfaz).

### Notas
- Probado con datos sintéticos (exportación tipo CD a 5 niveles, series mezcladas
  con copia duplicada, DICOM suelto, fotos PNG/JPG, imagen corrupta) y con Qt sin
  pantalla. No probado en Windows real ni con el .exe: reconstruir con `build.bat`.
- Sin cambios de versión: sube `version.py` al publicar.
- `vissium.spec`/`requirements.txt` sin cambios (los formatos de imagen vienen en
  los plugins de Qt de PySide6).

## 2026-10-02 — Splash con el icono anterior; icono nuevo solo dentro de la app

Archivos modificados: `theme.py`, `assets/vissium_icon.png` y
`assets/vissium_icon.ico` (nuevos), `readme-cloude.md`.

- El icono nuevo (cráneo en círculo con rayos) pasa a llamarse
  `assets/vissium_icon.*` y NO sustituye a `assets/icon.png|ico`.
- `theme.app_icon()` carga `vissium_icon.ico|png` (con respaldo a `icon.*`) y se
  usa solo en el icono de la ventana y en las pestañas de DICOM.
- El splash (`main.py`) sigue cargando `assets/icon.png|ico`, es decir, el
  icono anterior. Mantiene el lienzo oscuro con el texto debajo (sin solaparse).
- Bandeja (`tray.py`) y .exe (`vissium.spec`) siguen con `assets/icon.ico`
  (el anterior). Si se quiere el nuevo ahí, apuntar a `vissium_icon.ico`.
- Corrección: en la entrada anterior se habían nombrado los iconos nuevos
  `icon.png|ico`; no copiar esos nombres sobre los del proyecto.

## 2026-10-01 (2) — Splash, zoom inicial de DICOM e icono de la app

Archivos modificados: `main.py`, `theme.py`, `preview_window.py`,
`viewers/dicom_viewer.py` (incluye también los cambios de la entrada anterior),
`assets/icon.png` y `assets/icon.ico` (nuevos, generados desde el PNG que
envió Mario: recortado al contenido, cuadrado, fondo transparente; el .ico
lleva 16/20/24/32/40/48/64/128/256 px).

- **Splash (main.py):** el texto "Iniciando Vissium…" se dibujaba encima del
  icono. Ahora el splash es un lienzo oscuro de 300x340 con el icono arriba y
  una franja libre abajo para el texto. Además, `preview_window` (que importa
  VTK/pydicom y tarda) se importa DESPUÉS de mostrar el splash; antes se
  importaba al principio del archivo, así que el splash salía tarde, ya
  caducado o no llegaba a verse. El splash lleva `WindowStaysOnTopHint` y los
  1,5 s mínimos (`SPLASH_MIN_MS`) se cuentan desde que aparece.
- **Zoom inicial del DICOM (dicom_viewer.py):** la primera imagen se escalaba
  con el tamaño provisional del panel (aún sin layout) y salía pequeña hasta
  mover la rueda. Ahora `_ImageView` emite `resized` y cada vista se vuelve a
  pintar cuando su panel recibe su tamaño real; además hay un repintado tras
  el primer `showEvent`. Se quita el repintado redundante de
  `DicomViewer.resizeEvent`.
- **Icono:** `theme.app_icon()` carga `assets/icon.ico|png`. Se usa en el
  icono de la ventana (`setWindowIcon` en la ventana y en la app), en las
  pestañas de DICOM (sustituye al emoji 🩻; `tabs.setIconSize(20x20)`) y, como
  ya hacía, en la bandeja y el .exe (`vissium.spec` ya apunta a
  `assets/icon.ico`). Las pestañas de STL/PLY siguen con 🧊.
- **Notas:** el zoom se reprodujo en pruebas con Qt sin pantalla y queda
  corregido; el splash se revisó renderizado a imagen. No probado en Windows
  real (DPI/escalado) ni con el .exe: reconstruir con `build.bat`.

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
