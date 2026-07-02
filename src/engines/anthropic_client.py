"""Anthropic chat completion client. No web grounding — plain model knowledge."""
import os

from anthropic import Anthropic

# Verify this against current model availability at build/run time — flagship
# model ids change. Override via ANTHROPIC_MODEL in .env without touching code.
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

ENGINE_NAME = "anthropic"


def call(prompt_text: str) -> dict:
    """Returns {'raw_response': str, 'citations': None}."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt_text}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return {"raw_response": text, "citations": None}
