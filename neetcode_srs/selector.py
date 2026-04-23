from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from neetcode_srs import db


@dataclass
class Pick:
    card: db.Card | None
    kind: str  # "review" | "new" | "quota_hit" | "empty"
    done_today: int = 0
    daily_target: int = 1


def pick_today(conn: sqlite3.Connection, today: date, daily_target: int = 1) -> Pick:
    done = db.count_reviewed_on(conn, today)
    if done >= daily_target:
        return Pick(card=None, kind="quota_hit", done_today=done, daily_target=daily_target)

    due = db.pick_due(conn, today)
    if due is not None:
        # Skip cards already answered earlier today (re-surface tomorrow).
        if due.last_reviewed != today:
            return Pick(card=due, kind="review", done_today=done, daily_target=daily_target)

    new = db.pick_new(conn)
    if new is not None:
        return Pick(card=new, kind="new", done_today=done, daily_target=daily_target)

    return Pick(card=None, kind="empty", done_today=done, daily_target=daily_target)
