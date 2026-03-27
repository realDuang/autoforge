@echo off
title AutoForge — Infinite Autonomous Development
cd /d "%~dp0"
echo Starting AutoForge...
powershell -ExecutionPolicy Bypass -File start.ps1 -Loop
pause
