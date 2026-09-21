# -*- coding: utf-8 -*-
"""democlip 재발방지 시험.

여기서 지키려는 것 두 가지.
  · 자막 글자는 기록에 있는 그대로 나간다 — 다듬으면 그 영상은 증거가 아니다.
  · 잰 시각이 최종 영상에서도 그대로여야 한다. mp3 를 이어붙이면 이음매마다
    프레임이 반 토막 끼어 자막이 밀린다(6턴 0.28초 실측). 그 결함을 다시
    들이면 마지막 시험이 운다.

네트워크는 쓰지 않는다. edge-tts 대신 ffmpeg 로 길이를 아는 무음을 만든다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import democlip  # noqa: E402


def _turn(src, dst):
    return {"source": src, "translated": dst}


# ── 시각 표기 ───────────────────────────────────────────────────────────

def test_timestamp_has_millisecond_precision():
    assert democlip._ts(0) == "00:00:00,000"
    assert democlip._ts(1.5) == "00:00:01,500"
    assert democlip._ts(61.25) == "00:01:01,250"


def test_timestamp_rolls_over_into_hours():
    """초를 60으로 안 넘기면 한 시간짜리에서 자막이 통째로 어긋난다."""
    assert democlip._ts(3661.007) == "01:01:01,007"


# ── 자막 내용 ───────────────────────────────────────────────────────────

def test_subtitle_keeps_both_languages_verbatim():
    srt = democlip.build_srt([(0.0, 1.0, "오늘 회의는 세 시입니다.",
                               "Today's meeting is at three.")])
    assert "오늘 회의는 세 시입니다." in srt
    assert "Today's meeting is at three." in srt


def test_subtitle_does_not_tidy_up_awkward_output():
    """번역기가 이상하게 뱉었으면 이상한 채로 보여준다.

    보기 좋게 고치면 영상이 번역기가 한 일의 증거가 아니게 된다.
    """
    ugly = "- Hi, how are you? Today's meeting starts at 3:00."
    srt = democlip.build_srt([(0.0, 1.0, "안녕하세요.", ugly)])
    assert ugly in srt


def test_segments_are_numbered_from_one_in_order():
    srt = democlip.build_srt([(0.0, 1.0, "가", "a"), (1.4, 2.0, "나", "b")])
    lines = srt.splitlines()
    assert lines[0] == "1"
    assert "-->" in lines[1]
    assert "2" in lines


# ── 원천이 없으면 멈춘다 ────────────────────────────────────────────────

def test_no_translated_turns_raises_instead_of_emitting_a_file(tmp_path):
    """반쪽 mp4 를 남기면 사람이 그걸 진짜 산출물로 착각한다."""
    out = tmp_path / "demo.mp4"
    with pytest.raises(RuntimeError):
        democlip.render([], out)
    assert not out.exists()


def test_turns_without_translation_do_not_count_as_source(tmp_path):
    out = tmp_path / "demo.mp4"
    with pytest.raises(RuntimeError):
        democlip.render([_turn("안녕", ""), _turn("잘가", "   ")], out)
    assert not out.exists()


# ── 잰 시각이 영상에서도 그대로인가 ─────────────────────────────────────

_HAS_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe 없음")
def test_subtitle_timing_survives_the_concat(tmp_path, monkeypatch):
    """이음매가 자막을 밀지 않는지 **실제로 만들어서** 확인한다.

    한 turn 당 정확히 1초짜리 소리를 쓰므로 기대 길이는 산수로 나온다.
    mp3 이어붙이기로 되돌리면 이 시험이 운다(실측 0.28초 밀림).
    """
    ffmpeg = shutil.which("ffmpeg")

    def fake_speak(text, path, voice=democlip.VOICE):
        # 네트워크 대신, 길이를 아는 소리를 만든다.
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
             "-i", "anullsrc=r=24000:cl=mono", "-t", "1.0", str(path)],
            check=True)

    async def _fake(text, path, voice=democlip.VOICE):
        fake_speak(text, path, voice)

    monkeypatch.setattr(democlip, "_speak", _fake)

    turns = [_turn(f"문장 {i}", f"sentence {i}") for i in range(4)]
    out = democlip.render(turns, tmp_path / "demo.mp4")

    expected = 4 * 1.0 + 4 * democlip.GAP
    actual = democlip.audio_duration(shutil.which("ffprobe"), out)
    assert abs(actual - expected) < 0.05, (
        f"자막이 기대하는 끝 {expected:.3f}s 인데 영상은 {actual:.3f}s — "
        "이음매에서 밀렸다")


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe 없음")
def test_render_produces_a_playable_vertical_video(tmp_path, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")

    async def _fake(text, path, voice=democlip.VOICE):
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
             "-i", "anullsrc=r=24000:cl=mono", "-t", "1.0", str(path)],
            check=True)

    monkeypatch.setattr(democlip, "_speak", _fake)
    out = democlip.render([_turn("안녕하세요", "Hello")], tmp_path / "d.mp4")

    assert out.exists() and out.stat().st_size > 0
    probe = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True)
    assert probe.stdout.strip().startswith(f"{democlip.WIDTH},{democlip.HEIGHT}")


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe 없음")
def test_limit_caps_how_many_turns_are_rendered(tmp_path, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")
    spoken = []

    async def _fake(text, path, voice=democlip.VOICE):
        spoken.append(text)
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
             "-i", "anullsrc=r=24000:cl=mono", "-t", "0.5", str(path)],
            check=True)

    monkeypatch.setattr(democlip, "_speak", _fake)
    turns = [_turn(f"문장 {i}", f"sentence {i}") for i in range(10)]
    democlip.render(turns, tmp_path / "d.mp4", limit=3)
    assert len(spoken) == 3
