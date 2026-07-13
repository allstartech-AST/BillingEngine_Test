"""Tests for Groq/OpenAI retry-after parsing."""

from app.engine.llm_errors import extract_retry_after, retry_after_from_exception


def test_extract_retry_after_groq_try_again_in() -> None:
    message = (
        "Rate limit reached for model `llama-3.1-8b-instant` ... "
        "Please try again in 24.2s."
    )
    assert extract_retry_after(message) == 24.2


def test_extract_retry_after_openai_style() -> None:
    assert extract_retry_after("Please retry after 9.5 seconds") == 9.5


def test_retry_after_from_exception_string_body() -> None:
    exc = Exception("Error code: 429 - Please try again in 18.07s")
    assert retry_after_from_exception(exc) == 18.07
