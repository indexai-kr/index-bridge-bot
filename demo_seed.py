# -*- coding: utf-8 -*-
"""데모용 기록 만들기 — **진짜 번역기**를 돌려서 남긴다.

지금 실사용자가 0명이라 보여줄 실제 대화가 없다. 그렇다고 영어 문장을
손으로 지어 넣으면 그 영상은 번역기가 한 일의 증거가 아니라 내가 쓴 글이
된다(CLAUDE.md #4). 그래서 한국어 문장만 여기 적고, 영어는 봇이 실제로
쓰는 그 번역기(nllb_local)에 물어서 받는다.

kind="데모" 로 남긴다 — 나중에 진짜 사용 기록과 섞였을 때 어느 쪽이
사람이 쓴 말이고 어느 쪽이 시연용인지 구별되어야 하기 때문이다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import outreach

# 실제 업무용 디스코드에서 나올 법한 말들. 영어는 여기 적지 않는다.
SENTENCES = [
    "안녕하세요, 오늘 회의는 세 시에 시작합니다.",
    "화면 공유가 안 되는데 잠깐만 기다려 주세요.",
    "이번 주까지 초안을 보내드리겠습니다.",
    "그 부분은 제가 다시 확인해 보고 말씀드릴게요.",
    "좋은 의견 감사합니다, 반영하겠습니다.",
    "다음 주 같은 시간에 다시 뵙겠습니다.",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description="진짜 번역기로 데모 기록 만들기")
    ap.add_argument("--out", type=Path, default=None,
                    help="기록 파일 (기본: 임시폴더)")
    args = ap.parse_args(argv)

    from nllb_local import translate_local

    path = args.out or outreach.transcript_path()
    ok = 0
    for ko in SENTENCES:
        en = translate_local(ko, "en")
        if not en.strip():
            print(f"[건너뜀] 번역이 비었습니다: {ko}")
            continue
        outreach.append_turn(ko, en, "ko", "en", "데모", path=path)
        ok += 1
        print(f"  {ko}\n  → {en}")
    print(f"\n{ok}건을 남겼습니다: {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
