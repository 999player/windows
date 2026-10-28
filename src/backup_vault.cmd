@echo off
cd /d "%~dp0"
py backup_vault.py %*
pause
