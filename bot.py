"""INDEX Bridge Bot — 디스코드 한↔영 텍스트 번역 봇 (양방향 MVP).

동작: 한국어를 치면 영어로, 영어를 치면 한국어로 답장. 방향은 글자로 자동 판별.
읽고 번역 답장만 한다. 삭제·DM·다른 행동 없음.

필요: Message Content Intent ON (개발자 포털 Bot 탭).
토큰은 환경변수 DISCORD_BOT_TOKEN으로만 읽는다 (파일에 적지 말 것).
"""
import os
import re

import discord
from deep_translator import GoogleTranslator

CHANNEL = os.environ.get("TRANSLATE_CHANNEL", "").strip()

_HANGUL = re.compile(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]")


def detect_direction(text):
    """한글 자모가 하나라도 있으면 ko→en, 없으면 en→ko. 빈 문자열은 None."""
    if not text or not text.strip():
        return None
    return "ko-en" if _HANGUL.search(text) else "en-ko"


def translate(text, direction):
    """Google 무료 백엔드 (API 키 불필요, 인터넷 필요)."""
    if direction == "ko-en":
        return GoogleTranslator(source="ko", target="en").translate(text)
    return GoogleTranslator(source="en", target="ko").translate(text)


# --- 다음 단계 훅 (P2 이후, 지금은 자리만) ---
def only_user(user_id):  # 특정 사용자만 번역
    raise NotImplementedError("P2")


def voice_bridge():  # 음성
    raise NotImplementedError("P2")


def ledger_store(item):  # INDEX 원장 적재
    raise NotImplementedError("P3")


class BridgeClient(discord.Client):
    async def on_ready(self):
        print(f"[INDEX Bridge] 로그인됨: {self.user} (이 창을 켜둔 동안만 동작)")

    async def on_message(self, message):
        if message.author.bot:  # 봇끼리 무한응답 방지
            return
        if CHANNEL and message.channel.name != CHANNEL:
            return
        direction = detect_direction(message.content)
        if direction is None:
            return
        try:
            out = translate(message.content, direction)
        except Exception as e:
            print(f"[번역 오류] {e}")
            return
        await message.reply(out, mention_author=False)


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN 환경변수가 비어 있습니다.")
    intents = discord.Intents.default()
    intents.message_content = True  # 개발자 포털에서도 Message Content Intent ON 필수
    BridgeClient(intents=intents).run(token)


if __name__ == "__main__":
    main()
