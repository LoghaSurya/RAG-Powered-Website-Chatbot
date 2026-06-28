import os
import sys
import asyncio
from collections import deque
from urllib.parse import urljoin, urlparse
from typing import Callable, List, Optional, Set, Dict, Tuple
from bs4 import BeautifulSoup
import httpx
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────

DEFAULT_MAX_PAGES  = 15    # Maximum pages to crawl
DEFAULT_MAX_DEPTH  = 2     # How many link-levels deep to follow
REQUEST_TIMEOUT    = 6.0   # Seconds before giving up on a page (HTTP mode)
CONCURRENT_FETCHES = 10    # Max simultaneous connections (HTTP mode)
PW_CONCURRENT      = 2     # Max simultaneous browser tabs (Playwright mode — RAM heavy!)
PW_PAGE_TIMEOUT    = 12_000  # Playwright navigation timeout in ms

# Realistic browser headers for HTTP mode
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# File extensions that are never HTML content — skip these
SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".zip", ".tar", ".gz", ".mp4", ".mp3", ".wav",
    ".css", ".js", ".json", ".xml", ".ico", ".woff", ".woff2", ".ttf",
)


# ──────────────────────────────────────────────
# HELPERS  (shared by both crawl modes)
# ──────────────────────────────────────────────

def get_domain(url: str) -> str:
    """Extracts the base domain from a URL."""
    return urlparse(url).netloc


