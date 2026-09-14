"""Command line entry point.

    python -m tt setup       create the database and load the company list
    python -m tt refresh     full pull of every board (run this first)
    python -m tt poll        check for brand-new jobs and send alerts
    python -m tt snapshot    record today's open counts
    python -m tt themes      ask Claude what companies are solving
    python -m tt reprocess   re-run the filters over stored postings
    python -m tt ticker      print the top skills to the terminal
    python -m tt serve       dashboard plus the background scheduler
"""
from __future__ import annotations

import argparse
import json
import pathlib
import logging
import sys

from . import alerts, db, discover, export, ingest, state
from .analytics import (
    emerging, geo, industry, skill_discovery, skill_proposals, themes, ticker,
)


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_setup(args) -> int:
    db.init()
    count = ingest.sync_companies()
    with db.session() as conn:
        from .alerts import watchlist

        watchlist.ensure_defaults(conn)
    print(f"database ready at {db.config.DB_PATH}")
    print(f"{count} companies loaded from {db.config.COMPANIES_FILE}")
    print("next: python -m tt refresh")
    return 0


def cmd_refresh(args) -> int:
    db.init()
    ingest.sync_companies()
    stats = ingest.refresh(tier=args.tier, limit=args.limit)
    ingest.snapshot()
    print(json.dumps(stats, indent=2))
    if stats["failed"]:
        print(f"\n{stats['failed']} board(s) did not respond and were skipped.")
    return 0


def cmd_poll(args) -> int:
    db.init()
    new_ids = ingest.poll(tier=args.tier)
    print(f"{len(new_ids)} new posting(s)")
    if new_ids:
        result = alerts.dispatch(new_ids)
        print(json.dumps(result, indent=2))
    return 0


def cmd_snapshot(args) -> int:
    db.init()
    print(f"{ingest.snapshot()} rows recorded")
    return 0


def cmd_reprocess(args) -> int:
    db.init()
    print(f"{ingest.reprocess()} postings reprocessed")
    return 0


def _explain_api_error(exc: Exception) -> int:
    """Turn an Anthropic failure into something readable.

    A raw traceback for "you have no credit left" helps nobody, and the two
    common causes - no credit, bad key - have completely different fixes.
    """
    import anthropic

    if isinstance(exc, anthropic.BadRequestError) and "credit balance" in str(exc):
        print("Anthropic API: out of credit.")
        print("  Add credit at https://console.anthropic.com/settings/billing")
        print("  Everything else in TalentTicker works without it - only the")
        print("  Claude write-ups and skill discovery need credit.")
        return 1
    if isinstance(exc, anthropic.AuthenticationError):
        print("Anthropic API: the key was rejected.")
        print("  Check ANTHROPIC_API_KEY in .env")
        return 1
    if isinstance(exc, anthropic.RateLimitError):
        print("Anthropic API: rate limited. Try again shortly.")
        return 1
    raise exc


def cmd_themes(args) -> int:
    db.init()
    if args.dry_run:
        with db.session() as conn:
            preview = themes.estimate(conn, scope=args.scope, subject=args.subject)
        print(f"postings included : {preview['postings']}")
        print(f"prompt size       : {preview['prompt_chars']:,} characters "
              f"(~{preview['approx_input_tokens']:,} tokens)")
        print(f"estimated cost    : ${preview['approx_cost_usd']:.4f} per run")
        print("\n--- start of prompt ---")
        print(preview["prompt"][:2000])
        print("... (truncated)")
        return 0

    try:
        with db.session() as conn:
            result = themes.build(
                conn, scope=args.scope, subject=args.subject, force=args.force
            )
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return _explain_api_error(exc)
    print(result.get("summary", ""))
    print()
    for theme in result.get("themes", []):
        print(f"  [{theme['momentum']}] {theme['title']}")
        print(f"      {theme['problem']}")
        if theme.get("skills"):
            print(f"      skills: {', '.join(theme['skills'])}")
        print()
    if result.get("usage"):
        print(f"(tokens in/out: {result['usage']['input_tokens']}/"
              f"{result['usage']['output_tokens']})")
    return 0


