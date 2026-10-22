# readme-cloude

Registro de cambios hechos con Claude en Vissium. Se amplía cada vez que se
modifica cualquier archivo del proyecto (lo más reciente, arriba).

## Estructura del proyecto (resumen)

Ver `README.md`. Rutas relevantes: raíz (`main.py`, `volume.py`, `file_types.py`,
`preview_window.py`, ...) y `viewers/` (`dicom_viewer.py`, `mesh_viewer.py`,
`image_viewer.py`).

## 2026-10-22 — Rediseño de la ventana 3D del CBCT, del botón Studio, del umbral y de la calavera

Archivos modificados: `theme.py`, `viewers/cbct_viewer.py`, `viewers/dicom_viewer.py`,
`viewers/studio_panel.py` (nuevo), `test_app.py`, `README.md`, `readme-cloude.md`.
Base: `master` (v2.1.2, ya con el CBCT 3D y Studio).

### Ventana 3D (viewers/cbct_viewer.py)
- Mismo diseño que las vistas MPR: caja negra con borde fino y esquinas de 10 px
  (`#cbctView` en `theme.py`), cabecera con el título "3D" y fondo de escena negro
  (antes casi negro y sin marco). El widget de VTK es nativo: se recorta solo por
  abajo (`_round_bottom_corners`). OJO: la máscara NO puede tener coordenadas
  negativas (en X11 recortaba la cabecera).
- Se maximiza como las demás: doble clic sobre el modelo o botón de la cabecera
  (señal `maximizeRequested`). `DicomViewer` mete la ventana en `_plane_positions`
  con la clave `"cbct"` (sustituye a `"info"` mientras el 3D está activo), así que
  `_toggle_maximize("cbct")` funciona igual que con axial/sagital/coronal.
  Al activar o desactivar el 3D con una vista maximizada, primero se restaura la rejilla.
- Umbral: ya no es un botón + deslizador sueltos. Es una **cápsula** en la cabecera
  (icono de regletas, "UMBRAL", deslizador con relleno degradado índigo y asa con aro,
  valor en una pastilla de tipografía monoespaciada). **Recogida por defecto** (queda
  un círculo con el icono de regletas); el botón la abre. Resolución del deslizador:
  10 000 pasos (`SLIDER_STEPS`, antes 1000), valor con un decimal.
- Umbral en vivo: la superficie se actualiza mientras se arrastra (temporizador de 0 ms,
  sin espera). Mientras se arrastra se usa una malla de media resolución y suavizado
  ligero (`SMOOTH_DRAG`); al soltar se recalcula a resolución completa. El coste estaba
  en los ~700k triángulos (normales ≈ 380 ms), no en el suavizado. Gradientes de
  FlyingEdges desactivados (no se usaban). Nombres conservados: `threshold_button`,
  `threshold_slider`, `threshold_value`. La lógica del umbral no cambia.
- Navegación igual que los STL (`_RotateZoomStyle`): clic derecho = girar, rueda = zoom,
  izquierdo y central = nada; el modelo nunca se desplaza y no hay atajos de VTK.

### Botón flotante y panel Studio (viewers/studio_panel.py, nuevo)
- `StudioLauncher`: botón **circular de 60 px** con el texto "Studio" abajo a la derecha
  (como el de un chat de ayuda en una web), con degradado, borde fino, borde índigo al
  pasar el ratón o con foco. Es el estado "minimizado".
- `StudioPanel`: ventana con el diseño de las celdas (fondo de tarjeta, línea fina,
  esquinas de 12 px), cabecera con "Studio" + nombre del paciente y botones minimizar /
  maximizar / volver a la vista del paciente. Dentro va el `_InfoPanel` (ahora sin caja
  doble: `set_flat(True)`). Al abrirlo desde el botón flotante es **alargado en vertical** (casi toda la altura
  del visor, hasta 780 px, 380 px de ancho) y puede tapar el botón del umbral: se
  minimiza para volver a verlo.
- Ambos son ventanas nativas (`WA_NativeWindow`) porque flotan sobre el widget nativo
  de VTK (antes quedaban restos de pintura). Se pintan a mano y se recortan con máscara.
- `DicomViewer`: `studio_launcher`, `studio` (StudioPanel), `_patient_name()`,
  `_layout_studio/_minimize_studio/_restore_studio/_maximize_studio` reescritos. Se
  conservan `studio_minimized`, `studio_maximized` y `set_cbct_3d_visible`.

