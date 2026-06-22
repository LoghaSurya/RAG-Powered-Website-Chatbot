# RAG-Powered Website Chatbot

A high-performance chatbot that allows users to ingest website URLs, scrape their content, and query them using Retrieval-Augmented Generation (RAG) powered by Google Gemini.

To demonstrate a professional progress cycle, this repository is built in iterative stages from the first baseline approach to a fully recursive async full-stack solution.

## Approach 1: Simple Single-Page Scraper (Baseline)

Our first iteration is a simple Command Line Interface (CLI) tool that:
1. Accepts a single URL.
2. Performs a synchronous fetch using `HTTPX`.
3. Extracts visible text using `BeautifulSoup`.
4. Feeds the **entire raw webpage text** directly into the context window of `gemini-1.5-flash` to answer questions.

This approach serves as a baseline to test fetching speed, text parser formatting, and basic QA accuracy.

### Prerequisites

* Python 3.10+
* A Gemini API Key from Google AI Studio.

### Installation

1. Clone the repository and navigate to the directory:
   ```bash
   git clone https://github.com/LoghaSurya/RAG-Powered-Website-Chatbot.git
   cd "RAG-Powered Website Chatbot"
   ```

2. Create a virtual environment and activate it:
   ```bash
   python -m venv .venv
   # On Windows (PowerShell)
   .venv\Scripts\Activate.ps1
   # On macOS/Linux
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```

4. Create a `.env` file in the root directory and add your API key:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

### Usage (Approach 1)

Run the simple chatbot in interactive mode:
```bash
python backend/app_simple.py
```

Or query it directly via arguments:
```bash
python backend/app_simple.py --url "https://en.wikipedia.org/wiki/Retrieval-augmented_generation" --query "What is retrieval augmented generation?"
```
