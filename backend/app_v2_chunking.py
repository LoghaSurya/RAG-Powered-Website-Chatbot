import os
import sys
import json
import numpy as np
from typing import List, Dict, Any
from bs4 import BeautifulSoup
import httpx
from google import genai
from dotenv import load_dotenv

# Load API key from .env file
load_dotenv()

# ──────────────────────────────────────────────
# STEP 1: Scrape a single webpage (same as v1)
# ──────────────────────────────────────────────

def scrape_page(url: str) -> str:
    """Fetches a URL and returns clean visible text."""
    print(f"\n[*] Fetching: {url}")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        response = httpx.get(url, headers=headers, follow_redirects=True, timeout=10.0)
        response.raise_for_status()
    except Exception as e:
        print(f"[!] Failed to fetch page: {e}")
        sys.exit(1)

    soup = BeautifulSoup(response.text, "html.parser")
    for noise in soup(["script", "style", "nav", "footer", "header", "aside"]):
        noise.decompose()

    raw_text = soup.get_text(separator="\n")
    lines = (line.strip() for line in raw_text.splitlines())
    clean_text = "\n".join(line for line in lines if line)

    print(f"[+] Scraped {len(clean_text):,} characters.")
    return clean_text


# ──────────────────────────────────────────────
# STEP 2: Split text into smaller chunks
# ──────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    """
    Splits a long text into overlapping chunks.

    Why chunking?
      - Approach 1 dumped the entire page into the prompt.
      - If the page has 50,000 characters, that wastes tokens and
        can confuse the model with irrelevant content.
      - By chunking, we only send the RELEVANT pieces to Gemini.

    Why overlap?
      - Overlap ensures that sentences split across chunk boundaries
        are still fully captured in at least one chunk.
    """
    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        # Try to end at a natural boundary (newline or space)
        if end < len(text):
            for i in range(end, max(end - 100, start), -1):
                if text[i] in ("\n", " "):
                    end = i + 1
                    break

        chunk = text[start:end].strip()
        if len(chunk) > 50:  # skip tiny/empty chunks
            chunks.append(chunk)

        start = end - overlap  # step back by overlap for continuity

    print(f"[+] Split into {len(chunks)} chunks (size={chunk_size}, overlap={overlap}).")
    return chunks


# ──────────────────────────────────────────────
# STEP 3: Simple Vector Store (JSON + NumPy)
# ──────────────────────────────────────────────

class SimpleVectorStore:
    """
    A lightweight vector store using:
      - Gemini 'text-embedding-004' to convert text → numbers (vectors)
      - NumPy cosine similarity to find the most relevant chunks
      - A local JSON file to persist the vectors between sessions

    This avoids needing a heavy external database (like ChromaDB)
    for this intermediate approach.
    """

    STORAGE_FILE = "vector_store.json"

    def __init__(self):
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        self.data: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        """Load previously saved vectors from disk."""
        if os.path.exists(self.STORAGE_FILE):
            try:
                with open(self.STORAGE_FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                print(f"[+] Loaded {len(self.data)} chunks from local vector store.")
            except Exception:
                self.data = []

    def _save(self):
        """Save current vectors to disk."""
        with open(self.STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def add_chunks(self, chunks: List[str], source_url: str):
        """
        Converts each chunk into an embedding vector using Gemini
        and saves it to the JSON store.
        """
        print(f"[*] Generating embeddings for {len(chunks)} chunks...")
        try:
            response = self.client.models.embed_content(
                model="text-embedding-004",
                contents=chunks
            )
            for chunk, emb in zip(chunks, response.embeddings):
                self.data.append({
                    "text": chunk,
                    "embedding": emb.values,
                    "source": source_url
                })
            self._save()
            print(f"[+] Embeddings saved. Total chunks in store: {len(self.data)}")
        except Exception as e:
            print(f"[!] Embedding error: {e}")
            raise

    def search(self, query: str, top_k: int = 4) -> List[Dict[str, Any]]:
        """
        Finds the top_k most relevant chunks for a query using
        cosine similarity between the query embedding and stored embeddings.
        """
        if not self.data:
            return []

        # Embed the query
        response = self.client.models.embed_content(
            model="text-embedding-004",
            contents=query
        )
        query_vec = np.array(response.embeddings[0].values)

        # Score each stored chunk
        scored = []
        for item in self.data:
            doc_vec = np.array(item["embedding"])
            # Cosine similarity = dot product / (magnitude1 * magnitude2)
            score = np.dot(query_vec, doc_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(doc_vec)
            )
            scored.append((score, item))

        # Return top K by score
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"score": float(s), "text": item["text"], "source": item["source"]}
            for s, item in scored[:top_k]
        ]

    def clear(self):
        """Wipe all stored vectors."""
        self.data = []
        if os.path.exists(self.STORAGE_FILE):
            os.remove(self.STORAGE_FILE)
        print("[*] Vector store cleared.")


# ──────────────────────────────────────────────
# STEP 4: RAG — Retrieve then Generate
# ──────────────────────────────────────────────

def ask_with_rag(store: SimpleVectorStore, question: str) -> str:
    """
    Retrieval-Augmented Generation:
      1. Search the vector store for relevant chunks
      2. Build a focused prompt using ONLY those chunks
      3. Send to Gemini for an accurate, grounded answer
    """
    results = store.search(question, top_k=4)
    if not results:
        return "No relevant content found. Please ingest a webpage first."

    # Build context from retrieved chunks
    context_parts = []
    sources = set()
    for i, result in enumerate(results):
        sources.add(result["source"])
        context_parts.append(
            f"[Chunk {i+1} | Source: {result['source']}]\n{result['text']}"
        )
    context = "\n\n".join(context_parts)

    prompt = f"""You are a precise Q&A assistant for website content.
Answer the question using ONLY the context chunks provided below.
Always mention the source URL when referencing information.
If the answer is not in the context, say "This information is not available in the ingested content."

=== RETRIEVED CONTEXT ===
{context}
=========================

Question: {question}

Answer:"""

    try:
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        answer = response.text
        answer += "\n\n📎 Sources:\n" + "\n".join(f"  • {s}" for s in sources)
        return answer
    except Exception as e:
        return f"[!] Gemini error: {e}"


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Approach 2 — Chunking + Vector Store RAG Chatbot")
    print("=" * 55)

    if not os.environ.get("GEMINI_API_KEY"):
        print("[!] Please set GEMINI_API_KEY in your .env file.")
        sys.exit(1)

    store = SimpleVectorStore()

    url = input("\nEnter webpage URL to ingest (or press Enter to use existing store): ").strip()

    if url:
        store.clear()
        page_text = scrape_page(url)
        chunks = chunk_text(page_text)
        store.add_chunks(chunks, source_url=url)

    print("\n[+] Ready! Ask questions about the page. Type 'exit' to quit.\n")

    while True:
        try:
            question = input("You: ").strip()
            if not question:
                continue
            if question.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            answer = ask_with_rag(store, question)
            print(f"\nBot: {answer}\n")
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    main()
