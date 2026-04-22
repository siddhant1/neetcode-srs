from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

NEETCODE_HOME = "https://neetcode.io/"
LEETCODE_BASE = "https://leetcode.com/problems/"
USER_AGENT = "neetcode-srs/0.1 (+https://github.com/local)"


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def _find_main_bundle_url(home_html: str) -> str:
    m = re.search(r'src="(main\.[a-f0-9]+\.js)"', home_html)
    if not m:
        raise RuntimeError("Could not locate main.<hash>.js in neetcode.io homepage")
    return NEETCODE_HOME + m.group(1)


def _extract_problems_array(js: str) -> str:
    """Return the JS source of the big problems array from the bundle.

    The array starts with `[{problem:"Concatenation of Array"...` and we walk
    bracket depth — respecting strings — to find the matching close.
    """
    m = re.search(r'=\[\{problem:"Concatenation of Array"', js)
    if not m:
        raise RuntimeError("Could not locate problems array in neetcode.io bundle")
    start = m.start() + 1
    depth = 0
    in_str = False
    esc = False
    i = start
    n = len(js)
    while i < n:
        c = js[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return js[start : i + 1]
        i += 1
    raise RuntimeError("Unterminated problems array in bundle")


def _js_to_json(src: str) -> str:
    """Convert the JS object-literal array to JSON.

    Handles two non-JSON-isms: unquoted keys and !0 / !1 boolean shorthand.
    String contents are left untouched.
    """
    out: list[str] = []
    i = 0
    n = len(src)
    in_str = False
    esc = False
    while i < n:
        c = src[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            out.append(c)
            in_str = True
            i += 1
            continue
        if c in "{,":
            out.append(c)
            i += 1
            while i < n and src[i].isspace():
                out.append(src[i])
                i += 1
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            if j > i and j < n and src[j] == ":":
                out.append('"' + src[i:j] + '"')
                i = j
            continue
        if c == "!" and i + 1 < n and src[i + 1] in "01":
            out.append("true" if src[i + 1] == "0" else "false")
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _normalize(raw: list[dict]) -> list[dict]:
    nc250 = [p for p in raw if p.get("neetcode250")]
    if len(nc250) != 250:
        # Don't hard-fail — NeetCode may tweak the list. Warn via exception only if way off.
        if not (200 <= len(nc250) <= 300):
            raise RuntimeError(
                f"Extracted {len(nc250)} problems flagged neetcode250 — expected ~250"
            )
    normalized = []
    for p in nc250:
        slug = p["link"].rstrip("/")
        normalized.append(
            {
                "id": slug,
                "title": p["problem"],
                "difficulty": p["difficulty"],
                "topics": [p["pattern"]],
                "leetcode_url": f"{LEETCODE_BASE}{slug}/",
            }
        )
    return normalized


def fetch_neetcode250() -> list[dict]:
    """Fetch the NeetCode 250 list from neetcode.io. Network + parse."""
    home = _http_get(NEETCODE_HOME)
    bundle_url = _find_main_bundle_url(home)
    js = _http_get(bundle_url)
    arr_src = _extract_problems_array(js)
    raw = json.loads(_js_to_json(arr_src))
    return _normalize(raw)


def load_cached(cache_path: Path) -> list[dict] | None:
    if not cache_path.exists():
        return None
    blob = json.loads(cache_path.read_text())
    return blob["problems"]


def save_cache(cache_path: Path, problems: list[dict]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "count": len(problems),
                "problems": problems,
            },
            indent=2,
        )
    )
