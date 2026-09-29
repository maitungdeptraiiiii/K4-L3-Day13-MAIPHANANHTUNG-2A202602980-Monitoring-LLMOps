import re

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BODY = {"user_id": "u1", "session_id": "s1", "feature": "qa", "message": "hello"}


def test_generates_request_id_and_timing_headers() -> None:
    r = client.post("/chat", json=BODY)
    assert re.fullmatch(r"req-[0-9a-f]{8}", r.headers["x-request-id"])
    assert r.headers["x-response-time-ms"].isdigit()
    assert r.json()["correlation_id"] == r.headers["x-request-id"]


def test_reuses_incoming_request_id() -> None:
    r = client.post("/chat", json=BODY, headers={"x-request-id": "req-abc12345"})
    assert r.headers["x-request-id"] == "req-abc12345"
