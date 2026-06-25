import os
from typing import List, Dict, Any
import chromadb
from google import genai
from dotenv import load_dotenv
from config import (
    GEMINI_API_KEY,
    EMBEDDING_MODEL,
    GENERATION_MODEL,
    CHROMA_DB_PATH,
    CHROMA_COLLECTION,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    TOP_K_RESULTS,
)

load_dotenv()


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

        start = end - overlap

    return chunks


# ──────────────────────────────────────────────
# STEP 2: ChromaDB Vector Store
# ──────────────────────────────────────────────

class VectorStore:
    """
    Upgrade from Approach 2's JSON-based store to ChromaDB:

    Why ChromaDB over JSON + NumPy?
      ✅ Persistent storage with proper indexing (no full scan needed)
      ✅ Handles thousands of chunks efficiently
      ✅ Built-in metadata filtering (filter by source URL etc.)
      ✅ Industry-standard vector database used in production RAG systems
      ✅ Supports HNSW indexing for sub-millisecond nearest-neighbor search

    We still use Gemini 'text-embedding-004' to generate the vectors,
    but ChromaDB takes care of storing and searching them efficiently.
    """

    def __init__(self):
        # Initialize Gemini client
        self.genai_client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY") or GEMINI_API_KEY
        )

        # Initialize ChromaDB (persistent local storage)
        self.chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

        # Get or create collection
        self.collection = self.chroma_client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"}  # Use cosine distance metric
        )

        print(f"[+] ChromaDB ready. Collection '{CHROMA_COLLECTION}' has {self.collection.count()} chunks.")

    def add_pages(self, pages: List[Dict[str, str]]) -> int:
        """
        Takes a list of crawled pages [{url, text}, ...],
        chunks each page's text, generates embeddings, and stores them in ChromaDB.
        Returns total number of chunks added.
        """
        all_chunks  = []
        all_ids     = []
        all_meta    = []
        chunk_index = self.collection.count()  # Continue from existing count

        for page in pages:
            url  = page["url"]
            text = page["text"]

            if not text.strip():
                continue

            page_chunks = chunk_text(text)
            print(f"  [*] {url} → {len(page_chunks)} chunks")

            for chunk in page_chunks:
                chunk_index += 1
                all_chunks.append(chunk)
                all_ids.append(f"chunk_{chunk_index}")
                all_meta.append({"source": url})

        if not all_chunks:
            print("[!] No chunks to add.")
            return 0

        # Generate all embeddings in one batched API call (efficient!)
        print(f"\n[*] Generating embeddings for {len(all_chunks)} chunks via Gemini...")
        try:
            response = self.genai_client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=all_chunks
            )
            embeddings = [emb.values for emb in response.embeddings]
        except Exception as e:
            print(f"[!] Embedding error: {e}")
            raise

        # Store in ChromaDB
        self.collection.add(
            documents=all_chunks,
            embeddings=embeddings,
            ids=all_ids,
            metadatas=all_meta
        )

        print(f"[+] Added {len(all_chunks)} chunks. Total in DB: {self.collection.count()}")
        return len(all_chunks)

    def search(self, query: str, top_k: int = TOP_K_RESULTS) -> List[Dict[str, Any]]:
        """
        Searches ChromaDB for the most relevant chunks using the query embedding.
        Returns a list of {text, source, score} dicts.
        """
        if self.collection.count() == 0:
            return []

        # Embed the query
        try:
            response = self.genai_client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=query
            )
            query_embedding = response.embeddings[0].values
        except Exception as e:
            print(f"[!] Query embedding error: {e}")
            return []

        # Query ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
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
            metadata={"hnsw:space": "cosine"}
        )
        print("[*] Vector store cleared.")

    def count(self) -> int:
        """Returns how many chunks are currently stored."""
        return self.collection.count()


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
        self.client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY") or GEMINI_API_KEY
        )

    def ingest(self, pages: List[Dict[str, str]]) -> int:
        """Ingests a list of crawled pages into the vector store."""
        self.store.clear()
        return self.store.add_pages(pages)

    def query(self, question: str) -> Dict[str, Any]:
        """
        Runs the full RAG pipeline for a user question.
        Returns a dict with 'answer' and 'sources'.
        """
        # Retrieve relevant chunks
        chunks = self.store.search(question, top_k=TOP_K_RESULTS)

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
                f"[Chunk {i+1} | Score: {chunk['score']} | Source: {chunk['source']}]\n{chunk['text']}"
            )
            if chunk["source"] not in seen_sources:
                sources.append(chunk["source"])
                seen_sources.add(chunk["source"])

        context = "\n\n".join(context_parts)

        # Build RAG prompt
        prompt = f"""You are an expert Q&A assistant for website content.
Answer the user's question using ONLY the retrieved context chunks below.
Be concise, accurate, and always cite the source URL when referencing specific information.
If the answer is not present in the context, clearly state: "This information is not available in the ingested content."

=== RETRIEVED CONTEXT ===
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
