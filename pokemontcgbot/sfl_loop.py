"""Durable three-stage self-fixing loop (SFL) for the TCG bot.

The loop has three deliberately separate stages:

1. FAILURE  -> append a raw record to ``corrections/tcg/failures.jsonl``.
2. RULE     -> synthesize an idempotent, deduplicated rule into
               ``corrections/tcg/rules.md`` and expose it through
               ``active_rules()`` for context injection.
3. VERIFY   -> record a check in ``corrections/tcg/verify.json`` where the
               *rule result* is tracked independently of the match *outcome*.

``failures.jsonl`` is the authoritative source of truth.  ``rules.md`` is a
derived, human-readable view and is never trusted as input; ``verify.json``
is validated strictly and corruption is surfaced, never zeroed silently.

All reads and writes are serialized in-process with an RLock and across
processes with a POSIX ``flock`` on ``corrections/tcg/.lock``.  On platforms
without ``fcntl`` exactly one writer process may own a correction directory;
concurrent writers are not supported there.

Stdlib only.  This module never changes live policy, decks, or processes; it
only maintains durable correction artifacts under a caller-supplied root.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:  # pragma: no cover - exercised only on POSIX hosts
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms: single writer only
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

CORRECTIONS_REL = Path("corrections") / "tcg"
FAILURES_NAME = "failures.jsonl"
RULES_NAME = "rules.md"
VERIFY_NAME = "verify.json"
LOCK_NAME = ".lock"
RULES_HEADER = "# Active SFL rules\n\n"

MAX_RULE_ID_LEN = 128
MAX_RULE_TEXT_LEN = 2000
MAX_TOKEN_LEN = 128
DEFAULT_RULE_ID = "R-SFL-UNSPECIFIED"
_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9._:-]")
_UNDERSCORES = re.compile(r"_+")
_WHITESPACE = re.compile(r"\s+")
_LINE_SEPARATORS = {"\u2028", "\u2029"}


class VerificationDataCorrupt(ValueError):
    """Raised when verify.json is malformed; never silently zero its data."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_id(raw: Any, fallback: str) -> str:
    """Reduce an arbitrary value to a single safe markdown bracket token.

    Newlines, control characters, brackets and other punctuation are removed
    so a rule id can never inject a phantom bullet into ``rules.md``.
    """
    text = _UNSAFE_ID_CHARS.sub("_", str(raw).strip())
    text = _UNDERSCORES.sub("_", text).strip("_.")
    text = text[:MAX_RULE_ID_LEN]
    return text or fallback


def _sanitize_text(raw: Any, max_len: int = MAX_RULE_TEXT_LEN) -> str:
    """Collapse arbitrary text into one safe single-line string."""
    cleaned = "".join(
        " "
        if (ord(ch) < 32 or ord(ch) == 127 or ch in _LINE_SEPARATORS)
        else ("(" if ch == "[" else ")" if ch == "]" else ch)
        for ch in str(raw)
    )
    return _WHITESPACE.sub(" ", cleaned).strip()[:max_len]


def _sanitize_severity(raw: Any) -> str:
    return _sanitize_id(raw, "warning").lower()[:MAX_TOKEN_LEN]


