@echo off
REM Script para ejecutar backup de base de datos
REM Log para debugging
echo [%date% %time%] Iniciando backup... >> "C:\Users\bastian-asus\Documents\proyecto_titulo\siper_pirula\backup_log.txt"

REM Cambiar al directorio del proyecto
cd /d "C:\Users\bastian-asus\Documents\proyecto_titulo\siper_pirula"

REM Activar entorno virtual y ejecutar
call "C:\Users\bastian-asus\Documents\proyecto_titulo\.venv\Scripts\activate.bat"
python manage.py backup_db --s3

REM Registrar resultado
echo [%date% %time%] Backup completado con codigo: %ERRORLEVEL% >> "C:\Users\bastian-asus\Documents\proyecto_titulo\siper_pirula\backup_log.txt"
