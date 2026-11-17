import json
import urllib.parse

import pytest

import wr_report


SINCE = "2026-11-17T22:49:27+08:00"
SINCE_MS = 1794926967000


def match(mid, outcome, updated_at, agent="me", opponent="rival", reason="all_prizes_taken"):
    payload = {
        "matchId": mid,
        "status": "Settled",
        "players": [{"agentId": agent, "handle": "me"}, {"agentId": "opp", "handle": opponent}],
        "result": {"reason": reason, "winnerAgentId": agent if outcome == "win" else "opp"},
        "updatedAt": updated_at,
    }
    if outcome is not None:
        payload["agentResult"] = {"outcome": outcome}
    return payload


def test_parse_since_naive_is_asia_shanghai():
    assert wr_report.parse_since(SINCE) == SINCE_MS
    assert wr_report.parse_since("2026-11-17T22:49:27") == SINCE_MS
    assert wr_report.parse_since("2026-11-17T14:49:27Z") == SINCE_MS


def test_parse_since_rejects_garbage():
    with pytest.raises(wr_report.ReportError):
        wr_report.parse_since("not-a-date")


def test_wilson_interval_matches_known_values():
    low, high = wr_report.wilson_interval(13, 30)
    assert low == pytest.approx(0.2738, abs=1e-4)
    assert high == pytest.approx(0.6080, abs=1e-4)
    assert wr_report.wilson_interval(0, 0) is None


def test_binom_p_value_matches_known_values():
    z, p = wr_report.binom_p_value(13, 30, 208 / 979)
    assert z == pytest.approx(2.957, abs=1e-3)
    assert p == pytest.approx(0.0031, abs=1e-4)
    assert wr_report.binom_p_value(1, 0, 0.2) == (None, None)
    assert wr_report.binom_p_value(1, 10, 1.0) == (None, None)


def test_fetch_paginates_filters_and_stops_on_old_page():
    pages = {
        None: {
            "matches": [
                match("m3", "win", SINCE_MS + 3000),
                match("m2", "loss", SINCE_MS - 1000),
            ],
            "nextCursor": "c2",
            "profile": {"wins": 208, "matches": 979},
            "total": 5,
        },
        "c2": {
            "matches": [
                match("m1", "win", SINCE_MS - 2000),
                match("m0", "loss", SINCE_MS - 3000),
            ],
            "nextCursor": "c3",
        },
        "c3": {"matches": [match("ancient", "win", SINCE_MS - 99999)], "nextCursor": None},
    }
    calls = []

    def fake_fetcher(url, api_key):
        cursor = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("cursor", [None])[0]
        calls.append(cursor)
        return pages[cursor]

    fetched = wr_report.fetch_matches(
        "key", "comp", "me", SINCE_MS, limit=50, fetcher=fake_fetcher
    )

    assert calls == [None, "c2"]
    assert [m["matchId"] for m in fetched["matches"]] == ["m3"]
    assert fetched["pages"] == 2
    assert fetched["seen"] == 4
    assert fetched["stop"] == "page_older_than_since"
    assert fetched["profile"] == {"wins": 208, "matches": 979}
    assert fetched["total"] == 5


def test_fetch_clamps_limit_and_follows_cursor():
    urls = []

    def fake_fetcher(url, api_key):
        urls.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if "cursor" not in query:
            return {
                "matches": [match("m2", "win", SINCE_MS + 1)],
                "nextCursor": "next",
                "profile": {"wins": 10, "matches": 40},
            }
        return {"matches": [match("m1", "loss", SINCE_MS + 2)], "nextCursor": None}

    fetched = wr_report.fetch_matches(
        "key", "comp", "me", SINCE_MS, limit=999, fetcher=fake_fetcher
    )

    first = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)
    second = urllib.parse.parse_qs(urllib.parse.urlparse(urls[1]).query)
    assert first["limit"] == ["50"]
    assert second["cursor"] == ["next"]
    assert [m["matchId"] for m in fetched["matches"]] == ["m2", "m1"]
    assert fetched["stop"] == "no_cursor"


