@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo 請先安裝 64 位元 Python 3.12 以上，並勾選 py 啟動器。
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 安裝套件失敗，請檢查網路與安裝權限。
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" run_app.py
if errorlevel 1 pause
