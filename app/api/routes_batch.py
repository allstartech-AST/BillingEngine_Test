from fastapi import APIRouter, HTTPException
from app.engine.loader import load_metadata
from app.engine.pipeline import evaluate_session
from app.models.input import BillingSessionInput
from app.models.output import BillingReport

router = APIRouter(prefix="/billing", tags=["batch"])


@router.post("/evaluate", response_model=BillingReport)
def billing_evaluate(payload: BillingSessionInput) -> BillingReport:
    try:
        store = load_metadata()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Billing metadata failed to load",
                "error": str(exc),
                "type": type(exc).__name__,
                "hint": "Ensure JSON data files exist in ProperData and loader uses encoding=utf-8-sig",
            },
        ) from exc
    return evaluate_session(payload, store)
