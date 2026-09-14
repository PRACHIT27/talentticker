"""Settings, all read from the environment with sensible defaults."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is a convenience, not a requirement
    pass

ROOT = Path(__file__).resolve().parent.parent

# One database per profile. `eligible` means something different for each, and
# sharing a table would mean every query carrying a profile filter.
from .profiles import active as _active_profile  # noqa: E402

PROFILE = _active_profile()
DB_PATH = Path(os.getenv("TT_DB", ROOT / "var" / PROFILE.db_name))
MAX_YEARS = PROFILE.max_years
COMPANIES_FILE = Path(os.getenv("TT_COMPANIES", ROOT / "data" / "companies.yml"))

MODEL = os.getenv("TT_MODEL", "claude-opus-5")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# Deliberately not read from ANTHROPIC_BASE_URL: other tooling sets that to a
# local proxy, and inheriting it silently redirects these calls. Set
# TT_ANTHROPIC_BASE_URL only if you really mean to point somewhere else.
ANTHROPIC_BASE_URL = os.getenv("TT_ANTHROPIC_BASE_URL", "https://api.anthropic.com")

# Separate from "is a key set". A key can be present and still have no credit -
# API billing is independent of a Claude Code or chat subscription - and in that
# state the scheduled write-ups would fail every night for nothing. This is the
# switch that decides whether anything paid runs on a schedule.
CLAUDE_ENABLED = os.getenv("TT_CLAUDE_ENABLED", "1") == "1"

# The profile wins, so two people sharing one install each get their own.
ALERT_TO = PROFILE.alert_to or os.getenv("TT_ALERT_TO", "")
SMTP_HOST = os.getenv("TT_SMTP_HOST", "")
SMTP_PORT = int(os.getenv("TT_SMTP_PORT", "587"))
SMTP_USER = os.getenv("TT_SMTP_USER", "")
SMTP_PASS = os.getenv("TT_SMTP_PASS", "")
SMTP_FROM = os.getenv("TT_SMTP_FROM", "") or SMTP_USER
SMTP_DRY_RUN = os.getenv("TT_SMTP_DRY_RUN", "0") == "1"


# Politeness settings for the job board fetchers.
USER_AGENT = os.getenv(
    "TT_USER_AGENT",
    "talentticker/0.1 (early-career job market research; contact via repo)",
)
HTTP_TIMEOUT = float(os.getenv("TT_HTTP_TIMEOUT", "30"))
FETCH_CONCURRENCY = int(os.getenv("TT_FETCH_CONCURRENCY", "8"))

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
