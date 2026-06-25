import os
import asyncio
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from dotenv import load_dotenv

from scraper import AsyncCrawler
from rag import RAGPipeline
from config import DEFAULT_MAX_PAGES, DEFAULT_MAX_DEPTH

load_dotenv()

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


# ──────────────────────────────────────────────
# Request / Response Schemas
# ──────────────────────────────────────────────

class CrawlRequest(BaseModel):
    url:       str
    max_pages: int = DEFAULT_MAX_PAGES
    max_depth: int = DEFAULT_MAX_DEPTH

class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    answer:  str
    sources: list[str]


# ──────────────────────────────────────────────
# Background Crawl Task
# ──────────────────────────────────────────────

async def run_crawl(url: str, max_pages: int, max_depth: int):
    """
    Runs in the background after the /crawl endpoint is called.
    1. Crawls the website asynchronously
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

        crawler = AsyncCrawler(max_pages=max_pages, max_depth=max_depth)
        pages   = await crawler.run(url)

        crawl_state["pages_found"] = len(pages)
        crawl_state["pages"] = [
            {"url": p["url"], "word_count": len(p["text"].split())}
            for p in pages
        ]

        # Phase 2: Indexing into ChromaDB
        crawl_state["status"] = "indexing"
        rag_pipeline = RAGPipeline()
        total_chunks = rag_pipeline.ingest(pages)

        # Done
        crawl_state["chunks"] = total_chunks
        crawl_state["status"] = "ready"

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
        request.max_depth
    )

    return {"message": f"Crawl started for {request.url}", "status": "crawling"}


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

    result = rag_pipeline.query(request.question)
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
