# INDEX Bridge Bot

Discord voice + text bidirectional translation bot.

Korean speech in voice channel → ST → translated English voice & text.
English text in text channel → translated Korean text.

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
```

Write-Content -Path "C:\Projects\index-bridge-bot\README.md" -Value (Get-Content -Path "C:\Projects\index-bridge-bot\README.md" -Raw)