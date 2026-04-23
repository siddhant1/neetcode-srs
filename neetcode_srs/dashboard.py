"""
Single-file HTML progress dashboard for neetcode-srs.

Generates a self-contained report from the live SQLite DB: GitHub-style
activity heatmap, streak and completion stats, difficulty breakdown, and a
recent-reviews log. Opens it in the default browser.
"""
from __future__ import annotations

import html as _html
import json
import sqlite3
import tempfile
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

from neetcode_srs import db


# --- data assembly --------------------------------------------------------

def build_data(conn: sqlite3.Connection, today: date) -> dict:
    window_start = today - timedelta(days=371)
    rows = conn.execute(
        """
        SELECT date(reviewed_at) AS day, outcome, COUNT(*) AS cnt
        FROM reviews
        WHERE date(reviewed_at) >= ?
        GROUP BY day, outcome
        """,
        (window_start.isoformat(),),
    ).fetchall()

    days: dict[str, dict] = {}
    for r in rows:
        d = r["day"]
        days.setdefault(d, {"y": 0, "n": 0, "e": 0, "skip": 0, "graded": 0})
        days[d][r["outcome"]] = r["cnt"]
    for d in days.values():
        d["graded"] = d["y"] + d["n"] + d["e"]

    # Current streak: consecutive days back from today with ≥1 graded review.
    # Today not yet done doesn't break the streak — we look from yesterday.
    streak = 0
    cursor = today
    if days.get(today.isoformat(), {}).get("graded", 0) == 0:
        cursor = today - timedelta(days=1)
    while days.get(cursor.isoformat(), {}).get("graded", 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)

    # Totals from the full reviews table, not just the 52-week window.
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN outcome='y' THEN 1 ELSE 0 END), 0) AS ny,
            COALESCE(SUM(CASE WHEN outcome='n' THEN 1 ELSE 0 END), 0) AS nn,
            COALESCE(SUM(CASE WHEN outcome='e' THEN 1 ELSE 0 END), 0) AS ne
        FROM reviews
        """
    ).fetchone()
    total_y, total_n, total_e = totals["ny"], totals["nn"], totals["ne"]
    total_graded = total_y + total_n + total_e
    accuracy = round(100 * (total_y + total_e) / total_graded) if total_graded else None

    # Deck stats + difficulty breakdown.
    s = db.stats(conn, today)
    attempted = s["total"] - s["new"]

    recent = db.recent_reviews(conn, limit=25)

    # Most-recent review datetime (for subhead).
    last_row = conn.execute(
        "SELECT reviewed_at FROM reviews ORDER BY id DESC LIMIT 1"
    ).fetchone()
    last_reviewed_at = last_row["reviewed_at"] if last_row else None

    return {
        "today": today,
        "attempted": attempted,
        "total": s["total"],
        "streak": streak,
        "total_reviews": total_graded,
        "accuracy": accuracy,
        "days": days,
        "difficulty": s["by_difficulty"],
        "recent": recent,
        "last_reviewed_at": last_reviewed_at,
        "counts": {"y": total_y, "n": total_n, "e": total_e},
    }


# --- heatmap grid ---------------------------------------------------------

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _level_for_count(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count == 2:
        return 2
    if count == 3:
        return 3
    return 4


def _build_heatmap(today: date, days: dict) -> dict:
    # 53 columns × 7 rows, Sunday at top. Anchor the first column to the
    # Sunday on/before (today - 52 weeks).
    target_start = today - timedelta(days=52 * 7)
    offset = (target_start.weekday() + 1) % 7  # Mon=0 → 1, Sun=6 → 0
    grid_start = target_start - timedelta(days=offset)

    cells_html: list[str] = []
    month_labels: list[tuple[int, str]] = []  # (col_index, label)
    last_month_seen = None

    for col in range(53):
        col_start = grid_start + timedelta(days=col * 7)
        # Month label is placed on the column where a new month starts
        # within that week's top row (Sunday). Use the Sunday date.
        if col_start.month != last_month_seen and col_start <= today:
            month_labels.append((col, _MONTHS[col_start.month - 1]))
            last_month_seen = col_start.month

        for row in range(7):
            d = grid_start + timedelta(days=col * 7 + row)
            if d > today:
                cells_html.append(
                    f'<div class="cell cell-future" '
                    f'style="grid-column:{col + 1};grid-row:{row + 1};'
                    f'animation-delay:{col * 8}ms"></div>'
                )
                continue
            count = days.get(d.isoformat(), {}).get("graded", 0)
            level = _level_for_count(count)
            label = f'{d.strftime("%a %b %-d, %Y")} — {count} review{"s" if count != 1 else ""}'
            cells_html.append(
                f'<div class="cell" data-level="{level}" '
                f'data-label="{_html.escape(label, quote=True)}" '
                f'style="grid-column:{col + 1};grid-row:{row + 1};'
                f'animation-delay:{col * 8}ms"></div>'
            )

    months_html = "".join(
        f'<span style="grid-column:{col + 1}">{lbl}</span>'
        for col, lbl in month_labels
    )

    return {
        "cells_html": "".join(cells_html),
        "months_html": months_html,
        "grid_start": grid_start,
    }


# --- html rendering -------------------------------------------------------

_CSS = r"""
:root {
  --bg: #0e0e10;
  --bg-lift: #15151a;
  --ink: #ece5d1;
  --ink-strong: #f5efde;
  --ink-dim: #8a8472;
  --ink-dimmer: #55524a;
  --rule: #24242a;
  --amber: #e89d3c;
  --sage: #8db37e;
  --terra: #c96a54;
  --gold: #d4a84b;
  --cell-0: #1c1c21;
  --cell-1: #2c3a2b;
  --cell-2: #456343;
  --cell-3: #6c9566;
  --cell-4: #9cc393;
}