def cmd_ticker(args) -> int:
    db.init()
    with db.session() as conn:
        rows = ticker.board(conn, window_days=args.window)
        movers = ticker.movers(conn, window_days=args.window)
        summary = ticker.summary(conn)

    # The wording follows the profile - this is not always software.
    print(f"\n{summary['total']} matching roles ({db.config.PROFILE.label}) from "
          f"{summary['scanned']} postings across {summary['companies']} companies")
    print(f"{summary['last30']} posted in the last 30 days\n")

    print(f"{'#':<4}{'SKILL':<24}{'JOBS':>6}{'SHARE':>9}{'CHANGE':>10}")
    print("-" * 53)
    for row in rows[: args.limit]:
        arrow = "+" if row["change"] > 0 else ""
        print(f"{row['rank']:<4}{row['skill']:<24}{row['postings']:>6}"
              f"{row['share']:>8.1f}%{arrow + format(row['change'], '.1f'):>9}%")

    print("\nRISING FAST")
    for row in movers["emerging"][:8]:
        print(f"  {row['skill']:<24}{row['postings']:>4} jobs   {row['change']:>+7.0f}%")

    print("\nSLIPPING")
    for row in movers["losers"][:6]:
        print(f"  {row['skill']:<24}{row['postings']:>4} jobs   {row['change']:>+7.0f}%")
    return 0


def cmd_emerging(args) -> int:
    db.init()
    with db.session() as conn:
        rows = emerging.rising(conn, limit=args.limit)
    print(f"\n{'PHRASE':<38}{'JOBS':>5}{'CO.':>5}{'WAS':>6}{'LIFT':>8}")
    print("-" * 62)
    for row in rows:
        print(f"{row['phrase'][:37]:<38}{row['recent']:>5}{row['companies']:>5}"
              f"{row['baseline']:>6}{row['lift']:>7.1f}x")
    print("\n'CO.' is how many different companies use the phrase. "
          "Anything under three is usually one firm's house style.")
    return 0


def cmd_metros(args) -> int:
    db.init()
    with db.session() as conn:
        rows = geo.metros(conn, window_days=args.window)
        flow = geo.company_flow(conn, window_days=args.window)
    print(f"\n{'METRO':<22}{'JOBS':>6}{'SHARE':>8}{'SHARE CHANGE':>14}")
    print("-" * 50)
    for row in rows:
        print(f"{row['metro']:<22}{row['postings']:>6}{row['share']:>7.1f}%"
              f"{row['share_change']:>+13.1f}pt")
    print("\nOPENING MORE EARLY-CAREER ROLES")
    for row in flow["growing"][:10]:
        print(f"  {row['company']:<26}{row['postings']:>4}  ({row['delta']:+d})")
    return 0


def cmd_sectors(args) -> int:
    db.init()
    with db.session() as conn:
        rows = industry.board(conn, window_days=args.window)
        if args.sector:
            detail = industry.detail(conn, args.sector)

    if args.sector:
        print(f"\n{args.sector}\n" + "=" * len(args.sector))
        print(f"\n{'SKILL':<24}{'JOBS':>6}{'IN SECTOR':>11}{'MARKET':>9}{'LIFT':>8}")
        print("-" * 58)
        for row in detail["skills"]:
            lift = f"{row['lift']:.1f}x" if row["lift"] else "-"
            print(f"{row['skill']:<24}{row['postings']:>6}{row['share']:>10.1f}%"
                  f"{row['market_share']:>8.1f}%{lift:>8}")
        print("\nLift compares against the whole market. Above 1.0 means this "
              "sector wants it\nmore than everyone else does.")
        print("\nTOP EMPLOYERS")
        for row in detail["companies"][:8]:
            print(f"  {row['name']:<28}{row['n']:>4}")
        return 0

    print(f"\n{'SECTOR':<24}{'JOBS':>6}{'COS':>5}{'SHARE':>8}{'CHANGE':>9}   TYPICAL PAY")
    print("-" * 74)
    for row in rows:
        pay = (f"${row['pay_low'] // 1000}k-${row['pay_high'] // 1000}k"
               if row["pay_low"] else "-")
        print(f"{row['sector'][:23]:<24}{row['postings']:>6}{row['companies']:>5}"
              f"{row['share']:>7.1f}%{row['change']:>+8.1f}%   {pay}")
    print("\nAdd --sector \"AI\" for the skills one sector wants.")
    return 0


