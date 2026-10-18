@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
title TikTok to Amharic Telegram Bot
echo ======================================================
echo    🤖 TikTok to Amharic Telegram Bot Starting...
echo ======================================================
cd /d "%~dp0"
call venv\Scripts\activate.bat
python bot.py
pause
