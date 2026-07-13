"""Tests for global LLM request throttling."""

import asyncio
import time

from app.engine import llm_provider


def test_llm_throttle_spaces_requests_after_completion(monkeypatch):
    monkeypatch.setattr(llm_provider, "LLM_REQUEST_INTERVAL_SECONDS", 0.25)
    monkeypatch.setattr(llm_provider, "LLM_GROQ_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(llm_provider, "llm_provider_name", lambda: "OpenAI")
    llm_provider._last_llm_request_finished_at = None

    start_times: list[float] = []

    async def fake_call() -> int:
        start_times.append(time.monotonic())
        await asyncio.sleep(0.05)
        return 1

    async def run() -> None:
        await llm_provider._run_throttled(fake_call)
        await llm_provider._run_throttled(fake_call)
        await llm_provider._run_throttled(fake_call)

    asyncio.run(run())

    assert len(start_times) == 3
    assert start_times[1] - start_times[0] >= 0.24
    assert start_times[2] - start_times[1] >= 0.24