def cmd_discover(args) -> int:
    """Find company boards referenced by the aggregated new-grad lists."""
    db.init()
    report = discover.run(add=args.add, min_rows=args.min_rows)
    print(f"{report['seen']} board(s) referenced, "
          f"{report['already_known']} already in the registry\n")

    if report["new"]:
        print(f"{'ATS':<12}{'TOKEN':<44}{'JOBS':>6}  COMPANY")
        print("-" * 86)
        for entry in report["new"]:
            print(f"{entry['ats']:<12}{entry['token'][:43]:<44}{entry['jobs']:>6}  {entry['name'][:24]}")
    else:
        print("nothing new found")

    if report["dead"]:
        print(f"\n{len(report['dead'])} link(s) pointed at boards that did not "
              "respond and were skipped.")

    if args.add and report["new"]:
        print(f"\nAdded {len(report['new'])} board(s) to {db.config.COMPANIES_FILE}.")
        print("Run `python -m tt refresh` to pull them in.")
    elif report["new"]:
        print("\nRe-run with --add to write these into companies.yml.")
    return 0


def cmd_sponsorship(args) -> int:
    """Who says they sponsor a work visa, and who says they do not."""
    db.init()
    from .extract.sponsorship import LABELS
    from datetime import date, timedelta

    since = (date.today() - timedelta(days=args.window)).isoformat()
    with db.session() as conn:
        totals = dict(conn.execute(
            """SELECT COALESCE(sponsorship,'unknown'), COUNT(*) FROM postings
               WHERE eligible=1 AND has_content=1
                 AND substr(first_published,1,10) >= ? GROUP BY 1""",
            (since,),
        ).fetchall())
        rows = conn.execute(
            """SELECT company_name,
                      SUM(sponsorship='yes') yes,
                      SUM(sponsorship='no') no,
                      SUM(sponsorship='clearance') clearance,
                      COUNT(*) total
               FROM postings
               WHERE eligible=1 AND has_content=1
                 AND substr(first_published,1,10) >= ?
               GROUP BY company_name HAVING yes>0 OR no>0 OR clearance>0
               ORDER BY yes DESC, no DESC""",
            (since,),
        ).fetchall()

    grand = sum(totals.values()) or 1
    print(f"\n{grand} early-career postings in the last {args.window} days\n")
    for key in ("yes", "no", "clearance", "unknown"):
        n = totals.get(key, 0)
        print(f"  {LABELS[key]:<22}{n:>6}  ({n / grand * 100:4.1f}%)")

    print(f"\n{'COMPANY':<26}{'SPONSORS':>9}{'WILL NOT':>10}"
          f"{'CLEARANCE':>11}{'TOTAL':>7}")
    print("-" * 63)
    for r in rows[:args.limit]:
        print(f"{r['company_name'][:25]:<26}{r['yes']:>9}{r['no']:>10}"
              f"{r['clearance']:>11}{r['total']:>7}")
    print("\nRead from what each posting says. Most never mention it, and")
    print("silence is not a no - it just means you have to ask.")
    return 0


