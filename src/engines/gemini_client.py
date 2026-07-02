"""Google Gemini chat completion client. No web grounding — plain model knowledge.

Uses the google-genai SDK (the supported successor to the deprecated
google-generativeai package).
"""
import os

from google import genai

# gemini-2.5-flash: included in the free API tier (Pro models have zero free
# quota) and matches the consumer Gemini app default, which is what
# prospective students actually see.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

ENGINE_NAME = "gemini"


def call(prompt_text: str) -> dict:
    """Returns {'raw_response': str, 'citations': None}."""
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(model=MODEL, contents=prompt_text)
    return {"raw_response": response.text, "citations": None}
