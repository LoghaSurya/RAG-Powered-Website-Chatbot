import os

# ──────────────────────────────────────────────
# App-wide configuration settings
# All values can be overridden via environment variables or .env file
# ──────────────────────────────────────────────

# Gemini API
GOOGLE_API_KEY     = os.environ.get("GOOGLE_API_KEY", "")
EMBEDDING_MODEL    = "gemini-embedding-001"
GENERATION_MODEL   = "gemini-2.5-flash"

# ChromaDB
CHROMA_DB_PATH     = "./chroma_db"          # Local folder where vectors are stored
CHROMA_COLLECTION  = "website_content_local"      # Name of the collection inside ChromaDB

# Chunking
CHUNK_SIZE         = 800                    # Characters per chunk
CHUNK_OVERLAP      = 150                    # Overlap between consecutive chunks

# Retrieval
TOP_K_RESULTS      = 5                      # Number of chunks to retrieve per query

# Crawler defaults (keep low to avoid RAM exhaustion on large sites)
DEFAULT_MAX_PAGES  = 15
DEFAULT_MAX_DEPTH  = 2
