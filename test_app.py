"""Offline self-check for the /api/explain trust boundary. Run: python test_app.py"""
import os

from app import app

client = app.test_client()
r = client.post("/api/analyze", data={"sample": "1"}, content_type="multipart/form-data")
assert r.status_code == 200, r.data
analysis = r.get_json()
plan = {k: v for k, v in analysis.items() if k != "findings"}

# A request with no file is a clean 400, not a 500.
assert client.post("/api/analyze", data={}, content_type="multipart/form-data").status_code == 400

# Bad bodies are rejected instead of crashing the route.
assert client.post("/api/explain", data="nope").status_code == 400
assert client.post("/api/explain", json={"plan": "x", "findings": []}).status_code == 400
os.environ["GEMINI_API_KEY"] = "dummy"  # lets explain() reach the plan data, no network call
assert client.post("/api/explain", json={"plan": {}, "findings": []}).status_code == 400
os.environ.pop("GEMINI_API_KEY", None)

# The real analysis is accepted; with no key the explanation is skipped, not an error.
r = client.post("/api/explain", json={"plan": plan, "findings": analysis["findings"]})
assert r.status_code == 200, r.data
assert isinstance(r.get_json()["ai_status"], str), r.data
print("ok")
