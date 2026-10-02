"""
Versión de Vissium.

Este número es la única fuente de verdad para la versión instalada.
Al preparar una nueva versión para publicar:

1. Sube este número (por ejemplo "1.0.0" -> "1.1.0").
2. Haz commit y merge de los cambios de la rama `testing` a `master`.
3. Crea en GitHub un tag/Release sobre `master` con el mismo número,
   con el prefijo "v" (por ejemplo `v1.1.0`).
4. El workflow de GitHub Actions (.github/workflows/release.yml)
   compila el .exe de Windows automáticamente y lo adjunta a ese
   Release.

El actualizador (updater.py) compara este número con el de la última
Release publicada en GitHub (la de `master`) para saber si hay una
versión nueva disponible.
"""
__version__ = "1.1.4"

APP_NAME = "Vissium"

# Propietario/nombre del repositorio de GitHub, usado por el
# actualizador para consultar la API de Releases:
# https://api.github.com/repos/{GITHUB_REPO}/releases/latest
GITHUB_REPO = "Mario-gl7/Vissium"
