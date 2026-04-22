from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from neetcode_srs import db, problems, selector
from neetcode_srs.srs import schedule

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "state.db"
CACHE_PATH = DATA_DIR / "neetcode250.json"


# --- output helpers -------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()

BOLD = "\033[1m" if _USE_COLOR else ""
DIM = "\033[2m" if _USE_COLOR else ""
RESET = "\033[0m" if _USE_COLOR else ""
GREEN = "\033[32m" if _USE_COLOR else ""
YELLOW = "\033[33m" if _USE_COLOR else ""
RED = "\033[31m" if _USE_COLOR else ""
CYAN = "\033[36m" if _USE_COLOR else ""

DIFFICULTY_COLOR = {"Easy": GREEN, "Medium": YELLOW, "Hard": RED}


def _color(s: str, c: str) -> str:
    if not c:
        return s
    return f"{c}{s}{RESET}"


def _print_card(card: db.Card, kind: str) -> None:
    banner = {
        "review": "Review due",
        "new": "New problem",
    }.get(kind, kind)
    diff = _color(card.difficulty, DIFFICULTY_COLOR.get(card.difficulty, ""))
    print()
    print(_color(f"  {banner}", DIM))
    print(f"  {_color(card.title, BOLD)}  [{diff}]  {DIM}{', '.join(card.topics)}{RESET}")
    print(f"  {_color(card.leetcode_url, CYAN)}")
    if kind == "review":
        streak = card.reps
        prior = card.interval_days
        print(f"  {DIM}streak: {streak} · last interval: {prior}d · ease: {card.ease:.2f}{RESET}")
    print()


def _parse_today(raw: str | None) -> date:
    if raw is None:
        return date.today()
    return date.fromisoformat(raw)


# --- commands -------------------------------------------------------------

def cmd_setup(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    cached = problems.load_cached(CACHE_PATH)
    if cached is None or args.refresh:
        print("Fetching NeetCode 250 from neetcode.io …")
        plist = problems.fetch_neetcode250()
        problems.save_cache(CACHE_PATH, plist)
        print(f"Cached {len(plist)} problems → {CACHE_PATH}")
    else:
        plist = cached
        print(f"Using cached problem list ({len(plist)} problems). Use --refresh to re-fetch.")
    n = db.upsert_problems(conn, plist)
    print(f"Loaded {n} problems into the deck.")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    today = _parse_today(args.today)
    s = db.stats(conn, today)
    if s["total"] == 0:
        print("Deck is empty. Run `neetcode setup` first.")
        return 1
    print()
    print(f"  {_color('Deck', BOLD)}: {s['total']} total  ·  {s['new']} new  ·  "
          f"{s['learning']} learning  ·  {s['mature']} mature")
    print(f"  {_color('Due today', BOLD)}: {s['due_today']}")
    print(f"  {_color('By difficulty', BOLD)}:")
    for d, counts in s["by_difficulty"].items():
        color = DIFFICULTY_COLOR.get(d, "")
        print(f"    {_color(d, color):<20} {counts['seen']}/{counts['total']} seen")
    print()
    return 0


def cmd_today(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    today = _parse_today(args.today)

    pick = selector.pick_today(conn, today)
    if pick.kind == "empty":
        print("Deck is empty. Run `neetcode setup` first.")
        return 1
    if pick.kind == "already_done":
        c = pick.already_done_card
        assert c is not None
        print(f"\n  Already done today: {_color(c.title, BOLD)}. Come back tomorrow.\n")
        return 0
    assert pick.card is not None

    _print_card(pick.card, pick.kind)
    prompt = f"  {_color('Did you solve it?', BOLD)} [y/n/skip] > "
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 130

    if answer in ("skip", "s"):
        next_due = today + timedelta(days=1)
        db.postpone(conn, pick.card, next_due)
        print(f"  {_color('Postponed', DIM)} to {next_due.isoformat()}.\n")
        return 0
    if answer not in ("y", "n"):
        print("  Expected y / n / skip. No changes made.")
        return 2

    result = schedule(pick.card.state, answer, today)
    db.apply_review(conn, pick.card, answer, result.state, result.next_due, today)

    verb = "solved" if answer == "y" else "failed"
    color = GREEN if answer == "y" else RED
    days = result.state.interval_days
    print()
    print(f"  {_color(verb, color)} — next review in {days} day{'s' if days != 1 else ''} "
          f"({result.next_due.isoformat()}).")
    print(f"  {DIM}ease {pick.card.ease:.2f} → {result.state.ease:.2f}  ·  "
          f"streak {result.state.reps}{RESET}\n")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    rows = db.recent_reviews(conn, args.n)
    if not rows:
        print("No reviews yet.")
        return 0
    print()
    for r in rows:
        icon = {"y": _color("✓", GREEN), "n": _color("✗", RED), "skip": _color("⋯", DIM)}[r["outcome"]]
        diff = _color(r["difficulty"], DIFFICULTY_COLOR.get(r["difficulty"], ""))
        when = r["reviewed_at"][:16].replace("T", " ")
        delta = (
            f"interval {r['interval_before']}d → {r['interval_after']}d"
            if r["outcome"] != "skip"
            else "postponed"
        )
        print(f"  {icon}  {when}  {r['title']:<40} [{diff}]  {DIM}{delta}{RESET}")
    print()
    return 0


def cmd_skip(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    today = _parse_today(args.today)
    pick = selector.pick_today(conn, today)
    if pick.kind in ("empty", "already_done"):
        print("Nothing to skip.")
        return 0
    assert pick.card is not None
    next_due = today + timedelta(days=1)
    db.postpone(conn, pick.card, next_due)
    print(f"Postponed {pick.card.title} to {next_due.isoformat()}.")
    return 0


# --- entrypoint -----------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # Parent parser with the hidden --today flag, inherited by all subparsers
    # so it works in both `neetcode --today ...` and `neetcode today --today ...`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--today", help=argparse.SUPPRESS)

    p = argparse.ArgumentParser(
        prog="neetcode",
        description="Daily NeetCode 250 SRS.",
        parents=[common],
    )
    sub = p.add_subparsers(dest="command")

    p_setup = sub.add_parser("setup", parents=[common],
                             help="Fetch the NeetCode 250 list and populate the deck.")
    p_setup.add_argument("--refresh", action="store_true", help="Re-fetch even if cached.")
    p_setup.set_defaults(func=cmd_setup)

    p_stats = sub.add_parser("stats", parents=[common], help="Show deck progress.")
    p_stats.set_defaults(func=cmd_stats)

    p_today = sub.add_parser("today", parents=[common], help="Show today's card (default).")
    p_today.set_defaults(func=cmd_today)

    p_hist = sub.add_parser("history", parents=[common], help="Show recent reviews.")
    p_hist.add_argument("n", nargs="?", type=int, default=10)
    p_hist.set_defaults(func=cmd_history)

    p_skip = sub.add_parser("skip", parents=[common], help="Postpone today's card by one day.")
    p_skip.set_defaults(func=cmd_skip)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_today(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
