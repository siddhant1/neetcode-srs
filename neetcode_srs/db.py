from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from neetcode_srs.srs import CardState, EASE_START

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    topics TEXT NOT NULL,
    leetcode_url TEXT NOT NULL,
    order_idx INTEGER NOT NULL,
    ease REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    next_due TEXT,
    last_reviewed TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES cards(id),
    reviewed_at TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('y','n','skip')),
    interval_before INTEGER NOT NULL,
    interval_after INTEGER NOT NULL,
    ease_before REAL NOT NULL,
    ease_after REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cards_next_due ON cards(next_due);
CREATE INDEX IF NOT EXISTS idx_cards_order ON cards(order_idx);
"""


@dataclass
class Card:
    id: str
    title: str
    difficulty: str
    topics: list[str]
    leetcode_url: str
    order_idx: int
    ease: float
    interval_days: int
    reps: int
    next_due: date | None
    last_reviewed: date | None

    @property
    def state(self) -> CardState:
        return CardState(ease=self.ease, interval_days=self.interval_days, reps=self.reps)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _row_to_card(row: sqlite3.Row) -> Card:
    return Card(
        id=row["id"],
        title=row["title"],
        difficulty=row["difficulty"],
        topics=json.loads(row["topics"]),
        leetcode_url=row["leetcode_url"],
        order_idx=row["order_idx"],
        ease=row["ease"],
        interval_days=row["interval_days"],
        reps=row["reps"],
        next_due=date.fromisoformat(row["next_due"]) if row["next_due"] else None,
        last_reviewed=date.fromisoformat(row["last_reviewed"]) if row["last_reviewed"] else None,
    )


def upsert_problems(conn: sqlite3.Connection, problems: list[dict]) -> int:
    with conn:
        for idx, p in enumerate(problems):
            conn.execute(
                """
                INSERT INTO cards (id, title, difficulty, topics, leetcode_url, order_idx, ease)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    difficulty = excluded.difficulty,
                    topics = excluded.topics,
                    leetcode_url = excluded.leetcode_url,
                    order_idx = excluded.order_idx
                """,
                (
                    p["id"],
                    p["title"],
                    p["difficulty"],
                    json.dumps(p["topics"]),
                    p["leetcode_url"],
                    idx,
                    EASE_START,
                ),
            )
    return len(problems)


def get_card(conn: sqlite3.Connection, card_id: str) -> Card | None:
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return _row_to_card(row) if row else None


def reviewed_today(conn: sqlite3.Connection, today: date) -> Card | None:
    row = conn.execute(
        "SELECT * FROM cards WHERE last_reviewed = ?",
        (today.isoformat(),),
    ).fetchone()
    return _row_to_card(row) if row else None


def pick_due(conn: sqlite3.Connection, today: date) -> Card | None:
    row = conn.execute(
        """
        SELECT * FROM cards
        WHERE next_due IS NOT NULL AND next_due <= ?
        ORDER BY next_due ASC, ease ASC, order_idx ASC
        LIMIT 1
        """,
        (today.isoformat(),),
    ).fetchone()
    return _row_to_card(row) if row else None


def pick_new(conn: sqlite3.Connection) -> Card | None:
    # Easy → Medium → Hard, then by NeetCode order within a tier.
    row = conn.execute(
        """
        SELECT * FROM cards
        WHERE next_due IS NULL
        ORDER BY
            CASE difficulty
                WHEN 'Easy' THEN 0
                WHEN 'Medium' THEN 1
                WHEN 'Hard' THEN 2
                ELSE 3
            END,
            order_idx ASC
        LIMIT 1
        """
    ).fetchone()
    return _row_to_card(row) if row else None


def apply_review(
    conn: sqlite3.Connection,
    card: Card,
    outcome: str,
    new_state: CardState,
    next_due: date,
    today: date,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE cards SET
                ease = ?, interval_days = ?, reps = ?,
                next_due = ?, last_reviewed = ?
            WHERE id = ?
            """,
            (
                new_state.ease,
                new_state.interval_days,
                new_state.reps,
                next_due.isoformat(),
                today.isoformat(),
                card.id,
            ),
        )
        conn.execute(
            """
            INSERT INTO reviews
                (card_id, reviewed_at, outcome, interval_before, interval_after, ease_before, ease_after)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card.id,
                datetime.now().isoformat(timespec="seconds"),
                outcome,
                card.interval_days,
                new_state.interval_days,
                card.ease,
                new_state.ease,
            ),
        )


def postpone(conn: sqlite3.Connection, card: Card, next_due: date) -> None:
    with conn:
        conn.execute(
            "UPDATE cards SET next_due = ? WHERE id = ?",
            (next_due.isoformat(), card.id),
        )
        conn.execute(
            """
            INSERT INTO reviews
                (card_id, reviewed_at, outcome, interval_before, interval_after, ease_before, ease_after)
            VALUES (?, ?, 'skip', ?, ?, ?, ?)
            """,
            (
                card.id,
                datetime.now().isoformat(timespec="seconds"),
                card.interval_days,
                card.interval_days,
                card.ease,
                card.ease,
            ),
        )


def stats(conn: sqlite3.Connection, today: date) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    new = conn.execute("SELECT COUNT(*) FROM cards WHERE next_due IS NULL").fetchone()[0]
    learning = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE next_due IS NOT NULL AND reps < 2"
    ).fetchone()[0]
    mature = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE reps >= 2"
    ).fetchone()[0]
    due_today = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE next_due IS NOT NULL AND next_due <= ?",
        (today.isoformat(),),
    ).fetchone()[0]
    by_difficulty = {
        d: {
            "total": conn.execute(
                "SELECT COUNT(*) FROM cards WHERE difficulty = ?", (d,)
            ).fetchone()[0],
            "seen": conn.execute(
                "SELECT COUNT(*) FROM cards WHERE difficulty = ? AND next_due IS NOT NULL",
                (d,),
            ).fetchone()[0],
        }
        for d in ("Easy", "Medium", "Hard")
    }
    return {
        "total": total,
        "new": new,
        "learning": learning,
        "mature": mature,
        "due_today": due_today,
        "by_difficulty": by_difficulty,
    }


def recent_reviews(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.*, c.title, c.difficulty
        FROM reviews r JOIN cards c ON c.id = r.card_id
        ORDER BY r.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
