"""Explicit endpoint selection shared by interactive and unattended clients."""
import os
from urllib.parse import urlsplit

DEFAULT_API_URL = "https://data2.deadtrees.earth/api/v1/"
PROD_SUPABASE_URL = "https://supabase.deadtrees.earth"
PROD_SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ewogICJyb2xlIjogImFub24iLAogICJpc3MiOiAic3VwYWJhc2UiLAogICJpYXQiOiAxNzQwODcwMDAwLAogICJleHAiOiAxODk4NjM2NDAwCn0.A3HdTofLNcrRrtDDbDAP9kRBobxXqnUKB6IYHvM6da4"


def validate_url(value: str) -> str:
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.scheme not in {"http", "https"}):
        raise ValueError("Use an HTTP(S) endpoint without credentials, query or fragment")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote endpoints require HTTPS")
    return value.rstrip("/")


def supabase_config(api_url: str) -> tuple[str, str]:
    api_url = validate_url(api_url)
    url, key = os.getenv("DEADTREES_SUPABASE_URL"), os.getenv("DEADTREES_SUPABASE_KEY")
    if url or key:
        if not (url and key):
            raise ValueError("Set both DEADTREES_SUPABASE_URL and DEADTREES_SUPABASE_KEY")
        return validate_url(url), key
    if api_url == DEFAULT_API_URL.rstrip("/"):
        return PROD_SUPABASE_URL, PROD_SUPABASE_KEY
    raise ValueError("Custom API requires explicit DEADTREES_SUPABASE_URL and DEADTREES_SUPABASE_KEY; no shared local default")
