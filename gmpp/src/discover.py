"""Discover every GMPP data attachment on gov.uk via the content API.

Writes `data/raw/gmpp/manifest.csv`: one row per downloadable attachment, plus
`data/raw/gmpp/collection.json` and one `doc_<slug>.json` per publication so the
discovery step is auditable offline.

Run: .venv/bin/python -m gmpp.src.discover
"""
from __future__ import annotations

import json
import re
import sys
import time
from html.parser import HTMLParser

import pandas as pd
import requests

from .paths import COLLECTION_JSON, MANIFEST_PATH, RAW_DIR

API = "https://www.gov.uk/api/content"
COLLECTION_PATH = "/government/collections/major-projects-data"
DOCS_DIR = RAW_DIR / "_api"

SPREADSHEET_EXT = {".csv", ".xlsx", ".xls", ".ods"}

# Attachment titles carry the portfolio snapshot date, and it is NOT always the
# publication year: the 2015 publications carry the September 2014 position and
# the 2024 publications carry the March 2024 position. Observed in the API
# responses on 2026-09-15; see report.md "Snapshot dating".
MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december"
)
SNAPSHOT_RE = re.compile(rf"\b({MONTHS})\s+(20\d{{2}})\b", re.I)
YEAR_RE = re.compile(r"\b(20\d{2})\b")


