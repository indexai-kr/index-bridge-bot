# INDEX Bridge Bot

Discord voice + text bidirectional translation bot.

Korean speech in voice channel → ST → translated English voice & text.
English text in text channel → translated Korean text.

**[디스코드에 추가하기](https://indexai-kr.github.io/index-bridge-bot/)** — 설치도 가입도 없이 초대만 하면 씁니다.

**[데모 영상 보기](demo.mp4)** (23초, 1080×1920) — 실제 번역기로 만든 6턴 시연 (`demo_seed.py` + `democlip.py`, 대본 손글 없음).

**Stack:** Python 3.10+ · discord.py 2.7 · faster-whisper (small/CPU) · NLLB (local) · edge-tts · Gemini (fallback).

## Quick start

### 1. Install
```bash
pip install -r requirements.txt
```
Requires: ffmpeg on PATH, PyNaCl, edge-tts, faster-whisper.

### 2. Create a Discord bot
1. Go to https://discord.com/developers/applications → **New Application**.
2. **Bot** tab → **Reset Token** → copy it. (Treat it like a password.)
3. Enable **Message Content Intent**.
4. **OAuth2 URL Generator** → Scopes: `bot`, Permissions: `Send Messages`, `Read Message History`.
5. Invite the bot URL to a server.

### 3. Run
```bash
set DISCORD_BOT_TOKEN=<paste_token_here>
python bot_voice.py
```
- Override channel: `set TRANSLATE_CHANNEL=<channel_name>`
- Bot sees `[INDEX Bridge] 로그인됨...` → ready.

## Usage

- In text channel: speak Korean → bot replies Korean.
- In voice channel: speak Korean → bot replies Korean (TTS).
- **`!flip`** toggles voice/text language direction.
- **`!join`** explicitly joins the user's voice channel to start receiving.
- **`!leave`** leaves the voice channel.

## Known issues
- Bot not responding: check Message Content Intent, bot is in the channel, check console logs.
- Voice not receiving: `!join` command required to activate `VoiceRecvClient` listener.

## About
Free translation backend (deep-translator / NLLB), no API keys needed for core translation.
Edge-tts for free TTS (no API key).
Voice + text bidirectional MVP.

## Requirements
- Python 3.10+
- ffmpeg (for TTS playback)
- PyNaCl
- edge-tts
- faster-whisper (small model, CPU)
- PyTorch (CPU)
- discord-ext-voice-recv@03dd1e2dafe85522cc458441cd5b143b136ac836 (PR #58 DAVE patch)

## Growth / ops tooling

Optional, all off by default. Nothing here runs unless you configure it.

| File | What it does | Needs |
|---|---|---|
| `outreach.py` | Help/invite text, onboarding DM, usage counting | — |
| `botlists.py` | Posts server count to bot directories | `TOPGG_TOKEN` / `BOTSGG_TOKEN` |
| `democlip.py` | Renders saved translations into a subtitled clip | ffmpeg, edge-tts |
| `demo_seed.py` | Seeds a transcript using the real translator | NLLB model |
| `site_build.py` | Builds the invite page + sitemap/robots | Application ID |

### Environment

| Variable | Effect if unset |
|---|---|
| `BRIDGE_OWNER_ID` | Owner notifications off (falls back to app owner) |
| `TOPGG_TOKEN`, `BOTSGG_TOKEN` | That directory is skipped |
| `BRIDGE_STATE_FILE` | Usage counts go to the temp directory |
| `BRIDGE_TRANSCRIPT_FILE` | Transcript goes to the temp directory |

State and transcripts default to the temp directory on purpose — this
repository is public, and translated message bodies must not follow a
`git add .` into it.

### Building the invite page

```bash
python site_build.py --application-id <your app id> \
                     --base-url https://<user>.github.io/index-bridge-bot/
```

The Application ID is required; there is no default, because a wrong one
produces a page whose button invites somebody else's bot.

Sitemap submission is *not* automated: Google retired the ping endpoint in
2023 and it now returns 404. The live automatic path is the `Sitemap:` line
in `robots.txt`, which the builder writes. Search Console registration is a
one-time manual step.

### Tests

```bash
python -m pytest tests -q
```