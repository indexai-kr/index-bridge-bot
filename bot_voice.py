# -*- coding: utf-8 -*-
"""
INDEX Bridge Bot (Voice) — 디스코드 이중언어 봇
타이핑 한 줄을 두 갈래로 내보낸다:
  · 텍스트 채널 : TEXT_LANG 로 번역해 답장
  · 음성 채널   : VOICE_LANG 로 번역해 TTS(소리)로 읽어줌
                 (글쓴 사람이 들어가 있는 음성채널로 봇이 들어가 재생)
기본: 음성=한국어(ko) / 텍스트=영어(en).   채팅창에 !flip 치면 서로 뒤집힘.
필요: PyNaCl(음성) · ffmpeg(시스템) · edge-tts(무료 TTS) · deep-translator.
동작은 읽기·번역 답장·음성 재생만. 삭제·다른 행동 없음.
"""
import os
import uuid
import asyncio
import tempfile

import discord
import edge_tts
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()  # .env 파일이 있으면 환경변수로 읽음 (없으면 무시)

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "").strip())
_gem = genai.GenerativeModel(
    os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip()
    or "gemini-3.6-flash")   # 2026-09 실측 동작 확인 모델. 바뀌면 GEMINI_MODEL로 지정
_LANG = {"ko": "Korean", "en": "English", "ja": "Japanese", "zh-CN": "Chinese"}

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
VOICE_LANG = os.environ.get("VOICE_LANG", "ko").strip().lower()   # 음성으로 나갈 언어
TEXT_LANG = os.environ.get("TEXT_LANG", "en").strip().lower()     # 채팅으로 나갈 언어
CHANNEL_NAME = os.environ.get("TRANSLATE_CHANNEL", "").strip()    # 비우면 모든 텍스트채널

# 언어코드 → edge-tts 목소리
VOICES = {
    "ko": "ko-KR-SunHiNeural",
    "en": "en-US-AriaNeural",
    "ja": "ja-JP-NanamiNeural",
    "zh-CN": "zh-CN-XiaoxiaoNeural",
}

intents = discord.Intents.default()
intents.message_content = True   # 개발자 포털에서 Message Content Intent 켜야 함
intents.voice_states = True

client = discord.Client(intents=intents)
_play_lock = asyncio.Lock()      # 음성 재생 겹침 방지


def translate(text: str, target: str) -> str:
    try:
        lang = _LANG.get(target, target)
        r = _gem.generate_content(
            f"Translate into {lang}. Output ONLY the translation:\n\n{text}")
        return (r.text or "").strip()
    except Exception as e:
        print("[Bridge] 번역 오류:", e)
        return ""


async def tts_to_file(text: str, lang: str) -> str:
    voice = VOICES.get(lang, VOICES["en"])
    path = os.path.join(tempfile.gettempdir(), f"bridge_tts_{uuid.uuid4().hex}.mp3")
    await edge_tts.Communicate(text, voice).save(path)
    return path


async def speak_in_channel(voice_channel, text: str, lang: str):
    """글쓴 사람이 있는 음성채널에 봇이 들어가 TTS 재생."""
    async with _play_lock:
        vc = discord.utils.get(client.voice_clients, guild=voice_channel.guild)
        try:
            if vc and vc.is_connected():
                if vc.channel.id != voice_channel.id:
                    await vc.move_to(voice_channel)
            else:
                vc = await voice_channel.connect()
        except Exception as e:
            print("[Bridge] 음성채널 연결 오류:", e)
            return
        mp3 = None
        try:
            mp3 = await tts_to_file(text, lang)
            done = asyncio.Event()

            def _after(err):
                if err:
                    print("[Bridge] 재생 오류:", err)
                client.loop.call_soon_threadsafe(done.set)

            vc.play(discord.FFmpegPCMAudio(mp3), after=_after)
            await done.wait()
        except Exception as e:
            print("[Bridge] TTS/재생 오류:", e)
        finally:
            if mp3:
                try:
                    os.remove(mp3)
                except Exception:
                    pass


@client.event
async def on_ready():
    print(f"[INDEX Bridge · Voice] 로그인됨: {client.user}")
    print(f"  음성={VOICE_LANG} / 텍스트={TEXT_LANG}   (채팅에 !flip 치면 뒤집힘, !leave 로 음성 나감)")


@client.event
async def on_message(message: discord.Message):
    global VOICE_LANG, TEXT_LANG
    if message.author.bot:
        return
    content = (message.content or "").strip()
    if not content:
        return

    low = content.lower()
    if low == "!flip":
        VOICE_LANG, TEXT_LANG = TEXT_LANG, VOICE_LANG
        await message.channel.send(f"🔁 이제  음성={VOICE_LANG} / 텍스트={TEXT_LANG}")
        return
    if low == "!leave":
        vc = discord.utils.get(client.voice_clients, guild=message.guild)
        if vc:
            await vc.disconnect()
        return
    if low.startswith("!"):
        return  # 그 외 명령은 무시

    if CHANNEL_NAME and getattr(message.channel, "name", "") != CHANNEL_NAME:
        return

    loop = asyncio.get_running_loop()

    # 1) 텍스트 채널 → TEXT_LANG
    text_out = await loop.run_in_executor(None, translate, content, TEXT_LANG)
    if text_out.strip() and text_out.strip().lower() != content.lower():
        await message.reply(f"[{TEXT_LANG}] {text_out}", mention_author=False)

    # 2) 음성 채널 → VOICE_LANG (글쓴 사람이 음성채널에 있을 때만)
    author_voice = getattr(message.author, "voice", None)
    if author_voice and author_voice.channel:
        voice_out = await loop.run_in_executor(None, translate, content, VOICE_LANG)
        if voice_out.strip():
            await speak_in_channel(author_voice.channel, voice_out, VOICE_LANG)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("환경변수 DISCORD_BOT_TOKEN 에 봇 토큰을 넣고 실행하세요.")
    client.run(TOKEN)
