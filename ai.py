"""Optional plain-English explanation using the Gemini API free tier (REST, no SDK)."""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from rules import walk

SYSTEM = (
    "You are a SQL Server performance tutor explaining an execution plan to a beginner. "
    "Use only the facts provided. Never invent table or column names. If information is missing, say so. "
    'Reply with JSON only: {"summary": str, "why_slow": [str], '
    '"fixes": [{"title": str, "explanation": str, "sql": str}], "risks": [str]}'
)
_cache = {}

# Load .env next to this file so the key works without exporting it in every shell.
_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV):
    for line in open(_ENV, encoding="utf-8"):
        k, _, v = line.strip().partition("=")
        if k and not k.startswith("#"):
            os.environ.setdefault(k, v)


def _post(url, key, body, tries=3):
    """Retry the transient 429/5xx errors Gemini returns under load."""
    last = "unknown error"
    for i in range(tries):
        req = urllib.request.Request(url, json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(raw)["error"]["message"].splitlines()[0]
            except Exception:
                msg = ""
            last = f"HTTP {e.code}{': ' + msg if msg else ''}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        if i + 1 < tries:
            time.sleep(2 * (i + 1))
    raise RuntimeError(last)


def _ask(key, body):
    # Each free-tier model has its own daily quota, so move to the next one when one is used up.
    models = dict.fromkeys([os.environ.get("GEMINI_MODEL") or "gemini-flash-lite-latest",
                            "gemini-3.6-flash", "gemini-flash-lite-latest"])
    errors = []
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            text = _post(url, key, body)["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text.strip().removeprefix("```json").removesuffix("```"))
        except Exception as e:
            errors.append(str(e)[:140])
    raise RuntimeError("; ".join(errors))


def explain(plan, findings):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, "Set GEMINI_API_KEY to turn on AI explanations. Rule-based findings are shown below."
    top = sorted(walk(plan["tree"]), key=lambda n: -n["cost_pct"])[:5]
    blob = json.dumps({
        "query": plan["statement"][:1500],
        "top_operators": [{k: n[k] for k in ("physical_op", "object", "cost_pct", "est_rows", "actual_rows")} for n in top],
        "findings": [{k: f[k] for k in ("severity", "title", "detail", "fix_sql")} for f in findings],
    }, sort_keys=True)
    h = hashlib.sha256(blob.encode()).hexdigest()
    if h in _cache:
        return _cache[h], "ok"
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"parts": [{"text": blob}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    try:
        data = _ask(key, body)
    except Exception as e:
        return None, f"The AI is unavailable right now ({e}). Rule-based findings are still shown."
    _cache[h] = data
    return data, "ok"
