from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from neetcode_srs import db


@dataclass
class Pick:
    card: db.Card | None
    kind: str  # "review" | "new" | "already_done" | "empty"
    already_done_card: db.Card | None = None


def pick_today(conn: sqlite3.Connection, today: date) -> Pick:
    done = db.reviewed_today(conn, today)
    if done is not None:
        return Pick(card=None, kind="already_done", already_done_card=done)

    due = db.pick_due(conn, today)
    if due is not None:
        return Pick(card=due, kind="review")

    new = db.pick_new(conn)
    if new is not None:
        return Pick(card=new, kind="new")

    return Pick(card=None, kind="empty")
