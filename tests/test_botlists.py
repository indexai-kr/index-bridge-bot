# -*- coding: utf-8 -*-
"""botlists 재발방지 시험 — 네트워크에 나가지 않는다(가짜 session)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import botlists  # noqa: E402

TOKEN = "s3cr3t-token-do-not-log"


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    """올라간 요청을 그대로 붙잡아 둔다."""

    def __init__(self, status=200, body="ok", raise_exc=None):
        self.status, self.body, self.raise_exc = status, body, raise_exc
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.raise_exc:
            raise self.raise_exc
        return FakeResponse(self.status, self.body)


def run(coro):
    return asyncio.run(coro)


# ── 꺼짐 상태 ───────────────────────────────────────────────────────────

def test_no_token_means_off_not_crash():
    assert botlists.enabled_providers({}) == []
    assert run(botlists.post_stats(FakeSession(), 1, 5, env={})) == []


def test_off_state_explains_itself():
    """조용히 꺼지면 '왜 서버 수가 안 올라가지'를 아무도 못 푼다."""
    msg = botlists.describe_status({})
    assert "OFF" in msg
    assert "TOPGG_TOKEN" in msg, "어느 환경변수를 넣어야 하는지 안 알려준다"


def test_on_state_names_the_sites():
    msg = botlists.describe_status({"TOPGG_TOKEN": TOKEN})
    assert "ON" in msg and "top.gg" in msg


# ── 토큰이 새지 않는다 ──────────────────────────────────────────────────

def test_status_line_never_contains_the_token():
    for env in ({}, {"TOPGG_TOKEN": TOKEN}, {"BOTSGG_TOKEN": TOKEN}):
        assert TOKEN not in botlists.describe_status(env)


def test_network_error_message_does_not_leak_the_token():
    """예외 문자열에 토큰이 섞여 나오면 그게 로그에 박힌다."""
    sess = FakeSession(raise_exc=RuntimeError(f"connect failed key={TOKEN}"))
    out = run(botlists.post_stats(sess, 1, 5, env={"TOPGG_TOKEN": TOKEN}))
    assert TOKEN not in out[0]["body"]
    assert "<토큰>" in out[0]["body"]


# ── 실제로 올리는 모양 ──────────────────────────────────────────────────

def test_posts_the_measured_count_to_the_right_place():
    sess = FakeSession()
    run(botlists.post_stats(sess, 42, 7, env={"TOPGG_TOKEN": TOKEN}))
    call = sess.calls[0]
    assert "42" in call["url"], "봇 id가 주소에 안 들어갔다"
    assert call["json"] == {"server_count": 7}
    assert call["headers"]["Authorization"] == TOKEN


def test_each_site_gets_its_own_field_name():
    """사이트마다 키 이름이 다르다. 한 이름으로 밀면 한 곳은 0으로 받는다."""
    sess = FakeSession()
    run(botlists.post_stats(sess, 42, 7,
                            env={"TOPGG_TOKEN": TOKEN, "BOTSGG_TOKEN": TOKEN}))
    bodies = [c["json"] for c in sess.calls]
    assert {"server_count": 7} in bodies
    assert {"guildCount": 7} in bodies


def test_only_sites_with_tokens_are_contacted():
    sess = FakeSession()
    run(botlists.post_stats(sess, 42, 7, env={"TOPGG_TOKEN": TOKEN}))
    assert len(sess.calls) == 1


# ── 실패를 성공이라 하지 않는다 ────────────────────────────────────────

@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_non_2xx_is_a_failure(status):
    """사이트가 안 받았는데 '올렸다'로 적으면 서버 수가 영영 안 맞는다."""
    sess = FakeSession(status=status, body="nope")
    out = run(botlists.post_stats(sess, 42, 7, env={"TOPGG_TOKEN": TOKEN}))
    assert out[0]["ok"] is False
    assert out[0]["status"] == status
    assert "nope" in out[0]["body"], "응답 본문을 버리면 원인을 못 푼다"


def test_2xx_is_a_success():
    sess = FakeSession(status=204, body="")
    out = run(botlists.post_stats(sess, 42, 7, env={"TOPGG_TOKEN": TOKEN}))
    assert out[0]["ok"] is True


def test_one_site_failing_does_not_stop_the_other(monkeypatch):
    calls = []

    async def flaky(session, provider, bot_id, guild_count, token):
        calls.append(provider.key)
        return {"provider": provider.key, "ok": provider.key != "top.gg",
                "status": 500, "body": ""}

    monkeypatch.setattr(botlists, "post_one", flaky)
    out = run(botlists.post_stats(FakeSession(), 42, 7,
                                  env={"TOPGG_TOKEN": TOKEN,
                                       "BOTSGG_TOKEN": TOKEN}))
    assert len(out) == 2 and len(calls) == 2
