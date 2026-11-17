#!/usr/bin/env python3
"""Win-rate report for the DevFun Arena TCG bot.

Pulls paginated match records, filters by an ISO-8601 window start, counts the
caller's own outcomes (``agentResult.outcome``), and reports the win rate with a
Wilson 95% confidence interval and a two-sided binomial p-value against a
baseline (by default the lifetime profile wins/matches).

Stdlib only. This module never starts, stops, or joins the bot process.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_EVIDENCE = SCRIPT_DIR / "evidence" / "wr-report.json"
DEFAULT_CREDS = Path.home() / ".arena-credentials"

API_BASE = "https://arena.dev.fun/api/arena"
DEFAULT_COMPETITION_ID = "cmw99opb57gssgfb7rj39a1o1"
DEFAULT_AGENT_ID = "cmqogaydkdghsnq1ql4t9anjt"

SHANGHAI = timezone(timedelta(hours=8))
Z95 = 1.959963984540054
MAX_LIMIT = 50
MAX_PAGES = 100


class ReportError(RuntimeError):
    """Raised for malformed API responses or unusable arguments."""


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
def parse_since(value: str) -> int:
    """Parse an ISO-8601 timestamp into epoch milliseconds.

    Naive timestamps are interpreted as Asia/Shanghai (+08:00), matching the
    restart log and the arena's local reporting convention.
    """
    text = value.strip()
    if not text:
        raise ReportError("--since must not be empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReportError(f"invalid --since timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SHANGHAI)
    return int(dt.timestamp() * 1000)


def iso_shanghai(epoch_ms: int | float | None) -> str | None:
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, SHANGHAI).isoformat(timespec="seconds")


def coerce_updated_at(value) -> int | None:
    """Return updatedAt as epoch milliseconds, or None if it cannot be read."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=SHANGHAI)
        return int(dt.timestamp() * 1000)
    return None


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def wilson_interval(wins: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return None
    p_hat = wins / n
    denom = 1.0 + z * z / n
    center = (p_hat + z * z / (2.0 * n)) / denom
    half = (z / denom) * math.sqrt(p_hat * (1.0 - p_hat) / n + z * z / (4.0 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def binom_p_value(wins: int, n: int, p0: float) -> tuple[float | None, float | None]:
    """Two-sided normal-approximation p-value for H0: p = p0.

    Uses the standard z statistic and ``math.erf`` (no continuity correction),
    so the result matches the arena's earlier 2.957 / 0.0031 calculation.
    """
    if n <= 0 or not (0.0 < p0 < 1.0):
        return None, None
    p_hat = wins / n
    se = math.sqrt(p0 * (1.0 - p0) / n)
    if se == 0:
        return None, None
    z = (p_hat - p0) / se
    phi = 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0)))
    p = max(0.0, min(1.0, 2.0 * (1.0 - phi)))
    return z, p


