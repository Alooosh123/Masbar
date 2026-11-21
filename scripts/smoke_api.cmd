@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke_api.ps1" %*
