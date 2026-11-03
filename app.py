import os

from flask import Flask, jsonify, request, send_from_directory

from ai import explain
from plan_parser import parse
from rules import analyze

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="")
# /api/explain sends the analysis back as JSON, which is larger than the plan XML.
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify(status="ok")


def _plan_bytes(req):
    if req.form.get("sample"):
        with open(os.path.join(BASE, "sample_plans", "slow_query.sqlplan"), "rb") as fh:
            return fh.read()
    f = req.files.get("plan")
    if not f:
        raise ValueError("Choose a plan file (.sqlplan or .xml).")
    return f.read()


@app.post("/api/analyze")
def analyze_route():
    try:
        plan = parse(_plan_bytes(request))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    findings = analyze(plan)
    return jsonify({**plan, "findings": findings})


@app.post("/api/explain")
def explain_route():
    # The browser sends back what /api/analyze returned, so the plan is parsed and analyzed once.
    data = request.get_json(silent=True)
    plan = data.get("plan") if isinstance(data, dict) else None
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(plan, dict) or not isinstance(findings, list):
        return jsonify(error="Send the analysis returned by /api/analyze."), 400
    try:
        ai, status = explain(plan, findings)
    except Exception:  # Malformed tree or findings from the browser.
        return jsonify(error="The analysis data was not usable. Upload the plan again."), 400
    return jsonify(ai=ai, ai_status=status)


@app.errorhandler(413)
def too_big(_):
    return jsonify(error="That request is larger than 16 MB."), 413


if __name__ == "__main__":
    app.run(debug=True)
