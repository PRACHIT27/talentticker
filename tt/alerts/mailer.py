"""Send new-job alerts by email.

Works with any SMTP server. Set TT_SMTP_DRY_RUN=1 while you are tuning your
watchlists and the messages print to the console instead of being sent, so you
can see what you would have received without filling your inbox.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr

from .. import config
from ..extract.sponsorship import LABELS as SPONSOR_LABELS

log = logging.getLogger("tt.mailer")

# Colours for the sponsorship badge in the HTML mail. Every one ships with
# its label, so colour never carries the meaning on its own.
SPONSOR_COLOURS = {
    "yes": ("#0a6b2a", "#e4f6e8"),
    "no": ("#8f2020", "#fbe6e6"),
    "clearance": ("#7a5200", "#fdf1dc"),
    "unknown": ("#555555", "#eeeeee"),
}


def _money(low, high) -> str:
    if not low:
        return ""
    if high and high != low:
        return f"${low:,} - ${high:,}"
    return f"${low:,}"


def _years(posting: dict) -> str:
    low = posting.get("yoe_min")
    if low is None:
        return "not stated"
    high = posting.get("yoe_max")
    if high and high != low:
        return f"{low:g}-{high:g} years"
    return f"{low:g}+ years" if low else "no experience required"


def render(watchlist_name: str, postings: list[dict]) -> tuple[str, str, str]:
    """Build the subject line, plain text body and HTML body."""
    count = len(postings)
    lead = postings[0]
    # The profile goes in the subject. Two profiles running side by side used to
    # produce identical subject lines, so a product alert and an engineering one
    # were indistinguishable in the inbox and read as duplicates.
    tag = config.PROFILE.label.split("·")[0].strip() or config.PROFILE.name
    if count == 1:
        subject = f"[{tag}] New: {lead['title']} at {lead['company_name']}"
    else:
        others = len({p["company_name"] for p in postings})
        subject = f"[{tag}] {count} new early-career roles ({others} companies)"

    text_lines = [f"{count} new posting(s) matching '{watchlist_name}'.", ""]
    html_parts = [
        "<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
        "max-width:640px;color:#111\">",
        f"<p style='color:#555;font-size:14px'>{count} new posting(s) matching "
        f"<b>{watchlist_name}</b></p>",
    ]

    for posting in postings:
        where = posting.get("metro") or posting.get("location_raw") or "location not given"
        if posting.get("remote"):
            where += " (remote)"
        pay = _money(posting.get("salary_min"), posting.get("salary_max"))
        skills = ", ".join(posting.get("skills", [])[:8])

        status = posting.get("sponsorship") or "unknown"
        sponsor_label = SPONSOR_LABELS.get(status, "Not stated")

        text_lines += [
            f"{posting['title']}",
            f"  {posting['company_name']} - {where}",
            f"  experience: {_years(posting)}" + (f"  pay: {pay}" if pay else ""),
            f"  sponsorship: {sponsor_label}",
            f"  skills: {skills}" if skills else "",
            f"  {posting.get('url','')}",
            "",
        ]

        html_parts.append(
            "<div style='border:1px solid #e3e3e3;border-radius:10px;padding:14px;"
            "margin:12px 0'>"
            f"<div style='font-size:16px;font-weight:600'>"
            f"<a href='{posting.get('url','')}' style='color:#0b57d0;text-decoration:none'>"
            f"{posting['title']}</a></div>"
            f"<div style='color:#444;margin-top:4px'>{posting['company_name']} &middot; {where}</div>"
            f"<div style='color:#666;font-size:13px;margin-top:6px'>"
            f"Experience: {_years(posting)}"
            + (f" &middot; {pay}" if pay else "")
            + "</div>"
            + "<div style='margin-top:8px'>"
            + f"<span style='background:{SPONSOR_COLOURS.get(status, SPONSOR_COLOURS['unknown'])[1]};"
              f"color:{SPONSOR_COLOURS.get(status, SPONSOR_COLOURS['unknown'])[0]};"
              "border-radius:99px;padding:2px 9px;font-size:12px;font-weight:600'>"
            + f"{sponsor_label}</span></div>"
            + (f"<div style='color:#666;font-size:13px;margin-top:6px'>{skills}</div>"
               if skills else "")
            + "</div>"
        )

    html_parts.append(
        "<p style='color:#888;font-size:12px'>Sent by TalentTicker. "
        "Edit your watchlists to change what arrives here.</p></div>"
    )
    return subject, "\n".join(l for l in text_lines if l is not None), "".join(html_parts)


def send(subject: str, text: str, html: str, to: str = "") -> bool:
    """Deliver one message. Returns True when it actually went out."""
    recipient = to or config.ALERT_TO
    if not recipient:
        log.warning("no TT_ALERT_TO set; skipping email")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(("TalentTicker", config.SMTP_FROM or "talentticker@localhost"))
    message["To"] = recipient
    message["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    if config.SMTP_DRY_RUN or not config.SMTP_HOST:
        print("\n" + "=" * 70)
        print(f"[dry run] would email {recipient}")
        print(f"Subject: {subject}")
        print("-" * 70)
        print(text)
        print("=" * 70 + "\n")
        return False

    context = ssl.create_default_context()
    try:
        if config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context) as server:
                if config.SMTP_USER:
                    server.login(config.SMTP_USER, config.SMTP_PASS)
                server.send_message(message)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                if config.SMTP_USER:
                    server.login(config.SMTP_USER, config.SMTP_PASS)
                server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("could not send email: %s", exc)
        return False

    log.info("emailed %s: %s", recipient, subject)
    return True
