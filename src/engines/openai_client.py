"""OpenAI chat completion client. No web grounding — plain model knowledge."""
import os

from openai import OpenAI

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

ENGINE_NAME = "openai"


def call(prompt_text: str) -> dict:
    """Returns {'raw_response': str, 'citations': None}."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt_text}],
    )
    text = response.choices[0].message.content
    return {"raw_response": text, "citations": None}
