# Vissium

Visor local y offline de **DICOM** (con las tres vistas MPR: axial,
sagital y coronal) y mallas **STL/PLY**, que se ejecuta en segundo
plano e integrado con el **Explorador de Windows**: seleccionas un
archivo o carpeta en el Explorador normal de Windows y pulsas la
**barra espaciadora** para abrir una vista previa, sin necesidad de
tener Vissium abierto — al estilo "Quick Look" de macOS.

> Vissium se llamaba antes **FastLook**; el repositorio de GitHub
> conserva ese nombre por ahora (`Mario-gl7/FastLook`) — si lo
> renombras en GitHub, actualiza `GITHUB_REPO` en `version.py`.

## Instalación (Windows)

1. Instala Python 3.10 o superior (marca "Add python.exe to PATH" al
   instalar).
2. Abre PowerShell o CMD en esta carpeta y ejecuta:

   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Ejecutar

```
venv\Scripts\activate
python main.py
```

Al arrancar no aparece ninguna ventana: Vissium se queda como un
icono en la bandeja del sistema (junto al reloj), escuchando en
segundo plano.

## Uso

1. Abre el Explorador de Windows con normalidad y navega hasta una
   carpeta con una serie DICOM, un archivo DICOM suelto, un archivo
   `.stl`/`.ply` o una imagen (`.png`, `.jpg`, ...).
2. Selecciona el archivo o la carpeta y pulsa **Espacio**.
3. Se abre (o se trae al frente, si ya estaba abierta) la ventana de
   Vissium con una pestaña nueva para esa previsualización:
   - **DICOM**: se muestran las tres vistas ortogonales — axial,
     sagital y coronal — cada una con su barra de desplazamiento para
     recorrer los cortes. La cuarta celda de la rejilla es el panel de
     información: selector de **serie** (si la selección contiene
     varias, se elige cuál ver; se detectan también las de subcarpetas
     y, al abrir un DICOM suelto, todas las de su carpeta), los **avisos**
     de lectura, controles de ventana/nivel (brillo/contraste,
     compartidos entre las tres vistas) y los datos del estudio con
     scroll: paciente, estudio (nº de acceso), serie (nº y UID de
     referencia), imagen y equipo (doble clic sobre un valor lo copia). El espaciado físico real de cada eje
     se respeta (importante en CBCT, donde el espaciado entre cortes
     suele ser mucho mayor que dentro del plano: sin esto, las vistas
     sagital/coronal saldrían distorsionadas).
   - **STL/PLY**: modelo 3D sólido interactivo (arrastra para rotar,
     rueda para zoom), con sus estadísticas (vértices, triángulos,
     tamaño) superpuestas en la esquina.
   - **Imágenes** (PNG, JPG, BMP, GIF, TIFF, WEBP, ICO): se ajustan a
     la ventana; rueda = zoom, arrastrar = desplazar, doble clic =
     ajustar/100 %, flechas = imagen anterior/siguiente de la carpeta.
4. La barra de iconos de la izquierda actúa sobre la pestaña activa:
   explorador manual, mostrar/ocultar las guías de cruce (DICOM) y
   restablecer la vista (zoom/pan en DICOM, cámara en STL/PLY).
5. Volver a pulsar Espacio sobre algo ya abierto simplemente cambia a
   esa pestaña, sin duplicarla.
6. Cerrar la ventana de Vissium (la "x") NO cierra la aplicación:
   sigue activa en la bandeja. Para cerrarla de verdad, usa "Salir de
   Vissium" en el menú de la bandeja (clic derecho sobre el icono).

### Modo de respaldo (explorador manual)

Si por lo que sea la integración con el Explorador de Windows no
funciona en tu equipo (ver limitaciones más abajo), desde el menú de
la bandeja hay una opción **"Abrir explorador manual (modo
respaldo)"**: abre la ventana de Vissium con su propio árbol de
carpetas, donde la barra espaciadora funciona igual pero sin depender
del Explorador de Windows.

## Arrancar automáticamente con Windows (opcional)

Para que Vissium se inicie solo al arrancar Windows:

1. Pulsa `Win + R`, escribe `shell:startup` y pulsa Enter (se abre la
   carpeta de inicio de tu usuario).
2. Crea un acceso directo ahí que apunte a:
   `ruta\a\fastlook\venv\Scripts\pythonw.exe` con el argumento
   `ruta\a\fastlook\main.py` (usa `pythonw.exe`, no `python.exe`, para
   que no se abra ninguna ventana de consola).

## Compilar el ejecutable (.exe)

Vissium se distribuye como un único `.exe` de Windows (generado con
PyInstaller), con el icono de la app y sin ventana de consola.

**En Windows, manualmente:**

```
venv\Scripts\activate
build.bat
```

El resultado queda en `dist\Vissium.exe`.

**Automáticamente en GitHub (recomendado):** el workflow
`.github/workflows/release.yml` compila el `.exe` en un runner de
Windows y lo publica como Release cada vez que se sube un tag de
versión. Ver la siguiente sección.

## Ramas y publicación de versiones

