from __future__ import annotations

import gzip
import json
from pathlib import Path

from . import config, db

DEFAULT = Path(config.ROOT) / "var" / "state.json.gz"


def save(path: Path | None = None) -> dict:
    target = path or DEFAULT
    target.parent.mkdir(parents=True, exist_ok=True)
    with db.session() as conn:
        seen = [r["id"] for r in conn.execute("SELECT id FROM postings")]
        alerted = [
            [r["posting_id"], r["watchlist"], r["sent_at"]]
            for r in conn.execute(
                "SELECT posting_id, watchlist, sent_at FROM alerts_sent"
            )
        ]
    payload = {"profile": config.PROFILE.name, "seen": seen, "alerted": alerted}
    with gzip.open(target, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return {
        "path": str(target),
        "seen": len(seen),
        "alerted": len(alerted),
        "size_kb": round(target.stat().st_size / 1024),
    }


def load(path: Path | None = None) -> dict:
    source = path or DEFAULT
    if not source.exists():
        return {"seen": 0, "alerted": 0, "missing": True}
    with gzip.open(source, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)

    db.init()
    with db.session() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO postings (id, company_slug, eligible, processed) "
            "VALUES (?, '', 0, 1)",
            [(pid,) for pid in payload.get("seen", [])],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO alerts_sent (posting_id, watchlist, sent_at) "
            "VALUES (?,?,?)",
            payload.get("alerted", []),
        )
    return {
        "seen": len(payload.get("seen", [])),
        "alerted": len(payload.get("alerted", [])),
        "missing": False,
    }
