"""Browser MCP tools — HTTP fetching and basic web scraping."""
import logging
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("harqis-mcp.browser")

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; harqis-mcp/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
_TIMEOUT = 30


def register_browser_tools(mcp: FastMCP):

    @mcp.tool()
    def browser_fetch(url: str, method: str = "GET", headers: Optional[dict] = None,
                      body: Optional[str] = None, follow_redirects: bool = True) -> dict:
        """Fetch a URL and return the raw response.

        Args:
            url:              The URL to fetch.
            method:           HTTP method (GET, POST, etc.). Default: GET.
            headers:          Additional request headers to merge with defaults.
            body:             Request body for POST/PUT requests.
            follow_redirects: Follow HTTP redirects (default: True).
        """
        logger.info("Tool called: browser_fetch method=%s url=%s", method, url)
        req_headers = {**_DEFAULT_HEADERS, **(headers or {})}
        with httpx.Client(follow_redirects=follow_redirects, timeout=_TIMEOUT) as client:
            resp = client.request(method.upper(), url, headers=req_headers, content=body)
        out = {
            "success": resp.is_success,
            "status_code": resp.status_code,
            "url": str(resp.url),
            "content_type": resp.headers.get("content-type", ""),
            "content_length": len(resp.content),
            "text": resp.text[:50_000],
        }
        logger.info("browser_fetch status=%d length=%d", resp.status_code, len(resp.content))
        return out

    @mcp.tool()
    def browser_get_text(url: str) -> dict:
        """Fetch a webpage and return its visible text content (strips HTML tags).

        Args:
            url: The URL to fetch.
        """
        logger.info("Tool called: browser_get_text url=%s", url)
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return {"success": False, "error": "beautifulsoup4 is required", "text": None}
        with httpx.Client(follow_redirects=True, timeout=_TIMEOUT) as client:
            resp = client.get(url, headers=_DEFAULT_HEADERS)
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        title = soup.title.string.strip() if soup.title else ""
        logger.info("browser_get_text status=%d text_len=%d", resp.status_code, len(text))
        return {
            "success": resp.is_success,
            "status_code": resp.status_code,
            "url": str(resp.url),
            "title": title,
            "text": text[:50_000],
        }

    @mcp.tool()
    def browser_get_links(url: str, base_domain_only: bool = False) -> dict:
        """Fetch a webpage and extract all hyperlinks.

        Args:
            url:              The URL to fetch.
            base_domain_only: Only return links from the same domain (default: False).
        """
        logger.info("Tool called: browser_get_links url=%s", url)
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return {"success": False, "error": "beautifulsoup4 is required", "links": []}
        from urllib.parse import urljoin, urlparse
        with httpx.Client(follow_redirects=True, timeout=_TIMEOUT) as client:
            resp = client.get(url, headers=_DEFAULT_HEADERS)
        soup = BeautifulSoup(resp.text, "html.parser")
        base_domain = urlparse(str(resp.url)).netloc
        links = []
        for tag in soup.find_all("a", href=True):
            href = urljoin(str(resp.url), tag["href"])
            text = tag.get_text(strip=True)
            if base_domain_only and urlparse(href).netloc != base_domain:
                continue
            links.append({"url": href, "text": text})
        links = list({l["url"]: l for l in links}.values())[:200]
        logger.info("browser_get_links found %d link(s)", len(links))
        return {"success": resp.is_success, "url": str(resp.url), "links": links, "count": len(links)}

    @mcp.tool()
    def browser_extract_json(url: str) -> dict:
        """Fetch a URL that returns JSON and parse it.

        Args:
            url: The URL returning a JSON response.
        """
        logger.info("Tool called: browser_extract_json url=%s", url)
        with httpx.Client(follow_redirects=True, timeout=_TIMEOUT) as client:
            resp = client.get(url, headers={**_DEFAULT_HEADERS, "Accept": "application/json"})
        if not resp.is_success:
            return {"success": False, "status_code": resp.status_code, "data": None}
        try:
            data = resp.json()
        except Exception as exc:
            return {"success": False, "error": f"JSON parse error: {exc}", "data": None}
        logger.info("browser_extract_json status=%d", resp.status_code)
        return {"success": True, "status_code": resp.status_code, "url": str(resp.url), "data": data}

    @mcp.tool()
    def browser_get_headers(url: str) -> dict:
        """Send a HEAD request and return the response headers.

        Args:
            url: The URL to inspect.
        """
        logger.info("Tool called: browser_get_headers url=%s", url)
        with httpx.Client(follow_redirects=True, timeout=_TIMEOUT) as client:
            resp = client.head(url, headers=_DEFAULT_HEADERS)
        headers = dict(resp.headers)
        logger.info("browser_get_headers status=%d", resp.status_code)
        return {"success": resp.is_success, "status_code": resp.status_code, "url": str(resp.url), "headers": headers}
