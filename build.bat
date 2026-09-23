@echo off
REM Compila Vissium.exe localmente en Windows.
REM Requiere que el venv ya exista con las dependencias instaladas
REM (ver README.md) y añade pyinstaller si falta.

setlocal
call venv\Scripts\activate.bat || goto :error

pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Instalando PyInstaller...
    pip install pyinstaller
)

echo Compilando Vissium.exe ...
pyinstaller vissium.spec --noconfirm
if errorlevel 1 goto :error

echo.
echo Listo: dist\Vissium.exe
exit /b 0

:error
echo Ha fallado la compilacion.
exit /b 1
