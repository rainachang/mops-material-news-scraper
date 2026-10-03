# MOPS 重大訊息爬蟲：從一個問題到可自動執行的流程

> 用 AI（Claude）協助，把「手動查公開資訊觀測站」變成**自動定時、輸出 CSV** 的流程。
> 這個專案同時記錄了：我的問題、原本的想法、AI 給我的修正、踩過的雷，以及最後可以直接操作的成果。

![MOPS Scraper](https://github.com/<你的帳號>/mops-material-news-scraper/actions/workflows/run.yml/badge.svg)

---

## 1. 我的問題

> ✏️ **【請改寫成你自己的話】** 這段最能讓人理解這個專案的價值，建議用你自己的語氣寫。可以回答：
> - 我為什麼需要追蹤這些公司的人事異動？
> - 手動在公開資訊觀測站查詢，遇到什麼麻煩？（公司很多、每天都要看、容易漏掉……）
> - 我對 Python 爬蟲的熟悉程度？

範例開頭（請替換）：

我需要持續追蹤數百家上市櫃公司的「人員變動」重大訊息。手動逐一查詢既耗時又容易漏看，所以想用 Python 自動化。

## 2. 想要解決的問題

- 自動從公開資訊觀測站（MOPS）取得重大訊息
- 只看**指定的公司**（數百檔）
- 只看**特定類型的訊息**（人員變動）
- **自動定時**執行，並把結果輸出成 **CSV 檔**到指定位置

## 3. 我原本預想的路徑

```
開啟 MOPS 網站 → 爬重大訊息 → 篩選出自己想看的公司 → 篩選出特定訊息（人事異動）
```

## 4. AI 給我的更好做法

AI 檢查了我的流程，指出 **5 個問題**並提出修正：

| # | 我原本做法的問題 | AI 的修正 |
|---|---|---|
| 1 | 直接爬網頁，容易因網站改版或存取限制而失效 | 改用證交所**官方 OpenAPI**，不用開瀏覽器，也不需要 Selenium |
| 2 | 只涵蓋上市公司 | 同時處理**上市與上櫃**，並讓單一來源失敗時不影響另一邊 |
| 3 | 沒考慮資料是每日更新的彙總報表，無法確定是否保留歷史 | **每天定時執行**，每次輸出帶時間戳的 CSV |
| 4 | 缺少「排程」與「輸出設定」兩個步驟 | 補上排程與輸出資料夾設定 |
| 5 | 在程式裡寫死資料夾名稱，名稱打錯就找不到檔案 | 用「程式所在位置」自動決定輸出與清單路徑（見下方踩雷紀錄） |

修正後的流程：

```mermaid
flowchart LR
    A[排程觸發<br/>每個交易日] --> B[呼叫官方 OpenAPI<br/>上市 + 上櫃]
    B --> C[篩選公司<br/>watchlist.txt]
    C --> D[篩選關鍵字<br/>主旨或說明含「人員變動」]
    D --> E[輸出新的 CSV<br/>檔名帶日期時間]
```

### 資料來源

- 上市：證交所 OpenAPI `https://openapi.twse.com.tw/v1/opendata/t187ap04_L`（上市公司每日重大訊息）
- 上櫃：櫃買中心 OpenAPI（端點請以 [TPEx OpenAPI](https://www.tpex.org.tw/openapi) 官方文件為準）
- 欄位包含：發言日期、發言時間、公司代號、公司名稱、主旨、符合條款、事實發生日、說明

---

## 踩雷紀錄：為什麼不要在程式裡寫資料夾名稱？

### 發生了什麼事

程式一開始把輸出路徑寫死成：

```python
OUTPUT_DIR = Path.home() / "Desktop" / "project-python-spider-2026"
```

但我實際的資料夾叫 `project-python-scraper-2026`，只差 `spider` 和 `scraper` 一個字。結果：

- 程式**沒有報錯**，而且 log 顯示「已輸出新檔案」
- 但 CSV 被寫到桌面上另一個**自動新建**的資料夾
- 同資料夾的 `watchlist.txt` 也因此找不到，程式默默改成「不篩公司」，輸出了不符合預期的結果

最麻煩的是：**程式看起來一切正常，錯誤卻很難察覺。**

### 修正方式：讓程式自己知道「我在哪裡」

```python
from pathlib import Path
import os

# 程式所在的資料夾（不需要手動寫資料夾名稱）
BASE_DIR = Path(__file__).resolve().parent

# 預設輸出到程式所在資料夾；需要時可用環境變數覆寫
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR))
WATCHLIST_FILE = Path(os.getenv("WATCHLIST_FILE", BASE_DIR / "watchlist.txt"))
```

`Path(__file__).resolve().parent` 的意思是「這支 `.py` 檔案目前所在的資料夾」。

### 這樣做的好處

| 好處 | 說明 |
|---|---|
| **不會再打錯路徑** | 程式跟資料放在同一個資料夾，就一定找得到 |
| **資料夾可以隨意改名、搬家** | 不需要同步修改程式 |
| **別人下載後可以直接用** | 不用把 `/Users/某某人/Desktop/...` 改成自己的路徑 |
| **本機與 GitHub Actions 共用同一份程式** | 在 GitHub 上用環境變數 `OUTPUT_DIR=output` 指定輸出位置即可 |
| **要自訂時仍然有彈性** | 想輸出到別的資料夾，設定 `OUTPUT_DIR` 環境變數就好 |

### 順便加上的安全網

程式在 log 中印出**完整的輸出路徑**，即使路徑錯了也能立刻發現：

```
[INFO] 輸出資料夾：/Users/.../project-python-scraper-2026
[INFO] 已輸出新檔案：/Users/.../project-python-scraper-2026/mops_scraper_20261003_214948.csv（7 筆）
```

### 一個小原則

> **能讓程式自己判斷的路徑，就不要用人手寫。** 手寫的路徑只要錯一個字，程式不一定會報錯，而是安靜地做出錯誤的事。

---

## 5. 成果與直接操作

### 方式 A：線上操作（不用安裝任何東西）

1. 點上方 **Actions** 分頁 → 左側選 **MOPS Scraper** → 右側按 **Run workflow**
2. 等約 1 分鐘，點進該次執行的頁面，在 **Artifacts** 下載 `mops-csv`
3. 也可以直接到 [`output/`](./output) 資料夾查看自動產生的 CSV

> 這個 workflow 也設定為**每個交易日台灣時間 18:00 自動執行**，不需要任何人操作。

### 方式 B：在自己的電腦執行（Mac / Linux）

```bash
git clone https://github.com/<你的帳號>/mops-material-news-scraper.git
cd mops-material-news-scraper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 想追蹤自己的公司：複製範例清單後編輯
cp watchlist.example.txt watchlist.txt

# 只執行一次
RUN_FOREVER=0 python mops_scraper.py

# 或：常駐模式，每個交易日 18:00 自動執行（Mac 建議加 caffeinate 避免休眠）
caffeinate -i python mops_scraper.py
```

Windows（PowerShell）只執行一次：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:RUN_FOREVER="0"; python mops_scraper.py
```

> 程式與 `watchlist.txt`、輸出的 CSV 都在同一個資料夾，不需要修改任何路徑設定。

### 如何客製化

| 想改什麼 | 怎麼改 |
|---|---|
| 追蹤哪些公司 | 編輯 `watchlist.txt`（一行一個股票代號，也可用空白或逗號分隔） |
| 篩選哪些訊息 | 修改 `mops_scraper.py` 的 `KEYWORDS`（主旨或說明含任一詞就保留） |
| 每天幾點執行（本機常駐） | 修改 `DAILY_RUN_TIME` |
| 輸出到別的資料夾 | 設定環境變數 `OUTPUT_DIR` |
| GitHub 自動執行的時間 | 修改 `.github/workflows/run.yml` 的 `cron`（注意是 UTC，台灣時間 −8 小時） |

### 輸出行為

| 情況 | 結果 |
|---|---|
| 每次執行 | 產生新檔 `mops_scraper_日期_時間.csv`，**不覆蓋舊檔** |
| 沒有符合條件的訊息 | 仍產生新檔，內容只有欄位標題（證明程式有跑） |
| 所有 API 都連不上 | 不輸出檔案，log 顯示錯誤 |
| `watchlist.txt` 不存在 | 不篩公司，輸出所有符合關鍵字的訊息 |

## 6. 完整程式碼

見 [`mops_scraper.py`](./mops_scraper.py)（約 150 行，含註解）。

```
mops-material-news-scraper/
├── README.md
├── mops_scraper.py              ← 主程式
├── requirements.txt             ← requests / pandas / schedule
├── watchlist.example.txt        ← 範例追蹤清單
├── output/                      ← 自動產生的 CSV
└── .github/workflows/run.yml    ← 一鍵執行＋自動定時
```

---

## 開發過程中的幾個決策

| 主題 | 一開始 | 後來改成 | 原因 |
|---|---|---|---|
| 篩選關鍵字 | 一長串人事異動相關詞（董事長、總經理、發言人……） | 只用「人員變動」 | 需求更聚焦，並改為比對「主旨」或「說明」任一欄 |
| 輸出方式 | 累積寫入同一份 CSV，並去除重複 | 每次執行都產生**新的** CSV，檔名帶日期時間 | 每次結果獨立、好對照，展示時也看得出「這次有跑」 |
| 排程 | 作業系統排程（cron / 工作排程器） | 展示用常駐排程；上線版用 GitHub Actions | 展示最直觀；線上版不需要自己的電腦開著 |
| 資料夾路徑 | 寫死在程式裡 | 以程式所在位置自動決定 | 避免路徑打錯卻沒有報錯（見踩雷紀錄） |

---

## 7. 注意事項

- **資料來源**：證交所與櫃買中心公開的 OpenAPI，使用時請遵守其使用條款，並保持低頻率（一天一次即可）。
- **關鍵字需依實際用字調整**：「人員變動」是否逐字出現在每則公告的主旨或說明中，需用實際資料驗證；若一直是 0 筆，請檢查公告的實際用字後調整 `KEYWORDS`。
- **上櫃端點需自行確認**：程式中的上櫃網址請對照 [TPEx OpenAPI](https://www.tpex.org.tw/openapi) 官方文件確認；失效時程式會略過該來源，不會中斷。
- **GitHub Actions 的限制**：
  - 排程以 **UTC** 計算，尖峰時段可能延遲，不保證準時。
  - 公開 repo 長時間沒有活動時，排程可能被 GitHub 自動停用，可到 Actions 頁手動重新啟用。
  - 政府網站有可能限制境外 IP；若線上執行連線失敗，請改用方式 B 在本機執行。
- 公開版 repo 只附**範例清單**，不含完整的追蹤公司名單。
- 本專案僅供學習與展示，**不構成任何投資建議**。
- 本專案的流程設計與程式碼是在 AI（Claude）協助下完成。