def cmd_testmail(args) -> int:
    """Check the email settings and, unless asked not to, send one real message.

    Worth having as its own command: a misconfigured mailbox fails silently in
    the background, and you would only notice by never receiving an alert you
    were counting on.
    """
    from .alerts import mailer
    from . import config as cfg

    problems = []
    if not cfg.ALERT_TO:
        problems.append("TT_ALERT_TO is empty - nowhere to send to")
    if not cfg.SMTP_HOST:
        problems.append("TT_SMTP_HOST is empty")
    if not cfg.SMTP_USER:
        problems.append("TT_SMTP_USER is empty")
    if not cfg.SMTP_PASS:
        problems.append("TT_SMTP_PASS is empty")
    elif "gmail" in cfg.SMTP_HOST.lower():
        stripped = cfg.SMTP_PASS.replace(" ", "")
        if not (len(stripped) == 16 and stripped.isalpha()):
            problems.append(
                f"TT_SMTP_PASS does not look like a Gmail App Password "
                f"({len(stripped)} characters, expected 16 letters). "
                "Gmail rejects normal account passwords over SMTP - create an "
                "App Password at https://myaccount.google.com/apppasswords "
                "(needs 2-Step Verification turned on first)."
            )
    if cfg.SMTP_DRY_RUN:
        problems.append("TT_SMTP_DRY_RUN=1 - nothing will actually be sent")

    print(f"to      : {cfg.ALERT_TO or '(empty)'}")
    print(f"server  : {cfg.SMTP_HOST or '(empty)'}:{cfg.SMTP_PORT}")
    print(f"login   : {cfg.SMTP_USER or '(empty)'}")
    print(f"password: {'set, ' + str(len(cfg.SMTP_PASS)) + ' chars' if cfg.SMTP_PASS else '(empty)'}")
    print()

    if problems:
        print("not ready to send:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    if args.check_only:
        print("settings look right. Run without --check-only to send a test message.")
        return 0

    ok = mailer.send(
        "TalentTicker test message",
        "If you are reading this, alerts will reach you.\n\n"
        "New early-career software roles matching your watchlists will arrive "
        "here within about five minutes of being posted.",
        "<p>If you are reading this, alerts will reach you.</p>"
        "<p style='color:#555'>New early-career software roles matching your "
        "watchlists will arrive here within about five minutes of being posted.</p>",
    )
    print("sent" if ok else "could not send - see the error above")
    return 0 if ok else 1


def cmd_learn_skills(args) -> int:
    """Ask Claude which skills the dictionary is missing.

    Claude proposes vocabulary; the dictionary still does the counting. That
    keeps every number reproducible, and means a newly added skill is applied
    to all stored postings by `tt reprocess` rather than needing a paid re-read.
    """
    import yaml

    db.init()
    if args.dry_run and not args.ai:
        print("the free proposer costs nothing - just run it without --dry-run")
        return 0
    if args.dry_run:
        with db.session() as conn:
            preview = skill_discovery.estimate(conn, sample=args.sample, days=args.days)
        print(f"postings sampled : {preview['postings']}")
        print(f"requests         : {preview['requests']}")
        print(f"approx tokens in : {preview['approx_input_tokens']:,}")
        print(f"estimated cost   : ${preview['approx_cost_usd']:.2f}")
        return 0

    if args.ai:
        try:
            with db.session() as conn:
                result = skill_discovery.run(
                    conn, sample=args.sample, days=args.days,
                    min_companies=args.min_companies,
                )
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            return _explain_api_error(exc)
        print(f"read {result['postings']} postings in {result['requests']} "
              f"request(s), cost ${result['usage'].get('cost_usd', 0):.2f}")
    else:
        # Free by default: an API subscription is billed separately from a
        # Claude Code or chat plan, so nothing here may assume credit exists.
        with db.session() as conn:
            result = skill_proposals.run(
                conn, min_companies=max(args.min_companies, 4)
            )
        print(f"scanned every stored posting, {result['considered']} candidate "
              f"term(s) considered, no API calls")

    proposals = result["proposals"]
    print(f"{len(proposals)} proposal(s) worth adding\n")

    if not proposals:
        print("nothing new - the dictionary already covers what is out there.")
        return 0

    print(f"{'SKILL':<30}{'CATEGORY':<12}{'JOBS':>6}{'COS':>5}  ALIASES")
    print("-" * 96)
    for item in proposals:
        print(f"{item['name'][:29]:<30}{item['category']:<12}{item['postings']:>6}"
              f"{item['companies']:>5}  {', '.join(item['aliases'][:4])}")

    if not args.add:
        print("\nRun again with --add to write these into data/learned_skills.yml,")
        print("then `tt reprocess` to apply them to every stored posting.")
        return 0

    path = db.config.ROOT / "data" / "learned_skills.yml"
    existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = existing.get("skills") or []
    known = {e.get("name") for e in entries}
    added = 0
    for item in proposals:
        if item["name"] in known:
            continue
        entries.append({
            "name": item["name"],
            "category": item["category"],
            "aliases": item["aliases"],
            "seen_at_companies": item["companies"],
            "added": __import__("datetime").date.today().isoformat(),
        })
        added += 1

    header = path.read_text(encoding="utf-8").split("skills:")[0]
    path.write_text(
        header + yaml.safe_dump({"skills": entries}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"\nadded {added} skill(s) to {path.name}")
    print("next: python -m tt reprocess   (applies them to all stored postings)")
    return 0


def cmd_state(args) -> int:
    path = pathlib.Path(args.path) if args.path else None
    if args.action == "save":
        db.init()
        result = state.save(path)
        print(f"saved {result['seen']:,} seen ids and {result['alerted']:,} "
              f"alert records to {result['path']} ({result['size_kb']} KB)")
    else:
        result = state.load(path)
        if result["missing"]:
            print("no state file - treating every posting as new")
        else:
            print(f"loaded {result['seen']:,} seen ids, "
                  f"{result['alerted']:,} alert records")
    return 0


def cmd_vacuum(args) -> int:
    db.init()
    result = ingest.vacuum()
    print(f"freed {result['freed_mb']} MB of description text")
    print(f"{result['remaining_mb']} MB kept | database now {result['db_mb']} MB")
    return 0


def cmd_export(args) -> int:
    db.init()
    dest = pathlib.Path(args.out) if args.out else None
    result = export.write(dest)
    print(f"wrote {result['path']}")
    print(f"  {result['size_kb']} KB | {result['skills']} skills | "
          f"{result['jobs']} jobs | {result['sectors']} sectors")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    db.init()
    print(f"dashboard: http://{args.host}:{args.port}")
    uvicorn.run("tt.web.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tt", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup").set_defaults(func=cmd_setup)

    p = subparsers.add_parser("refresh", help="full pull of every board")
    p.add_argument("--tier", type=int, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_refresh)

    p = subparsers.add_parser("poll", help="check for new jobs, send alerts")
    p.add_argument("--tier", type=int, default=2)
    p.set_defaults(func=cmd_poll)

    subparsers.add_parser("snapshot").set_defaults(func=cmd_snapshot)
    subparsers.add_parser("reprocess").set_defaults(func=cmd_reprocess)

    p = subparsers.add_parser("themes", help="what companies are solving")
    p.add_argument("--scope", default="market", choices=["market", "company", "skill", "metro"])
    p.add_argument("--subject", default="")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="show the prompt and estimated cost without calling Claude")
    p.set_defaults(func=cmd_themes)

    p = subparsers.add_parser("ticker", help="top skills")
    p.add_argument("--window", type=int, default=30)
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_ticker)

    p = subparsers.add_parser("emerging", help="rising terms not yet in the taxonomy")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_emerging)

    p = subparsers.add_parser("metros", help="where the jobs are")
    p.add_argument("--window", type=int, default=30)
    p.set_defaults(func=cmd_metros)

    p = subparsers.add_parser("sectors", help="early-career roles by industry")
    p.add_argument("--window", type=int, default=90)
    p.add_argument("--sector", default="", help="drill into one sector, e.g. \"AI\"")
    p.set_defaults(func=cmd_sectors)

    p = subparsers.add_parser("discover", help="find company boards we are missing")
    p.add_argument("--add", action="store_true", help="write them into companies.yml")
    p.add_argument("--min-rows", type=int, default=1, dest="min_rows")
    p.set_defaults(func=cmd_discover)

    p = subparsers.add_parser("sponsorship", help="who sponsors a work visa")
    p.add_argument("--window", type=int, default=90)
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_sponsorship)

    p = subparsers.add_parser("learn-skills",
                              help="ask Claude what the skill dictionary is missing")
    p.add_argument("--sample", type=int, default=120)
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--min-companies", type=int, default=3)
    p.add_argument("--add", action="store_true",
                   help="write the proposals into data/learned_skills.yml")
    p.add_argument("--ai", action="store_true",
                   help="use Claude instead of the free statistical finder "
                        "(needs API credit, which a Claude Code or chat plan "
                        "does not include)")
    p.add_argument("--dry-run", action="store_true",
                   help="show the cost of an --ai run without making it")
    p.set_defaults(func=cmd_learn_skills)

    p = subparsers.add_parser("state", help="save or load the seen-job state")
    p.add_argument("action", choices=["save", "load"])
    p.add_argument("--path", default="")
    p.set_defaults(func=cmd_state)

    subparsers.add_parser(
        "vacuum", help="drop description text from rejected and closed postings"
    ).set_defaults(func=cmd_vacuum)

    p = subparsers.add_parser("export", help="write the static site data")
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_export)

    p = subparsers.add_parser("testmail", help="check email settings and send a test")
    p.add_argument("--check-only", action="store_true",
                   help="validate the settings without sending anything")
    p.set_defaults(func=cmd_testmail)

    p = subparsers.add_parser("serve", help="dashboard and scheduler")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
