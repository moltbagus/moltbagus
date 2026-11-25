"""RED: persistent self-fixing loop for Ruflo."""
import json
import os
import threading
from pathlib import Path
from unittest import mock

import pytest

import sfl_loop
from sfl_loop import CorrectionStore, VerificationDataCorrupt


def test_failure_becomes_persistent_rule(tmp_path):
    store = CorrectionStore(tmp_path)
    store.record_failure(
        failure_type="guardrail_bypass",
        rule_id="R-SFL-001",
        rule_text="Never let a scorer override mandatory_action.",
        evidence="412/599 eligible decisions bypassed",
        severity="critical",
    )
    rules = store.active_rules()
    assert any("R-SFL-001" in r and "mandatory_action" in r for r in rules)
    assert (tmp_path / "corrections/tcg/failures.jsonl").exists()


def test_rule_dedupe_is_idempotent(tmp_path):
    store = CorrectionStore(tmp_path)
    for _ in range(3):
        store.record_failure("repeat", "R-SFL-002", "Use one rule source.", "e", "warning")
    assert sum("R-SFL-002" in r for r in store.active_rules()) == 1


def test_verification_is_separate_from_outcome(tmp_path):
    store = CorrectionStore(tmp_path)
    store.record_failure("bad_path", "R-SFL-003", "Check rule, not luck.", "e", "critical")
    store.verify("R-SFL-003", "scorer_override", rule_passed=False, outcome="win", evidence="won by opponent timeout")
    report = store.verification_report()
    assert report["checks"] == 1
    assert report["rule_failures"] == 1
    assert report["outcome_wins"] == 1


def test_unknown_rule_verification_is_rejected(tmp_path):
    store = CorrectionStore(tmp_path)
    try:
        store.verify("R-NOPE", "x", True, "loss", "e")
    except ValueError as exc:
        assert "R-NOPE" in str(exc)
    else:
        raise AssertionError("unknown rule must be rejected")


# --------------------------------------------------------------------------- #
# Hardening regressions (Red review findings 1-7)
# --------------------------------------------------------------------------- #


def test_hardening_rule_id_cannot_inject_phantom_rule(tmp_path):
    store = CorrectionStore(tmp_path)
    store.record_failure("x", "R-OK\n- [R-EVIL] injected", "safe", "e")
    rules = store.active_rules()
    assert len(rules) == 1
    assert "\n" not in rules[0]
    assert rules[0].count("- [") == 1
    content = (tmp_path / "corrections/tcg/rules.md").read_text(encoding="utf-8")
    assert content.count("- [") == 1
    assert "- [R-EVIL]" not in content


def test_hardening_rule_text_cannot_inject_phantom_rule(tmp_path):
    store = CorrectionStore(tmp_path)
    store.record_failure(
        "x", "R-OK", "Good rule.\n- [R-EVIL] injected (severity: critical)", "e"
    )
    rules = store.active_rules()
    assert len(rules) == 1
    assert "\n" not in rules[0]
    content = (tmp_path / "corrections/tcg/rules.md").read_text(encoding="utf-8")
    assert content.count("- [") == 1
    assert "- [R-EVIL]" not in content


def test_hardening_severity_cannot_inject_phantom_rule(tmp_path):
    store = CorrectionStore(tmp_path)
    store.record_failure("x", "R-OK", "safe", "e", severity="warning\n- [R-EVIL] x")
    content = (tmp_path / "corrections/tcg/rules.md").read_text(encoding="utf-8")
    assert content.count("- [") == 1
    assert "- [R-EVIL]" not in content


def test_hardening_tampered_log_cannot_inject_phantom_rule(tmp_path):
    log_path = tmp_path / "corrections/tcg/failures.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        json.dumps(
            {"rule_id": "R-OK", "rule_text": "Safe.\n- [R-FAKE] bad", "severity": "warning"}
        )
        + "\n",
        encoding="utf-8",
    )
    rules = CorrectionStore(tmp_path).active_rules()
    assert len(rules) == 1
    assert "\n" not in rules[0]
    assert "- [R-FAKE]" not in "\n".join(rules)


