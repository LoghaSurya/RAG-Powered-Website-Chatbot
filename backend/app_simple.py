import os
import sys
import argparse
from bs4 import BeautifulSoup
import httpx
from google import genai
from google.genai.errors import APIError
from dotenv import load_dotenv

# Load environment variables (e.g. GEMINI_API_KEY)
load_dotenv()

def scrape_page(url: str) -> str:
    """
    Scrapes a single URL and extracts visible text content.
    This is a simple baseline scraper.
    """
    print(f"\n[*] Fetching content from: {url}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = httpx.get(url, headers=headers, follow_redirects=True, timeout=10.0)
        response.raise_for_status()
    except Exception as e:
        print(f"[!] Error fetching URL: {e}")
        sys.exit(1)
        
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Remove script, style, and element boilerplate
    for script_or_style in soup(["script", "style", "nav", "footer", "header", "aside"]):
        script_or_style.decompose()
        
    # Get text and clean up whitespaces
    text = soup.get_text(separator="\n")
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase for phrase in lines if phrase)
    cleaned_text = "\n".join(chunks)
    
    print(f"[+] Successfully scraped {len(cleaned_text)} characters.")
    return cleaned_text

def get_answer_from_gemini(context: str, question: str, api_key: str = None) -> str:
    """
    Answers a question by placing the entire scraped text directly into the prompt.
    No vector database retrieval is used in this first approach.
    """
    # Initialize the modern Google Gen AI Client
    # It automatically picks up GEMINI_API_KEY from environment if api_key is None
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"[!] Failed to initialize Gemini Client: {e}")
        print("[!] Please make sure GEMINI_API_KEY is set in your environment or a .env file.")
        sys.exit(1)
        
    prompt = f"""You are a helpful assistant. Answer the user's question accurately using ONLY the provided website context.
If the answer cannot be found in the context, state that the information is not available on the page.

Website Context:
---
{context}
---

Question: {question}

Answer:"""

    try:
        # Using gemini-1.5-flash for low-latency, fast generation
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        return response.text
    except APIError as e:
        return f"API Error: {e.message}"
    except Exception as e:
        return f"Unexpected Error: {str(e)}"

def main():
    parser = argparse.ArgumentParser(description="Approach 1: Simple Webpage Q&A Chatbot")
    parser.add_argument("--url", help="The URL of the webpage to ingest")
    parser.add_argument("--query", help="The question you want to ask about the webpage")
    args = parser.parse_args()

    # Verify API key
    if not os.environ.get("GEMINI_API_KEY"):
        print("[!] Warning: GEMINI_API_KEY environment variable is not set.")
        api_key_input = input("Please enter your Gemini API Key to proceed (or press Enter if configured elsewhere): ").strip()
        if api_key_input:
            os.environ["GEMINI_API_KEY"] = api_key_input
        else:
            print("[!] API key is required. Exiting.")
            sys.exit(1)

    url = args.url
    if not url:
        url = input("Enter website URL to ingest (e.g. https://en.wikipedia.org/wiki/Retrieval-augmented_generation): ").strip()
        if not url:
            print("[!] URL cannot be empty.")
            sys.exit(1)

    # Scrape content
    context = scrape_page(url)

    if args.query:
        # Run single query
        answer = get_answer_from_gemini(context, args.query)
        print(f"\n[Question]: {args.query}")
        print(f"[Answer]:\n{answer}")
    else:
        # Start interactive chat loop
        print("\n[+] Entering chat loop. Type 'exit' or 'quit' to stop.")
        while True:
            try:
                query = input("\nAsk a question about the page: ").strip()
                if not query:
                    continue
                if query.lower() in ["exit", "quit"]:
                    break
                answer = get_answer_from_gemini(context, query)
                print(f"\n[Answer]:\n{answer}")
            except KeyboardInterrupt:
                break
        print("\n[*] Exiting chat. Goodbye!")

if __name__ == "__main__":
    main()
