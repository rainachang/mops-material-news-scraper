"""
MOPS 重大訊息爬蟲（本機常駐展示 / GitHub Actions 共用）
流程：抓取 -> 篩公司 -> 篩關鍵字 -> 每次輸出新的 CSV（檔名帶日期時間）
需求：pip install requests pandas schedule
"""
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

# ========================= 使用者設定區 =========================
# 程式所在的資料夾（不需要手動寫資料夾名稱）
BASE_DIR = Path(__file__).resolve().parent

# 輸出資料夾：預設就是程式所在資料夾；可用環境變數 OUTPUT_DIR 覆寫
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR))

# 追蹤公司清單：預設為程式同資料夾的 watchlist.txt；可用 WATCHLIST_FILE 覆寫
WATCHLIST_FILE = Path(os.getenv("WATCHLIST_FILE", BASE_DIR / "watchlist.txt"))

# 輸出檔名前綴，實際檔名：mops_scraper_20261003_183000.csv
FILE_PREFIX = "mops_scraper"

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


def load_watchlist() -> list[str]:
    """讀取 watchlist.txt，支援換行／空白／逗號分隔，並去除重複。"""
    if not WATCHLIST_FILE.exists():
        logging.warning("找不到 %s，將不篩公司（抓全部）。", WATCHLIST_FILE)
        return []
    text = WATCHLIST_FILE.read_text(encoding="utf-8-sig")
    codes = re.findall(r"\d{4,6}", text)
    unique = list(dict.fromkeys(codes))
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


def filter_df(df: pd.DataFrame, watchlist: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for col in ["公司代號", "主旨", "說明"]:
        if col not in df.columns:
            df[col] = ""
    df["公司代號"] = df["公司代號"].astype(str).str.strip()

    if watchlist:
        df = df[df["公司代號"].isin(watchlist)]

    pattern = "|".join(KEYWORDS)
    text = df["主旨"].fillna("") + " " + df["說明"].fillna("")
    return df[text.str.contains(pattern, na=False)]


def add_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ["發言日期", "發言時間"]:
        if col not in df.columns:
            df[col] = ""
    df["發言日期(西元)"] = df["發言日期"].map(roc_to_iso)
    df["抓取時間"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df.sort_values(["發言日期(西元)", "發言時間"], ascending=False)


def save_new_file(df: pd.DataFrame) -> None:
    """每次執行都寫一個新檔，檔名帶日期時間，不覆蓋舊檔。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{FILE_PREFIX}_{stamp}.csv"
    if df.empty:
        df = pd.DataFrame(columns=OUTPUT_COLUMNS)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logging.info("已輸出新檔案：%s（%d 筆）", path, len(df))  # 顯示完整路徑，方便確認位置


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

    df = filter_df(pd.concat(frames, ignore_index=True), watchlist)
    logging.info("篩選後符合條件：%d 筆", len(df))

    save_new_file(add_dates(df) if not df.empty else df)
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