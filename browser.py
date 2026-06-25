"""
browser.py — Playwright web browsing
Search, visit, extract text, screenshot.
"""

import asyncio
import re
from typing import Optional


async def _get_browser():
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    return pw, browser


async def search_web_async(query: str, num_results: int = 5) -> list[dict]:
    """DuckDuckGo search, return title + url + snippet."""
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    pw, browser = await _get_browser()
    results = []
    try:
        page = await browser.new_page()
        await page.goto(url, timeout=15000)
        items = await page.query_selector_all(".result")
        for item in items[:num_results]:
            try:
                title_el = await item.query_selector(".result__title")
                url_el = await item.query_selector(".result__url")
                snippet_el = await item.query_selector(".result__snippet")
                title = await title_el.inner_text() if title_el else ""
                href = await url_el.inner_text() if url_el else ""
                snippet = await snippet_el.inner_text() if snippet_el else ""
                if title:
                    results.append({"title": title.strip(), "url": href.strip(), "snippet": snippet.strip()})
            except Exception:
                pass
    finally:
        await browser.close()
        await pw.stop()
    return results


async def fetch_page_text_async(url: str, max_chars: int = 3000) -> str:
    """Fetch a URL and return cleaned text."""
    if not url.startswith("http"):
        url = "https://" + url
    pw, browser = await _get_browser()
    try:
        page = await browser.new_page()
        await page.goto(url, timeout=20000, wait_until="domcontentloaded")
        # Remove scripts/styles
        await page.evaluate("""
            document.querySelectorAll('script,style,nav,footer,header').forEach(el => el.remove())
        """)
        text = await page.inner_text("body")
        # Clean up whitespace
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        return text[:max_chars]
    except Exception as e:
        return f"Could not fetch page: {e}"
    finally:
        await browser.close()
        await pw.stop()


def search_web(query: str, num_results: int = 5) -> list[dict]:
    try:
        return asyncio.run(search_web_async(query, num_results))
    except Exception as e:
        return [{"title": "Error", "url": "", "snippet": str(e)}]


def fetch_page_text(url: str, max_chars: int = 3000) -> str:
    try:
        return asyncio.run(fetch_page_text_async(url, max_chars))
    except Exception as e:
        return f"Error: {e}"


def format_search_results_for_voice(results: list[dict]) -> str:
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        snippet = r.get("snippet", "")[:120]
        lines.append(f"{i}. {r['title']} — {snippet}")
    return "\n".join(lines)
