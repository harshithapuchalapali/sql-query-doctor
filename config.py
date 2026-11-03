"""Runtime settings and .env loading, kept out of the modules that use them."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
SAMPLE_PLAN = os.path.join(BASE_DIR, "sample_plans", "slow_query.sqlplan")
# /api/explain sends the analysis back as JSON, which is larger than the plan XML.
MAX_UPLOAD_BYTES = 16 * 1024 * 1024


def load_env():
    """Read .env next to this file so the key works without exporting it in every shell."""
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        k, _, v = line.strip().partition("=")
        if k and not k.startswith("#"):
            os.environ.setdefault(k, v)


def gemini_key():
    return os.environ.get("GEMINI_API_KEY")


def gemini_model():
    return os.environ.get("GEMINI_MODEL") or "gemini-flash-lite-latest"
