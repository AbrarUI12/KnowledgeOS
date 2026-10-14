"""Conservative HTML boilerplate removal; never fetches a canonical URL."""

from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


def clean_html(data: bytes) -> tuple[bytes, dict[str, Any]]:
    soup = BeautifulSoup(data, "html.parser")
    metadata: dict[str, Any] = {}
    if soup.title:
        metadata["html_title"] = soup.title.get_text(" ", strip=True)
    canonical = soup.find("link", rel="canonical")
    if canonical:
        href = canonical.get("href")
        if isinstance(href, str):
            try:
                parsed = urlsplit(href)
                if parsed.scheme in {"http", "https"} and parsed.hostname:
                    metadata["canonical_url"] = href
            except ValueError:
                pass
    for element in soup.select(
        "nav, footer, script, style, [role=navigation], "
        "#cookie-banner, #cookie-notice, .cookie-banner, .cookie-notice, #consent-banner"
    ):
        element.decompose()
    links = [link.get("href") for link in soup.find_all("a")]
    targets = list(dict.fromkeys(link for link in links if isinstance(link, str)))
    if targets:
        metadata["links"] = targets  # untrusted targets, retained for the content scanner
    return str(soup).encode("utf-8"), metadata
