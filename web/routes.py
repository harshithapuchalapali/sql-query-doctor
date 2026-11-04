"""HTTP boundary: read the request, call the core, return JSON."""
from flask import Blueprint, jsonify, request, send_from_directory

from config import SAMPLE_PLAN, STATIC_DIR, gemini_key, gemini_model
from core.explain import explain
from core.findings import analyze
from core.plan import PlanError, parse

bp = Blueprint("api", __name__)


@bp.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@bp.get("/api/health")
def health():
    return jsonify(status="ok")


def _plan_bytes(req):
    if req.form.get("sample"):
        with open(SAMPLE_PLAN, "rb") as fh:
            return fh.read()
    f = req.files.get("plan")
    if not f:
        raise PlanError("Choose a plan file (.sqlplan or .xml).")
    return f.read()


@bp.post("/api/analyze")
def analyze_route():
    try:
        plan = parse(_plan_bytes(request))
    except PlanError as e:
        return jsonify(error=str(e)), 400
    findings = analyze(plan)
    try:
        return jsonify({**plan, "findings": findings})
    except RecursionError:
        # Python's JSON encoder is recursive, so a plan nested deeper than this cannot be returned.
        return jsonify(error="This plan is nested too deeply to display. Upload a plan with fewer levels."), 400


@bp.post("/api/explain")
def explain_route():
    # The browser sends back what /api/analyze returned, so the plan is parsed and analyzed once.
    data = request.get_json(silent=True)
    plan = data.get("plan") if isinstance(data, dict) else None
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(plan, dict) or not isinstance(findings, list):
        return jsonify(error="Send the analysis returned by /api/analyze."), 400
    try:
        ai, status = explain(plan, findings, gemini_key(), gemini_model())
    except Exception:  # Malformed tree or findings from the browser.
        return jsonify(error="The analysis data was not usable. Upload the plan again."), 400
    return jsonify(ai=ai, ai_status=status)
