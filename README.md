# neetcode-srs

Daily spaced-repetition CLI over the [NeetCode 250](https://neetcode.io/practice?tab=neetcode250).
One card a day, answer `y` or `n`, SM-2 scheduling decides when you see it again.
New cards go Easy → Medium → Hard so muscle memory builds up gradually.

```
  New problem
  Two Sum  [Easy]  Arrays & Hashing
  https://leetcode.com/problems/two-sum/

  y = solved · n = couldn't solve · e = trivially easy · skip
  Answer [y/n/e/skip] > y
  solved — next review in 4 days (2026-04-26).
```

## Install

Requirements: Python 3.10+ and `git`. On macOS, `brew install python@3.13` if you need it.

```bash
git clone https://github.com/siddhant1/neetcode-srs.git ~/projects/neetcode-srs
cd ~/projects/neetcode-srs

python3 -m venv .venv
.venv/bin/pip install -e .

# Symlink the CLI onto your PATH (adjust target dir if needed):
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/neetcode" ~/.local/bin/neetcode
```

Make sure `~/.local/bin` is on your `PATH`. Add this to `~/.zshrc` if it isn't:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Open a new shell, then initialize the deck:

```bash
neetcode setup      # fetches the 250 list from neetcode.io, populates SQLite
neetcode stats      # should show: 250 total · 250 new
```

## Daily use

```bash
neetcode            # show today's card, prompts y / n / e / skip
neetcode stats      # deck progress
neetcode history 20 # last 20 reviews
neetcode skip       # postpone today's card one day
neetcode setup --refresh   # re-fetch the problem list if NeetCode updates it
```

One card per calendar day by default. Run `neetcode` again after answering
and it tells you you're done. Want more per day?

```bash
neetcode config daily 3   # now you can do 3 cards/day
neetcode config           # show current config
```

Each invocation still shows one card — `daily` just controls how many times
you can run it before it blocks you until tomorrow.

## Scheduling rules

Three grades, SM-2 under the hood:

- **`y` — solved it.**
  - First time on a fresh card: interval jumps to **4 days** (no 1-day probe — a first-shot pass is strong evidence, and each LeetCode review costs real time).
  - After that: `round(interval × ease)`. Ease grows by 0.05 per correct (cap 2.8).
- **`e` — trivially easy.**
  - First time on a fresh card: interval jumps to **7 days**.
  - After that: `round(interval × ease × 1.3)` — the Anki "easy bonus". Ease grows by 0.15.
- **`n` — couldn't solve.**
  - Streak resets, card pushed out **at least 3 days** — not tomorrow. The brain needs time to forget and re-encounter cleanly.
  - Ease drops by 0.2 (floor 1.3).

New cards are introduced in order **Easy (60) → Medium (155) → Hard (35)** within the
NeetCode list ordering. Due reviews always beat new cards when both are available.

## Data

Everything lives in `data/`:

- `neetcode250.json` — cached problem list (committed).
- `state.db` — SQLite with your progress and audit log (gitignored).

Back up `state.db` if you care about your streak.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/pytest
```
