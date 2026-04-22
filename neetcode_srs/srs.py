from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

EASE_START = 2.5
EASE_MIN = 1.3
EASE_MAX = 2.8
EASE_STEP_UP = 0.05
EASE_STEP_DOWN = 0.2

# On a wrong answer, the minimum interval before the card resurfaces.
# User-requested: failing a problem should not bring it back tomorrow —
# the brain needs a couple of days to forget and re-encounter cleanly.
WRONG_MIN_INTERVAL = 3


@dataclass(frozen=True)
class CardState:
    ease: float
    interval_days: int
    reps: int


@dataclass(frozen=True)
class Schedule:
    state: CardState
    next_due: date


def schedule(current: CardState, outcome: str, today: date) -> Schedule:
    if outcome not in ("y", "n"):
        raise ValueError(f"outcome must be 'y' or 'n', got {outcome!r}")

    if outcome == "y":
        reps = current.reps + 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = max(1, round(current.interval_days * current.ease))
        ease = min(current.ease + EASE_STEP_UP, EASE_MAX)
    else:
        reps = 0
        interval = WRONG_MIN_INTERVAL
        ease = max(current.ease - EASE_STEP_DOWN, EASE_MIN)

    next_state = CardState(ease=ease, interval_days=interval, reps=reps)
    return Schedule(state=next_state, next_due=today + timedelta(days=interval))


def initial_state() -> CardState:
    return CardState(ease=EASE_START, interval_days=0, reps=0)
