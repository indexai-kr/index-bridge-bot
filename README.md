# INDEX Bridge Bot — 디스코드 한↔영 번역 봇 (텍스트, 양방향)
한국어를 치면 영어로, 영어를 치면 한국어로 봇이 바로 답한다. 방향은 자동(글자 보고 판별).
읽고 번역 답장만 한다 — 삭제·DM·다른 행동 없음.

## 1. 준비 (한 번만)
1. Python 3.10 이상 설치 — 설치 첫 화면 **"Add Python to PATH" 체크**.
2. 이 폴더에서 명령창 열고: `pip install -r requirements.txt`

## 2. 디스코드 봇 만들기 (한 번만, ~10분)
1. https://discord.com/developers/applications → **New Application** (이름 아무거나).
2. 왼쪽 **Bot** 탭 → **Reset Token** → 토큰 복사. (비밀번호처럼 취급 — 남한테 안 보이게.)
3. 같은 Bot 탭에서 **Message Content Intent 를 켠다.** ★필수 — 이거 안 켜면 번역 안 됨.
4. 왼쪽 **OAuth2 → URL Generator** → Scopes에서 `bot` 체크 → Bot Permissions에서 `Send Messages`, `Read Message History` 체크 → 맨 아래 생성된 URL 복사 → 브라우저에 붙여 **내 디스코드 서버에 봇 초대**.
   - 개인 DM에는 봇을 못 넣는다. 내 서버에 채널 하나 만들어 둘이 들어가서 쓴다.

## 3. 실행
Windows 명령창(그 폴더에서):
```
set DISCORD_BOT_TOKEN=붙여넣은_토큰
python bot.py
```
- 특정 채널에서만 돌리려면 먼저: `set TRANSLATE_CHANNEL=채널이름`
- `[INDEX Bridge] 로그인됨...` 이 뜨면 성공. **그 창을 켜둔 동안만** 봇이 돈다.

## 4. 쓰기
그 서버 채널에서 한국어를 치면 밑에 영어로, 영어를 치면 한국어로 봇이 답한다.

## 5. 막히면
- 봇이 답을 안 함 → ① Message Content Intent 켰는지 ② 봇이 그 채널에 있는지 ③ 실행한 창에 오류 떴는지.
- 토큰 오류 → Bot 탭에서 Reset Token으로 새로 복사.

## 참고
- 번역은 무료 구글 번역 백엔드(deep-translator), API 키 불필요, 인터넷 필요.
- 이 버전은 텍스트·양방향 MVP. 다음 단계(특정 사용자만 번역, 음성, INDEX 원장 적재)는 훅만 두고 아직 없음.

## 음성판 (bot_voice.py)
- 타이핑 한 줄을 두 갈래로: 텍스트 채널에는 `TEXT_LANG`(기본 en) 번역 답장, 글쓴 사람이 들어있는 음성채널에는 `VOICE_LANG`(기본 ko) TTS 재생.
- `!flip` 치면 음성/텍스트 언어 뒤집힘. `!leave` 치면 봇이 음성채널에서 나감.
- 실행: `set DISCORD_BOT_TOKEN=토큰` → `python bot_voice.py` (환경변수로 `VOICE_LANG`, `TEXT_LANG` 변경 가능).
- 추가 필요: `pip install -r requirements.txt` (PyNaCl·edge-tts 포함), ffmpeg 시스템 설치, 개발자 포털에서 voice_states는 기본값이라 별도 Intent 불필요.
- TTS는 edge-tts 무료 엔드포인트 (API 키 불필요, 인터넷 필요).
