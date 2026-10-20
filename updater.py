"""
Comprobación y aplicación de actualizaciones de Vissium vía GitHub
Releases.

Cómo funciona el flujo de versiones (master = estable, testing = en
pruebas):

    - El desarrollo del día a día ocurre en la rama `testing`.
    - Cuando algo de `testing` está listo para publicarse, se
      fusiona ("merge") a `master`.
    - En ese momento se crea en GitHub un Release con tag `vX.Y.Z`
      sobre `master`. El workflow de CI (.github/workflows/release.yml)
      compila el .exe de Windows y lo adjunta a ese Release.
    - `releases/latest` en la API de GitHub siempre devuelve el
      último Release NO marcado como borrador ni como "pre-release" —
      es decir, siempre el de `master`, nunca commits sueltos de
      `testing` que aún no se hayan publicado. Por eso no hace falta
      leer las ramas directamente: basta con mirar el último Release.

Este módulo:
    1. Consulta `GET /repos/{GITHUB_REPO}/releases/latest`.
    2. Compara esa versión con `version.__version__`.
    3. Si hay una versión más nueva, localiza el asset .exe adjunto
       y lo descarga.
    4. Aplica la actualización sustituyendo el ejecutable en marcha
       por el nuevo y reiniciando la app (solo tiene sentido cuando
       se ejecuta como .exe empaquetado con PyInstaller; en modo
       "código fuente" solo se informa de que hay una versión nueva).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from paths import app_dir
from version import GITHUB_REPO, __version__

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT = 10  # segundos


@dataclass
class UpdateInfo:
    version: str          # p. ej. "1.1.0" (sin la "v")
    tag: str              # p. ej. "v1.1.0"
    notes: str            # cuerpo del Release (changelog)
    download_url: str     # URL directa del asset .exe
    asset_name: str


def _parse_version(text: str) -> tuple[int, ...]:
    text = text.strip().lstrip("vV")
    parts = []
    for chunk in text.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote_version: str, local_version: str = __version__) -> bool:
    return _parse_version(remote_version) > _parse_version(local_version)


def check_for_update() -> Optional[UpdateInfo]:
    """
    Devuelve un UpdateInfo si hay una versión más nueva publicada en
    GitHub, o None si ya se está en la última versión (o si la
    comprobación falla, p. ej. sin conexión: no se interrumpe la app
    por esto).
    """
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Vissium-Updater",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None

    tag = data.get("tag_name", "")
    remote_version = tag.lstrip("vV")
    if not tag or not is_newer(remote_version):
        return None

    asset = next(
        (a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")),
        None,
    )
    if asset is None:
        # Hay Release nuevo pero sin .exe adjunto (p. ej. aún compilando en CI).
        return None

    return UpdateInfo(
        version=remote_version,
        tag=tag,
        notes=data.get("body", "") or "",
        download_url=asset["browser_download_url"],
        asset_name=asset["name"],
    )


# Variables que PyInstaller (modo un solo archivo) deja en el entorno del proceso en marcha.
# Si el nuevo .exe las hereda, intenta reutilizar la carpeta temporal `_MEI…` del
# antiguo, que se borra al cerrarse, y falla con "Failed to load Python DLL".
_PYINSTALLER_ENV_VARS = (
    "_MEIPASS2",
    "_PYI_APPLICATION_HOME_DIR",
    "_PYI_ARCHIVE_FILE",
    "_PYI_PARENT_PROCESS_LEVEL",
    "_PYI_LINUX_PROCESS_NAME",
)


def clean_environment(env: dict | None = None) -> dict:
    """Copia del entorno sin las variables de PyInstaller, para arrancar un .exe independiente."""
    clean = dict(os.environ if env is None else env)
    for name in _PYINSTALLER_ENV_VARS:
        clean.pop(name, None)
    clean["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # PyInstaller >= 6.9: instancia nueva
    return clean


def _download(url: str, destination: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Vissium-Updater"})
    with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as out:
        out.write(response.read())


def apply_update(info: UpdateInfo) -> bool:
    """
    Descarga el nuevo .exe y se auto-sustituye:

    - Solo funciona cuando la app corre empaquetada como .exe
      (PyInstaller, `sys.frozen`). En modo fuente, se limita a avisar.
    - Windows permite renombrar/mover un .exe que está en ejecución
      (aunque no sobrescribirlo directamente), así que el truco es:
      descargar el nuevo exe con otro nombre, lanzar un script .bat
      que: 1) espera a que este proceso termine, 2) renombra el exe
      viejo, 3) coloca el nuevo con el nombre original, 4) lo arranca,
      5) se autodestruye. Después esta función cierra la aplicación.
    - El .bat y el nuevo .exe se arrancan con el entorno limpio de las
      variables de PyInstaller; si no, el nuevo .exe busca la carpeta
      temporal `_MEI…` del antiguo (ya borrada) y falla al cargar python311.dll.

    Devuelve True si se ha lanzado el proceso de actualización (la
    app debe cerrarse justo después), False si no se pudo aplicar
    (p. ej. no es un .exe empaquetado, o falló la descarga).
    """
    if not (getattr(sys, "frozen", False) and sys.platform == "win32"):
        return False

    current_exe = sys.executable
    directory = app_dir()
    new_exe = os.path.join(directory, f"_update_{info.tag}.exe")
    old_backup = os.path.join(directory, "_previous_version.exe.bak")

    try:
        _download(info.download_url, new_exe)
    except (urllib.error.URLError, OSError):
        return False

    bat_path = os.path.join(tempfile.gettempdir(), "vissium_update.bat")
    # /nobreak /t 3: pequeña espera para que el proceso actual termine
    # de cerrarse antes de tocar su .exe.
    # Se vacían aquí también las variables de PyInstaller: el .bat las heredaría y
    # `start` se las pasaría al nuevo .exe (ver `clean_environment`).
    script = f"""@echo off
set _MEIPASS2=
set _PYI_APPLICATION_HOME_DIR=
set _PYI_ARCHIVE_FILE=
set _PYI_PARENT_PROCESS_LEVEL=
set PYINSTALLER_RESET_ENVIRONMENT=1
timeout /t 3 /nobreak >nul
if exist "{old_backup}" del /f /q "{old_backup}"
move /y "{current_exe}" "{old_backup}" >nul
move /y "{new_exe}" "{current_exe}" >nul
start "" "{current_exe}"
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as fh:
        fh.write(script)

    subprocess.Popen(
        ["cmd", "/c", bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
        close_fds=True,
        env=clean_environment(),
    )
    return True
