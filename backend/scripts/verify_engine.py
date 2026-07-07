"""End-to-end smoke verification for the billing engine (no OpenAI key required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND_ROOT / "app" / "static" / "fixtures"

sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402
from app.engine.loader import load_metadata  # noqa: E402
from app.engine.summary_unit_validation import (  # noqa: E402
    SummaryValidateLine,
    validate_summary_units_local,
)
from app.engine.realtime.handlers_session import SENTENCES_PER_AI_BATCH  # noqa: E402


def ok(name: str) -> None:
    print(f"  PASS  {name}")


def fail(name: str, detail: str) -> None:
    print(f"  FAIL  {name}: {detail}")
    raise AssertionError(f"{name}: {detail}")


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def main() -> None:
    print("Billing Engine Verification")
    print("=" * 40)

    # 1. Metadata
    store = load_metadata()
    assert store.medexa, "medexa lookup empty"
    assert store.knows_cpt("97110"), "97110 missing from metadata"
    ok("Metadata loads")

    # 2. Local unit validation (CMS pooled — matches capture demo allocation)
    local = validate_summary_units_local(
        [
            SummaryValidateLine(cpt="97110", duration_minutes=8, summary_units=0),
            SummaryValidateLine(cpt="97140", duration_minutes=16, summary_units=1),
            SummaryValidateLine(cpt="97530", duration_minutes=28, summary_units=2),
        ],
        "cms_8_minute",
        store,
    )
    if local.overall_status != "PASSED":
        fail("CMS local validation", f"expected PASSED, got {local.overall_status}")
    ok("CMS 8-minute local unit validation (pooled 0/1/2)")

    client = TestClient(app)

    # 3. Health
    r = client.get("/health")
    if r.status_code != 200:
        fail("GET /health", str(r.status_code))
    ok("Health endpoint")

    # 4. Batch evaluate — capture demo
    payload = load_fixture("capture_demo_session.json")
    payload["billing_rule"] = "cms_8_minute"
    r = client.post("/billing/evaluate", json=payload)
    if r.status_code != 200:
        fail("POST /billing/evaluate", f"{r.status_code} {r.text[:300]}")
    report = r.json()
    codes = {c["cpt_code"]: c["units"] for c in report.get("billable_codes", [])}
    total = report.get("ui_display", {}).get("summary_cards", {}).get("session_units_total")
    expected_codes = {"97110": 0, "97140": 1, "97530": 2}
    if codes != expected_codes or total != 3:
        fail("Capture demo CMS units", f"expected {expected_codes} total 3, got {codes} total={total}")
    ok(f"Batch evaluate capture demo (CMS total={total}, codes={codes})")

    # 5. Stress test evaluate
    stress = load_fixture("stress_test_session.json")
    stress["billing_rule"] = "cms_8_minute"
    r = client.post("/billing/evaluate", json=stress)
    if r.status_code != 200:
        fail("POST /billing/evaluate stress", f"{r.status_code} {r.text[:300]}")
    ok("Batch evaluate stress test session")

    # 5b. AMA rule batch evaluate
    ama_payload = load_fixture("capture_demo_session.json")
    ama_payload["billing_rule"] = "ama_rule_of_8"
    r = client.post("/billing/evaluate", json=ama_payload)
    if r.status_code != 200:
        fail("POST /billing/evaluate AMA", f"{r.status_code} {r.text[:300]}")
    ama_codes = {c["cpt_code"]: c["units"] for c in r.json().get("billable_codes", [])}
    if ama_codes.get("97110") != 1 or ama_codes.get("97140") != 1 or ama_codes.get("97530") != 2:
        fail("AMA capture demo units", str(ama_codes))
    ok(f"Batch evaluate AMA rule (codes={ama_codes})")

    # 6. Summary validation (local by default — no OpenAI call)
    r = client.post(
        "/billing/validate-summary-units",
        json={
            "billing_rule": "cms_8_minute",
            "auditor": "local",
            "lines": [
                {"cpt": "97110", "duration_minutes": 8, "summary_units": 0},
                {"cpt": "97140", "duration_minutes": 16, "summary_units": 1},
                {"cpt": "97530", "duration_minutes": 28, "summary_units": 2},
            ],
        },
    )
    if r.status_code != 200:
        fail("validate-summary-units", f"{r.status_code} {r.text[:300]}")
    val = r.json()
    if val.get("overall_status") != "PASSED":
        fail("validate-summary-units result", val.get("overall_status"))
    if val.get("auditor") != "local":
        fail("validate-summary-units auditor", f"expected local, got {val.get('auditor')}")
    ok("Summary validation (local default, no API key)")

    r = client.post(
        "/billing/validate-summary-units",
        json={
            "billing_rule": "cms_8_minute",
            "auditor": "openai",
            "lines": [{"cpt": "97110", "duration_minutes": 15, "summary_units": 1}],
        },
    )
    if r.status_code != 503:
        fail("validate-summary-units openai without key", f"expected 503, got {r.status_code}")
    ok("Summary validation OpenAI auditor returns 503 without API key")

    # 7. OpenAI endpoints fail gracefully without key
    r = client.post(
        "/billing/llm-calculate-units",
        json={"billing_rule": "cms_8_minute", "codes": [{"cpt": "97110", "minutes": 15}]},
    )
    if r.status_code != 503:
        fail("llm-calculate-units without key", f"expected 503, got {r.status_code}")
    ok("LLM unit calculator returns 503 without API key")

    r = client.post(
        "/billing/compliance-audit",
        json={
            "billing_rule": "cms_8_minute",
            "rows": [{"cpt": "97110", "duration_minutes": 15, "body_region": "Shoulder"}],
        },
    )
    if r.status_code != 503:
        fail("compliance-audit without key", f"expected 503, got {r.status_code}")
    ok("Compliance audit returns 503 without API key")

    # 8. Live session workflow
    r = client.post(
        "/live/session",
        json={"client_name": "Verify Patient", "client_id": "V-001", "billing_rule": "cms_8_minute"},
    )
    if r.status_code != 200:
        fail("create live session", r.text[:300])
    session_id = r.json()["session"]["session_id"]
    ok(f"Create live session ({session_id[:8]}...)")

    # Sentence feeding + AI batch gating
    for batch in range(4):
        r = client.post(
            f"/live/session/{session_id}/transcript/sentence",
            json={"sentence": f"Sentence batch {batch}.", "sentence_count": 5},
        )
        if r.status_code != 200:
            fail(f"feed sentence batch {batch}", r.text[:300])
    count_after_20 = r.json()["session"]["sentences_fed_count"]
    if count_after_20 != 20:
        fail("sentence count after 4x5", f"expected 20, got {count_after_20}")
    ok("Sentence feed 4x5 (count=20, no AI threshold yet)")

    # Feed until sentence count crosses SENTENCES_PER_AI_BATCH (40 by default).
    count = count_after_20
    batch_num = 4
    while count // SENTENCES_PER_AI_BATCH < 1:
        r = client.post(
            f"/live/session/{session_id}/transcript/sentence",
            json={"sentence": f"Sentence batch {batch_num}.", "sentence_count": 5},
        )
        if r.status_code != 200:
            fail(f"feed sentence batch {batch_num}", r.text[:300])
        count = r.json()["session"]["sentences_fed_count"]
        batch_num += 1

    if count // SENTENCES_PER_AI_BATCH < 1:
        fail("AI batch threshold", f"expected to cross {SENTENCES_PER_AI_BATCH}-sentence threshold")
    ok(
        f"Sentence feed hits {SENTENCES_PER_AI_BATCH}-sentence AI threshold "
        f"(count={count}, task schedules safely)"
    )

    # CPT detect + lifecycle
    r = client.post(
        f"/live/session/{session_id}/icd",
        json={"icd10_code": "M25.511"},
    )
    if r.status_code != 200:
        fail("add ICD", r.text[:300])
    ok("Add ICD to live session")

    r = client.post(
        f"/live/session/{session_id}/cpt/detect",
        json={"cpt_code": "97110"},
    )
    if r.status_code != 200:
        fail("detect CPT", r.text[:300])
    ok("Detect CPT 97110")

    r = client.post(f"/live/session/{session_id}/cpt/start", json={"cpt_code": "97110"})
    if r.status_code != 200:
        fail("start CPT", r.text[:300])
    ok("Start CPT timer")

    r = client.post(
        f"/live/session/{session_id}/cpt/end",
        json={"cpt_code": "97110", "duration_minutes": 15},
    )
    if r.status_code != 200:
        fail("end CPT", r.text[:300])
    units = next(
        (row["units"] for row in r.json()["session"]["cpts"] if row["cpt_code"] == "97110"),
        None,
    )
    if units != 1:
        fail("CPT 97110 units after 15 min CMS", f"expected 1, got {units}")
    ok("End CPT with duration (15 min -> 1 unit CMS)")

    # 9. Prototype page
    r = client.get("/prototype")
    if r.status_code != 200:
        fail("GET /prototype", str(r.status_code))
    ok("Prototype page serves")

    print("=" * 40)
    print("All checks passed.")


if __name__ == "__main__":
    main()
