"""Playwright MCP tools — headless browser automation."""
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("harqis-mcp.playwright")


def register_playwright_tools(mcp: FastMCP):

    @mcp.tool()
    def playwright_screenshot(
        url: str,
        output_path: str,
        full_page: bool = False,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        wait_for: Optional[str] = None,
    ) -> dict:
        """Navigate to a URL and take a screenshot using a headless browser.

        Args:
            url:             Page URL to screenshot.
            output_path:     Local file path to save the PNG screenshot.
            full_page:       Capture the full scrollable page (default: False).
            viewport_width:  Browser viewport width in pixels (default: 1280).
            viewport_height: Browser viewport height in pixels (default: 720).
            wait_for:        CSS selector or 'networkidle' to wait for before screenshotting.
        """
        logger.info("Tool called: playwright_screenshot url=%s output=%s", url, output_path)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "error": "playwright is not installed"}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})
            page.goto(url, timeout=30_000)
            if wait_for:
                if wait_for == "networkidle":
                    page.wait_for_load_state("networkidle", timeout=15_000)
                else:
                    page.wait_for_selector(wait_for, timeout=15_000)
            page.screenshot(path=output_path, full_page=full_page)
            title = page.title()
            browser.close()
        logger.info("playwright_screenshot saved to %s title=%s", output_path, title)
        return {"success": True, "url": url, "output_path": output_path, "title": title}

    @mcp.tool()
    def playwright_get_text(url: str, selector: Optional[str] = None) -> dict:
        """Navigate to a URL and extract visible text using a headless browser.

        Args:
            url:      Page URL to navigate to.
            selector: CSS selector to extract text from a specific element.
                      Omit to extract all visible text.
        """
        logger.info("Tool called: playwright_get_text url=%s selector=%s", url, selector)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "error": "playwright is not installed", "text": None}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30_000)
            page.wait_for_load_state("domcontentloaded")
            if selector:
                el = page.query_selector(selector)
                text = el.inner_text() if el else ""
            else:
                text = page.inner_text("body")
            title = page.title()
            browser.close()
        logger.info("playwright_get_text title=%s text_len=%d", title, len(text))
        return {"success": True, "url": url, "title": title, "text": text[:50_000]}

    @mcp.tool()
    def playwright_click_and_get_text(url: str, click_selector: str, result_selector: Optional[str] = None) -> dict:
        """Navigate to a URL, click an element, and return the resulting page text.

        Args:
            url:             Page URL.
            click_selector:  CSS selector of the element to click.
            result_selector: CSS selector to extract text from after clicking.
                             Omit to return all body text.
        """
        logger.info("Tool called: playwright_click_and_get_text url=%s click=%s", url, click_selector)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "error": "playwright is not installed", "text": None}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30_000)
            page.wait_for_selector(click_selector, timeout=10_000)
            page.click(click_selector)
            page.wait_for_load_state("domcontentloaded")
            if result_selector:
                el = page.query_selector(result_selector)
                text = el.inner_text() if el else ""
            else:
                text = page.inner_text("body")
            current_url = page.url
            browser.close()
        logger.info("playwright_click_and_get_text new_url=%s text_len=%d", current_url, len(text))
        return {"success": True, "url": current_url, "text": text[:50_000]}

    @mcp.tool()
    def playwright_fill_and_submit(
        url: str,
        fields: dict,
        submit_selector: Optional[str] = None,
        result_selector: Optional[str] = None,
    ) -> dict:
        """Navigate to a URL, fill form fields, submit, and return the result.

        Args:
            url:             Page URL containing the form.
            fields:          Dict mapping CSS selector → value to fill, e.g.
                             {"#username": "john", "#password": "secret"}.
            submit_selector: CSS selector of the submit button. If omitted,
                             presses Enter on the last filled field.
            result_selector: CSS selector to extract result text from.
                             Omit to return all body text.
        """
        logger.info("Tool called: playwright_fill_and_submit url=%s fields=%d", url, len(fields))
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "error": "playwright is not installed", "text": None}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30_000)
            last_selector = None
            for selector, value in fields.items():
                page.wait_for_selector(selector, timeout=10_000)
                page.fill(selector, str(value))
                last_selector = selector
            if submit_selector:
                page.click(submit_selector)
            elif last_selector:
                page.press(last_selector, "Enter")
            page.wait_for_load_state("domcontentloaded")
            if result_selector:
                el = page.query_selector(result_selector)
                text = el.inner_text() if el else ""
            else:
                text = page.inner_text("body")
            current_url = page.url
            browser.close()
        logger.info("playwright_fill_and_submit new_url=%s text_len=%d", current_url, len(text))
        return {"success": True, "url": current_url, "text": text[:50_000]}

    @mcp.tool()
    def playwright_evaluate(url: str, script: str, wait_for: Optional[str] = None) -> dict:
        """Navigate to a URL and evaluate JavaScript, returning the result.

        Args:
            url:      Page URL to navigate to.
            script:   JavaScript expression to evaluate (must return a serialisable value).
            wait_for: CSS selector or 'networkidle' to wait for before evaluating.
        """
        logger.info("Tool called: playwright_evaluate url=%s script_len=%d", url, len(script))
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "error": "playwright is not installed", "result": None}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30_000)
            if wait_for:
                if wait_for == "networkidle":
                    page.wait_for_load_state("networkidle", timeout=15_000)
                else:
                    page.wait_for_selector(wait_for, timeout=15_000)
            result = page.evaluate(script)
            browser.close()
        logger.info("playwright_evaluate done result_type=%s", type(result).__name__)
        return {"success": True, "url": url, "result": result}
