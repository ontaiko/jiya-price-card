# 集雅社價格牌產生器

Windows 桌面程式，用來編輯商品價格牌、保存專案，並輸出實際尺寸的 PDF。本儲存庫包含 Python 原始碼；不需安裝 Python 的 Windows 版本放在 [Releases](https://github.com/ontaiko/jiya-price-card/releases)。

## 下載與開啟

1. 從 Releases 下載最新的 `JiYaPriceCard-Windows-x64-*.zip`。
2. 解壓縮整個 ZIP，保留 `JiYaPriceCard.exe` 與 `_internal` 資料夾的相對位置。
3. 雙擊 `JiYaPriceCard.exe`。首次開啟不需要網路或 Python。

先前的 v1.1.0 Windows ZIP 漏包 `tkinter`，開啟時會顯示 `No module named 'tkinter'`。請改下載 v1.1.1 或更新版本。

這是 64 位元 Windows 桌面版。程式會在 `%APPDATA%\JiYaPriceCard\autosave.jyp` 自動保存草稿；正式使用時也請從「檔案 → 另存專案」保存 `.jyp` 專案檔。示範專案標示為「非現價」，不可直接當作目前售價使用。

## 目前功能

- 五種成品尺寸、七種內建版型，另可建立空白版型及另存自訂版型。
- 集中輸入商品資料、切換品牌 Logo／文字、上傳自訂圖片。
- 左上集雅社標誌及右下五條裝飾採各版型原稿的尺寸，並可像其他方塊一樣選取、拖移及縮放。
- 在預覽中拖移方塊或四角縮放；方向鍵以 0.1 mm 微調，`Shift` 加方向鍵以 1 mm 移動。右側可調整座標、大小、字級、粗體、文字背景色、顏色和對齊。
- 中文輸入法下的 `。`、`．` 可作為數值小數點，也有「輸入小數點」按鈕。`Ctrl+Z` 復原、`Ctrl+Y` 或 `Ctrl+Shift+Z` 重做，頂端亦有按鈕。
- 保存及重開專案、匯入匯出自訂版型、復原與重做單張價格牌編輯。
- 匯出單張實際尺寸 PDF，或將列印清單排在 A4／A3 紙張上；輸出前提示文字溢出等問題。

列印 PDF 時請在列印對話框選「實際大小／100%」。紙本尺寸仍需用實際印表機量測確認。

## 原始碼與建置

程式入口為 `run_app.py`，介面位於 `pricecard/gui.py`，資料及版型位於 `pricecard/core.py`，PDF 繪製位於 `pricecard/core_pdf.py`。內建版型在 `pricecard/resources/templates.json`。請閱讀[使用說明](使用說明.md)及[第三方素材與套件](第三方素材與套件.md)。

原始碼開發需要 64 位元 Python 3.11 或更新版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_app.py
```

在 Windows 上建立執行檔可執行 `製作Windows執行檔.bat`。腳本會先確認 Python 能啟動 Tk 視窗，打包後檢查 `_tkinter` 與 Tcl/Tk 資料，缺少任一項就停止交付。建置產物為 `dist\JiYaPriceCard\JiYaPriceCard.exe`，使用時需要保留整個 `JiYaPriceCard` 資料夾。

## 企劃與現況

原企劃以瀏覽器版為方向；本版採 Windows 桌面介面。試算表批次匯入、跨裝置同步、手機介面與自動查價尚未實作。多型號資料目前固定為兩款，組合內容以文字輸入。原始企劃書存於 `docs/集雅社價格牌產生器App企劃.docx`，其中「尚未實作」為撰寫企劃當時的狀態。

商品規格與價格需由使用者核對。程式不會自動查證現價。
