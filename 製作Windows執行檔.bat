@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo 請先安裝 64 位元 Python 3.12 以上。
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt "pyinstaller>=6,<7"
if errorlevel 1 (
  echo 無法安裝建立執行檔所需套件。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name JiYaPriceCard --icon "pricecard\resources\app.ico" --add-data "pricecard\resources;pricecard\resources" --collect-all pypdfium2 run_app.py
if errorlevel 1 (
  echo 建置失敗，請保留畫面中的錯誤資訊。
  pause
  exit /b 1
)
echo 已完成：dist\JiYaPriceCard\JiYaPriceCard.exe
pause