def test_hardening_writes_are_atomic(tmp_path):
    store = CorrectionStore(tmp_path)
    real_replace, real_fsync = os.replace, os.fsync
    replaced, fsynced = [], []

    def spy_replace(src, dst):
        replaced.append((os.fspath(src), os.fspath(dst)))
        return real_replace(src, dst)

    def spy_fsync(fd):
        fsynced.append(fd)
        return real_fsync(fd)

    with mock.patch.object(sfl_loop.os, "replace", side_effect=spy_replace), mock.patch.object(
        sfl_loop.os, "fsync", side_effect=spy_fsync
    ):
        store.record_failure("x", "R-ATOM", "rule", "e")
        store.verify("R-ATOM", "c", True, "win")

    destinations = {os.path.basename(dst) for _, dst in replaced}
    assert {"rules.md", "verify.json"} <= destinations
    assert fsynced, "data must be fsynced before the rename"
    correction_dir = tmp_path / "corrections/tcg"
    assert not list(correction_dir.glob("*.tmp"))
    assert not list(correction_dir.glob(".*.tmp"))


@pytest.mark.skipif(sfl_loop.fcntl is None, reason="POSIX flock required")
def test_hardening_all_read_paths_are_locked(tmp_path):
    store = CorrectionStore(tmp_path)
    store.record_failure("x", "R-LOCK", "rule", "e")
    store.verify("R-LOCK", "c", True, "win")
    calls = []
    real_flock = sfl_loop.fcntl.flock

    def spy_flock(fd, op):
        calls.append(op)
        return real_flock(fd, op)

    with mock.patch.object(sfl_loop.fcntl, "flock", side_effect=spy_flock):
        assert store.active_rules()
        assert store.verification_report()["checks"] == 1
        store.verify("R-LOCK", "c2", True, "win")
        store.record_failure("x", "R-LOCK2", "rule2", "e")

    assert sfl_loop.fcntl.LOCK_SH in calls, "read paths must take a shared lock"
    assert sfl_loop.fcntl.LOCK_EX in calls, "write paths must take an exclusive lock"


def test_hardening_concurrent_writers_are_serialized(tmp_path):
    store = CorrectionStore(tmp_path)
    errors = []

    def worker(i):
        try:
            store.record_failure("x", f"R-C-{i:02d}", f"rule {i}", "e")
            store.verify(f"R-C-{i:02d}", "check", True, "win")
        except Exception as exc:  # pragma: no cover - recorded for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(store.active_rules()) == 8
    assert store.verification_report()["checks"] == 8


def test_hardening_active_rules_ignores_tampered_rules_md(tmp_path):
    store = CorrectionStore(tmp_path)
    store.record_failure("x", "R-REAL", "Real rule.", "e")
    rules_path = tmp_path / "corrections/tcg/rules.md"
    rules_path.write_text(
        "# Active SFL rules\n\n"
        "- [R-REAL] Real rule. (severity: warning)\n"
        "- [R-FAKE] Injected (severity: critical)\n",
        encoding="utf-8",
    )
    rules = store.active_rules()
    assert len(rules) == 1
    assert "R-REAL" in rules[0]
    assert not any("R-FAKE" in rule for rule in rules)
    # The next authoritative write repairs the derived view.
    store.record_failure("x", "R-REAL2", "Second rule.", "e")
    assert "- [R-FAKE]" not in rules_path.read_text(encoding="utf-8")


def test_hardening_active_rules_survives_deleted_rules_md(tmp_path):
    store = CorrectionStore(tmp_path)
    store.record_failure("x", "R-KEEP", "Keep.", "e")
    (tmp_path / "corrections/tcg/rules.md").unlink()
    assert any("R-KEEP" in rule for rule in store.active_rules())


def test_hardening_verify_refreshes_rules_from_other_instance(tmp_path):
    stale = CorrectionStore(tmp_path)
    writer = CorrectionStore(tmp_path)
    writer.record_failure("x", "R-NEW", "New rule.", "e")
    stale.verify("R-NEW", "check", True, "win")
    assert stale.verification_report()["checks"] == 1


