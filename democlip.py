# -*- coding: utf-8 -*-
"""번역 기록 → 자막 영상 (MSG-P4).

전제 정정: 지시에는 "index-video-renderer가 이미 있으니 어댑터 하나면 된다"고
돼 있었으나, 그 이름의 저장소는 없다. indexai-kr/video-agent 는 트리에
.gitignore·README.md 둘뿐인 기획 문서다(2026-09-22 실측). 그래서 어댑터가
아니라 **작은 렌더러**를 여기 직접 둔다 — 이미 깔려 있는 ffmpeg·edge-tts만 쓴다.

만드는 법:
  1. 기록(JSONL)에서 번역 turn 을 읽는다
  2. 각 turn 의 영어 문장을 edge-tts 로 읽혀 mp3 를 만든다
  3. **mp3 의 실제 길이를 재서** 자막 타이밍을 잡는다 (추정하지 않는다)
  4. 배경 + 자막 + 이어붙인 소리 → mp4

정직 규칙: 자막은 기록에 있는 문장 그대로 쓴다. 보기 좋게 다듬거나
줄이지 않는다 — 그러면 그 영상은 이 봇이 한 일의 증거가 아니게 된다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    # cp949 콘솔에서 한글·기호가 터지면 성공한 작업이 실패로 보인다.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import outreach

WIDTH, HEIGHT = 1080, 1920          # 쇼츠 비율
GAP = 0.4                           # turn 사이 숨 쉬는 틈(초)
VOICE = "en-US-AriaNeural"
SAMPLE_RATE = 24000                 # 이어붙일 조각은 전부 같은 규격이어야 한다


# ── 도구 확인 ───────────────────────────────────────────────────────────

def require_ffmpeg() -> tuple[str, str]:
    """ffmpeg/ffprobe 가 없으면 **여기서 멈춘다**. 반쪽 파일을 남기지 않는다."""
    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    missing = [n for n, v in (("ffmpeg", ff), ("ffprobe", fp)) if not v]
    if missing:
        raise RuntimeError(
            f"{', '.join(missing)} 를 찾지 못했습니다. 설치하고 PATH에 넣어주세요.")
    return ff, fp


def audio_duration(ffprobe: str, path: Path) -> float:
    """소리 파일의 실제 길이(초). 글자 수로 추정하면 자막이 밀린다."""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


# ── 자막 ────────────────────────────────────────────────────────────────

def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(segments) -> str:
    """segments: [(start, end, 원문, 번역문)] → SRT 문자열."""
    out = []
    for i, (start, end, src, dst) in enumerate(segments, 1):
        out.append(str(i))
        out.append(f"{_ts(start)} --> {_ts(end)}")
        out.append(src)
        out.append(dst)
        out.append("")
    return "\n".join(out)


# ── TTS ─────────────────────────────────────────────────────────────────

async def _speak(text: str, path: Path, voice: str = VOICE) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice).save(str(path))


# ── 렌더 ────────────────────────────────────────────────────────────────

def render(turns, out_path: Path, limit: int = 6, voice: str = VOICE) -> Path:
    """turns → mp4. 실제로 만들어진 파일 경로를 돌려준다."""
    ffmpeg, ffprobe = require_ffmpeg()
    turns = [t for t in turns if (t.get("translated") or "").strip()][:limit]
    if not turns:
        raise RuntimeError(
            "기록에 번역된 문장이 없습니다. 영상을 만들 원천이 없어 멈춥니다. "
            "(봇을 띄워 몇 마디 번역시키면 기록이 쌓입니다)")

    work = Path(tempfile.mkdtemp(prefix="democlip_"))
    try:
        segments, parts, t = [], [], 0.0
        for i, turn in enumerate(turns):
            src = str(turn.get("source") or "").strip()
            dst = str(turn.get("translated") or "").strip()
            mp3 = work / f"{i:03d}.mp3"
            asyncio.run(_speak(dst, mp3, voice))
            # mp3 를 그대로 이어붙이면 이음매마다 프레임 반 토막이 끼어
            # 자막이 뒤로 밀린다(6턴에 0.28초 실측, 턴이 늘면 더 벌어진다).
            # wav(PCM)로 바꿔 놓고 재면 잰 값이 그대로 최종 위치가 된다.
            wav = work / f"{i:03d}.wav"
            subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-i", str(mp3),
                 "-ar", str(SAMPLE_RATE), "-ac", "1", str(wav)], check=True)
            dur = audio_duration(ffprobe, wav)       # 재서 쓴다
            segments.append((t, t + dur, src, dst))
            parts.append(wav)
            t += dur + GAP

        srt = work / "sub.srt"
        srt.write_text(build_srt(segments), encoding="utf-8")

        # 소리 이어붙이기 (사이에 무음 GAP). 전부 같은 규격의 wav 라서
        # -c copy 가 샘플 단위로 정확하다 — 위에서 잰 시각이 안 틀어진다.
        concat = work / "list.txt"
        silence = work / "gap.wav"
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
             "-i", f"anullsrc=r={SAMPLE_RATE}:cl=mono", "-t", str(GAP),
             str(silence)], check=True)
        lines = []
        for part in parts:
            lines.append(f"file '{part.as_posix()}'")
            lines.append(f"file '{silence.as_posix()}'")
        concat.write_text("\n".join(lines), encoding="utf-8")
        audio = work / "audio.wav"
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat), "-c", "copy", str(audio)], check=True)

        total = audio_duration(ffprobe, audio)

        # 자막을 태워 넣는다. 윈도우 경로는 subtitles 필터에서 이스케이프가 필요하다.
        sub_arg = srt.as_posix().replace(":", r"\:")
        style = ("FontName=Malgun Gothic,FontSize=15,PrimaryColour=&H00FFFFFF,"
                 "OutlineColour=&H00202020,BorderStyle=1,Outline=2,Shadow=0,"
                 "Alignment=2,MarginV=90")
        vf = f"subtitles='{sub_arg}':force_style='{style}'"

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [ffmpeg, "-y", "-v", "error",
             "-f", "lavfi", "-i",
             f"color=c=0x101418:s={WIDTH}x{HEIGHT}:d={total:.3f}:r=30",
             "-i", str(audio), "-vf", vf,
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
             "-c:a", "aac", "-b:a", "128k", "-shortest", str(out_path)],
            check=True)
        return out_path
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="번역 기록으로 데모 영상 만들기")
    ap.add_argument("--transcript", type=Path, default=None,
                    help="기록 파일 (기본: 임시폴더의 index_bridge_transcript.jsonl)")
    ap.add_argument("--out", type=Path, default=Path("demo.mp4"))
    ap.add_argument("--limit", type=int, default=6)
    args = ap.parse_args(argv)

    turns = outreach.read_turns(args.transcript)
    print(f"기록 {len(turns)}건을 읽었습니다.")
    path = render(turns, args.out, args.limit)
    size = path.stat().st_size
    print(f"만들었습니다: {path}  ({size:,} 바이트)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
