# FastLook

Visor local y offline de **DICOM** (con las tres vistas MPR: axial,
sagital y coronal) y mallas **STL/PLY**, que se ejecuta en segundo
plano e integrado con el **Explorador de Windows**: seleccionas un
archivo o carpeta en el Explorador normal de Windows y pulsas la
**barra espaciadora** para abrir una vista previa, sin necesidad de
tener FastLook abierto — al estilo "Quick Look" de macOS.

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

Al arrancar no aparece ninguna ventana: FastLook se queda como un
icono **"FL"** en la bandeja del sistema (junto al reloj), escuchando
en segundo plano.

## Uso

1. Abre el Explorador de Windows con normalidad y navega hasta una
   carpeta con una serie DICOM, un archivo DICOM suelto, o un archivo
   `.stl`/`.ply`.
2. Selecciona el archivo o la carpeta y pulsa **Espacio**.
3. Se abre (o se trae al frente, si ya estaba abierta) la ventana de
   FastLook con una pestaña nueva para esa previsualización:
   - **DICOM**: se muestran las tres vistas ortogonales — axial,
     sagital y coronal — cada una con su propio slider para recorrer
     los cortes, más controles de ventana/nivel (brillo/contraste)
     compartidos entre las tres. El espaciado físico real de cada eje
     se respeta (importante en CBCT, donde el espaciado entre cortes
     suele ser mucho mayor que dentro del plano: sin esto, las vistas
     sagital/coronal saldrían distorsionadas).
   - **STL/PLY**: modelo 3D interactivo (arrastra para rotar, rueda
     para zoom).
4. Volver a pulsar Espacio sobre algo ya abierto simplemente cambia a
   esa pestaña, sin duplicarla.
5. Cerrar la ventana de FastLook (la "x") NO cierra la aplicación:
   sigue activa en la bandeja. Para cerrarla de verdad, usa "Salir de
   FastLook" en el menú de la bandeja (clic derecho sobre el icono).

### Modo de respaldo (explorador manual)

Si por lo que sea la integración con el Explorador de Windows no
funciona en tu equipo (ver limitaciones más abajo), desde el menú de
la bandeja hay una opción **"Abrir explorador manual (modo
respaldo)"**: abre la ventana de FastLook con su propio árbol de
carpetas, donde la barra espaciadora funciona igual pero sin depender
del Explorador de Windows.

## Arrancar automáticamente con Windows (opcional)

Para que FastLook se inicie solo al arrancar Windows:

1. Pulsa `Win + R`, escribe `shell:startup` y pulsa Enter (se abre la
   carpeta de inicio de tu usuario).
2. Crea un acceso directo ahí que apunte a:
   `ruta\a\fastlook\venv\Scripts\pythonw.exe` con el argumento
   `ruta\a\fastlook\main.py` (usa `pythonw.exe`, no `python.exe`, para
   que no se abra ninguna ventana de consola).

## Estructura del proyecto

```
fastlook/
  main.py                    Punto de entrada: arranca la bandeja y el hook de teclado
  preview_window.py          Ventana de pestañas con las previsualizaciones (oculta hasta que se necesita)
  tray.py                    Icono y menú de la bandeja del sistema
  explorer_integration.py    Obtiene la selección activa del Explorador de Windows (COM)
  hotkey_listener.py         Hook global de la barra espaciadora, filtrado al Explorador
  file_browser.py            Explorador de archivos propio (solo para el modo de respaldo)
  file_types.py              Detección de tipo: serie DICOM / DICOM suelto / STL / PLY
  volume.py                  Reconstrucción del volumen 3D y extracción de cortes MPR
  viewers/
    dicom_viewer.py            Visor MPR (axial + sagital + coronal)
    mesh_viewer.py              Visor 3D de STL/PLY (VTK)
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
  contextual del botón derecho ("Vista previa con FastLook") mediante
  el Registro de Windows, que no depende de hooks de teclado. Si te
  interesa, lo añadimos en otra iteración.
- El resto de la lógica (clasificación de archivos, reconstrucción
  MPR con corrección de aspecto físico, visor de mallas VTK, gestión
  de pestañas) sí se ha probado de extremo a extremo con datos
  sintéticos.
