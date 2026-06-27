import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
import chromadb
from chromadb.utils import embedding_functions
from google import genai
from dotenv import load_dotenv, dotenv_values

def get_domain(url: str) -> str:
    """Extracts the base domain from a URL."""
    try:
        return urlparse(url).netloc
    except Exception:
        return "Unknown"
from config import (
    EMBEDDING_MODEL,
    GENERATION_MODEL,
    CHROMA_DB_PATH,
    CHROMA_COLLECTION,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    TOP_K_RESULTS,
)

load_dotenv(override=True)

# ──────────────────────────────────────────────
# API Key Helper
# ──────────────────────────────────────────────

def get_api_key() -> str:
    """
    Reads the Gemini API key by manually parsing the .env file.
    Tries GOOGLE_API_KEY and GEMINI_API_KEY variable names.
    """
    env_path = Path(__file__).parent / ".env"
    print(f"[*] Looking for .env at: {env_path}")
    print(f"[*] .env exists: {env_path.exists()}")

    # Manual .env file parsing (most reliable)
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8-sig") as f:  # utf-8-sig strips BOM
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    print(f"[*] .env key found: {k} ({len(v)} chars)")
                    if k in ("GOOGLE_API_KEY", "GEMINI_API_KEY") and v:
                        print(f"[+] Using API key from .env file")
                        return v

    # Fallback: check environment
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if key and key.strip():
        print(f"[+] API key loaded from environment ({len(key)} chars)")
        return key.strip()

    raise ValueError(
        "No API key found! Please add GOOGLE_API_KEY=your_key to your .env file."
    )

# ──────────────────────────────────────────────
# STEP 1: Text Chunking (same logic as v2, now imported from here)
# ──────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Splits a long text into overlapping chunks for embedding.
    Tries to split at natural boundaries (newline or space).
    """
    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        if end < len(text):
            for i in range(end, max(end - 100, start), -1):
                if text[i] in ("\n", " "):
                    end = i + 1
                    break

        chunk = text[start:end].strip()
        if len(chunk) > 50:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = end - overlap

    return chunks


# ──────────────────────────────────────────────
# STEP 2: ChromaDB Vector Store
# ──────────────────────────────────────────────

class VectorStore:
    """
    Persistent local vector store using ChromaDB.
    
    Generates embeddings locally using the default embedding function
    (all-MiniLM-L6-v2) to avoid hitting Gemini API rate limits and 429 pauses.
    """

    def __init__(self):
        # Initialize the local embedding function (downloads once, runs locally)
        self.embedding_function = embedding_functions.DefaultEmbeddingFunction()

        # Initialize ChromaDB (persistent local storage)
        self.chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

        # Get or create collection using the local embedding function
        self.collection = self.chroma_client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"}  # Use cosine distance metric
        )

        print(f"[+] ChromaDB ready (Local Embeddings). Collection '{CHROMA_COLLECTION}' has {self.collection.count()} chunks.")

    def add_pages(self, pages: List[Dict[str, str]]) -> int:
        """
        Takes a list of crawled pages [{url, text}, ...],
        chunks each page's text, and stores them in ChromaDB.
        Embeddings are generated locally by ChromaDB's default function.
        Returns total number of chunks added.
        """
        all_chunks:  List[str]         = []
        all_ids:     List[str]         = []
        all_meta:    List[Dict]        = []
        chunk_index: int               = self.collection.count()

        for page in pages:
            url  = page["url"]
            text = page["text"]

            if not text.strip():
                continue

            page_chunks = chunk_text(text)
            print(f"  [*] {url} -> {len(page_chunks)} chunks")

            for chunk in page_chunks:
                chunk_index += 1
                all_chunks.append(chunk)
                all_ids.append(f"chunk_{chunk_index}")
                all_meta.append({
                    "source": url,
                    "domain": get_domain(url)
                })

        if not all_chunks:
            print("[!] No chunks to add.")
            return 0

        # Store in ChromaDB — let ChromaDB generate local embeddings
        CHROMA_BATCH_SIZE = 100
        for i in range(0, len(all_chunks), CHROMA_BATCH_SIZE):
            self.collection.add(
                documents=all_chunks[i : i + CHROMA_BATCH_SIZE],
                ids=all_ids[i : i + CHROMA_BATCH_SIZE],
                metadatas=all_meta[i : i + CHROMA_BATCH_SIZE],
            )

        print(f"[+] Added {len(all_chunks)} chunks. Total in DB: {self.collection.count()}")
        return len(all_chunks)

    def search(self, query: str, top_k: int = TOP_K_RESULTS, domain_filter: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Searches ChromaDB for the most relevant chunks using local embeddings.
        Supports filtering by domain list.
        """
        if self.collection.count() == 0:
            return []

        # Prepare metadata query constraint if a domain filter is active
        where_clause = None
        if domain_filter:
            if len(domain_filter) == 1:
                where_clause = {"domain": domain_filter[0]}
            else:
                where_clause = {"domain": {"$in": domain_filter}}

        # Query ChromaDB using raw text (ChromaDB embeds it automatically)
        results = self.collection.query(
            query_texts=[query],
            n_results=min(top_k, self.collection.count()),
            where=where_clause,
            include=["documents", "metadatas", "distances"]
        )

        # Format results
        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        ):
            output.append({
                "text":   doc,
                "source": meta.get("source", "Unknown"),
                "score":  round(1 - dist, 4)  # Convert distance to similarity score
            })

        return output

    def clear(self):
        """Deletes and recreates the ChromaDB collection (wipes all data)."""
        self.chroma_client.delete_collection(CHROMA_COLLECTION)
        self.collection = self.chroma_client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"}
        )
        print("[*] Vector store cleared.")

    def count(self) -> int:
        """Returns how many chunks are currently stored."""
        return self.collection.count()

    def delete_domain(self, domain: str):
        """Deletes all chunks associated with a specific domain."""
        self.collection.delete(where={"domain": domain})
        print(f"[+] Deleted all chunks for domain: {domain}")

    def get_ingested_sources(self) -> List[Dict[str, Any]]:
        """Returns a list of dicts with unique domains, page counts, and chunk counts."""
        if self.collection.count() == 0:
            return []

        data = self.collection.get(include=["metadatas"])
        metadatas = data.get("metadatas", [])
        
        # Count pages and chunks per domain
        domain_stats = {}
        seen_pages = {} # domain -> set of page urls
        
        for meta in metadatas:
            if not meta:
                continue
            dom = meta.get("domain")
            src = meta.get("source")
            if not dom:
                continue
                
            if dom not in domain_stats:
                domain_stats[dom] = {"domain": dom, "chunks": 0, "pages": 0}
                seen_pages[dom] = set()
                
            domain_stats[dom]["chunks"] += 1
            if src and src not in seen_pages[dom]:
                seen_pages[dom].add(src)
                domain_stats[dom]["pages"] += 1
                
        return list(domain_stats.values())