* { box-sizing: border-box; }

html { background: var(--bg); }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
  font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
  font-size: 13px;
  line-height: 1.55;
  font-feature-settings: "ss01", "cv01";
  -webkit-font-smoothing: antialiased;
  letter-spacing: 0.01em;
  position: relative;
  overflow-x: hidden;
}

.grain {
  position: fixed;
  inset: -50%;
  pointer-events: none;
  z-index: 0;
  opacity: 0.05;
  mix-blend-mode: screen;
}

main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 72px 56px 96px;
  position: relative;
  z-index: 1;
}

/* ---------- header ---------- */

header.masthead {
  margin-bottom: 96px;
}

.eyebrow {
  display: flex;
  gap: 18px;
  align-items: center;
  font-size: 10.5px;
  letter-spacing: 0.35em;
  text-transform: uppercase;
  color: var(--ink-dim);
  margin-bottom: 80px;
}
.eyebrow .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--amber);
  box-shadow: 0 0 10px var(--amber);
}
.eyebrow .rule {
  flex: 1;
  height: 1px;
  background: var(--rule);
}

h1.display {
  font-family: 'Fraunces', 'Times New Roman', serif;
  font-weight: 300;
  font-size: clamp(56px, 9vw, 128px);
  line-height: 0.9;
  letter-spacing: -0.035em;
  margin: 0;
  color: var(--ink-strong);
  font-variation-settings: "opsz" 144, "SOFT" 30;
}
h1.display em {
  font-style: italic;
  font-weight: 900;
  color: var(--amber);
  font-variation-settings: "opsz" 144, "SOFT" 50;
}

.subhead {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-top: 56px;
  padding-top: 20px;
  border-top: 1px solid var(--rule);
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--ink-dim);
}
.subhead em {
  font-style: normal;
  color: var(--ink-strong);
}

/* ---------- hero stats ---------- */