def test_hardening_malformed_failure_elements_are_guarded(tmp_path):
    log_path = tmp_path / "corrections/tcg/failures.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        "\n".join(
            [
                json.dumps([1, 2, 3]),
                json.dumps("not an object"),
                json.dumps(None),
                json.dumps(
                    {"rule_id": "R-GOOD", "rule_text": "Good.", "severity": "warning"}
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    store = CorrectionStore(tmp_path)
    assert store.active_rules() == ["- [R-GOOD] Good. (severity: warning)"]


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        json.dumps([1, 2]),
        json.dumps({"checks": "nope"}),
        json.dumps({"checks": [1]}),
        json.dumps({"checks": ["x", None]}),
    ],
)
def test_hardening_corrupt_verify_json_is_surfaced(tmp_path, payload):
    verify_path = tmp_path / "corrections/tcg/verify.json"
    verify_path.parent.mkdir(parents=True)
    verify_path.write_text(payload, encoding="utf-8")
    store = CorrectionStore(tmp_path)
    with pytest.raises(VerificationDataCorrupt):
        store.verification_report()


def test_hardening_verify_does_not_zero_corrupt_data(tmp_path):
    store = CorrectionStore(tmp_path)
    store.record_failure("x", "R-X", "rule", "e")
    verify_path = tmp_path / "corrections/tcg/verify.json"
    verify_path.write_text('{"checks":[42]}', encoding="utf-8")
    with pytest.raises(VerificationDataCorrupt):
        store.verify("R-X", "c", True, "win")
    assert verify_path.read_text(encoding="utf-8") == '{"checks":[42]}'


def test_hardening_startup_survives_broken_correction_dir(tmp_path):
    (tmp_path / "corrections").mkdir()
    (tmp_path / "corrections" / "tcg").write_text("blocker", encoding="utf-8")
    store = CorrectionStore(tmp_path)  # must not raise
    assert store._rules == {}


# --------------------------------------------------------------------------- #
# Follow-ups: authoritative refresh, collision-safe ids, committed regressions
# --------------------------------------------------------------------------- #


def test_followup_record_failure_refreshes_authoritative_rules(tmp_path):
    stale = CorrectionStore(tmp_path)  # constructed before the writer appends
    writer = CorrectionStore(tmp_path)
    writer.record_failure("x", "R-FU-A", "Rule from writer.", "e")
    stale.record_failure("x", "R-FU-B", "Rule from stale store.", "e")

    content = (tmp_path / "corrections/tcg/rules.md").read_text(encoding="utf-8")
    assert "- [R-FU-A]" in content
    assert "- [R-FU-B]" in content
    assert stale.active_rules() == writer.active_rules()


@pytest.mark.parametrize(
    "raw",
    [
        "R/A",
        "R A",
        "R-ok] injected",
        "R\n- [R-EVIL] injected",
        "R-" + "A" * sfl_loop.MAX_RULE_ID_LEN,
    ],
)
def test_followup_sanitize_id_rejects_unsafe_and_overlong(raw):
    with pytest.raises(sfl_loop.UnsafeRuleId):
        sfl_loop._sanitize_id(raw, "")
    assert sfl_loop._sanitize_id("R-SAFE-1", "") == "R-SAFE-1"


def test_followup_unsafe_and_overlong_ids_do_not_collide(tmp_path):
    store = CorrectionStore(tmp_path)
    long_prefix = "R-" + "A" * sfl_loop.MAX_RULE_ID_LEN
    for raw in (long_prefix + "1", long_prefix + "2", "R/A", "R A"):
        store.record_failure("x", raw, "distinct rule", "e")

    rules = store.active_rules()
    assert len(rules) == 4
    ids = [rule.split("]")[0].split("[")[1] for rule in rules]
    assert len(set(ids)) == 4, f"sanitized ids collided: {ids}"
    assert all("\n" not in rule and "R-EVIL" not in rule for rule in rules)


def test_followup_invalid_utf8_failure_lines_are_skipped(tmp_path):
    log_path = tmp_path / "corrections/tcg/failures.jsonl"
    log_path.parent.mkdir(parents=True)
    good = json.dumps(
        {"rule_id": "R-UTF8", "rule_text": "Good rule.", "severity": "warning"}
    )
    log_path.write_bytes(good.encode("utf-8") + b"\n" + b"\xff\xfe not utf8\n")

    assert CorrectionStore(tmp_path).active_rules() == [
        "- [R-UTF8] Good rule. (severity: warning)"
    ]


