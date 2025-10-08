#!/usr/bin/env python3
"""
TradingView Bonds Scraper (Playwright, Python)
Author: ChatGPT
Purpose: Extract bond ladder rows (YTM, Price %, Volume, Coupon %, Maturity, Outstanding Amt, etc.)
         from TradingView /bonds pages for a list of homebuilder tickers, plus each ticker's equity price.
         
Schema (CSV columns):
Ticker, Stock_Price, Bond_Symbol, YTM_pct, Price_pct, Volume, Coupon_pct, Maturity_Date, Outstanding_Amt, Face_Value, Min_Denom_Amt, Issuer, Source_URL

Quick start:
1) python -m pip install -r requirements.txt
2) python -m playwright install
3) (First time) Authenticate to TradingView to store cookies:
   python scrape_bonds.py --login
   # A browser window opens; sign in to TradingView. When done, press ENTER in the terminal.
4) Run the scraper (headless) using saved cookies:
   python scrape_bonds.py --watchlist bond_watchlist.csv --outdir output

Notes:
- Use --headed to debug. Use --slowmo 50 to slow interactions.
- If TradingView changes table structure, tweak CSS/XPath in parse_bonds_table().
"""
import argparse
import csv
import datetime as dt
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --- Defaults ---
DEFAULT_WATCHLIST = "bond_watchlist.csv"
DEFAULT_OUTDIR = "output"
STORAGE_STATE = "tv_storage_state.json"
WAIT_TIMEOUT_MS = 30000  # 30s

def norm_pct(txt: str) -> Optional[float]:
    if not txt:
        return None
    t = txt.strip().replace('%', '').replace(',', '')
    # Some cells like '102.76%'
    try:
        return float(t)
    except:
        return None

def norm_number(text: str) -> Optional[float]:
    """Normalize '24.97 M USD' -> 24.97 (millions). '40K' -> 0.04 (millions)."""
    if not text:
        return None
    t = text.strip().upper().replace(',', '')
    # Handle currency artifacts like 'USD'
    t = t.replace('USD', '').strip()
    # Units
    mult = 1.0
    if t.endswith('M'):
        mult = 1.0
        t = t[:-1]
    elif t.endswith('B'):
        mult = 1000.0
        t = t[:-1]
    elif t.endswith('K'):
        mult = 0.001
        t = t[:-1]
    # Now attempt float
    try:
        val = float(t)
        return round(val * mult, 6)
    except:
        # Try patterns like '24.97 M'
        m = re.match(r'^([0-9]*\.?[0-9]+)\s*([KMB])$', t)
        if m:
            base = float(m.group(1))
            unit = m.group(2)
            mult = {'K':0.001, 'M':1.0, 'B':1000.0}[unit]
            return round(base * mult, 6)
    return None

def norm_date(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    # Expect YYYY-MM-DD from TradingView
    iso = re.match(r'^\d{4}-\d{2}-\d{2}$', text)
    if iso:
        return text
    # Try a few common formats
    for fmt in ("%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y", "%d-%m-%Y"):
        try:
            d = dt.datetime.strptime(text, fmt).date()
            return d.isoformat()
        except:
            pass
    return text  # best effort

def get_stock_price(page, ticker: str) -> Optional[float]:
    # Open main symbol page and read the big quote value
    sym_url = f"https://www.tradingview.com/symbols/NYSE-{ticker}/"
    page.goto(sym_url, timeout=WAIT_TIMEOUT_MS, wait_until="domcontentloaded")
    # The big quote can have different data-testids; we try a few heuristics
    selectors = [
        "[data-symbol-last='true']",
        "[data-test='price']",
        "div.js-symbol-last",
        "section:has-text('USD') h2",
        "div.tv-symbol-header__first-line span:has-text('USD')"
    ]
    price_val = None
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el and el.count() > 0:
                txt = el.inner_text(timeout=2000).strip()
                # Extract first number
                m = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)', txt.replace(',', ''))
                if m:
                    price_val = float(m.group(1))
                    break
        except PWTimeout:
            continue
        except Exception:
            continue
    return price_val