# --------------------------------------------------------------------------- #
# API fetching
# --------------------------------------------------------------------------- #
def http_get_json(url: str, api_key: str, timeout: float = 30.0) -> dict:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-arena-api-key"] = api_key
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise ReportError(f"arena API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ReportError(f"arena API unreachable: {exc.reason}") from exc
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ReportError(f"arena API returned non-JSON: {raw[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise ReportError("arena API returned an unexpected payload type")
    return payload


def _page_is_entirely_older(page: list[dict], since_ms: int) -> bool:
    if not page:
        return False
    for match in page:
        stamp = coerce_updated_at(match.get("updatedAt"))
        if stamp is None or stamp >= since_ms:
            return False
    return True


def fetch_matches(
    api_key: str,
    competition_id: str,
    agent_id: str,
    since_ms: int,
    limit: int = MAX_LIMIT,
    fetcher=None,
    max_pages: int = MAX_PAGES,
) -> dict:
    """Page through matches newest-first until the window is exhausted.

    ``fetcher(url, api_key) -> dict`` is injectable so tests never touch the
    network. Returns matches inside the window plus fetch metadata.
    """
    fetcher = fetcher or http_get_json
    limit = max(1, min(int(limit), MAX_LIMIT))
    cursor: str | None = None
    seen = 0
    pages = 0
    collected: list[dict] = []
    profile = None
    total = None
    stop = "max_pages"

    while pages < max_pages:
        params = {
            "competitionId": competition_id,
            "agentId": agent_id,
            "limit": str(limit),
        }
        if cursor:
            params["cursor"] = cursor
        url = f"{API_BASE}/tcg/matches?{urllib.parse.urlencode(params)}"
        payload = fetcher(url, api_key)
        pages += 1
        if not isinstance(payload, dict):
            raise ReportError("match fetcher must return a dict")

        if profile is None and isinstance(payload.get("profile"), dict):
            profile = payload["profile"]
        if total is None and isinstance(payload.get("total"), (int, float)):
            total = int(payload["total"])

        page = payload.get("matches") or []
        if not isinstance(page, list):
            raise ReportError("matches field is not a list")
        if not page:
            stop = "empty_page"
            break

        seen += len(page)
        collected.extend(page)

        if _page_is_entirely_older(page, since_ms):
            stop = "page_older_than_since"
            break

        next_cursor = payload.get("nextCursor")
        if not next_cursor or next_cursor == cursor:
            stop = "no_cursor"
            break
        cursor = str(next_cursor)

    in_window = [
        match
        for match in collected
        if (stamp := coerce_updated_at(match.get("updatedAt"))) is not None
        and stamp >= since_ms
    ]
    return {
        "matches": in_window,
        "profile": profile,
        "pages": pages,
        "seen": seen,
        "total": total,
        "stop": stop,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def summarize(matches: list[dict], agent_id: str | None = None) -> dict:
    counts = {"win": 0, "loss": 0, "draw": 0}
    records: list[dict] = []
    skipped = 0

    for match in matches:
        agent_result = match.get("agentResult") or {}
        outcome = str(agent_result.get("outcome") or "").lower()
        if outcome == "tie":
            outcome = "draw"
        if outcome not in counts:
            skipped += 1
            continue
        counts[outcome] += 1

        opponent = None
        players = match.get("players")
        if isinstance(players, list):
            for player in players:
                if not isinstance(player, dict):
                    continue
                if agent_id and player.get("agentId") == agent_id:
                    continue
                opponent = player.get("handle") or player.get("agentId")
                break

        records.append(
            {
                "matchId": match.get("matchId"),
                "outcome": outcome,
                "updatedAt": iso_shanghai(coerce_updated_at(match.get("updatedAt"))),
                "opponent": opponent,
                "reason": (match.get("result") or {}).get("reason"),
            }
        )

    n = counts["win"] + counts["loss"] + counts["draw"]
    win_rate = counts["win"] / n if n else None
    return {
        "matches": n,
        "wins": counts["win"],
        "losses": counts["loss"],
        "draws": counts["draw"],
        "win_rate": win_rate,
        "skipped_unsettled": skipped,
        "records": records,
    }


def resolve_baseline(spec: str | None, profile: dict | None) -> dict:
    """Resolve a baseline from a file, inline JSON, ratio, or the profile.

    Accepted forms:
      * path to a JSON file: {"wins": 208, "matches": 979} or {"rate": 0.2125}
      * inline JSON with the same shapes
      * "208/979"
      * "0.2125"
      * omitted -> profile wins/matches
    """
    source = "profile lifetime"
    wins = matches = None
    p0 = None

    if spec:
        raw: object
        candidate = Path(spec).expanduser()
        if candidate.is_file():
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ReportError(f"cannot read baseline file {spec!r}: {exc}") from exc
            source = f"file:{candidate}"
        else:
            try:
                raw = json.loads(spec)
                source = "inline json"
            except json.JSONDecodeError:
                raw = spec
                source = "inline value"

        if isinstance(raw, dict):
            if "wins" in raw and "matches" in raw:
                wins, matches = int(raw["wins"]), int(raw["matches"])
            elif "rate" in raw:
                p0 = float(raw["rate"])
            elif "p0" in raw:
                p0 = float(raw["p0"])
            else:
                raise ReportError("baseline JSON needs wins/matches, rate, or p0")
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            p0 = float(raw)
        elif isinstance(raw, str):
            text = raw.strip()
            if "/" in text:
                left, right = text.split("/", 1)
                try:
                    wins, matches = int(left), int(right)
                except ValueError as exc:
                    raise ReportError(f"invalid baseline ratio: {spec!r}") from exc
            else:
                try:
                    p0 = float(text)
                except ValueError as exc:
                    raise ReportError(f"invalid baseline: {spec!r}") from exc
        else:
            raise ReportError(f"unsupported baseline: {spec!r}")

    if p0 is None and wins is not None and matches:
        p0 = wins / matches
    if p0 is None and profile:
        pw, pm = profile.get("wins"), profile.get("matches")
        if isinstance(pw, (int, float)) and isinstance(pm, (int, float)) and pm:
            wins, matches = int(pw), int(pm)
            p0 = wins / matches
            source = "profile lifetime"
    if p0 is None:
        raise ReportError("no baseline available (profile has no wins/matches)")
    if not (0.0 <= p0 <= 1.0):
        raise ReportError(f"baseline rate out of range: {p0}")
    return {
        "source": source,
        "wins": wins,
        "matches": matches,
        "p0": p0,
    }


def build_report(
    matches: list[dict],
    profile: dict | None,
    since_ms: int,
    baseline_spec: str | None,
    agent_id: str,
    competition_id: str,
    fetch_meta: dict | None = None,
    now_ms: int | None = None,
) -> dict:
    summary = summarize(matches, agent_id=agent_id)
    baseline = resolve_baseline(baseline_spec, profile)
    ci = wilson_interval(summary["wins"], summary["matches"])
    z, p_value = binom_p_value(summary["wins"], summary["matches"], baseline["p0"])
    now_ms = now_ms if now_ms is not None else int(datetime.now(tz=SHANGHAI).timestamp() * 1000)

    fetch_meta = fetch_meta or {}
    report = {
        "task": "TCG-WR-REPORT",
        "requirement": (
            "Count caller outcomes in the window, win rate, Wilson 95% CI, and a "
            "two-sided binomial p-value versus a baseline."
        ),
        "generated_at": iso_shanghai(now_ms),
        "since": iso_shanghai(since_ms),
        "since_epoch_ms": since_ms,
        "competition_id": competition_id,
        "agent_id": agent_id,
        "window": {
            "matches": summary["matches"],
            "wins": summary["wins"],
            "losses": summary["losses"],
            "draws": summary["draws"],
            "win_rate": summary["win_rate"],
            "skipped_unsettled": summary["skipped_unsettled"],
        },
        "wilson_95_ci": list(ci) if ci else None,
        "baseline": {
            "source": baseline["source"],
            "wins": baseline["wins"],
            "matches": baseline["matches"],
            "p0": baseline["p0"],
            "z": z,
            "p_value": p_value,
        },
        "fetch": {
            "pages": fetch_meta.get("pages"),
            "matches_seen": fetch_meta.get("seen"),
            "matches_in_window": len(matches),
            "total_reported": fetch_meta.get("total"),
            "stop_reason": fetch_meta.get("stop"),
        },
        "matches": summary["records"],
    }
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def format_summary(report: dict, evidence_path: Path | None) -> str:
    win = report["window"]
    base = report["baseline"]
    ci = report["wilson_95_ci"]
    rate = win["win_rate"]
    lines = [
        f"Win-rate report  since {report['since']}  (Asia/Shanghai)",
        f"Agent {report['agent_id']}  competition {report['competition_id']}",
        f"Matches {win['matches']}  W {win['wins']}  L {win['losses']}  D {win['draws']}"
        + (f"  (skipped {win['skipped_unsettled']})" if win["skipped_unsettled"] else ""),
        "Win rate "
        + (f"{rate * 100:.2f}%" if rate is not None else "n/a")
        + (f"  Wilson 95% CI [{ci[0] * 100:.2f}%, {ci[1] * 100:.2f}%]" if ci else ""),
    ]
    baseline_desc = f"{base['p0'] * 100:.2f}%"
    if base["wins"] is not None and base["matches"]:
        baseline_desc += f" ({base['wins']}W/{base['matches']}M, {base['source']})"
    else:
        baseline_desc += f" ({base['source']})"
    if base["z"] is not None and base["p_value"] is not None:
        lines.append(
            f"Baseline {baseline_desc}  z={base['z']:.2f}  two-sided p={base['p_value']:.4f}"
        )
    else:
        lines.append(f"Baseline {baseline_desc}  z/p n/a")
    fetch = report["fetch"]
    if fetch.get("pages"):
        lines.append(
            f"Pages {fetch['pages']}  seen {fetch['matches_seen']}  "
            f"in window {fetch['matches_in_window']}  stop {fetch.get('stop_reason')}"
        )
    if evidence_path:
        lines.append(f"JSON evidence {evidence_path}")
    return "\n".join(lines)


def load_api_key(path: Path) -> tuple[str, str | None]:
    try:
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read credentials {path}: {exc}") from exc
    api_key = data.get("apiKey")
    if not api_key:
        raise ReportError(f"credentials {path} missing apiKey")
    return api_key, data.get("agentId")


def run(argv: list[str] | None = None, fetcher=None, now_ms: int | None = None) -> dict:
    parser = argparse.ArgumentParser(
        description="Win-rate report from paginated arena TCG match records."
    )
    parser.add_argument(
        "--since",
        required=True,
        help="ISO-8601 window start; naive values are Asia/Shanghai.",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Baseline as a JSON file, inline JSON, 'wins/matches', or a rate.",
    )
    parser.add_argument(
        "--json",
        nargs="?",
        const=str(DEFAULT_EVIDENCE),
        default=str(DEFAULT_EVIDENCE),
        help=f"JSON evidence output path (default: {DEFAULT_EVIDENCE})",
    )
    parser.add_argument("--no-json", action="store_true", help="Do not write JSON evidence.")
    parser.add_argument("--limit", type=int, default=MAX_LIMIT, help="Page size (max 50).")
    parser.add_argument("--competition-id", default=DEFAULT_COMPETITION_ID)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument("--credentials", default=str(DEFAULT_CREDS))
    args = parser.parse_args(argv)

    since_ms = parse_since(args.since)
    api_key = ""
    creds_agent_id = None
    if fetcher is None:
        api_key, creds_agent_id = load_api_key(Path(args.credentials))
    agent_id = args.agent_id or creds_agent_id or DEFAULT_AGENT_ID

    fetched = fetch_matches(
        api_key=api_key,
        competition_id=args.competition_id,
        agent_id=agent_id,
        since_ms=since_ms,
        limit=args.limit,
        fetcher=fetcher,
    )
    report = build_report(
        matches=fetched["matches"],
        profile=fetched.get("profile"),
        since_ms=since_ms,
        baseline_spec=args.baseline,
        agent_id=agent_id,
        competition_id=args.competition_id,
        fetch_meta=fetched,
        now_ms=now_ms,
    )

    evidence_path = None
    if not args.no_json:
        evidence_path = Path(args.json).expanduser()
        if not evidence_path.is_absolute():
            evidence_path = SCRIPT_DIR / evidence_path
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    print(format_summary(report, evidence_path))
    return report


def main(argv: list[str] | None = None) -> int:
    try:
        run(argv)
    except ReportError as exc:
        print(f"wr_report: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