### Iconos (theme.py)
- Calavera nueva (curvas suaves, órbitas rellenas, nariz y tres dientes); se ilumina
  con el acento cuando el botón "CBCT 3D" está activo. Nuevos: `patient`, `sliders`;
  nueva `icon_pixmap(nombre, color, tamaño)`.

### Pruebas
- `test_app.py`: 7 pruebas nuevas (botón flotante, abrir/maximizar/minimizar Studio y forma vertical,
  maximizar la ventana 3D, cápsula del umbral, umbral en vivo, navegación como el STL,
  apagar el 3D devuelve el panel a la rejilla). 19 pruebas en total con Qt real bajo Xvfb
  (`QT_QPA_PLATFORM=xcb xvfb-run pytest`); revisadas capturas reales de pantalla.
- No probado en Windows real (DPI/escalado, máscaras de ventanas nativas) ni con el
  .exe: reconstruir con `build.bat`. Sin cambios de versión: sube `version.py` al publicar.

## 2026-10-21 — Interfaz estilo Linear, dos STL en la misma vista y nueva navegación STL

Archivos modificados: `theme.py`, `preview_window.py`, `viewers/mesh_viewer.py`,
`viewers/dicom_viewer.py`, `viewers/image_viewer.py`, `test_app.py`, `README.md`,
`readme-cloude.md`.

### Estilo (referencia: Linear, captura enviada por Mario)
- Mismos colores (fondo casi negro, acento índigo `#7b86e8`, colores de plano). Se
  añaden `CARD` (`#131416`), líneas más claras (`LINE` `#2f3035`, `LINE_STRONG`
  `#45464c`), `RADIUS` (10) y `RADIUS_CARD` (12). Todo sigue en hexadecimal
  (`main.py` usa `QColor(LINE)` en el splash).
- La hoja de estilos hace los widgets TRANSPARENTES por defecto: el fondo lo ponen
  la ventana (`BG`), la tarjeta `#card` y cada celda. Si un widget nuevo sale sin
  fondo, darle uno explícito.
- `preview_window.py`: barra lateral de 150 px con el nombre de la app y botones de
  texto + icono ("Abrir carpeta", "Guías", "Restablecer"; antes eran solo iconos) y,
  a su derecha, una tarjeta redondeada con línea fina que contiene las pestañas (la
  activa en píldora) y las vistas. Las pestañas siguen arriba, en la cabecera de la
  tarjeta (no se pasaron a la barra lateral). Los botones conservan sus nombres
  (`btn_browser`, `btn_guides`, `btn_reset`) y ahora son `QPushButton`.
- DICOM: cada vista y el panel de información son cajas con borde de 1 px y
  esquinas de 10 px, separadas por 8 px (antes 1 px de hueco).
- Imágenes: el lienzo se recorta con esquinas redondeadas y borde fino.
- Nuevos iconos de línea: `layers`, `eye`, `eye-off`; nueva `theme.rounded_mask()`.

### Visor STL (viewers/mesh_viewer.py, reescrito)
- Botón **"Dos STL"** (píldora, arriba a la derecha): ofrece los demás STL abiertos
  en otras pestañas + "Examinar archivo…". Ya con dos modelos, el botón pasa a
  "Quitar el segundo". Máximo dos modelos por vista.
- Cada modelo con su color (gris claro y verde azulado). Los modelos conservan sus
  coordenadas originales (si vienen del mismo escáner quedan en su posición relativa
  real). Panel "Modelos" a la derecha: seleccionar, ocultar (ojo) y opacidad del
  seleccionado. El seleccionado lleva una caja índigo y sus estadísticas en la esquina.
- El título de la pestaña pasa a "A + B" (señal `titleChanged`); la ventana principal
  le da la lista de STL abiertos (`PreviewWindow._other_meshes`).
- **Navegación (pedida por Mario):** clic izquierdo = seleccionar el STL bajo el
  cursor (no mueve ni gira nada); clic derecho + arrastrar = GIRAR la vista; rueda =
  zoom; botón central = nada. "Mover la vista" significa girar: los modelos NUNCA se
  desplazan. Implementado en `_MeshStyle` (observadores de VTK); además se anulan los
  atajos de teclado de VTK (w = alambre, etc.).
- El widget de VTK es una ventana nativa: se recorta con `rounded_mask` (en el
  evento de redimensionado) y el borde lo dibuja `_MeshFrame`. El fondo de la escena
  pasa a negro (como las vistas DICOM).

