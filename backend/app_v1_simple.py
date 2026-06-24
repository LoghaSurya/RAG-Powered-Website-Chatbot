import os
import sys
import argparse
from bs4 import BeautifulSoup
import httpx
from google import genai
from dotenv import load_dotenv

# Load API key from .env file if it exists
load_dotenv()

# ──────────────────────────────────────────────
# STEP 1: Scrape a single webpage
# ──────────────────────────────────────────────

def scrape_page(url: str) -> str:
    """
    Fetches a single URL and extracts all visible text.
    No chunking, no vector DB — just raw text from one page.
    """
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
    except httpx.HTTPStatusError as e:
        print(f"[!] HTTP Error {e.response.status_code} for URL: {url}")
        sys.exit(1)
    except Exception as e:
        print(f"[!] Failed to fetch page: {e}")
        sys.exit(1)

    # Parse HTML
    soup = BeautifulSoup(response.text, "html.parser")

    # Remove clutter: scripts, styles, nav, footer etc.
    for noise in soup(["script", "style", "nav", "footer", "header", "aside"]):
        noise.decompose()

    # Extract and clean text
    raw_text = soup.get_text(separator="\n")
    lines = (line.strip() for line in raw_text.splitlines())
    clean_text = "\n".join(line for line in lines if line)

    print(f"[+] Scraped {len(clean_text):,} characters from the page.")
    return clean_text


# ──────────────────────────────────────────────
# STEP 2: Ask Gemini using the full page text
# ──────────────────────────────────────────────

def ask_gemini(context: str, question: str) -> str:
    """
    Sends the entire scraped page text + the user question
    directly to Gemini as one big prompt.

    Limitation: Only works if the page text fits within
    the model's context window (~1M tokens for gemini-1.5-flash).
    No retrieval — no vector DB — just plain prompting.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "[!] GEMINI_API_KEY is not set. Please add it to your .env file."

    client = genai.Client(api_key=api_key)

    prompt = f"""You are a helpful assistant that answers questions about a webpage.
Use ONLY the webpage content provided below to answer.
If the answer is not found in the content, say "This information is not available on the page."

=== WEBPAGE CONTENT ===
{context}
=======================

Question: {question}

Answer:"""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"[!] Gemini API error: {e}"


# ──────────────────────────────────────────────
# MAIN: CLI entry point
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Approach 1 — Simple single-page chatbot (no vector DB)"
    )
    parser.add_argument("--url", help="URL of the webpage to ingest")
    parser.add_argument("--query", help="Question to ask about the page")
    args = parser.parse_args()

    # Get URL
    url = args.url or input("Enter the webpage URL to ingest: ").strip()
    if not url:
        print("[!] URL cannot be empty.")
        sys.exit(1)

    # Scrape the page
    page_text = scrape_page(url)

    if args.query:
        # Single query mode
        answer = ask_gemini(page_text, args.query)
        print(f"\nQ: {args.query}\nA: {answer}")
    else:
        # Interactive chat loop
        print("\n[+] Page ingested! Start asking questions. Type 'exit' to quit.\n")
        while True:
            try:
                question = input("You: ").strip()
                if not question:
                    continue
                if question.lower() in ["exit", "quit"]:
                    print("Goodbye!")
                    break
                answer = ask_gemini(page_text, question)
                print(f"\nBot: {answer}\n")
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break


if __name__ == "__main__":
    main()
