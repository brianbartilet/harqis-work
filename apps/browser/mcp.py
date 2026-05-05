"""Browser MCP tools — HTTP fetching and basic web scraping."""
import ipaddress
import logging
import os
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("harqis-mcp.browser")

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; harqis-mcp/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
_TIMEOUT = 30


def _allow_private_addresses() -> bool:
    """Honor the BROWSER_MCP_ALLOW_PRIVATE escape hatch."""
    return os.environ.get("BROWSER_MCP_ALLOW_PRIVATE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _assert_public_url(url: str) -> None:
    """Reject URLs whose hostname resolves to a non-public IP.

    Blocks Server-Side Request Forgery (SSRF) scenarios where the model is
    coerced into fetching internal endpoints — cloud metadata services
    (169.254.169.254), localhost (127.0.0.0/8, ::1), private LAN ranges
    (10.0.0.0/8, 192.168.0.0/16, etc.), and link-local/multicast/reserved
    IPs.

    Set ``BROWSER_MCP_ALLOW_PRIVATE=1`` in the environment to opt out — useful
    for scraping a deliberately self-hosted local service.

    Raises ValueError if any DNS-resolved address for the URL is non-public.
    Network resolution failures pass through unchanged so the caller still
    sees a meaningful httpx error.
    """
    if _allow_private_addresses():
        return

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL has no hostname: {url!r}")

    # Resolve every A/AAAA record for the hostname. If the host already *is*
    # an IP literal (or IPv6 in brackets), getaddrinfo will return it back
    # unchanged so this still catches direct-IP attempts.
    try:
        infos = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # DNS failure — let httpx surface the real error to the caller.
        return

    for info in infos:
        addr_str = info[4][0]
        try:
            ip = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                f"URL {url!r} resolves to non-public IP {addr_str} "
                "— refusing for SSRF safety. Set BROWSER_MCP_ALLOW_PRIVATE=1 "
                "to override."
            )


def _make_redirect_guard():
    """Return an httpx event-hook list that re-validates each redirect target.

    httpx surfaces redirects via the response hook; we inspect the Location
    header (resolved against the current URL) and call _assert_public_url
    before httpx follows it.
    """
    def _on_response(response: httpx.Response) -> None:
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                return
            target = str(response.url.join(location))
            _assert_public_url(target)
    return {"response": [_on_response]}


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
        _assert_public_url(url)
        req_headers = {**_DEFAULT_HEADERS, **(headers or {})}
        with httpx.Client(
            follow_redirects=follow_redirects,
            timeout=_TIMEOUT,
            event_hooks=_make_redirect_guard(),
        ) as client:
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
        _assert_public_url(url)
        with httpx.Client(
            follow_redirects=True,
            timeout=_TIMEOUT,
            event_hooks=_make_redirect_guard(),
        ) as client:
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
        from urllib.parse import urljoin
        _assert_public_url(url)
        with httpx.Client(
            follow_redirects=True,
            timeout=_TIMEOUT,
            event_hooks=_make_redirect_guard(),
        ) as client:
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
        _assert_public_url(url)
        with httpx.Client(
            follow_redirects=True,
            timeout=_TIMEOUT,
            event_hooks=_make_redirect_guard(),
        ) as client:
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
        _assert_public_url(url)
        with httpx.Client(
            follow_redirects=True,
            timeout=_TIMEOUT,
            event_hooks=_make_redirect_guard(),
        ) as client:
            resp = client.head(url, headers=_DEFAULT_HEADERS)
        headers = dict(resp.headers)
        logger.info("browser_get_headers status=%d", resp.status_code)
        return {"success": resp.is_success, "status_code": resp.status_code, "url": str(resp.url), "headers": headers}