def parse_bonds_table(page, bonds_url: str) -> List[Dict[str, Any]]:
    page.goto(bonds_url, timeout=WAIT_TIMEOUT_MS, wait_until="domcontentloaded")
    # Ensure "Bonds" tab is active; if not, click it
    try:
        page.get_by_role("tab", name=re.compile(r"bonds", re.I)).click(timeout=3000)
    except Exception:
        pass  # already on bonds

    # Wait for a table that contains headers we expect
    # Strategy: find tables and check their header texts
    page.wait_for_timeout(1000)
    tables = page.locator("table")
    rows_out = []
    found = False
    for i in range(min(10, tables.count())):
        table = tables.nth(i)
        # Get header cells
        try:
            headers = [h.inner_text().strip() for h in table.locator("thead tr th").all()]
        except Exception:
            headers = []
        header_ok = headers and any("YTM" in h for h in headers) and any("Maturity" in h for h in headers)
        if not header_ok:
            continue
        found = True
        body_rows = table.locator("tbody tr")
        for r in range(body_rows.count()):
            tr = body_rows.nth(r)
            tds = tr.locator("td").all()
            # Defensive: map by header names where possible
            cell_texts = [td.inner_text().strip() for td in tds]
            colmap = {headers[c]: cell_texts[c] if c < len(cell_texts) else "" for c in range(len(headers))}
            # Extract with fallbacks by column name containment
            def get_like(name_part):
                for k,v in colmap.items():
                    if name_part.lower() in k.lower():
                        return v
                return ""

            row = {
                "Bond_Symbol": get_like("Symbol"),
                "YTM_pct": norm_pct(get_like("YTM")),
                "Volume": get_like("Volume"),
                "Price_pct": norm_pct(get_like("Price")),
                "Coupon_pct": norm_pct(get_like("Coupon")),
                "Maturity_Date": norm_date(get_like("Maturity")),
                "Outstanding_Amt": norm_number(get_like("Outstanding")),
                "Face_Value": get_like("Face"),
                "Min_Denom_Amt": get_like("Min denom"),
                "Issuer": get_like("Issuer"),
                "Source_URL": bonds_url
            }
            rows_out.append(row)
        break

    if not found:
        # No recognizable table
        return []

    return rows_out

def run_scrape(watchlist_csv: str, outdir: str, headed: bool=False, slowmo: int=0) -> Path:
    ts = dt.datetime.now().strftime("%Y-%m-%d")
    outdir_path = Path(outdir)
    outdir_path.mkdir(parents=True, exist_ok=True)
    outfile = outdir_path / f"bonds_snapshot_{ts}.csv"

    watch = pd.read_csv(watchlist_csv)
    required_cols = {"Company","Ticker","BondsURL"}
    missing = required_cols - set(watch.columns)
    if missing:
        raise SystemExit(f"Watchlist missing required columns: {missing}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, slow_mo=slowmo)
        context = None
        storage_state_file = Path(STORAGE_STATE)
        if storage_state_file.exists():
            context = browser.new_context(storage_state=STORAGE_STATE)
        else:
            context = browser.new_context()
        page = context.new_page()

        all_rows = []
        for _, row in watch.iterrows():
            ticker = str(row["Ticker"]).strip()
            bonds_url = str(row["BondsURL"]).strip()
            # fetch stock price
            try:
                stock_price = get_stock_price(page, ticker)
            except Exception as e:
                stock_price = None
            # fetch bonds table
            bond_rows = []
            try:
                bond_rows = parse_bonds_table(page, bonds_url)
            except Exception as e:
                bond_rows = []

            if not bond_rows:
                # still emit a placeholder row so the dataset records attempt
                all_rows.append({
                    "Ticker": ticker,
                    "Stock_Price": stock_price,
                    "Bond_Symbol": "",
                    "YTM_pct": None,
                    "Price_pct": None,
                    "Volume": "",
                    "Coupon_pct": None,
                    "Maturity_Date": "",
                    "Outstanding_Amt": None,
                    "Face_Value": "",
                    "Min_Denom_Amt": "",
                    "Issuer": "",
                    "Source_URL": bonds_url
                })
            else:
                for br in bond_rows:
                    rec = {
                        "Ticker": ticker,
                        "Stock_Price": stock_price,
                        **br
                    }
                    all_rows.append(rec)

        # write CSV
        cols = ["Ticker","Stock_Price","Bond_Symbol","YTM_pct","Price_pct","Volume","Coupon_pct",
                "Maturity_Date","Outstanding_Amt","Face_Value","Min_Denom_Amt","Issuer","Source_URL"]
        with open(outfile, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in all_rows:
                w.writerow({k: r.get(k,"") for k in cols})

        context.close()
        browser.close()

    return outfile

def do_login(headed: bool=True, slowmo: int=0):
    """Open a headed browser so user can log in, then save storage_state for subsequent headless runs."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, slow_mo=slowmo)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.tradingview.com/")
        print("\nA browser window has opened. Please log in to TradingView.")
        input("Press ENTER here after you have finished logging in... ")
        context.storage_state(path=STORAGE_STATE)
        print(f"Saved cookies/session to {STORAGE_STATE}. Future runs will reuse this.")
        context.close()
        browser.close()

def main():
    ap = argparse.ArgumentParser(description="Scrape TradingView bond tables for a watchlist of tickers.")
    ap.add_argument("--watchlist", default=DEFAULT_WATCHLIST, help="CSV with columns: Company, Ticker, BondsURL")
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR, help="Directory to place snapshot CSVs")
    ap.add_argument("--login", action="store_true", help="Open a browser to log in to TradingView and save storage state")
    ap.add_argument("--headed", action="store_true", help="Run browser in headed mode (useful for debug)")
    ap.add_argument("--slowmo", type=int, default=0, help="Slow down actions (ms) when headed")
    args = ap.parse_args()

    if args.login:
        do_login(headed=True, slowmo=args.slowmo)
        return

    outfile = run_scrape(args.watchlist, args.outdir, headed=args.headed, slowmo=args.slowmo)
    print(f"Wrote snapshot: {outfile}")

if __name__ == "__main__":
    main()
