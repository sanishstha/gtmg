"""One RSS connector. Short feed blurbs are replaced by the article text."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.ingestion.html_text import html_to_text

USER_AGENT = "Mozilla/5.0 (compatible; IntelligenceDesk/0.1; research)"
MIN_BODY_CHARS = 400
CONTENT_TAG = "{http://purl.org/rss/1.0/modules/content/}encoded"


@dataclass(frozen=True)
class NormalizedDocument:
    source_type: str
    source_url: str
    title: str
    body: str
    published_at: datetime | None
    fetched_at: datetime


@dataclass(frozen=True)
class FeedItem:
    source_url: str
    title: str
    rss_body: str
    published_at: datetime | None


@dataclass
class FetchResult:
    documents: list[NormalizedDocument]
    fetched: int
    errors: list[str]


def parse_rss_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_rss(xml_text: str) -> list[FeedItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Feed XML did not parse: {exc}") from exc
    items: list[FeedItem] = []
    for item in root.findall("./channel/item"):
        title = html_to_text(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        encoded = item.findtext(CONTENT_TAG) or ""
        description = item.findtext("description") or ""
        body = html_to_text(encoded) if encoded.strip() else html_to_text(description)
        if not title or not link:
            continue
        items.append(
            FeedItem(
                source_url=link,
                title=title,
                rss_body=body or title,
                published_at=parse_rss_datetime(item.findtext("pubDate")),
            )
        )
    return items


def fetch_feeds(
    urls: list[str],
    *,
    items_per_feed: int,
    client: httpx.Client | None = None,
    fetched_at: datetime | None = None,
) -> FetchResult:
    owns_client = client is None
    http = client or httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20.0)
    stamp = fetched_at or datetime.now(timezone.utc)
    documents: list[NormalizedDocument] = []
    errors: list[str] = []
    try:
        for url in urls:
            try:
                response = http.get(url)
                response.raise_for_status()
                items = parse_rss(response.text)[:items_per_feed]
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"{url}: {exc}")
                continue
            for item in items:
                body = _body_for_item(http, item, errors)
                documents.append(
                    NormalizedDocument(
                        source_type="rss",
                        source_url=item.source_url,
                        title=item.title,
                        body=body,
                        published_at=item.published_at,
                        fetched_at=stamp,
                    )
                )
    finally:
        if owns_client:
            http.close()
    return FetchResult(documents=documents, fetched=len(documents), errors=errors)


def _body_for_item(http: httpx.Client, item: FeedItem, errors: list[str]) -> str:
    if len(item.rss_body) >= MIN_BODY_CHARS:
        return item.rss_body
    try:
        response = http.get(item.source_url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        errors.append(f"{item.source_url}: {exc}")
        return item.rss_body
    page_text = html_to_text(response.text)
    if len(page_text) > len(item.rss_body):
        return page_text
    return item.rss_body
