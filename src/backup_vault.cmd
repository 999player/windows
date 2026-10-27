@echo off
rem backs up (or resumes backing up) every song on juicewrldvault.com into B:\Comp.
rem   backup_vault.cmd            download what is new / incomplete
rem   backup_vault.cmd --check    verify the files on disk, download nothing
cd /d "%~dp0"
py backup_vault.py %*
pause
