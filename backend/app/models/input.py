from pydantic import BaseModel, Field


class ClientInfo(BaseModel):
    client_name: str
    client_id: str


class SessionMetadata(BaseModel):
    session_start: str
    session_end: str


class DetectedCptCode(BaseModel):
    cpt_code: str
    sequence: int
    timestamp_start: str
    timestamp_end: str


class BillingSessionInput(BaseModel):
    client_info: ClientInfo
    session_metadata: SessionMetadata
    diagnoses: dict[str, str]
    billing_detection_summary: dict | None = None
    detected_cpt_codes: list[DetectedCptCode]
    whole_transcript: str = ""
    primary_icd10: str | None = None
    billing_rule: str = "cms_8_minute"
