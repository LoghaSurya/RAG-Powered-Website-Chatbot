import os
import sys
import asyncio
import threading
from typing import Optional, List
from dotenv import load_dotenv

# Load .env FIRST before importing any local modules
# This ensures GEMINI_API_KEY is in os.environ before config.py reads it
load_dotenv(override=True)

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraper import AsyncCrawler, PlaywrightCrawler
from rag import RAGPipeline
from config import DEFAULT_MAX_PAGES, DEFAULT_MAX_DEPTH

# ──────────────────────────────────────────────
# FastAPI App Setup
# ──────────────────────────────────────────────

app = FastAPI(
    title="RAG-Powered Website Chatbot API",
    description="Recursively scrapes websites and answers questions using RAG + Gemini.",
    version="1.0.0"
)

# Allow frontend (React on localhost:5173) to talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Global State
# Tracks crawl progress and holds the RAG pipeline instance
# ──────────────────────────────────────────────

crawl_state = {
    "status":      "idle",       # idle | crawling | indexing | ready | error
    "url":         None,
    "pages_found": 0,
    "chunks":      0,
    "pages":       [],           # List of crawled {url, word_count}
    "error":       None,
}

rag_pipeline: Optional[RAGPipeline] = None

# Initialize RAG pipeline and restore state on startup if data exists in DB
try:
    rag_pipeline = RAGPipeline()
    chunk_count = rag_pipeline.store.count()
    if chunk_count > 0:
        crawl_state["status"] = "ready"
        crawl_state["chunks"] = chunk_count
except Exception:
    rag_pipeline = None


# ──────────────────────────────────────────────
# Request / Response Schemas
# ──────────────────────────────────────────────

class CrawlRequest(BaseModel):
    url:         str
    max_pages:   int  = DEFAULT_MAX_PAGES
    max_depth:   int  = DEFAULT_MAX_DEPTH
    use_browser: bool = False   # True = Playwright headless browser (for bot-protected sites)
    append_mode: bool = False   # True = Keep existing websites, False = Wipe database

class ChatRequest(BaseModel):
    question: str
    domains:  Optional[List[str]] = None  # Selected website domains to restrict context to

class ChatResponse(BaseModel):
    answer:  str
    sources: list[str]