.hero {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 0 0 120px;
  border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
}
.stat {
  padding: 48px 40px 40px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  position: relative;
}
.stat + .stat {
  border-left: 1px solid var(--rule);
}
.stat-num {
  font-family: 'Fraunces', serif;
  font-weight: 300;
  font-size: clamp(68px, 9vw, 128px);
  line-height: 0.88;
  letter-spacing: -0.045em;
  color: var(--ink-strong);
  font-variation-settings: "opsz" 144;
  font-feature-settings: "lnum", "tnum";
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.stat-num .unit {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 400;
  color: var(--ink-dim);
  letter-spacing: 0.15em;
  text-transform: uppercase;
  font-variation-settings: normal;
}
.stat-num .denom {
  font-family: 'Fraunces', serif;
  font-size: 0.55em;
  color: var(--ink-dim);
  font-weight: 300;
  font-style: italic;
}
.stat-kicker {
  width: 36px;
  height: 2px;
  background: var(--amber);
}
.stat-label {
  font-size: 10.5px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--ink-dim);
}
.stat-sub {
  font-size: 11px;
  color: var(--ink-dimmer);
  letter-spacing: 0.1em;
  margin-top: -8px;
}

/* ---------- section heading ---------- */

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--rule);
  margin-bottom: 40px;
}
.section-head h2 {
  font-family: 'Fraunces', serif;
  font-style: italic;
  font-weight: 300;
  font-size: 32px;
  letter-spacing: -0.015em;
  margin: 0;
  color: var(--ink-strong);
  font-variation-settings: "opsz" 144;
}
.section-head .meta {
  font-size: 10.5px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--ink-dim);
}

/* ---------- heatmap ---------- */

section.heatmap {
  margin: 0 0 120px;
}
.heatmap-frame {
  overflow-x: auto;
  padding-bottom: 4px;
}
.heatmap-inner {
  display: inline-grid;
  grid-template-rows: auto auto;
  row-gap: 10px;
}
.heatmap-months {
  display: grid;
  grid-template-columns: repeat(53, 14px);
  column-gap: 3px;
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--ink-dim);
  height: 14px;
}
.heatmap-months span {
  white-space: nowrap;
}
.heatmap-grid {
  display: grid;
  grid-template-columns: repeat(53, 14px);
  grid-template-rows: repeat(7, 14px);
  column-gap: 3px;
  row-gap: 3px;
}

.cell {
  background: var(--cell-0);
  border-radius: 2px;
  position: relative;
  animation: cellIn 480ms cubic-bezier(0.16, 0.8, 0.24, 1) both;
}
.cell-future {
  background: transparent;
  border: 1px dashed var(--rule);
}
.cell[data-level="1"] { background: var(--cell-1); }
.cell[data-level="2"] { background: var(--cell-2); }
.cell[data-level="3"] { background: var(--cell-3); }
.cell[data-level="4"] { background: var(--cell-4); box-shadow: 0 0 8px rgba(156, 195, 147, 0.4); }

.cell:hover {
  outline: 1px solid var(--amber);
  outline-offset: 1px;
  z-index: 5;
}
.cell[data-label]:hover::after {
  content: attr(data-label);
  position: absolute;
  bottom: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--bg-lift);
  color: var(--ink);
  padding: 8px 12px;
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  white-space: nowrap;
  border: 1px solid var(--rule);
  border-radius: 2px;
  pointer-events: none;
  z-index: 10;
}

.heatmap-legend {
  margin-top: 28px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--ink-dim);
}
.legend-scale { display: flex; gap: 3px; align-items: center; }
.legend-scale .cell {
  width: 14px; height: 14px; animation: none;
}

/* ---------- two column section ---------- */

section.columns {
  display: grid;
  grid-template-columns: 0.9fr 1.1fr;
  gap: 80px;
  margin-bottom: 96px;
}
@media (max-width: 860px) {
  section.columns { grid-template-columns: 1fr; gap: 48px; }
}