### Pruebas
- `test_app.py`: 4 pruebas nuevas (dos STL y título de pestaña, STL abiertos
  ofrecidos para comparar, clic izquierdo selecciona / derecho gira / izquierdo y
  central no mueven la cámara, colores válidos). 12 pruebas en total, con Qt real
  bajo Xvfb (`QT_QPA_PLATFORM=xcb xvfb-run pytest`); revisadas también capturas de
  pantalla de DICOM, STL (uno y dos), imágenes, bienvenida y explorador manual.
- No probado en Windows real (DPI/escalado, barra de título) ni con el .exe:
  reconstruir con `build.bat`. Sin cambios de versión: sube `version.py` al publicar.

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

---

## Rediseño de interfaz y auditoría (rama `design-premium`, 2026-10-20)

Referencias usadas: `taste-skill` (criterio estético: sin emojis, acento escaso,
bordes de 1 px, sombras casi nulas), `awesome-design-md` (Linear/Raycast: superficies
casi negras, hairlines, un único acento) y `web-interface-guidelines` (auditoría:
foco visible, nombres accesibles, estados vacíos, "…" en vez de "...").
La guía de Vercel es de web: solo se aplicaron las reglas que tienen equivalente en Qt.

### theme.py
- Paleta nueva (`BG`, `LINE`, `LINE_STRONG`, `HOVER_BG`, `ACCENT`...); se mantienen los
  nombres anteriores, así que los visores no necesitan cambios.
- Acento `#7b86e8` solo para foco, pestaña activa y asa del deslizador con foco.
- Estados de foco (`:focus`) en botones de iconos, botones, campos, desplegables y deslizadores.
- Iconos de línea nuevos: `close`, `image`, `cube`, `loading`, `warning`.
- `tab_icon(nombre)` y `make_close_button(callback)` (el botón nativo de cierre salía como
  un cuadrado blanco/rojo con la hoja de estilos).
- Tipografía: Segoe UI Variable / Segoe UI, 12 px.

### preview_window.py
- Pestañas sin emojis (antes ⏳ 🖼 🧊): iconos de línea y "Cargando <nombre>…".
- Botón de cierre propio en cada pestaña (`_add_tab`).
- Pantalla de bienvenida (`_EmptyState`) cuando no hay pestañas; vuelve al cerrar la última.
- Nombres accesibles en los botones de la barra de iconos.

### viewers/dicom_viewer.py
- El encabezado de avisos pierde el símbolo ⚠ ("Avisos (n)").

### tests/ (nuevo)
- `conftest.py`: DICOM, CD con 2 series, STL y PNG sintéticos; entorno offscreen.
- `test_app.py`: abrir cada tipo, CD multi-serie en una pestaña, cierre de pestaña,
  pantalla de bienvenida, sin emojis en títulos, nombres accesibles.
- Ejecutar: `pip install pytest pytest-qt` y `python -m pytest tests -q`.

### Notas
- Playwright es para navegadores web, no controla una ventana PySide6; por eso las
  pruebas usan `pytest-qt` en modo offscreen y capturas con `widget.grab()`.
- No probado aquí (requiere Windows): barra espaciadora global, integración con el
  Explorador, bandeja, barra de título oscura y el renderizado 3D real de VTK con GPU.
- Sin cambios de versión: sube `version.py` al publicar.

---

## Corrección: error "Failed to load Python DLL" al actualizar (2026-10-20)

### updater.py
- Causa: el .bat de actualización se lanzaba desde el proceso en marcha y heredaba las
  variables de entorno de PyInstaller (`_MEIPASS2`, `_PYI_*`). El nuevo .exe intentaba
  reutilizar la carpeta temporal `_MEI…` del antiguo, ya borrada al cerrarse, y fallaba
  al cargar `python311.dll`.
- Solución: `clean_environment()` quita esas variables y activa
  `PYINSTALLER_RESET_ENVIRONMENT=1`; se usa en el `Popen` y también dentro del .bat.
  La espera antes de sustituir el .exe pasa de 2 a 3 s.
- Prueba nueva en `tests/test_app.py` (`test_update_environment_drops_pyinstaller_vars`).

### Notas
- La corrección solo se aplica desde la versión que la incluya: la actualización desde una
  versión anterior seguirá fallando una vez. Instala esa versión a mano la primera vez.
- No probado aquí (requiere Windows): el flujo real de actualización con el .exe empaquetado.