def test_summarize_counts_outcomes_and_skips_unsettled():
    matches = [
        match("w", "win", SINCE_MS + 1),
        match("l", "loss", SINCE_MS + 2),
        match("d", "draw", SINCE_MS + 3),
        match("t", "tie", SINCE_MS + 4),
        match("u", None, SINCE_MS + 5),
    ]

    summary = wr_report.summarize(matches, agent_id="me")

    assert summary["matches"] == 4
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["draws"] == 2
    assert summary["win_rate"] == 0.25
    assert summary["skipped_unsettled"] == 1
    assert summary["records"][0]["matchId"] == "w"
    assert summary["records"][0]["opponent"] == "rival"


def test_resolve_baseline_variants(tmp_path):
    profile = {"wins": 208, "matches": 979}

    default = wr_report.resolve_baseline(None, profile)
    assert default["p0"] == pytest.approx(208 / 979)
    assert default["source"] == "profile lifetime"

    inline = wr_report.resolve_baseline('{"wins": 5, "matches": 10}', profile)
    assert inline["p0"] == 0.5

    rate = wr_report.resolve_baseline('{"rate": 0.3}', profile)
    assert rate["p0"] == 0.3

    ratio = wr_report.resolve_baseline("13/30", profile)
    assert ratio["p0"] == pytest.approx(13 / 30)

    number = wr_report.resolve_baseline("0.2125", profile)
    assert number["p0"] == 0.2125

    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"wins": 1, "matches": 4}), encoding="utf-8")
    from_file = wr_report.resolve_baseline(str(path), profile)
    assert from_file["p0"] == 0.25
    assert from_file["source"].startswith("file:")

    with pytest.raises(wr_report.ReportError):
        wr_report.resolve_baseline("nonsense", profile)


def test_run_writes_json_with_mocked_fetcher(tmp_path, capsys):
    json_path = tmp_path / "evidence" / "wr-report.json"
    requests = []

    def fake_fetcher(url, api_key):
        requests.append(url)
        return {
            "matches": [
                match("m3", "win", SINCE_MS + 3000),
                match("m2", "loss", SINCE_MS + 2000),
                match("m1", "win", SINCE_MS + 1000),
            ],
            "nextCursor": None,
            "profile": {"wins": 208, "matches": 979},
            "total": 3,
        }

    report = wr_report.run(
        [
            "--since",
            SINCE,
            "--json",
            str(json_path),
            "--agent-id",
            "me",
            "--limit",
            "50",
        ],
        fetcher=fake_fetcher,
        now_ms=SINCE_MS + 10_000,
    )

    assert report["window"] == {
        "matches": 3,
        "wins": 2,
        "losses": 1,
        "draws": 0,
        "win_rate": pytest.approx(2 / 3),
        "skipped_unsettled": 0,
    }
    assert report["wilson_95_ci"] is not None
    assert report["baseline"]["p0"] == pytest.approx(208 / 979)
    assert len(requests) == 1
    assert "limit=50" in requests[0]

    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["window"]["wins"] == 2
    assert saved["fetch"]["pages"] == 1
    assert saved["matches"][0]["matchId"] == "m3"

    out = capsys.readouterr().out
    assert "Matches 3" in out
    assert "66.67%" in out
    assert str(json_path) in out


def test_run_relative_json_path_resolves_under_script_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(wr_report, "SCRIPT_DIR", tmp_path)

    def fake_fetcher(url, api_key):
        return {
            "matches": [match("m1", "win", SINCE_MS + 1)],
            "nextCursor": None,
            "profile": {"wins": 1, "matches": 2},
        }

    report = wr_report.run(
        ["--since", SINCE, "--json", "evidence/report.json", "--limit", "1"],
        fetcher=fake_fetcher,
        now_ms=SINCE_MS + 2,
    )
    assert (tmp_path / "evidence" / "report.json").is_file()
    assert report["fetch"]["pages"] == 1
