import os
import sys
import asyncio
from urllib.parse import urljoin, urlparse
from typing import List, Set, Dict
from bs4 import BeautifulSoup
import httpx
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────

DEFAULT_MAX_PAGES  = 20   # Maximum pages to crawl
DEFAULT_MAX_DEPTH  = 2    # How many link-levels deep to follow
REQUEST_TIMEOUT    = 10.0 # Seconds before giving up on a page
CONCURRENT_FETCHES = 5    # How many pages to fetch at the same time

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def get_domain(url: str) -> str:
    """Extracts the base domain from a URL e.g. 'https://docs.python.org/3/library/' → 'docs.python.org'"""
    return urlparse(url).netloc


def is_valid_url(url: str, base_domain: str) -> bool:
    """
    Checks if a URL is worth crawling:
      - Must be http or https
      - Must belong to the same domain (we don't wander to external sites)
      - Must not be a file download, image, or anchor link
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return False

    if parsed.netloc != base_domain:
        return False

    # Skip common non-content file types
    skip_extensions = (
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg",
        ".zip", ".tar", ".gz", ".mp4", ".mp3", ".css", ".js"
    )
    if any(parsed.path.lower().endswith(ext) for ext in skip_extensions):
        return False

    return True


def extract_links(html: str, current_url: str, base_domain: str) -> List[str]:
    """
    Parses all <a href="..."> links from an HTML page,
    resolves them to absolute URLs, and filters to same-domain only.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()

        # Skip anchors, mailto, javascript
        if href.startswith(("#", "mailto:", "javascript:")):
            continue

        # Resolve relative URLs to absolute
        absolute = urljoin(current_url, href)

        # Remove fragment (#section) from URL
        absolute = absolute.split("#")[0].rstrip("/")

        if absolute and is_valid_url(absolute, base_domain):
            links.append(absolute)

    return list(set(links))  # deduplicate


def extract_text(html: str) -> str:
    """Strips HTML and returns clean readable text from a page."""
    soup = BeautifulSoup(html, "html.parser")
    for noise in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        noise.decompose()

    raw = soup.get_text(separator="\n")
    lines = (line.strip() for line in raw.splitlines())
    return "\n".join(line for line in lines if line)


# ──────────────────────────────────────────────
# ASYNC CRAWLER
# ──────────────────────────────────────────────

class AsyncCrawler:
    """
    Recursively crawls a website starting from a seed URL.

    Approach 3 upgrade over v1/v2:
      - ASYNC: Fetches multiple pages simultaneously (much faster)
      - RECURSIVE: Follows internal links up to a set depth
      - DOMAIN-LOCKED: Never wanders to external websites
      - CONFIGURABLE: Set max pages and crawl depth
    """

    def __init__(self, max_pages: int = DEFAULT_MAX_PAGES, max_depth: int = DEFAULT_MAX_DEPTH):
        self.max_pages  = max_pages
        self.max_depth  = max_depth
        self.visited:   Set[str]          = set()
        self.results:   List[Dict]        = []  # [{url, text}, ...]
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(CONCURRENT_FETCHES)

    async def fetch_page(self, client: httpx.AsyncClient, url: str) -> str | None:
        """Asynchronously fetches a single URL and returns its HTML, or None on failure."""
        async with self.semaphore:  # Limit concurrent connections
            try:
                response = await client.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True)
                response.raise_for_status()
                # Only process HTML pages
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type:
                    return None
                return response.text
            except Exception as e:
                print(f"  [!] Skipped {url} — {type(e).__name__}: {e}")
                return None

    async def crawl_url(self, client: httpx.AsyncClient, url: str, depth: int):
        """
        Recursively crawls a URL:
          1. Fetch the page HTML
          2. Extract and store its text
          3. Find all links on the page
          4. Recursively crawl each link (if depth allows)
        """
        # Stop conditions
        if url in self.visited:
            return
        if len(self.results) >= self.max_pages:
            return
        if depth > self.max_depth:
            return

        self.visited.add(url)
        print(f"  [→] Crawling (depth={depth}): {url}")

        html = await self.fetch_page(client, url)
        if not html:
            return

        # Extract and store text from this page
        text = extract_text(html)
        if text:
            self.results.append({"url": url, "text": text})
            print(f"  [✓] Scraped page {len(self.results)}/{self.max_pages}: {url}")

        # Stop recursing if at max depth or page limit
        if depth >= self.max_depth or len(self.results) >= self.max_pages:
            return

        # Find links on this page and crawl them
        base_domain = get_domain(url)
        links = extract_links(html, url, base_domain)

        # Schedule all child links concurrently
        tasks = [
            self.crawl_url(client, link, depth + 1)
            for link in links
            if link not in self.visited
        ]
        await asyncio.gather(*tasks)

    async def run(self, start_url: str) -> List[Dict]:
        """Entry point — starts crawling from a seed URL."""
        print(f"\n[*] Starting crawl from: {start_url}")
        print(f"[*] Max pages: {self.max_pages} | Max depth: {self.max_depth}\n")

        async with httpx.AsyncClient() as client:
            await self.crawl_url(client, start_url, depth=0)

        print(f"\n[+] Crawl complete! Scraped {len(self.results)} pages.")
        return self.results


# ──────────────────────────────────────────────
# MAIN — test the crawler standalone
# ──────────────────────────────────────────────

async def main():
    print("=" * 55)
    print("  Approach 3 — Async Recursive Web Crawler")
    print("=" * 55)

    url = input("\nEnter a URL to crawl: ").strip()
    if not url:
        print("[!] URL cannot be empty.")
        sys.exit(1)

    max_pages = input("Max pages to crawl (default 20): ").strip()
    max_pages = int(max_pages) if max_pages.isdigit() else DEFAULT_MAX_PAGES

    max_depth = input("Max crawl depth (default 2): ").strip()
    max_depth = int(max_depth) if max_depth.isdigit() else DEFAULT_MAX_DEPTH

    crawler = AsyncCrawler(max_pages=max_pages, max_depth=max_depth)
    pages = await crawler.run(url)

    print("\n── Crawled Pages ──────────────────────────────")
    for i, page in enumerate(pages, 1):
        word_count = len(page["text"].split())
        print(f"  {i}. {page['url']}  ({word_count:,} words)")

    total_words = sum(len(p["text"].split()) for p in pages)
    print(f"\n[+] Total content: {total_words:,} words across {len(pages)} pages.")


if __name__ == "__main__":
    asyncio.run(main())