.diff-list {
  display: flex;
  flex-direction: column;
}
.diff-row {
  display: grid;
  grid-template-columns: 84px 1fr 72px;
  gap: 20px;
  align-items: center;
  padding: 20px 0;
  border-bottom: 1px solid var(--rule);
}
.diff-row:last-child { border-bottom: none; }
.diff-label {
  font-size: 10.5px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--ink);
  display: flex;
  gap: 10px;
  align-items: center;
}
.diff-label::before {
  content: "";
  width: 6px; height: 6px; border-radius: 50%;
  background: currentColor;
}
.diff-row[data-diff="easy"] .diff-label { color: var(--sage); }
.diff-row[data-diff="medium"] .diff-label { color: var(--amber); }
.diff-row[data-diff="hard"] .diff-label { color: var(--terra); }

.bar-track {
  height: 3px;
  background: var(--cell-0);
  position: relative;
  overflow: hidden;
}
.bar-fill {
  position: absolute;
  inset: 0 auto 0 0;
  background: var(--amber);
  transform-origin: left;
  animation: barIn 900ms cubic-bezier(0.18, 0.78, 0.25, 1) both;
}
.diff-row[data-diff="easy"] .bar-fill { background: var(--sage); }
.diff-row[data-diff="medium"] .bar-fill { background: var(--amber); }
.diff-row[data-diff="hard"] .bar-fill { background: var(--terra); }

.diff-count {
  font-family: 'Fraunces', serif;
  font-size: 20px;
  color: var(--ink-strong);
  text-align: right;
  font-variation-settings: "opsz" 144;
  font-feature-settings: "tnum";
}
.diff-count .slash {
  color: var(--ink-dimmer);
  font-style: italic;
  margin: 0 2px;
}
.diff-count .tot {
  color: var(--ink-dim);
  font-size: 14px;
}

/* ---------- log ---------- */

.log {
  list-style: none;
  margin: 0;
  padding: 0;
}
.log li {
  display: grid;
  grid-template-columns: 36px 1fr auto;
  gap: 20px;
  align-items: baseline;
  padding: 18px 0;
  border-bottom: 1px solid var(--rule);
}
.log li:last-child { border-bottom: none; }
.log .mark {
  font-family: 'Fraunces', serif;
  font-size: 22px;
  line-height: 1;
  text-align: center;
  font-variation-settings: "opsz" 144;
}
.log .outcome-y .mark { color: var(--sage); }
.log .outcome-n .mark { color: var(--terra); }
.log .outcome-e .mark { color: var(--gold); }
.log .outcome-skip .mark { color: var(--ink-dim); }
.log .title {
  color: var(--ink-strong);
  font-size: 13.5px;
}
.log .row-meta {
  display: flex;
  gap: 12px;
  font-size: 10.5px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--ink-dim);
  align-items: baseline;
}
.row-meta .diff-tag { color: var(--ink); }
.row-meta .diff-tag[data-diff="Easy"] { color: var(--sage); }
.row-meta .diff-tag[data-diff="Medium"] { color: var(--amber); }
.row-meta .diff-tag[data-diff="Hard"] { color: var(--terra); }
.row-meta .interval {
  font-family: 'Fraunces', serif;
  font-size: 13px;
  letter-spacing: normal;
  text-transform: none;
  color: var(--ink);
  font-style: italic;
  font-variation-settings: "opsz" 14;
}

.log .empty {
  padding: 40px 0;
  color: var(--ink-dim);
  text-align: center;
  font-style: italic;
  font-family: 'Fraunces', serif;
  font-size: 16px;
}

/* ---------- ending ---------- */

footer.colophon {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 32px;
  border-top: 1px solid var(--rule);
  font-size: 10.5px;
  letter-spacing: 0.35em;
  text-transform: uppercase;
  color: var(--ink-dim);
}
.colophon .mark-fraunces {
  font-family: 'Fraunces', serif;
  font-style: italic;
  font-size: 18px;
  letter-spacing: -0.01em;
  text-transform: none;
  color: var(--amber);
  font-weight: 300;
}

/* ---------- animations ---------- */

