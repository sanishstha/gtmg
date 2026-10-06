from datetime import datetime, timezone

from app.ingestion.html_text import html_to_text
from app.ingestion.rss import parse_rss
from app.ingestion.service import ingest_documents
from app.ingestion.rss import NormalizedDocument


def test_html_prefers_article_text():
    html = "<html><nav>Ignore me</nav><article><p>OpenAI cut the price.</p></article></html>"
    assert html_to_text(html) == "OpenAI cut the price."


def test_rss_parser_reads_item_fields():
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <title>NVIDIA ships a new chip</title>
      <link>https://example.test/chip</link>
      <pubDate>Tue, 06 Oct 2026 13:00:00 GMT</pubDate>
      <description>A short blurb.</description>
    </item></channel></rss>
    """
    items = parse_rss(xml)
    assert len(items) == 1
    assert items[0].title == "NVIDIA ships a new chip"
    assert items[0].source_url == "https://example.test/chip"
    assert items[0].published_at == datetime(2026, 10, 6, 13, 0, tzinfo=timezone.utc)


def test_same_document_ingested_ten_times_creates_one_row(session):
    document = NormalizedDocument(
        source_type="rss",
        source_url="https://example.test/a",
        title="Price cut",
        body="OpenAI lowered the price of its API.",
        published_at=None,
        fetched_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )
    created = 0
    skipped = 0
    for _ in range(10):
        result = ingest_documents(session, [document])
        created += result.documents_created
        skipped += result.duplicates_skipped
    assert created == 1
    assert skipped == 9
