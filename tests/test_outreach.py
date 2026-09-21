# -*- coding: utf-8 -*-
"""outreach 재발방지 시험 — 봇을 띄우지 않고 돈다(discord import 없음)."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import outreach  # noqa: E402


# ── 초대링크 ────────────────────────────────────────────────────────────

def test_invite_url_refuses_to_invent_an_application_id():
    """id가 없으면 링크를 만들지 않는다. 빈 링크를 주면 사람이 그대로 복사한다."""
    for bad in (None, "", "   ", "abc", "12a3"):
        with pytest.raises(ValueError):
            outreach.invite_url(bad)


def test_invite_url_carries_the_id_it_was_given():
    url = outreach.invite_url("123456789012345678")
    assert "client_id=123456789012345678" in url
    assert url.startswith("https://discord.com/oauth2/authorize?")
    assert "scope=bot" in url


def test_invite_asks_only_for_what_the_bot_actually_does():
    """권한을 넉넉히 받아두면 관리자가 초대창에서 거절한다.

    이 봇이 하는 일: 채널 보기·답장·원문 읽기·음성방 접속·말하기. 그게 전부다.
    Administrator(1<<3)나 메시지 삭제(1<<13)가 들어오면 운다.
    """
    assert outreach.INVITE_PERMISSIONS == 3214336
    assert not outreach.INVITE_PERMISSIONS & (1 << 3), "Administrator 요구 금지"
    assert not outreach.INVITE_PERMISSIONS & (1 << 13), "메시지 관리 요구 금지"
    assert not outreach.INVITE_PERMISSIONS & (1 << 1), "멤버 차단 요구 금지"


# ── 사람에게 보이는 글 (CLAUDE.md #12 내부용어 금지) ────────────────────

_INTERNAL_WORDS = ["STT", "TTS", "NLLB", "파이프라인", "폴백", "폴링",
                   "Whisper", "sink", "Q1", "Q2", "Q3", "intent"]


@pytest.mark.parametrize("fn", [outreach.help_text,
                                outreach.intro_text,
                                outreach.onboarding_text])
def test_user_facing_text_has_no_internal_words(fn):
    text = fn()
    for word in _INTERNAL_WORDS:
        assert word.lower() not in text.lower(), f"내부용어 노출: {word}"


@pytest.mark.parametrize("fn", [outreach.help_text,
                                outreach.intro_text,
                                outreach.onboarding_text])
def test_user_facing_text_is_not_empty(fn):
    assert fn().strip(), "빈 안내문은 안내가 아니다"


def test_help_lists_every_command_the_bot_answers():
    """명령을 추가하고 안내문에 안 적으면 아무도 모른다."""
    text = outreach.help_text()
    for cmd in ("!join", "!leave", "!flip", "!invite", "!help"):
        assert cmd in text, f"안내문에 {cmd} 누락"


# ── 집계 ────────────────────────────────────────────────────────────────

def test_counts_only_what_it_actually_counted(tmp_path):
    u = outreach.Usage(tmp_path / "s.json")
    assert u.count_for("2026-09-22") == 0
    u.record_translation("2026-09-22")
    u.record_translation("2026-09-22")
    assert u.count_for("2026-09-22") == 2
    assert u.count_for("2026-09-23") == 0, "다른 날로 새면 안 된다"


def test_first_translation_is_reported_once(tmp_path):
    u = outreach.Usage(tmp_path / "s.json")
    assert u.record_translation("2026-09-22") is True
    assert u.record_translation("2026-09-22") is False
    assert u.record_translation("2026-09-23") is False, "날이 바뀌어도 첫 번역은 한 번"


def test_counts_survive_a_restart(tmp_path):
    p = tmp_path / "s.json"
    outreach.Usage(p).record_translation("2026-09-22")
    assert outreach.Usage(p).count_for("2026-09-22") == 1, "재시작하면 0으로 돌아감"


def test_onboarding_happens_once_per_person(tmp_path):
    u = outreach.Usage(tmp_path / "s.json")
    assert u.needs_onboarding(42) is True
    u.mark_onboarded(42)
    assert u.needs_onboarding(42) is False
    assert u.needs_onboarding(43) is True
    assert outreach.Usage(tmp_path / "s.json").needs_onboarding(42) is False


def test_a_broken_state_file_is_not_silently_overwritten(tmp_path):
    """깨진 파일을 비우고 새로 쓰면 어제 숫자가 소리 없이 사라진다."""
    p = tmp_path / "s.json"
    p.write_text("{ 이건 json이 아님", encoding="utf-8")
    u = outreach.Usage(p)
    u.record_translation("2026-09-22")      # 세는 건 계속 되어야 한다
    assert p.read_text(encoding="utf-8").startswith("{ 이건"), "원본을 덮어썼다"


def test_state_file_stays_valid_json(tmp_path):
    p = tmp_path / "s.json"
    u = outreach.Usage(p)
    u.record_translation("2026-09-22")
    u.mark_onboarded(7)
    json.loads(p.read_text(encoding="utf-8"))   # 깨지면 예외


# ── 날짜 경계 ───────────────────────────────────────────────────────────

def test_the_day_turns_at_korean_midnight_not_utc():
    """UTC로 끊으면 한국 저녁 9시에 날이 바뀐다."""
    utc = dt.timezone.utc
    assert outreach.today_kst(dt.datetime(2026, 9, 22, 14, 59, tzinfo=utc)) == "2026-09-22"
    assert outreach.today_kst(dt.datetime(2026, 9, 22, 15, 1, tzinfo=utc)) == "2026-09-23"


# ── 일일 보고 ───────────────────────────────────────────────────────────

def test_zero_is_reported_as_zero_not_as_silence():
    """아무도 안 쓴 날을 보고 안 하면 '봇이 죽었나'를 구분할 수 없다."""
    text = outreach.daily_report_text("2026-09-22", 0, 3)
    assert "0건" in text
    assert "2026-09-22" in text
    assert "3" in text


def test_daily_report_states_the_measured_count():
    text = outreach.daily_report_text("2026-09-22", 17, 2)
    assert "17건" in text
    for vague in ("약 ", "대략", "추정"):
        assert vague not in text, "집계는 센 것만 말한다"
