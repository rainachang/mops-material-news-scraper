"""
MOPS 重大訊息爬蟲（本機常駐展示 / GitHub Actions 共用）
流程：抓取今日資料 -> 併入歷史檔 -> 取最近 N 天 -> 篩公司 -> 篩關鍵字 -> 輸出新的 CSV
需求：pip install requests pandas schedule
"""
import hashlib
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

try:
    from zoneinfo import ZoneInfo
    TW = ZoneInfo("Asia/Taipei")
except Exception:  # 沒有時區資料時退回系統時間
    TW = None

# ========================= 使用者設定區 =========================
# 程式所在的資料夾（不需要手動寫資料夾名稱）
BASE_DIR = Path(__file__).resolve().parent

# 輸出資料夾：預設就是程式所在資料夾；可用環境變數 OUTPUT_DIR 覆寫
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR))

# 追蹤公司清單：預設為程式同資料夾的 watchlist.txt；可用 WATCHLIST_FILE 覆寫
WATCHLIST_FILE = Path(os.getenv("WATCHLIST_FILE", BASE_DIR / "watchlist.txt"))

# 輸出檔名前綴，實際檔名：mops_scraper_20261003_183000.csv
FILE_PREFIX = "mops_scraper"

# 每次輸出「執行當下往前推 N 天」的內容（預設 7 天）
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "7"))

# 歷史檔：每次執行都會把當天抓到的原始資料累積進來，才能湊出一週的內容
HISTORY_FILE = OUTPUT_DIR / "mops_history.csv"
HISTORY_KEEP_DAYS = 60  # 歷史檔只保留最近幾天，避免檔案無限變大

# 關鍵字：「主旨」或「說明」任一欄含有其中一個詞就保留
KEYWORDS = ["人員變動"]

# 資料來源（上櫃端點請自行至 TPEx OpenAPI 確認）
SOURCES = {
    "上市": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    "上櫃": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
}

# 本機預設常駐排程；GitHub Actions 會用環境變數 RUN_FOREVER=0 只跑一次
RUN_FOREVER = os.getenv("RUN_FOREVER", "1") == "1"
DAILY_RUN_TIME = "18:00"
# ================================================================

KEY = "_key"
OUTPUT_COLUMNS = [
    "市場別", "公司代號", "公司名稱", "發言日期", "發言日期(西元)",
    "發言時間", "主旨", "符合條款", "事實發生日", "說明", "抓取時間",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; mops-research-script/1.0)"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def now_tw() -> datetime:
    """台灣時間（GitHub 的機器是 UTC，這樣日期才不會差一天）。"""
    return datetime.now(TW) if TW else datetime.now()


def load_watchlist() -> list[str]:
    """讀取 watchlist.txt；找不到或是空的就停止，避免抓到不相關的公司。"""
    if not WATCHLIST_FILE.exists():
        if os.getenv("ALLOW_NO_WATCHLIST") == "1":
            logging.warning("找不到追蹤清單，依設定改為不篩公司（抓全部）。")
            return []
        logging.error("找不到追蹤清單：%s。為避免抓到不相關的公司，程式停止。", WATCHLIST_FILE)
        sys.exit(1)

    text = WATCHLIST_FILE.read_text(encoding="utf-8-sig")
    codes = re.findall(r"\d{4,6}", text)
    unique = list(dict.fromkeys(codes))
    if not unique:
        logging.error("追蹤清單裡沒有任何股票代號：%s，程式停止。", WATCHLIST_FILE)
        sys.exit(1)

    logging.info("已載入追蹤公司 %d 檔（去重後）：%s", len(unique), WATCHLIST_FILE)
    return unique


def fetch_json(url: str, retries: int = 3) -> list[dict]:
    for i in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.warning("第 %d 次抓取失敗：%s", i, e)
            time.sleep(3 * i)
    return []


def roc_to_iso(s: str) -> str:
    """民國日期（如 1150102）轉西元 2026-01-02；格式不符就原樣回傳。"""
    s = str(s).strip()
    try:
        if len(s) == 7:
            return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:7]}"
        if len(s) == 8:
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    except ValueError:
        pass
    return s


def load_market(name: str, url: str) -> pd.DataFrame:
    data = fetch_json(url)
    if not data:
        logging.error("%s：沒有取得資料（端點可能失效或今日無資料）", name)
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df.columns = [c.strip() for c in df.columns]
    df["市場別"] = name
    logging.info("%s：取得 %d 筆", name, len(df))
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """補上西元日期、抓取時間與唯一鍵（公司＋發言日期＋發言時間＋主旨）。"""
    df = df.copy()
    for col in ["公司代號", "發言日期", "發言時間", "主旨", "說明"]:
        if col not in df.columns:
            df[col] = ""
    df = df.fillna("").astype(str)
    df["公司代號"] = df["公司代號"].str.strip()
    df["發言日期(西元)"] = df["發言日期"].map(roc_to_iso)
    df["抓取時間"] = now_tw().strftime("%Y-%m-%d %H:%M:%S")
    raw = df["公司代號"] + df["發言日期"] + df["發言時間"] + df["主旨"]
    df[KEY] = raw.map(lambda x: hashlib.md5(x.encode("utf-8")).hexdigest())
    return df


