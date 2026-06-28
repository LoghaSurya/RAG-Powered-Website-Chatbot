# 🧭 Page Pilot

> **Ask anything about any website — instantly.**

Page Pilot is a full-stack, RAG-powered chatbot that lets you crawl any website and have an AI conversation about its content. Paste a URL, click crawl, and start asking questions — the answers are grounded exclusively in that site's actual content, powered by Google Gemini and ChromaDB.

---

## ✨ Features

- 🌐 **Multi-Website Indexing** — Crawl and index multiple websites simultaneously; knowledge accumulates across sessions
- 🤖 **RAG-Powered Q&A** — Retrieval-Augmented Generation ensures answers are factual and sourced from the crawled content
- 🎯 **Context Focus Pills** — Filter questions to specific indexed websites with one click
- 🕵️ **Dual Crawler Modes** — Fast HTTP crawler for standard sites, Playwright headless browser for JavaScript-heavy or bot-protected pages
- ⚡ **Live Crawl Progress** — Real-time page counter updates as the crawl runs in the background
- 🗑️ **Per-Site Deletion** — Remove any indexed website independently without affecting others
- 🌙 **Dark / Light Theme** — Smooth toggle with persisted preference
- 📌 **Auto-Focus Input** — Typing area automatically refocuses after every message so you never lose your place
- 🔒 **Bot-Protection Detection** — Clear user warnings when a site is blocked by CAPTCHA or Cloudflare

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19, Vite, Vanilla CSS |
| **Backend** | FastAPI, Python 3.11+ |
| **AI Generation** | Google Gemini 2.5 Flash |
| **Vector Database** | ChromaDB (local, persistent) |
| **Embeddings** | ChromaDB Default (SentenceTransformers `all-MiniLM-L6-v2`) |
| **HTTP Crawling** | httpx + BeautifulSoup4 (async BFS) |
| **Browser Crawling** | Playwright (headless Chromium) |

---

## 📁 Project Structure

```
Page Pilot/
├── backend/
│   ├── main.py          # FastAPI app — all API endpoints
│   ├── scraper.py       # Async BFS crawler + Playwright crawler
│   ├── rag.py           # RAG pipeline — chunking, embeddings, ChromaDB, querying
│   ├── config.py        # Global settings (models, chunk size, DB path)
│   ├── requirements.txt # Python dependencies
│   ├── .env             # Your API key (not committed to git)
│   └── chroma_db/       # Local vector database (auto-created)
│
└── frontend/
    ├── src/
    │   ├── App.jsx      # Main React component
    │   ├── App.css      # All styles
    │   └── main.jsx     # Entry point
    └── index.html       # HTML shell with Page Pilot branding
```

---

## 🚀 Getting Started

### Prerequisites

- **Python** 3.11+
- **Node.js** 18+
- A **Google Gemini API key** → [Get one here](https://aistudio.google.com/app/apikey)

### 1. Clone the repository

```bash
git clone https://github.com/LoghaSurya/RAG-Powered-Website-Chatbot.git
cd RAG-Powered-Website-Chatbot
```

### 2. Set up the backend

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser (for Browser Mode)
playwright install chromium
```

### 3. Configure your API key

Create a `.env` file inside the `backend/` folder:

```
GOOGLE_API_KEY=your_gemini_api_key_here
```

### 4. Start the backend

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

### 5. Set up and start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## 🖥️ How to Use

1. **Enter a URL** — Paste any website address in the left sidebar
2. **Choose crawl settings** — Set max pages, depth, and optionally enable Browser Mode for JS-heavy sites
3. **Click Start Crawling** — The app crawls the site in the background; watch the live page count
4. **Ask questions** — Once ready, type any question about the website content
5. **Add more websites** — Toggle Append Mode to keep building your knowledge base
6. **Focus context** — Click any website pill to restrict answers to that specific site

---

## 🔌 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/crawl` | Start a background crawl |
| `GET` | `/api/status` | Poll crawl progress |
| `POST` | `/api/chat` | Ask a question |
| `GET` | `/api/domains` | List all indexed websites |
| `DELETE` | `/api/domains/{domain}` | Delete a specific website |
| `POST` | `/api/reset` | Wipe all data and reset |

---

## ⚙️ Configuration

Edit `backend/config.py` to adjust:

| Setting | Default | Description |
|---------|---------|-------------|
| `GENERATION_MODEL` | `gemini-2.5-flash` | Gemini model for answers |
| `CHUNK_SIZE` | `800` | Characters per text chunk |
| `CHUNK_OVERLAP` | `150` | Overlap between chunks |
| `TOP_K_RESULTS` | `5` | Chunks retrieved per query |
| `DEFAULT_MAX_PAGES` | `15` | Default crawl page limit |
| `DEFAULT_MAX_DEPTH` | `2` | Default link-follow depth |

---

## 📝 License

MIT License — feel free to use, modify, and distribute.

---

> Built with ❤️ using Google Gemini, ChromaDB, FastAPI, and React.
