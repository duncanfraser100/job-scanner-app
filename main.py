# --- DEBUG LOGGER ------------------------------------------------------------
import json, sys
from datetime import datetime

def dbg(msg, obj=None):
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if obj is not None:
        try:
            print(json.dumps(obj, ensure_ascii=False)[:4000], flush=True)
        except Exception:
            print(str(obj)[:4000], flush=True)
# ----------------------------------------------------------------------------

import os, io, hashlib, re
from datetime import datetime, timedelta, timezone
import pandas as pd

# HTTP session with retries
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (JobScan/1.0)"})
_retry = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
SESSION.mount("http://", HTTPAdapter(max_retries=_retry))
SESSION.mount("https://", HTTPAdapter(max_retries=_retry))

from bs4 import BeautifulSoup
from dateutil import parser as dp

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

# =========================== CONFIG FROM ENV ================================
CITY_FILTER = os.getenv("CITY_FILTER", "SYDNEY").lower()
TIME_WINDOW_DAYS = int(os.getenv("TIME_WINDOW_DAYS", "7"))
REPORT_PREFIX = os.getenv("REPORT_PREFIX", "jobs_report")
ALIGNMENT_TECH_PREF = [s.strip().lower() for s in os.getenv("ALIGNMENT_TECH_PREF", "azure,fabric,powerbi").split(",")]
SECTOR_PRIORITY = [s.strip().lower() for s in os.getenv("SECTOR_PRIORITY", "").split(",") if s.strip()]
SOURCES = [s.strip().lower() for s in os.getenv("SOURCES", "").split(",") if s.strip()]

EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "sendgrid")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
GMAIL_SMTP_USER = os.getenv("GMAIL_SMTP_USER")
GMAIL_SMTP_APP_PASSWORD = os.getenv("GMAIL_SMTP_APP_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

STORAGE_ACCOUNT_NAME = os.getenv("STORAGE_ACCOUNT_NAME")
STORAGE_CONTAINER = os.getenv("STORAGE_CONTAINER", "reports")

UTC_NOW = datetime.now(timezone.utc)
SINCE = UTC_NOW - timedelta(days=TIME_WINDOW_DAYS)

dbg("[CFG] starting run", {
    "city": CITY_FILTER,
    "window_days": TIME_WINDOW_DAYS,
    "sources": SOURCES,
    "tech_pref": ALIGNMENT_TECH_PREF,
    "sector_priority": SECTOR_PRIORITY
})
# ===========================================================================

def http_get(url, headers=None):
    dbg("[HTTP] GET", {"url": url})
    r = SESSION.get(url, headers=headers, timeout=30)
    dbg("[HTTP] GET status", {"url": url, "status": r.status_code, "len": len(r.text)})
    r.raise_for_status()
    return r

def normalize_text(t): 
    return re.sub(r"\s+"," ", t or "").strip()

def parse_date_guess(s):
    if not s: 
        return None
    try:
        dt = dp.parse(s, dayfirst=False, yearfirst=False)
        if not dt.tzinfo: 
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except: 
        return None

def in_sydney_scope(city_text):
    t = (city_text or "").lower()
    return "sydney" in t or "nsw" in t or "australia" in t

def title_hits(title):
    t = title.lower()
    terms = [
        "head of data","head of analytics","head of data & analytics","director of data","director of analytics",
        "head of bi","head of insights","head of data platform","director of insights","data transformation","chief data officer","cdo"
    ]
    return any(term in t for term in terms)

def engagement_type(title_or_body):
    t = (title_or_body or "").lower()
    if "contract" in t or "day rate" in t or "daily rate" in t or "contractor" in t:
        return "Contract"
    return "Permanent"

def sector_of(body):
    b = (body or "").lower()
    for s in SECTOR_PRIORITY:
        if s and s in b:
            return s
    return "edge-case/other"

def alignment_score(title, body, sector, posted_dt):
    score = 0
    if title_hits(title): score += 3
    for tech in ALIGNMENT_TECH_PREF:
        if tech in (body or "").lower() or tech in title.lower():
            score += 2
    if sector and sector != "edge-case/other":
        score += 2
    if posted_dt and posted_dt >= SINCE:
        score += 2
    return max(1, min(10, score))

def row(role, company, source_url, posted_dt, engagement, status, sector, rationale, score):
    return {
        "Role": role,
        "Company/Agency": company,
        "Source (with link)": source_url,
        "Posting Date": posted_dt.strftime("%Y-%m-%d") if posted_dt else "",
        "Engagement Type (Perm/Contract)": engagement,
        "Status (Active/Closed)": status,
        "Sector": sector,
        "Rationale (why it fits)": rationale,
        "Alignment Score (1–10)": score
    }

# ----------------------- SCRAPERS (MVP versions) ----------------------------
def scrape_seek():
    url = ("https://www.seek.com.au/jobs"
           "?where=Sydney&keywords=head%20of%20data%20OR%20head%20of%20analytics%20"
           "OR%20director%20of%20data%20OR%20director%20of%20analytics")
    dbg("[SEEK] fetch begin", {"url": url})
    r = http_get(url); soup = BeautifulSoup(r.text, "html.parser")

    anchors = soup.select("a[href*='/job/']")
    dbg("[SEEK] raw anchors", {"count": len(anchors)})

    out = []
    for a in anchors:
        title = normalize_text(a.get_text())
        href = a.get("href", "")
        if not title or not href:
            continue
        full = "https://www.seek.com.au" + href if href.startswith("/") else href
        if not title_hits(title):
            continue
        posted_dt = UTC_NOW  # page often needs detail click; assume fresh
        if posted_dt < SINCE:
            continue
        sector = "edge-case/other"
        score = alignment_score(title, "", sector, posted_dt)
        out.append(row(title, "Seek Listing", full, posted_dt, engagement_type(title), "Active", sector,
                       "Title match; Sydney search", score))

    dbg("[SEEK] final rows", {"count": len(out)})
    return out

def scrape_indeed():
    url = ("https://au.indeed.com/jobs"
           "?q=head+of+data+OR+head+of+analytics+OR+director+of+data+OR+director+of+analytics"
           "&l=Sydney+NSW")
    dbg("[INDEED] fetch begin", {"url": url})
    r = http_get(url); soup = BeautifulSoup(r.text, "html.parser")

    cards = soup.select("a[href*='/pagead/'], a[href*='/viewjob']")
    dbg("[INDEED] raw anchors", {"count": len(cards)})

    out = []
    for card in cards:
        title = normalize_text(card.get_text())
        href = card.get("href", "")
        if not title or not href:
            continue
        full = "https://au.indeed.com" + href if href.startswith("/") else href
        if not title_hits(title):
            continue
        posted_dt = UTC_NOW
        if posted_dt < SINCE:
            continue
        sector = "edge-case/other"
        score = alignment_score(title, "", sector, posted_dt)
        out.append(row(title, "Indeed Listing", full, posted_dt, engagement_type(title), "Active", sector,
                       "Title match; Sydney search", score))

    dbg("[INDEED] final rows", {"count": len(out)})
    return out
# ----------------------------------------------------------------------------

SCRAPERS = {
    "seek": scrape_seek,
    "indeed": scrape_indeed,
    # TODO: add the rest of the sites following the same pattern.
}

def dedupe(rows):
    seen = set(); out = []
    for r in rows:
        key = (r["Role"].lower(), r["Company/Agency"].lower(), r["Source (with link)"])
        if key in seen: 
            continue
        seen.add(key); out.append(r)
    return out

def to_html_table(df: pd.DataFrame, report_title: str):
    header = f"<h2>{report_title}</h2>"
    return header + df.to_html(index=False, escape=False)

def upload_with_msi(local_bytes: bytes, path: str, content_type: str = "text/csv"):
    cred = DefaultAzureCredential()
    account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
    bsc = BlobServiceClient(account_url=account_url, credential=cred)

    container = bsc.get_container_client(STORAGE_CONTAINER)
    try:
        container.create_container()
    except Exception:
        pass

    blob = container.get_blob_client(path)
    blob.upload_blob(
        local_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )
    dbg("[BLOB] uploaded", {"path": path, "bytes": len(local_bytes)})

def main():
    all_rows = []
    per_source = {}

    # If SOURCES is empty, run all; else restrict to provided set
    selected = set(SOURCES) if SOURCES else set(SCRAPERS.keys())
    dbg("[RUN] selected sources", list(selected))

    for key, fn in SCRAPERS.items():
        if key not in selected:
            continue
        try:
            dbg("[RUN] source begin", {"source": key})
            rows = fn()
            per_source[key] = len(rows)
            all_rows.extend(rows)
            dbg("[RUN] source done", {"source": key, "rows": len(rows)})
        except Exception as e:
            per_source[key] = f"error: {type(e).__name__}"
            dbg(f"[ERR] {key}", str(e))

    dbg("[RUN] totals pre-dedupe", {"rows": len(all_rows), "per_source": per_source})

    all_rows = dedupe(all_rows)
    dbg("[RUN] totals post-dedupe", {"rows": len(all_rows)})

    df = pd.DataFrame(all_rows)

    # Sort by score desc, then date desc
    if not df.empty:
        df["ScoreInt"] = pd.to_numeric(df["Alignment Score (1–10)"], errors="coerce").fillna(1).astype(int)
        df["Posting Date Sort"] = pd.to_datetime(df["Posting Date"], errors="coerce")
        df = df.sort_values(by=["ScoreInt","Posting Date Sort"], ascending=[False, False]).drop(columns=["ScoreInt","Posting Date Sort"])

    # Filenames
    local_date = UTC_NOW.astimezone(timezone.utc)
    folder = f"{REPORT_PREFIX}/{local_date.strftime('%Y-%m-%d')}"
    csv_name = f"{folder}/report.csv"
    html_name = f"{folder}/report.html"
    debug_name = f"{folder}/debug.json"
    title = f"Sydney Data Leadership Intelligence Report — {datetime.now().strftime('%d %B %Y')} (08:30 Sydney)"

    csv_bytes = df.to_csv(index=False).encode("utf-8") if not df.empty else b""
    html_bytes = (
        to_html_table(df, title).encode("utf-8")
        if not df.empty else "<p>No matching roles today.</p>".encode("utf-8")
    )

    # Small debug artifact so we can see what's happening even if CSV is empty
    summary = {
        "since_utc": SINCE.isoformat(),
        "now_utc": UTC_NOW.isoformat(),
        "selected_sources": list(selected),
        "per_source": per_source,
        "total_rows": 0 if df.empty else int(df.shape[0])
    }
    debug_bytes = json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8")

    upload_with_msi(debug_bytes, debug_name, content_type="application/json")
    upload_with_msi(csv_bytes,  csv_name,  content_type="text/csv")
    upload_with_msi(html_bytes, html_name, content_type="text/html")

    # Optional: direct email via SendGrid (Logic App recommended instead)
    if EMAIL_TO and EMAIL_PROVIDER.lower()=="sendgrid" and SENDGRID_API_KEY and csv_bytes:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
            message = Mail(
                from_email="no-reply@yourdomain.com",
                to_emails=EMAIL_TO,
                subject=title,
                html_content=html_bytes.decode("utf-8")
            )
            import base64
            attachment = Attachment()
            attachment.file_content = FileContent(base64.b64encode(csv_bytes).decode())
            attachment.file_type = FileType("text/csv")
            attachment.file_name = FileName("report.csv")
            attachment.disposition = Disposition("attachment")
            message.attachment = attachment
            SendGridAPIClient(SENDGRID_API_KEY).send(message)
            dbg("[EMAIL] sendgrid ok")
        except Exception as e:
            dbg("[EMAIL] sendgrid error", str(e))

if __name__ == "__main__":
    main()