def is_valid_url(url: str, base_domain: str) -> bool:
    """Returns True only if the URL is http/https, on the same domain,
    and is not a known binary/asset file."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc != base_domain:
        return False
    path_lower = parsed.path.lower()
    if any(path_lower.endswith(ext) for ext in SKIP_EXTENSIONS):
        return False
    return True


def parse_page(html: str, current_url: str, base_domain: str) -> Tuple[str, List[str]]:
    """
    Parses HTML exactly ONCE and returns (clean_text, child_links).
    Single parse keeps CPU and RAM usage low.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract links BEFORE removing noisy tags
    raw_links: List[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        absolute = urljoin(current_url, href).split("#")[0].rstrip("/")
        if absolute and is_valid_url(absolute, base_domain):
            raw_links.append(absolute)
    links = list(set(raw_links))

    # Remove noise before extracting text
    for noise in soup(["script", "style", "nav", "footer", "header",
                       "aside", "form", "noscript"]):
        noise.decompose()

    raw = soup.get_text(separator="\n")
    lines = (line.strip() for line in raw.splitlines())
    text = "\n".join(line for line in lines if line)

    return text, links


# ──────────────────────────────────────────────
# SHARED BFS RUNNER
# ──────────────────────────────────────────────

class _BFSRunner:
    """
    Base BFS queue logic shared between HTTP and Playwright crawlers.
    Subclasses implement _fetch_html(url) → Optional[str].
    """

    def __init__(
        self,
        max_pages: int,
        max_depth: int,
        on_page_scraped: Optional[Callable[[Dict], None]],
        concurrency: int,
    ):
        self.max_pages       = max_pages
        self.max_depth       = max_depth
        self.on_page_scraped = on_page_scraped
        self.concurrency     = concurrency
        self.visited:  Set[str]   = set()
        self.results:  List[Dict] = []
        self.semaphore            = asyncio.Semaphore(concurrency)
        self._stop                = False

    async def _fetch_html(self, url: str) -> Optional[str]:
        raise NotImplementedError

    async def _process_one(self, url: str, depth: int, base_domain: str) -> List[str]:
        if self._stop or len(self.results) >= self.max_pages:
            self._stop = True
            return []

        html = await self._fetch_html(url)
        if not html:
            return []

        if self._stop or len(self.results) >= self.max_pages:
            self._stop = True
            return []

        text, links = parse_page(html, url, base_domain)

        if text:
            if len(self.results) >= self.max_pages:
                self._stop = True
                return []

            page_data = {"url": url, "text": text}
            self.results.append(page_data)
            print(f"  [OK] Scraped {len(self.results)}/{self.max_pages}: {url}")

            if self.on_page_scraped:
                self.on_page_scraped(page_data)

            if len(self.results) >= self.max_pages:
                self._stop = True
                return []

        if depth >= self.max_depth:
            return []

        return links

    async def _run_bfs(self, start_url: str) -> List[Dict]:
        base_domain = get_domain(start_url)
        queue: deque[Tuple[str, int]] = deque([(start_url, 0)])
        self.visited.add(start_url)

        while queue and not self._stop:
            batch: List[Tuple[str, int]] = []
            while queue and len(batch) < self.concurrency * 4:
                batch.append(queue.popleft())

            child_link_lists = await asyncio.gather(*[
                self._process_one(url, depth, base_domain)
                for url, depth in batch
            ])

            if self._stop:
                break

            for (_, depth), child_links in zip(batch, child_link_lists):
                next_depth = depth + 1
                if next_depth > self.max_depth:
                    continue
                for link in child_links:
                    if link not in self.visited and is_valid_url(link, base_domain):
                        self.visited.add(link)
                        queue.append((link, next_depth))

        self.results = self.results[:self.max_pages]
        return self.results


# ──────────────────────────────────────────────
# MODE 1 — Fast HTTP Crawler (default)
# ──────────────────────────────────────────────

class AsyncCrawler(_BFSRunner):
    """
    Fast BFS crawler using plain HTTP (httpx).
    Works on most documentation sites, blogs, company websites.
    Will get 403 on bot-protected sites like TripAdvisor.
    """

    def __init__(
        self,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_depth: int = DEFAULT_MAX_DEPTH,
        on_page_scraped: Optional[Callable[[Dict], None]] = None,
    ):
        super().__init__(max_pages, max_depth, on_page_scraped, CONCURRENT_FETCHES)
        self._client: Optional[httpx.AsyncClient] = None

    async def _fetch_html(self, url: str) -> Optional[str]:
        if self._stop or self._client is None:
            return None
        async with self.semaphore:
            try:
                resp = await self._client.get(
                    url,
                    headers=HEADERS,
                    timeout=REQUEST_TIMEOUT,
                    follow_redirects=True,
                )
                resp.raise_for_status()
                if "text/html" not in resp.headers.get("content-type", ""):
                    return None
                return resp.text
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code == 403:
                    print(f"  [!] 403 Forbidden: {url} — site blocks bots (try Browser Mode)")
                elif code == 429:
                    print(f"  [!] 429 Rate limited: {url} — slowing down")
                    await asyncio.sleep(2)
                else:
                    print(f"  [!] HTTP {code}: {url}")
                return None
            except Exception as e:
                print(f"  [!] Skipped {url} — {type(e).__name__}: {e}")
                return None

    async def run(self, start_url: str) -> List[Dict]:
        print(f"\n[*] HTTP mode  |  max_pages={self.max_pages}  "
              f"depth={self.max_depth}  concurrency={CONCURRENT_FETCHES}")
        print(f"[*] Starting: {start_url}\n")
        async with httpx.AsyncClient() as client:
            self._client = client
            await self._run_bfs(start_url)
        print(f"\n[+] Done. Scraped {len(self.results)} pages.")
        return self.results


# ──────────────────────────────────────────────
# MODE 2 — Playwright Browser Crawler (stealth)
# ──────────────────────────────────────────────

class PlaywrightCrawler(_BFSRunner):
    """
    Headless Chromium crawler using Playwright.

    Bypasses bot-detection on sites like TripAdvisor, LinkedIn, Glassdoor
    that block plain HTTP requests by checking JS execution, browser APIs,
    and fingerprinting.

    Requires:
        pip install playwright
        playwright install chromium

    Slower than HTTP mode (~3-5s per page) but works on heavily protected sites.
    Concurrency is kept low (PW_CONCURRENT=2) to avoid RAM exhaustion.
    """

    def __init__(
        self,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_depth: int = DEFAULT_MAX_DEPTH,
        on_page_scraped: Optional[Callable[[Dict], None]] = None,
    ):
        super().__init__(max_pages, max_depth, on_page_scraped, PW_CONCURRENT)
        self._browser = None
        self._context = None

    async def _fetch_html(self, url: str) -> Optional[str]:
        if self._stop or self._context is None:
            return None
        async with self.semaphore:
            page = None
            try:
                page = await self._context.new_page()

                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=PW_PAGE_TIMEOUT,
                )

                # Brief wait for lazy-loaded content, then scroll to trigger rendering
                await asyncio.sleep(0.4)
                await page.evaluate("window.scrollBy(0, window.innerHeight * 0.5)")
                await asyncio.sleep(0.2)

                html = await page.content()
                return html

            except Exception as e:
                print(f"  [!] Playwright skipped {url} — {type(e).__name__}: {e}")
                return None
            finally:
                if page:
                    await page.close()

    async def run(self, start_url: str) -> List[Dict]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )

        print(f"\n[*] Browser (Playwright) mode  |  max_pages={self.max_pages}  "
              f"depth={self.max_depth}  concurrency={PW_CONCURRENT}")
        print(f"[*] Starting: {start_url}\n")

        async with async_playwright() as pw:
            # Launch headless Chromium with anti-detection args
            self._browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1366,768",
                ],
            )

            # Realistic browser context — mimics a real Windows Chrome user
            self._context = await self._browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="Asia/Kolkata",
                java_script_enabled=True,
                accept_downloads=False,
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                },
            )

            # Patch navigator.webdriver = false (most basic bot-detection check)
            await self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3],
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });
            """)

            await self._run_bfs(start_url)
            await self._browser.close()

        print(f"\n[+] Done. Scraped {len(self.results)} pages.")
        return self.results


# ──────────────────────────────────────────────
# MAIN — standalone test
# ──────────────────────────────────────────────

async def main():
    print("=" * 55)
    print("  Web Crawler  (HTTP + Playwright modes)")
    print("=" * 55)

    url = input("\nEnter a URL to crawl: ").strip()
    if not url:
        print("[!] URL cannot be empty.")
        sys.exit(1)

    mode = input("Mode? [1] HTTP (fast)  [2] Browser/Playwright (stealth): ").strip()
    use_pw = mode == "2"

    raw_pages = input(f"Max pages (default {DEFAULT_MAX_PAGES}): ").strip()
    max_pages = int(raw_pages) if raw_pages.isdigit() else DEFAULT_MAX_PAGES

    raw_depth = input(f"Max depth (default {DEFAULT_MAX_DEPTH}): ").strip()
    max_depth = int(raw_depth) if raw_depth.isdigit() else DEFAULT_MAX_DEPTH

    CrawlerClass = PlaywrightCrawler if use_pw else AsyncCrawler
    crawler = CrawlerClass(max_pages=max_pages, max_depth=max_depth)
    pages = await crawler.run(url)

    print("\n── Crawled Pages ──────────────────────────────")
    for i, page in enumerate(pages, 1):
        wc = len(page["text"].split())
        print(f"  {i}. {page['url']}  ({wc:,} words)")

    total = sum(len(p["text"].split()) for p in pages)
    print(f"\n[+] Total: {total:,} words across {len(pages)} pages.")


if __name__ == "__main__":
    asyncio.run(main())