@keyframes cellIn {
  from { opacity: 0; transform: translateY(3px) scale(0.5); }
  to { opacity: 1; transform: none; }
}
@keyframes barIn {
  from { transform: scaleX(0); }
  to { transform: scaleX(1); }
}
@keyframes revealUp {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: none; }
}

.masthead, .hero, .heatmap, .columns, footer.colophon {
  animation: revealUp 720ms cubic-bezier(0.22, 0.8, 0.3, 1) both;
}
.masthead { animation-delay: 0ms; }
.hero { animation-delay: 120ms; }
.heatmap { animation-delay: 220ms; }
.columns { animation-delay: 320ms; }
footer.colophon { animation-delay: 420ms; }

/* Streak number gets a gentle amber glow if non-zero. */
.stat.is-streak.has-streak .stat-num {
  text-shadow: 0 0 36px rgba(232, 157, 60, 0.25);
}
"""


_GRAIN_SVG = (
    '<svg class="grain" xmlns="http://www.w3.org/2000/svg" '
    'preserveAspectRatio="none">'
    '<filter id="noiseFilter"><feTurbulence type="fractalNoise" '
    'baseFrequency="0.9" numOctaves="2" stitchTiles="stitch"/>'
    '<feColorMatrix values="0 0 0 0 1  0 0 0 0 0.92  0 0 0 0 0.75  '
    '0 0 0 0.55 0"/></filter>'
    '<rect width="100%" height="100%" filter="url(#noiseFilter)"/></svg>'
)


_MARK = {"y": "✓", "e": "★", "n": "✗", "skip": "—"}


def _fmt_recent_row(r: dict) -> str:
    outcome = r["outcome"]
    mark = _MARK.get(outcome, "·")
    when = r["reviewed_at"][:16].replace("T", " ")
    if outcome == "skip":
        interval_txt = "postponed"
    else:
        interval_txt = f"{r['interval_before']}d → {r['interval_after']}d"
    return (
        f'<li class="outcome-{outcome}">'
        f'<span class="mark">{mark}</span>'
        f'<span class="title">{_html.escape(r["title"])}</span>'
        f'<span class="row-meta">'
        f'<span class="diff-tag" data-diff="{r["difficulty"]}">{r["difficulty"]}</span>'
        f'<span class="interval">{interval_txt}</span>'
        f'<span>{when}</span>'
        f'</span></li>'
    )


def render_html(data: dict) -> str:
    today: date = data["today"]
    hm = _build_heatmap(today, data["days"])

    # Header + subhead
    attempted = data["attempted"]
    total = data["total"]
    streak = data["streak"]
    accuracy = data["accuracy"]
    total_reviews = data["total_reviews"]

    subhead_right = f"{attempted} of {total} attempted"
    if accuracy is not None:
        subhead_right += f" · {accuracy}% solved"

    # Hero
    has_streak_cls = " has-streak" if streak > 0 else ""
    hero_html = f'''
      <div class="stat is-streak{has_streak_cls}">
        <div class="stat-num">{streak}<span class="unit">days</span></div>
        <div class="stat-kicker"></div>
        <div class="stat-label">current streak</div>
        <div class="stat-sub">consecutive days practiced</div>
      </div>
      <div class="stat">
        <div class="stat-num">{attempted}<span class="denom">/ {total}</span></div>
        <div class="stat-kicker"></div>
        <div class="stat-label">problems attempted</div>
        <div class="stat-sub">of the neetcode two-fifty</div>
      </div>
      <div class="stat">
        <div class="stat-num">{total_reviews}<span class="unit">reviews</span></div>
        <div class="stat-kicker"></div>
        <div class="stat-label">total sessions</div>
        <div class="stat-sub">answers recorded in the log</div>
      </div>
    '''

    # Difficulty rows
    diff_rows = []
    for d in ("Easy", "Medium", "Hard"):
        counts = data["difficulty"].get(d, {"seen": 0, "total": 0})
        seen = counts["seen"]
        tot = counts["total"]
        pct = (seen / tot * 100) if tot else 0
        diff_rows.append(f'''
          <div class="diff-row" data-diff="{d.lower()}">
            <span class="diff-label">{d}</span>
            <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>
            <span class="diff-count">{seen}<span class="slash"> / </span><span class="tot">{tot}</span></span>
          </div>
        ''')

    # Recent log
    if data["recent"]:
        recent_html = "<ol class='log'>" + "".join(_fmt_recent_row(r) for r in data["recent"]) + "</ol>"
    else:
        recent_html = '<ol class="log"><li class="empty">no entries yet. open a card — your first mark goes here.</li></ol>'

    # Legend cells
    legend_html = (
        '<span>less</span>'
        '<span class="legend-scale">'
        '<div class="cell" data-level="0"></div>'
        '<div class="cell" data-level="1"></div>'
        '<div class="cell" data-level="2"></div>'
        '<div class="cell" data-level="3"></div>'
        '<div class="cell" data-level="4"></div>'
        '</span>'
        '<span>more</span>'
    )

    year = today.strftime("%Y")
    grid_start_year = hm["grid_start"].strftime("%Y")
    year_span = f'{grid_start_year} — {year}' if grid_start_year != year else year
    generated_stamp = today.strftime("%b %-d, %Y").upper()

    last_at = data.get("last_reviewed_at")
    last_note = ""
    if last_at:
        last_note = f' · last entry {last_at[:10]}'

    # Assemble
    html_doc = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>neetcode · logbook</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght,SOFT@0,9..144,300..900,30..100;1,9..144,300..900,30..100&family=JetBrains+Mono:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>{_CSS}</style>
</head>
<body>
  {_GRAIN_SVG}
  <main>

    <header class="masthead">
      <div class="eyebrow">
        <span class="dot"></span>
        <span>Logbook · NeetCode 250</span>
        <span class="rule"></span>
        <span>No. 01</span>
      </div>
      <h1 class="display">a record of<br><em>daily practice.</em></h1>
      <div class="subhead">
        <span>Generated <em>{generated_stamp}</em>{last_note}</span>
        <span>{subhead_right}</span>
      </div>
    </header>

    <section class="hero">
      {hero_html}
    </section>

    <section class="heatmap">
      <div class="section-head">
        <h2>Daily activity</h2>
        <span class="meta">Year in view · {year_span}</span>
      </div>
      <div class="heatmap-frame">
        <div class="heatmap-inner">
          <div class="heatmap-months">{hm["months_html"]}</div>
          <div class="heatmap-grid">{hm["cells_html"]}</div>
        </div>
      </div>
      <div class="heatmap-legend">
        <span>reviews per day</span>
        <span class="legend-scale-wrap">{legend_html}</span>
      </div>
    </section>

    <section class="columns">
      <article>
        <div class="section-head">
          <h2>By difficulty</h2>
          <span class="meta">Coverage</span>
        </div>
        <div class="diff-list">
          {''.join(diff_rows)}
        </div>
      </article>
      <article>
        <div class="section-head">
          <h2>Recent log</h2>
          <span class="meta">Latest 25 entries</span>
        </div>
        {recent_html}
      </article>
    </section>

    <footer class="colophon">
      <span>— end of record</span>
      <span class="mark-fraunces">neetcode srs</span>
      <span>{generated_stamp}</span>
    </footer>

  </main>
</body>
</html>
'''
    return html_doc


def render_to_file(conn: sqlite3.Connection, today: date | None = None) -> Path:
    if today is None:
        today = date.today()
    data = build_data(conn, today)
    html = render_html(data)
    out = Path(tempfile.gettempdir()) / "neetcode-dashboard.html"
    out.write_text(html, encoding="utf-8")
    return out


def open_dashboard(conn: sqlite3.Connection, today: date | None = None) -> Path:
    path = render_to_file(conn, today)
    webbrowser.open(f"file://{path}")
    return path