# Helper to run Playwright in a separate thread with Proactor Event Loop (on Windows)
async def run_async_in_new_thread(coro_func, *args, **kwargs):
    """
    Runs an async function in a separate thread with a Proactor event loop (on Windows),
    resolving the NotImplementedError with subprocesses under Uvicorn --reload.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def thread_target():
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        
        try:
            result = new_loop.run_until_complete(coro_func(*args, **kwargs))
            loop.call_soon_threadsafe(future.set_result, result)
        except Exception as e:
            loop.call_soon_threadsafe(future.set_exception, e)
        finally:
            new_loop.close()

    thread = threading.Thread(target=thread_target, daemon=True)
    thread.start()
    return await future


# ──────────────────────────────────────────────
# Background Crawl Task
# ──────────────────────────────────────────────

async def run_crawl(url: str, max_pages: int, max_depth: int, use_browser: bool, append_mode: bool):
    """
    Runs in the background after the /crawl endpoint is called.
    1. Crawls the website using HTTP (fast) or Playwright (stealth) mode
    2. Indexes all pages into ChromaDB via the RAG pipeline
    Updates crawl_state throughout so the frontend can poll /status.
    """
    global rag_pipeline

    try:
        # Phase 1: Crawling
        crawl_state["status"]      = "crawling"
        crawl_state["url"]         = url
        crawl_state["pages_found"] = 0
        crawl_state["chunks"]      = 0
        crawl_state["pages"]       = []
        crawl_state["error"]       = None

        # Live callback: fires after every page so the UI counter updates in real time
        def on_page_scraped(page: dict):
            crawl_state["pages_found"] += 1
            crawl_state["pages"].append({
                "url":        page["url"],
                "word_count": len(page["text"].split()),
            })

        # Choose crawler based on mode
        CrawlerClass = PlaywrightCrawler if use_browser else AsyncCrawler
        crawler = CrawlerClass(
            max_pages=max_pages,
            max_depth=max_depth,
            on_page_scraped=on_page_scraped,
        )
        
        if use_browser and sys.platform == "win32":
            pages = await run_async_in_new_thread(crawler.run, url)
        else:
            pages = await crawler.run(url)

        # Guard: if no pages were scraped the site likely blocked us
        if not pages:
            tip = (
                "No pages could be scraped.\n"
                "• In HTTP mode: the site is blocking bots (403). "
                "Enable \"Browser Mode\" and try again.\n"
                "• In Browser mode: the site uses Cloudflare or heavy JS protection. "
                "Try a different URL."
            ) if not use_browser else (
                "No pages could be scraped even in Browser mode. "
                "This site uses advanced Cloudflare/bot protection that requires "
                "a residential proxy to bypass. Try a different URL."
            )
            crawl_state["status"] = "error"
            crawl_state["error"]  = tip
            return

        # Phase 2: Indexing into ChromaDB
        crawl_state["status"] = "indexing"
        if rag_pipeline is None:
            rag_pipeline = RAGPipeline()
            
        # Ingest chunks (wipe first if append_mode is false)
        chunks_added = rag_pipeline.ingest(pages, clear_first=not append_mode)

        # Done
        crawl_state["chunks"] = rag_pipeline.store.count()
        if chunks_added == 0:
            crawl_state["status"] = "error"
            crawl_state["error"] = (
                "The website was reached, but no indexable text content could be extracted.\n"
                "This usually happens when the site is protected by bot blockers (like Cloudflare or DataDome CAPTCHA) "
                "or has no readable text. Try a different URL."
            )
        else:
            crawl_state["status"] = "ready"

    except RuntimeError as e:
        # Playwright not installed
        crawl_state["status"] = "error"
        crawl_state["error"]  = str(e)
    except Exception as e:
        crawl_state["status"] = "error"
        crawl_state["error"]  = str(e)


# ──────────────────────────────────────────────
# API Endpoints
# ──────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "RAG-Powered Website Chatbot API is running."}


@app.post("/api/crawl")
async def start_crawl(request: CrawlRequest, background_tasks: BackgroundTasks):
    """
    Starts a background crawl of the given URL.
    Returns immediately — use GET /api/status to track progress.
    """
    if crawl_state["status"] in ("crawling", "indexing"):
        raise HTTPException(status_code=409, detail="A crawl is already in progress.")

    background_tasks.add_task(
        run_crawl,
        str(request.url),
        request.max_pages,
        request.max_depth,
        request.use_browser,
        request.append_mode,
    )

    mode = "Browser (Playwright)" if request.use_browser else "HTTP"
    app_mode = "append" if request.append_mode else "overwrite"
    return {"message": f"Crawl started for {request.url} [{mode} mode, {app_mode}]", "status": "crawling"}


@app.get("/api/status")
def get_status():
    """
    Returns the current crawl status.
    Frontend polls this endpoint every 2 seconds to show live progress.
    """
    return crawl_state


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Answers a user question using the RAG pipeline.
    Requires a crawl to have been completed first.
    """
    if rag_pipeline is None or crawl_state["status"] != "ready":
        raise HTTPException(
            status_code=400,
            detail="No website has been ingested yet. Please crawl a URL first."
        )

    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    result = rag_pipeline.query(request.question, domain_filter=request.domains)
    return ChatResponse(answer=result["answer"], sources=result["sources"])


@app.post("/api/reset")
def reset():
    """
    Clears all crawled data and wipes the ChromaDB vector store.
    Resets the app back to idle state.
    """
    global rag_pipeline

    if rag_pipeline is not None:
        rag_pipeline.store.clear()
        rag_pipeline = None

    crawl_state.update({
        "status":      "idle",
        "url":         None,
        "pages_found": 0,
        "chunks":      0,
        "pages":       [],
        "error":       None,
    })

    return {"message": "Reset successful. Ready for a new crawl."}


@app.get("/api/sources")
def get_sources():
    """
    Returns all crawled pages with their URLs and word counts.
    Used by the frontend to display the knowledge base.
    """
    return {
        "total_pages":  crawl_state["pages_found"],
        "total_chunks": crawl_state["chunks"],
        "pages":        crawl_state["pages"]
    }


@app.get("/api/domains")
def get_domains():
    """Returns a list of all ingested websites/domains and their chunk stats."""
    global rag_pipeline
    if rag_pipeline is None:
        try:
            rag_pipeline = RAGPipeline()
        except Exception:
            return []
    return rag_pipeline.store.get_ingested_sources()


@app.delete("/api/domains/{domain}")
def delete_domain(domain: str):
    """Deletes a specific website domain and all its chunks from the database."""
    global rag_pipeline
    if rag_pipeline is None:
        try:
            rag_pipeline = RAGPipeline()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load database: {e}")
            
    try:
        rag_pipeline.store.delete_domain(domain)
        total_chunks = rag_pipeline.store.count()
        crawl_state["chunks"] = total_chunks
        
        # Reset app status back to idle if no chunks are left
        if total_chunks == 0:
            crawl_state["status"] = "idle"
            
        return {"message": f"Website {domain} successfully deleted.", "chunks_left": total_chunks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
