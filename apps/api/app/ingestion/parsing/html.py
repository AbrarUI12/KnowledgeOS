"""Conservative HTML boilerplate removal; never fetches a canonical URL."""

from urllib.parse import urlsplit

from bs4 import BeautifulSoup


def clean_html(data: bytes) -> tuple[bytes, dict[str, str]]:
    soup = BeautifulSoup(data, "html.parser")
    metadata: dict[str, str] = {}
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
    return str(soup).encode("utf-8"), metadata