def _atomic_write_text(path: Path, text: str) -> None:
    """Durably replace ``path`` with ``text`` (temp file + fsync + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        # Best-effort directory fsync so the rename itself survives a crash.
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:  # pragma: no cover - unsupported on some filesystems
            log.debug("sfl_loop: directory fsync unsupported for %s", path.parent)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class CorrectionStore:
    """Append-only failure log plus deduplicated, injectable rules.

    All artifacts live under ``root/corrections/tcg``.  ``failures.jsonl`` is
    the raw source of truth (append-only); ``rules.md`` and ``verify.json`` are
    derived/updated views.  Rules are keyed by ``rule_id`` so re-recording the
    same correction never duplicates an active rule.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.correction_dir = self.root / CORRECTIONS_REL
        self.failures_path = self.correction_dir / FAILURES_NAME
        self.rules_path = self.correction_dir / RULES_NAME
        self.verify_path = self.correction_dir / VERIFY_NAME
        self.lock_path = self.correction_dir / LOCK_NAME
        self._lock = threading.RLock()
        self._lock_depth = 0
        self._rules: dict[str, dict[str, str]] = {}
        # Startup must never prevent the host process from running: a bad or
        # read-only correction directory degrades to an empty in-memory map.
        try:
            self.correction_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("sfl_loop: cannot create correction dir %s: %s", self.correction_dir, exc)
        try:
            with self._locked(exclusive=False):
                self._rules = self._load_rules()
        except (OSError, UnicodeError, ValueError) as exc:
            log.warning("sfl_loop: startup rule load failed: %s", exc)

    @contextmanager
    def _locked(self, exclusive: bool = True) -> Iterator[None]:
        """Serialize access in-process (RLock) and across processes (flock).

        Nested acquisitions in the same instance share one flock; internal
        helpers therefore never take the lock themselves.
        """
        with self._lock:
            outermost = self._lock_depth == 0
            self._lock_depth += 1
            fd: int | None = None
            try:
                if outermost and fcntl is not None:
                    fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
                    fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                yield
            finally:
                self._lock_depth -= 1
                if fd is not None:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    finally:
                        os.close(fd)

    # ------------------------------------------------------------------ #
    # Stage 1 + 2: failure -> persistent rule
    # ------------------------------------------------------------------ #

    def _load_rules(self) -> dict[str, dict[str, str]]:
        """Rebuild the deduplicated rule map from the authoritative log.

        Caller holds ``_locked``.  Malformed lines are logged and skipped; a
        single bad line must not erase every other rule.
        """
        rules: dict[str, dict[str, str]] = {}
        if not self.failures_path.exists():
            return rules
        try:
            fh = self.failures_path.open("r", encoding="utf-8")
        except OSError as exc:
            log.warning("sfl_loop: cannot read failures log: %s", exc)
            return rules
        with fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (ValueError, TypeError):
                    log.warning("sfl_loop: skipping malformed failures.jsonl line %d", lineno)
                    continue
                if not isinstance(rec, dict):
                    log.warning(
                        "sfl_loop: skipping non-object failures.jsonl line %d", lineno
                    )
                    continue
                raw_id = rec.get("rule_id")
                if raw_id is None:
                    continue
                rule_id = _sanitize_id(raw_id, "")
                if not rule_id:
                    log.warning("sfl_loop: skipping unusable rule id on line %d", lineno)
                    continue
                # Last write wins for the text of an existing rule id; the
                # deduplication key is always the rule id.
                rules[rule_id] = {
                    "rule_text": _sanitize_text(rec.get("rule_text", "")),
                    "severity": _sanitize_severity(rec.get("severity", "warning")),
                    "failure_type": _sanitize_text(rec.get("failure_type", ""), MAX_TOKEN_LEN),
                }
        return rules

    def _format_rule(self, rule_id: str, entry: dict[str, str]) -> str:
        """Render one safe, single-line rule (never parse rules.md as input)."""
        rid = _sanitize_id(rule_id, DEFAULT_RULE_ID)
        text = _sanitize_text(entry.get("rule_text", ""))
        sev = _sanitize_severity(entry.get("severity", "warning"))
        return f"- [{rid}] {text} (severity: {sev})"

    def _write_rules(self) -> None:
        """Rewrite rules.md deterministically and atomically."""
        lines = [RULES_HEADER]
        for rule_id in sorted(self._rules):
            lines.append(self._format_rule(rule_id, self._rules[rule_id]) + "\n")
        _atomic_write_text(self.rules_path, "".join(lines))

    def record_failure(
        self,
        failure_type: str,
        rule_id: str,
        rule_text: str,
        evidence: str = "",
        severity: str = "warning",
    ) -> None:
        """Stage 1 + 2: log the failure and synthesize its persistent rule."""
        rid = _sanitize_id(rule_id, DEFAULT_RULE_ID)
        text = _sanitize_text(rule_text)
        sev = _sanitize_severity(severity)
        ftype = _sanitize_text(failure_type, MAX_TOKEN_LEN)
        with self._locked(exclusive=True):
            record = {
                "ts": _now_iso(),
                "failure_type": ftype,
                "rule_id": rid,
                "rule_text": text,
                "evidence": str(evidence),
                "severity": sev,
            }
            self.failures_path.parent.mkdir(parents=True, exist_ok=True)
            with self.failures_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._rules[rid] = {
                "rule_text": text,
                "severity": sev,
                "failure_type": ftype,
            }
            self._write_rules()

    def active_rules(self) -> list[str]:
        """Stage 2: rules to inject into an agent's context.

        Derived strictly from the authoritative failure log / in-memory map.
        ``rules.md`` is a derived view and is never consulted, so tampering
        with it cannot inject phantom rules into an agent's context.
        """
        with self._locked(exclusive=False):
            try:
                self._rules = self._load_rules()
            except (OSError, UnicodeError, ValueError) as exc:
                log.warning("sfl_loop: rule refresh failed, using in-memory map: %s", exc)
            return [
                self._format_rule(rule_id, entry)
                for rule_id, entry in sorted(self._rules.items())
            ]

    # ------------------------------------------------------------------ #
    # Stage 3: verification separate from outcome
    # ------------------------------------------------------------------ #

    def _load_verify(self) -> dict[str, list[dict[str, Any]]]:
        """Load verify.json strictly; corruption is surfaced, never zeroed."""
        if not self.verify_path.exists():
            return {"checks": []}
        try:
            raw = self.verify_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise VerificationDataCorrupt(f"cannot read verify.json: {exc}") from exc
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise VerificationDataCorrupt(f"verify.json is not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
            raise VerificationDataCorrupt(
                "verify.json must be an object with a 'checks' list"
            )
        for idx, check in enumerate(data["checks"]):
            if not isinstance(check, dict):
                raise VerificationDataCorrupt(
                    f"verify.json checks[{idx}] is not an object"
                )
        return data

    def verify(
        self,
        rule_id: str,
        check: str,
        rule_passed: bool,
        outcome: str,
        evidence: str = "",
    ) -> None:
        """Stage 3: record a check against a known rule.

        ``rule_passed`` is the *rule's* result; ``outcome`` is the match result.
        They are stored independently so a rule failure is not hidden by a
        winning outcome (or vice versa).
        """
        rid = _sanitize_id(rule_id, "")
        with self._locked(exclusive=True):
            # A rule may have been created by another store instance since
            # this one was constructed; always refresh the authoritative map.
            try:
                self._rules = self._load_rules()
            except (OSError, UnicodeError, ValueError) as exc:
                log.warning("sfl_loop: rule refresh failed on verify: %s", exc)
            if not rid or rid not in self._rules:
                raise ValueError(f"unknown rule id: {rule_id}")
            data = self._load_verify()
            data["checks"].append(
                {
                    "ts": _now_iso(),
                    "rule_id": rid,
                    "check": _sanitize_text(check, MAX_TOKEN_LEN),
                    "rule_passed": bool(rule_passed),
                    "outcome": _sanitize_text(outcome, MAX_TOKEN_LEN),
                    "evidence": str(evidence),
                }
            )
            _atomic_write_text(
                self.verify_path,
                json.dumps(data, indent=2, sort_keys=True) + "\n",
            )

    def verification_report(self) -> dict[str, int]:
        """Stage 3 totals: rule results and outcomes counted separately."""
        with self._locked(exclusive=False):
            checks = self._load_verify()["checks"]
            return {
                "checks": len(checks),
                "rule_failures": sum(1 for c in checks if not c.get("rule_passed")),
                "outcome_wins": sum(1 for c in checks if c.get("outcome") == "win"),
            }
