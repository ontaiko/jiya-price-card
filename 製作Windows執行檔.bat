@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo 請先安裝含 tkinter 的 64 位元 Python 3.11 以上。
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
".venv\Scripts\python.exe" -c "import tkinter; root = tkinter.Tk(); root.withdraw(); root.destroy()"
if errorlevel 1 (
  echo Python 的 Tcl/Tk 圖形介面無法啟動。請改用包含完整 tkinter 與 Tcl/Tk 的 Python 建立虛擬環境。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name JiYaPriceCard --icon "pricecard\resources\app.ico" --add-data "pricecard\resources;pricecard\resources" --collect-all pypdfium2 run_app.py
if errorlevel 1 (
  echo 建置失敗，請保留畫面中的錯誤資訊。
  pause
  exit /b 1
)
if not exist "dist\JiYaPriceCard\_internal\_tkinter.pyd" (
  echo 建置產物缺少 _tkinter，已停止交付。
  pause
  exit /b 1
)
findstr /C:"missing module named tkinter" "build\JiYaPriceCard\warn-JiYaPriceCard.txt" >nul
if not errorlevel 1 (
  echo PyInstaller 偵測到缺少 tkinter，已停止交付。
  pause
  exit /b 1
)
if not exist "dist\JiYaPriceCard\_internal\_tcl_data\init.tcl" (
  echo 建置產物缺少 Tcl 資料，已停止交付。
  pause
  exit /b 1
)
if not exist "dist\JiYaPriceCard\_internal\_tk_data\tk.tcl" (
  echo 建置產物缺少 Tk 資料，已停止交付。
  pause
  exit /b 1
)
echo 已完成：dist\JiYaPriceCard\JiYaPriceCard.exe
pause
