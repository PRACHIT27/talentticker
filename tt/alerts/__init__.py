"""Watchlists and the email that goes out when something matches."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import db
from . import mailer, watchlist

log = logging.getLogger("tt.alerts")


def dispatch(posting_ids: list[str]) -> dict:
    """Email whichever of these new postings match an active watchlist."""
    sent = {"watchlists": 0, "postings": 0, "delivered": 0}
    if not posting_ids:
        return sent

    with db.session() as conn:
        watchlist.ensure_defaults(conn)
        grouped = watchlist.pending(conn, posting_ids)
        for name, postings in grouped.items():
            subject, text, html = mailer.render(name, postings)
            delivered = mailer.send(subject, text, html)

            sent["watchlists"] += 1
            sent["postings"] += len(postings)
            sent["delivered"] += int(delivered)

            # Only record it as sent when it was sent. This used to run
            # unconditionally, so a dry run or an SMTP outage marked everything
            # delivered and the real mail never went out.
            if not delivered:
                continue

            watchlist.mark_sent(
                conn, name, [p["id"] for p in postings],
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            conn.executemany(
                "UPDATE postings SET alerted=1 WHERE id=?",
                [(p["id"],) for p in postings],
            )
    return sent


__all__ = ["dispatch", "mailer", "watchlist"]
