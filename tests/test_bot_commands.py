# -*- coding: utf-8 -*-
"""명령 배선 시험 — 봇을 실제로 로그인시키지 않고 on_message 를 직접 돌린다.

문구는 test_outreach 가 본다. 여기서 보는 건 **라우팅**이다:
"!help 를 쳤을 때 정말 그 함수가 불리고 정말 답이 나가는가".
문구 시험만 있으면 함수가 아예 안 불려도 초록불이 난다.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 봇 모듈은 import 시점에 토큰·상태파일을 읽는다. 실제 값이 새지 않게 먼저 막는다.
os.environ.setdefault("DISCORD_BOT_TOKEN", "")
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ["BRIDGE_STATE_FILE"] = str(
    Path(__file__).resolve().parent / "_state_test.json")

import bot_voice  # noqa: E402
import outreach   # noqa: E402


# ── 가짜 디스코드 ───────────────────────────────────────────────────────

class FakeUser:
    def __init__(self, uid=1, bot=False):
        self.id = uid
        self.bot = bot
        self.voice = None
        self.dms = []

    async def send(self, text):
        self.dms.append(text)


class FakeChannel:
    def __init__(self, name="general"):
        self.name = name
        self.sent = []
        self.id = 999

    async def send(self, text):
        self.sent.append(text)


class FakeMessage:
    def __init__(self, content, author=None, channel=None):
        self.content = content
        self.author = author or FakeUser()
        self.channel = channel or FakeChannel()
        self.guild = None
        self.replies = []

    async def reply(self, text, mention_author=True):
        self.replies.append(text)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_state(tmp_path, monkeypatch):
    """시험마다 집계 파일을 새로 — 앞 시험의 숫자가 넘어오면 안 된다."""
    monkeypatch.setattr(bot_voice, "_USAGE",
                        outreach.Usage(tmp_path / "state.json"))
    yield


# ── !help ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("typed", ["!help", "!HELP", "!도움말"])
def test_help_actually_answers(typed):
    msg = FakeMessage(typed)
    run(bot_voice.on_message(msg))
    assert len(msg.channel.sent) == 1, f"{typed} 에 답이 없다"
    assert "!join" in msg.channel.sent[0]


def test_help_does_not_get_translated_instead():
    """명령이 번역 경로로 새면 '!help' 를 영어로 옮겨 답한다."""
    msg = FakeMessage("!help")
    run(bot_voice.on_message(msg))
    assert msg.replies == [], "명령이 번역 답장으로 샜다"


# ── !invite ─────────────────────────────────────────────────────────────

def test_invite_answers_with_a_real_link():
    # client.user 는 읽기 전용 속성이라 뒤의 _connection.user 를 놓는다
    bot_voice.client._connection.user = FakeUser(uid=123456789012345678)
    msg = FakeMessage("!invite")
    run(bot_voice.on_message(msg))
    assert len(msg.channel.sent) == 1
    assert "client_id=123456789012345678" in msg.channel.sent[0]


def test_invite_before_login_still_answers_instead_of_going_silent():
    """로그인 전이면 링크를 못 만든다. 그래도 사람에겐 뭐라도 답해야 한다.

    client.user.id 를 그냥 쓰면 AttributeError 가 나고 사용자는 아무 답도
    못 받는다(봇이 죽은 걸로 보인다).
    """
    bot_voice.client._connection.user = None
    msg = FakeMessage("!invite")
    run(bot_voice.on_message(msg))
    assert len(msg.channel.sent) == 1, "조용히 죽었다"
    assert "http" not in msg.channel.sent[0], "만들지도 못한 링크를 내보냈다"


# ── 봇 메시지 무시 ──────────────────────────────────────────────────────

def test_bot_messages_are_ignored():
    """봇끼리 !help 를 주고받으면 무한 루프가 된다."""
    msg = FakeMessage("!help", author=FakeUser(bot=True))
    run(bot_voice.on_message(msg))
    assert msg.channel.sent == []


# ── 집계 ────────────────────────────────────────────────────────────────

def test_first_translation_notifies_once(monkeypatch):
    sent = []

    async def fake_notify(text):
        sent.append(text)
        return True

    monkeypatch.setattr(bot_voice, "notify_owner", fake_notify)
    run(bot_voice.count_translation("텍스트"))
    run(bot_voice.count_translation("텍스트"))
    assert len(sent) == 1, "첫 번역 통지가 매번 나간다"
    assert bot_voice._USAGE.count_for() == 2


def test_counting_failure_does_not_take_the_bot_down(monkeypatch):
    """집계가 깨져도 번역은 계속돼야 한다. 부가 기능이 본업을 죽이면 안 된다."""
    class Broken:
        def record_translation(self):
            raise RuntimeError("디스크 꽉 참")

        def count_for(self, day=None):
            return 0

    monkeypatch.setattr(bot_voice, "_USAGE", Broken())
    run(bot_voice.count_translation("텍스트"))   # 예외가 새어나오면 실패


# ── 온보딩 ──────────────────────────────────────────────────────────────

def test_closed_dms_do_not_retry_forever(monkeypatch):
    """DM이 닫힌 사람에게 매번 다시 시도하면 !join 마다 실패 로그가 쌓인다."""
    class ClosedDM(FakeUser):
        async def send(self, text):
            raise RuntimeError("Cannot send messages to this user")

    u = ClosedDM(uid=55)
    assert bot_voice._USAGE.needs_onboarding(u.id) is True
    try:
        run(u.send("x"))
    except RuntimeError:
        pass
    bot_voice._USAGE.mark_onboarded(u.id)
    assert bot_voice._USAGE.needs_onboarding(u.id) is False
