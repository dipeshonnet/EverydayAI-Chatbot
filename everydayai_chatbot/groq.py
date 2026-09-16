"""Groq configuration and credential-safe API error messages."""

from llama_index.llms.openai_like import OpenAILike
from openai import APIConnectionError, APIStatusError, APITimeoutError

from everydayai_chatbot.settings import AppSettings


GROQ_API_BASE = "https://api.groq.com/openai/v1"


def build_llm(settings: AppSettings, api_key: str) -> OpenAILike:
    additional_kwargs = {}
    if settings.reasoning_effort:
        additional_kwargs["reasoning_effort"] = settings.reasoning_effort
    return OpenAILike(
        api_key=api_key,
        api_base=GROQ_API_BASE,
        model=settings.chat_model,
        is_chat_model=True,
        is_function_calling_model=False,
        # A conservative prompt budget also works with smaller Groq models.
        context_window=32768,
        max_tokens=1024,
        temperature=settings.temperature,
        additional_kwargs=additional_kwargs,
        timeout=60.0,
        max_retries=2,
    )


def describe_api_error(exc: Exception) -> str:
    """Classify provider errors without echoing response bodies or credentials."""
    if isinstance(exc, APITimeoutError):
        return "The Groq request timed out. Please try again."
    if isinstance(exc, APIConnectionError):
        return "Could not connect to Groq. Check the network connection and try again."
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        # Inspect only for classification; never show the provider's raw error.
        detail = str(exc.body).lower()
        if status == 401 or any(term in detail for term in (
            "incorrect api key", "invalid api key", "invalid_api_key", "invalid token",
        )):
            return "Groq authentication failed. Check GROQ_API_KEY."
        if status == 402 or any(term in detail for term in (
            "insufficient_quota", "credit", "billing", "spending limit", "spend limit",
        )):
            return "Groq billing or credit limit reached. Check credits and spending limits in the Groq console."
        if status in (403, 404):
            return "Groq access was denied or the model is unavailable. Check the key's permissions and CHAT_MODEL."
        if status == 429:
            return "Groq rate limit reached. Please wait and try again."
        if status == 400:
            return "Groq rejected the request. Check CHAT_MODEL and CHAT_REASONING_EFFORT compatibility."
        if status >= 500:
            return "Groq is temporarily unavailable. Please try again later."
        return f"Groq request failed (HTTP {status})."
    return "The assistant could not complete the request. Please try again."