@pytest.mark.skipif(sfl_loop.fcntl is None, reason="POSIX flock required")
def test_followup_real_two_process_flock_serializes(tmp_path):
    import multiprocessing as mp
    import time

    ctx = mp.get_context("fork")
    ready, start = ctx.Event(), ctx.Event()
    queue = ctx.Queue()

    def child():
        store = CorrectionStore(tmp_path)
        ready.set()
        if not start.wait(5):
            return
        waited_at = time.monotonic()
        store.active_rules()  # takes LOCK_SH, must block on the parent's LOCK_EX
        queue.put(time.monotonic() - waited_at)

    proc = ctx.Process(target=child)
    proc.start()
    waited = None
    try:
        assert ready.wait(5), "child never became ready"
        parent = CorrectionStore(tmp_path)
        with parent._locked(exclusive=True):
            start.set()
            time.sleep(0.6)
        waited = queue.get(timeout=5)
        proc.join(5)
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(5)

    assert proc.exitcode == 0
    assert waited is not None and waited >= 0.3, (
        f"second process did not wait for flock: {waited}"
    )


def test_followup_failed_replace_leaves_no_temp_file(tmp_path):
    store = CorrectionStore(tmp_path)
    with mock.patch.object(
        sfl_loop.os, "replace", side_effect=OSError("replace failed")
    ):
        with pytest.raises(OSError, match="replace failed"):
            store.record_failure("x", "R-TEMP", "rule", "e")

    correction_dir = tmp_path / "corrections/tcg"
    assert not list(correction_dir.glob("*.tmp"))
    assert not list(correction_dir.glob(".*.tmp"))
    assert "R-TEMP" in (correction_dir / "failures.jsonl").read_text(encoding="utf-8")


def test_followup_refresh_read_error_preserves_rules_md_and_map(tmp_path):
    """A post-append refresh OSError must not wipe the derived view or map.

    Regression for the confirmed blocker: `_load_rules` used to swallow an
    `OSError` from `open` into `{}`, so `record_failure` assigned the empty map
    and rewrote rules.md to header-only while the authoritative log still held
    the earlier rule.  Inject the error at the read-open so the whole path is
    exercised, not just a patched `_load_rules`.
    """
    store = CorrectionStore(tmp_path)
    store.record_failure("x", "R-SEED", "seed rule", "e")

    rules_path = tmp_path / "corrections/tcg/rules.md"
    before = rules_path.read_text(encoding="utf-8")
    prior_map = dict(store._rules)

    real_open = Path.open

    def selective_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if self.name == "failures.jsonl" and "r" in mode:
            raise OSError("simulated refresh read failure")
        return real_open(self, *args, **kwargs)

    with mock.patch.object(Path, "open", selective_open):
        # The append (mode "a") still succeeds; only the refresh read fails.
        store.record_failure("x", "R-NEW", "new rule", "e")

    assert rules_path.read_text(encoding="utf-8") == before
    assert store._rules == prior_map
    log = (tmp_path / "corrections/tcg/failures.jsonl").read_text(encoding="utf-8")
    assert "R-SEED" in log and "R-NEW" in log


def test_followup_load_rules_distinguishes_missing_log_from_read_failure(tmp_path):
    """No log file is an empty map; an unreadable log raises to the caller."""
    store = CorrectionStore(tmp_path)
    # Fresh store: no authoritative log -> legitimate empty map, no exception.
    assert not (tmp_path / "corrections/tcg/failures.jsonl").exists()
    assert store._load_rules() == {}

    log_path = tmp_path / "corrections/tcg/failures.jsonl"
    log_path.write_text(
        json.dumps({"rule_id": "R-READ", "rule_text": "rule", "severity": "warning"})
        + "\n",
        encoding="utf-8",
    )
    real_open = Path.open

    def selective_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if self.name == "failures.jsonl" and "r" in mode:
            raise OSError("log present but unreadable")
        return real_open(self, *args, **kwargs)

    with mock.patch.object(Path, "open", selective_open):
        with pytest.raises(OSError, match="log present but unreadable"):
            store._load_rules()
