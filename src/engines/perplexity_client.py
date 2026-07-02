"""Perplexity search-grounded chat completion client (REST API).

Search-grounded — the response includes a `citations` array of URLs the
model actually pulled from. That's a stronger signal than a text mention,
so we surface it separately for the parser to cross-check.
"""
import os

import requests

MODEL = os.environ.get("PERPLEXITY_MODEL", "sonar-pro")
API_URL = "https://api.perplexity.ai/chat/completions"

ENGINE_NAME = "perplexity"


def call(prompt_text: str) -> dict:
    """Returns {'raw_response': str, 'citations': list[str] | None}."""
    headers = {
        "Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt_text}],
    }
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    citations = data.get("citations")
    return {"raw_response": text, "citations": citations}