- **`testing`**: rama de trabajo/pruebas. Aquí se hacen los cambios
  del día a día.
- **`master`**: rama estable. Solo se actualiza fusionando (`merge`)
  desde `testing` cuando algo está listo para publicarse.

Para sacar una versión nueva:

1. Sube el número en `version.py` (`__version__`).
2. Haz merge de `testing` a `master`.
3. Sobre `master`, crea y sube un tag con el mismo número (con
   prefijo `v`):

   ```
   git checkout master
   git pull
   git tag v1.1.0
   git push origin v1.1.0
   ```

4. El workflow de GitHub Actions compila `Vissium.exe` y crea
   automáticamente un Release con el `.exe` adjunto.

## Actualizaciones automáticas

Vissium comprueba en segundo plano, al arrancar (y también a mano
desde "Buscar actualizaciones…" en el menú de la bandeja), si hay una
versión más nueva publicada en GitHub Releases. Como los Releases
solo se crean sobre `master` (nunca sobre `testing`), la app nunca
detecta como "actualización" un cambio que todavía esté en pruebas —
solo lo que ya se ha liberado.

Si hay una versión nueva, se ofrece actualizar; al confirmar, se
descarga el `.exe` nuevo y se sustituye automáticamente el que está
en ejecución, reiniciando la app. Esto solo funciona con la app
instalada como `.exe` en Windows (no en modo "código fuente" con
`python main.py`, donde solo se avisa de que hay versión nueva).

## Estructura del proyecto

```
vissium/
  main.py                    Punto de entrada: arranca la bandeja, el hook de teclado y el chequeo de actualizaciones
  version.py                 Número de versión, nombre de la app y repo de GitHub (única fuente de verdad)
  updater.py                 Comprueba GitHub Releases y aplica la actualización sustituyendo el .exe
  paths.py                   Resolución de rutas a recursos, válida en fuente y en el .exe empaquetado
  preview_window.py          Ventana de pestañas con las previsualizaciones (oculta hasta que se necesita)
  tray.py                    Icono y menú de la bandeja del sistema
  explorer_integration.py    Obtiene la selección activa del Explorador de Windows (COM)
  hotkey_listener.py         Hook global de la barra espaciadora, filtrado al Explorador
  file_browser.py            Explorador de archivos propio (solo para el modo de respaldo)
  file_types.py              Detección de tipo: serie DICOM / DICOM suelto / STL / PLY / imagen
  volume.py                  Reconstrucción del volumen 3D, listado de series y extracción de cortes MPR
  theme.py                   Tema oscuro minimalista: colores, hoja de estilos e iconos de la barra lateral
  viewers/
    dicom_viewer.py            Visor MPR (axial + sagital + coronal) con panel de información y selector de series
    mesh_viewer.py              Visor 3D sólido de STL/PLY (VTK)
    image_viewer.py             Visor de imágenes (PNG, JPG, ...) con zoom, desplazamiento y navegación
  assets/
    icon.ico / icon.png        Icono de la app (bandeja del sistema y .exe)
  vissium.spec                Configuración de PyInstaller para compilar el .exe
  build.bat                   Script para compilar el .exe a mano en Windows
  .github/workflows/release.yml  CI: compila y publica el .exe al subir un tag de versión
  requirements.txt
```

## Limitaciones y notas técnicas importantes

- **La integración con el Explorador de Windows solo funciona en
  Windows** (usa `pywin32` para leer la selección vía COM, y
  `keyboard` para el hook global de teclado). La lógica de la
  aplicación (reconstrucción MPR, gestión de pestañas, icono de
  bandeja) se ha desarrollado y probado en un entorno Linux sin
  acceso a esas APIs de Windows, así que te recomiendo probar
  `explorer_integration.py` y `hotkey_listener.py` con calma la
  primera vez en tu equipo; si algo no engancha bien con tu versión
  de Windows, dímelo con el mensaje de error y lo ajustamos.
- El hook global de teclado (`keyboard`) instala un gancho a nivel de
  sistema operativo; en algunos equipos puede requerir ejecutar la
  aplicación **como administrador** para funcionar. Si Espacio no
  hace nada, prueba a abrir la terminal como administrador y ejecutar
  `python main.py` desde ahí.
- La detección de "¿la ventana activa es el Explorador?" se basa en
  la clase de ventana (`CabinetWClass`); el **escritorio de Windows**
  no se trata como una ventana de Explorador, así que de momento la
  barra espaciadora sobre iconos del escritorio no dispara la
  previsualización (solo dentro de carpetas abiertas).
- Como alternativa más robusta al hook global (si en tu equipo da
  problemas), una mejora natural sería añadir una entrada al menú
  contextual del botón derecho ("Vista previa con Vissium") mediante
  el Registro de Windows, que no depende de hooks de teclado. Si te
  interesa, lo añadimos en otra iteración.
- El resto de la lógica (clasificación de archivos, reconstrucción
  MPR con corrección de aspecto físico, visor de mallas VTK, gestión
  de pestañas) sí se ha probado de extremo a extremo con datos
  sintéticos.