# ──────────────────────────────────────────────
# STEP 3: Full RAG Pipeline
# ──────────────────────────────────────────────

class RAGPipeline:
    """
    Combines the VectorStore retrieval with Gemini generation
    into a single, clean RAG interface.

    Flow:
      User Question
          ↓
      Embed question → Search ChromaDB → Get top K chunks
          ↓
      Build focused prompt with only relevant chunks
          ↓
      Gemini generates a grounded, cited answer
    """

    def __init__(self):
        self.store  = VectorStore()
        # Read API key explicitly from .env file
        api_key = get_api_key()
        self.client = genai.Client(api_key=api_key)

    def ingest(self, pages: List[Dict[str, str]], clear_first: bool = True) -> int:
        """Ingests a list of crawled pages into the vector store."""
        if clear_first:
            self.store.clear()
        return self.store.add_pages(pages)

    def query(self, question: str, domain_filter: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Runs the full RAG pipeline for a user question.
        Returns a dict with 'answer' and 'sources'.
        """
        # Retrieve relevant chunks
        chunks = self.store.search(question, top_k=TOP_K_RESULTS, domain_filter=domain_filter)

        if not chunks:
            return {
                "answer":  "No relevant content found. Please ingest a website first.",
                "sources": []
            }

        # Build context from retrieved chunks
        context_parts = []
        sources = []
        seen_sources = set()

        for i, chunk in enumerate(chunks):
            context_parts.append(
                f"[Reference Source: {chunk['source']}]\n{chunk['text']}"
            )
            if chunk["source"] not in seen_sources:
                sources.append(chunk["source"])
                seen_sources.add(chunk["source"])

        context = "\n\n".join(context_parts)

        # Build RAG prompt
        prompt = f"""You are a friendly and helpful Q&A assistant for website content.

Guidelines:
1. Greetings & Chit-chat: If the user says "hi", "hello", "how are you", or uses other general greetings, reply in a friendly, warm, and conversational manner. Do not say that the information is not available.
2. Answering Questions:
   - Use the reference context below as your primary source of truth.
   - If the retrieved context is relevant but does not contain the exact answer, or if the user asks a general question about the core topic (e.g., "what is Python?" when the site is Python documentation), you may supplement it with your own general knowledge to give a helpful, complete, and correct answer.
   - Do NOT mention implementation terms like "chunks", "context", "reference documents", "database", or "score" in your response to the user. Speak naturally.
3. Citing Sources: When answering using the context, cite the relevant source URLs naturally.
4. Missing Information: If the question is a specific factual query about details that are completely missing from the context and cannot be answered, politely state that you couldn't find that specific information in the ingested content.

=== REFERENCE CONTEXT ===
{context}
=========================

Question: {question}

Answer:"""

        # Generate answer with Gemini
        try:
            response = self.client.models.generate_content(
                model=GENERATION_MODEL,
                contents=prompt
            )
            return {
                "answer":  response.text,
                "sources": sources
            }
        except Exception as e:
            return {
                "answer":  f"[!] Generation error: {e}",
                "sources": sources
            }
