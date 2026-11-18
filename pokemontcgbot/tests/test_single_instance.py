"""Regression guard: only one TCG bot poller may run per agent/competition."""

import pytest

import bot


def test_second_poller_is_refused(tmp_path):
    lock_path = tmp_path / "tcg.lock"
    first = bot.acquire_single_instance_lock(lock_path)
    try:
        with pytest.raises(SystemExit):
            bot.acquire_single_instance_lock(lock_path)
    finally:
        first.close()


def test_lock_is_reusable_after_release(tmp_path):
    lock_path = tmp_path / "tcg.lock"
    first = bot.acquire_single_instance_lock(lock_path)
    first.close()
    second = bot.acquire_single_instance_lock(lock_path)
    second.close()
