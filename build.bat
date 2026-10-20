@echo off
REM Compila Vissium.exe localmente, incluso si se ejecuta desde otro directorio.
setlocal
cd /d "%~dp0" || goto :error

REM Acepta ambos nombres de entorno virtual usados en Windows.
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else (
    echo No se encuentra .venv ni venv en "%CD%".
    echo Crea el entorno con: python -m venv .venv
    echo Instala las dependencias con: .venv\Scripts\python.exe -m pip install -r requirements.txt
    goto :error
)

"%PYTHON%" -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Instalando PyInstaller...
    "%PYTHON%" -m pip install pyinstaller || goto :error
)

echo Compilando Vissium.exe ...
"%PYTHON%" -m PyInstaller "%~dp0vissium.spec" --noconfirm
if errorlevel 1 goto :error

echo.
echo Listo: dist\Vissium.exe
exit /b 0

:error
echo Ha fallado la compilacion.
exit /b 1