def load_history() -> pd.DataFrame:
    if not HISTORY_FILE.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(HISTORY_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    except Exception as e:
        logging.error("讀取歷史檔失敗：%s（將重新建立）", e)
        return pd.DataFrame()


def update_history(today_df: pd.DataFrame) -> pd.DataFrame:
    """把今天抓到的資料併入歷史檔（去重），並清掉太舊的資料，回傳合併後的全部歷史。"""
    merged = pd.concat([load_history(), today_df], ignore_index=True).fillna("")
    before = len(merged)
    merged = merged.drop_duplicates(subset=KEY, keep="first")

    dt = pd.to_datetime(merged["發言日期(西元)"], errors="coerce")
    cutoff = pd.Timestamp(now_tw().date()) - pd.Timedelta(days=HISTORY_KEEP_DAYS)
    merged = merged[dt.isna() | (dt >= cutoff)]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")
    logging.info("歷史檔已更新：%s（共 %d 筆，本次去除重複 %d 筆）",
                 HISTORY_FILE.name, len(merged), before - len(merged))
    return merged


def select_window(df: pd.DataFrame) -> pd.DataFrame:
    """只留下「執行當下往前推 LOOKBACK_DAYS 天」的資料。"""
    dt = pd.to_datetime(df["發言日期(西元)"], errors="coerce")
    start = pd.Timestamp(now_tw().date()) - pd.Timedelta(days=LOOKBACK_DAYS)

    earliest = dt.min()
    if pd.notna(earliest) and earliest > start:
        logging.warning(
            "歷史資料目前最早只到 %s，尚未涵蓋完整 %d 天（%s 起）。"
            "每天持續執行，就會逐日補齊。",
            earliest.date(), LOOKBACK_DAYS, start.date())
    logging.info("輸出範圍：%s ～ %s（往前推 %d 天）",
                 start.date(), now_tw().date(), LOOKBACK_DAYS)
    return df[dt >= start]


def filter_df(df: pd.DataFrame, watchlist: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    if watchlist:
        df = df[df["公司代號"].isin(watchlist)]
    pattern = "|".join(KEYWORDS)
    text = df["主旨"].fillna("") + " " + df["說明"].fillna("")
    return df[text.str.contains(pattern, na=False)]


def save_new_file(df: pd.DataFrame) -> None:
    """每次執行都寫一個新檔，檔名帶日期時間，不覆蓋舊檔。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_tw().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{FILE_PREFIX}_{stamp}.csv"
    if df.empty:
        df = pd.DataFrame(columns=OUTPUT_COLUMNS)
    else:
        extra = [c for c in df.columns if c not in OUTPUT_COLUMNS and c != KEY]
        df = df.sort_values(["發言日期(西元)", "發言時間"], ascending=False)
        df = df[[c for c in OUTPUT_COLUMNS if c in df.columns] + extra]
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logging.info("已輸出新檔案：%s（%d 筆）", path, len(df))


def run_once() -> None:
    logging.info("===== 開始執行 =====")
    logging.info("輸出資料夾：%s", OUTPUT_DIR)
    watchlist = load_watchlist()

    frames = []
    for name, url in SOURCES.items():
        try:
            frames.append(load_market(name, url))
        except Exception as e:
            logging.error("%s 處理失敗：%s", name, e)

    frames = [f for f in frames if not f.empty]
    if not frames:
        logging.error("所有來源都沒有資料，本次不輸出檔案。")
        return

    today_df = prepare(pd.concat(frames, ignore_index=True))
    history = update_history(today_df)

    window = select_window(history)
    result = filter_df(window, watchlist)
    logging.info("近 %d 天資料 %d 筆，篩選後符合條件：%d 筆",
                 LOOKBACK_DAYS, len(window), len(result))

    save_new_file(result)
    logging.info("===== 完成 =====")


if __name__ == "__main__":
    if RUN_FOREVER:
        import schedule
        for d in ("monday", "tuesday", "wednesday", "thursday", "friday"):
            getattr(schedule.every(), d).at(DAILY_RUN_TIME).do(run_once)
        logging.info("常駐排程啟動，每個交易日 %s 執行（Ctrl+C 結束）", DAILY_RUN_TIME)
        run_once()
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        run_once()