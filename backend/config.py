import os

# ──────────────────────────────────────────────
# App-wide configuration settings
# All values can be overridden via environment variables or .env file
# ──────────────────────────────────────────────

# Gemini API
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
EMBEDDING_MODEL    = "text-embedding-004"
GENERATION_MODEL   = "gemini-1.5-flash"

# ChromaDB
CHROMA_DB_PATH     = "./chroma_db"          # Local folder where vectors are stored
CHROMA_COLLECTION  = "website_content"      # Name of the collection inside ChromaDB

# Chunking
CHUNK_SIZE         = 800                    # Characters per chunk
CHUNK_OVERLAP      = 150                    # Overlap between consecutive chunks

# Retrieval
TOP_K_RESULTS      = 5                      # Number of chunks to retrieve per query

# Crawler defaults
DEFAULT_MAX_PAGES  = 20
DEFAULT_MAX_DEPTH  = 2