class _LinkGrabber(HTMLParser):
    """Fallback: pull asset links out of `details.documents` HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value and "assets.publishing.service.gov.uk" in value:
                self.hrefs.append(value)


def fetch_json(path: str, session: requests.Session, retries: int = 4) -> dict:
    url = f"{API}{path}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - retry any transport error
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def dept_from_slug(slug: str) -> str:
    """Department token from a publication slug.

    Two slug generations exist, observed across the 197 collection documents:
    `<dept>-government-major-projects-portfolio-data-<year>` (2014 onward) and
    `government-major-projects-portfolio-data-for-<dept>-<year>` (2013).
    """
    s = slug.replace("/government/publications/", "")
    s = re.sub(r"--\d+$", "", s)
    marker = "government-major-projects-portfolio-data"
    if s.startswith(marker):
        rest = s[len(marker) :].strip("-")
        rest = re.sub(r"^for-", "", rest)
        rest = re.sub(r"-?(20\d{2})$", "", rest).strip("-")
        return rest or "unknown"
    if marker in s:
        return s.split(marker)[0].strip("-") or "unknown"
    return s


def year_from(slug: str, title: str, first_published: str | None) -> int | None:
    for text in (slug, title):
        found = YEAR_RE.findall(text or "")
        if found:
            return int(found[-1])
    if first_published:
        return int(first_published[:4])
    return None


def snapshot_from_title(title: str) -> tuple[str | None, int | None, int | None]:
    """(label, month, year) of the portfolio position named in an attachment title."""
    m = SNAPSHOT_RE.search(title or "")
    if not m:
        return None, None, None
    month_name, year = m.group(1).title(), int(m.group(2))
    month = [
        "January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December",
    ].index(month_name) + 1
    return f"{month_name} {year}", month, year


SEARCH_PATH = "/api/search.json"
# Only publications whose title matches the portfolio's own naming are taken,
# so the supplement cannot pull in unrelated pages. `filter_format=publication`
# is NOT used: gov.uk's search returns zero results for it on this query, while
# the unfiltered query returns the publications, so the title pattern and the
# /government/publications/ path prefix do the filtering instead.
_TITLE_RE = re.compile(
    r"major\s+project(?:s)?\s+portfolio\s+data", re.I
)


def search_for_publications(session: requests.Session) -> list[dict]:
    """GMPP data publications the gov.uk search API knows about."""
    found: dict[str, dict] = {}
    for start in range(0, 400, 100):
        url = f"https://www.gov.uk{SEARCH_PATH}"
        params = {
            "q": "Government Major Projects Portfolio data",
            "count": 100,
            "start": start,
            "fields": "title,link,public_timestamp",
        }
        for attempt in range(4):
            try:
                response = session.get(url, params=params, timeout=60)
                response.raise_for_status()
                payload = response.json()
                break
            except Exception:  # noqa: BLE001 - retry, then give up on this page
                if attempt == 3:
                    payload = {"results": []}
                else:
                    time.sleep(2 ** attempt)
        results = payload.get("results", [])
        if not results:
            break
        for item in results:
            title = str(item.get("title") or "")
            link = str(item.get("link") or "")
            if not _TITLE_RE.search(title):
                continue
            if not link.startswith("/government/publications/"):
                continue
            found[link] = {"base_path": link, "title": title}
    return sorted(found.values(), key=lambda d: d["base_path"])


def ext_of(url: str) -> str:
    tail = url.split("?")[0].rsplit("/", 1)[-1]
    return ("." + tail.rsplit(".", 1)[-1]).lower() if "." in tail else ""


def main() -> int:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = (
        "thesis-institute-procurement-research/0.1 (max@maxghenis.com)"
    )

    collection = fetch_json(COLLECTION_PATH, session)
    COLLECTION_JSON.write_text(json.dumps(collection, indent=1))
    documents = collection["links"]["documents"]
    print(f"collection lists {len(documents)} documents", flush=True)

    # The collection is not complete. The FCO's 2020 publication, which carries
    # the September 2019 position, is published on gov.uk at
    # /government/publications/fco-government-major-projects-portfolio-data-2020
    # and is simply not listed in the collection, so a department-year of the
    # portfolio goes missing. The gov.uk search API finds it, so the collection
    # is supplemented from a search for the publication title pattern and every
    # base path the collection does not already list is added.
    extra = search_for_publications(session)
    known = {doc["base_path"] for doc in documents}
    added = [doc for doc in extra if doc["base_path"] not in known]
    if added:
        print(
            f"gov.uk search found {len(added)} data publications the collection "
            f"does not list:",
            flush=True,
        )
        for doc in added:
            print(f"    {doc['base_path']}", flush=True)
        documents = documents + added

    rows: list[dict] = []
    for i, doc in enumerate(documents, 1):
        base_path = doc["base_path"]
        slug = base_path.rsplit("/", 1)[-1]
        cache = DOCS_DIR / f"{slug}.json"
        if cache.exists():
            payload = json.loads(cache.read_text())
        else:
            payload = fetch_json(base_path, session)
            cache.write_text(json.dumps(payload, indent=1))
            time.sleep(0.15)

        title = payload.get("title") or doc.get("title") or slug
        details = payload.get("details", {})
        attachments = details.get("attachments") or []
        if not attachments:
            grabber = _LinkGrabber()
            for html in details.get("documents") or []:
                if isinstance(html, str):
                    grabber.feed(html)
            attachments = [
                {"url": u, "title": title, "content_type": "", "file_size": None}
                for u in dict.fromkeys(grabber.hrefs)
            ]

        dept = dept_from_slug(slug)
        pub_year = year_from(slug, title, payload.get("first_published_at"))
        is_data_pub = "major-projects-portfolio-data" in slug

        for att in attachments:
            url = att.get("url") or ""
            if not url:
                continue
            ext = ext_of(url)
            label, snap_month, snap_year = snapshot_from_title(att.get("title") or "")
            rows.append(
                {
                    "publication_slug": slug,
                    "publication_title": title,
                    "publication_year": pub_year,
                    "department_slug": dept,
                    "is_data_publication": is_data_pub,
                    "first_published_at": payload.get("first_published_at"),
                    "public_updated_at": payload.get("public_updated_at"),
                    "attachment_title": att.get("title"),
                    "attachment_url": url,
                    "content_type": att.get("content_type"),
                    "file_size": att.get("file_size"),
                    "ext": ext,
                    "snapshot_label": label,
                    "snapshot_month": snap_month,
                    "snapshot_year": snap_year,
                    "is_spreadsheet": ext in SPREADSHEET_EXT,
                    "local_path": str(
                        (
                            RAW_DIR
                            / str(pub_year)
                            / dept
                            / url.rsplit("/", 1)[-1].split("?")[0]
                        ).relative_to(RAW_DIR)
                    ),
                }
            )
        if i % 25 == 0:
            print(f"  {i}/{len(documents)} documents", flush=True)

    frame = pd.DataFrame(rows)
    frame.to_csv(MANIFEST_PATH, index=False)
    print(f"wrote {MANIFEST_PATH} with {len(frame)} attachment rows")
    print(
        frame.groupby("is_spreadsheet").size().to_string(),
        "\nextensions:\n",
        frame["ext"].value_counts().to_string(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
