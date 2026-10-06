"""Turn HTML into the text the extractor and the grounding check share."""

from html.parser import HTMLParser

_SKIP_TAGS = {"script", "style", "noscript", "svg"}
_BREAK_TAGS = {"p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_depth = 0
        self.skip_depth = 0
        self.article_parts: list[str] = []
        self.all_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
            return
        if tag == "article":
            self.article_depth += 1
        if tag in _BREAK_TAGS:
            self.all_parts.append(" ")
            if self.article_depth:
                self.article_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if tag == "article" and self.article_depth:
            self.article_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.all_parts.append(data)
        if self.article_depth:
            self.article_parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    parts = parser.article_parts if any(part.strip() for part in parser.article_parts) else parser.all_parts
    return " ".join("".join(parts).split())
