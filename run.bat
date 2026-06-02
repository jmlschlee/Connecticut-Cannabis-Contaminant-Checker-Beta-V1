@echo off
REM CannaScope Beta V5 launcher (Windows)
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q --upgrade pip
pip install -q -r requirements.txt
python cannascope_beta_v5.py %*
