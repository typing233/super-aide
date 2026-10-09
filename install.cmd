@echo off
rem Install or update Super Aide (double-click). Details: scripts\install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
if errorlevel 1 pause
