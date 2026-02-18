# NyanRSS
## 심신에 해로운 귀여운 냥냥피드 🐱📰

> [!WARNING]
> 이 봇은 매우 귀여운 고양이 말투로 뉴스를 요약합니다. 과다 시청 시 심신이 약해질 수 있으니 주의하세요.
> 냥냥거림에 대한 알레르기가 있으신 분은 사용을 자제해주세요.

### 🎯 주요 기능 / Main Features
- 📡 RSS 피드 자동 구독 및 모니터링
- 🐱 OpenRouter API를 통한 LLM 기반 요약
- 🎨 Discord Embed 형식의 메시지
- 🖼️ 기사 이미지 자동 첨부
- 🔒 URL 및 제목 유사도 기반 중복 기사 방지
- 🎨 사이트별 색상 커스터마이징

---

## 📋 필수 요구사항 / Prerequisites
1. Python 3.8 or above
2. Discord Bot Token
3. OpenRouter API Key
4. RSS Feed URL

---

## 🚀 설치 방법

#### 1. 저장소 클론
```bash
git clone https://github.com/YOUR_USERNAME/NyanRSS.git
cd NyanRSS
```

#### 2. Python 패키지 설치
```bash
pip install -r requirements.txt
```

#### 3. Discord 봇 설정
1. [Discord Developer Portal](https://discord.com/developers/applications)에서 새 애플리케이션 생성
2. Bot 메뉴에서 봇 생성 및 토큰 복사
3. **중요:** Privileged Gateway Intents 활성화 필수
   - ✅ `PRESENCE INTENT`
   - ✅ `SERVER MEMBERS INTENT`
   - ✅ `MESSAGE CONTENT INTENT`
4. OAuth2 → URL Generator에서 봇 권한 설정:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Attach Files`, `Read Message History`
5. 생성된 URL로 봇을 서버에 초대

#### 4. OpenRouter API Key 발급
1. [OpenRouter](https://openrouter.ai/) 가입
2. API Keys 메뉴에서 새 API 키 생성
3. 크레딧 충전

#### 5. 환경 변수 설정
프로젝트 루트에 `.env` 파일 생성:

```env
# Discord 설정
DISCORD_BOT_TOKEN=your_discord_bot_token_here
DISCORD_CHANNEL_IDS=123456789012345678,987654321098765432

# RSS 피드 설정 (쉼표로 구분)
RSS_FEED_URLS=https://example.com/rss,https://another-site.com/feed

# OpenRouter API 설정
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=google/gemini-2.5-flash  # example

# 사이트별 색상 설정 (선택사항)
# 형식: URL:HEX색상코드,URL:HEX색상코드
SITE_COLORS=https://example.com/rss:#FF6B6B,https://another-site.com/feed:#4ECDC4
```

**환경 변수 설명:**
- `DISCORD_BOT_TOKEN`: Discord 봇 토큰
- `DISCORD_CHANNEL_IDS`: 메시지를 보낼 채널 ID (쉼표로 구분, 여러 개 가능)
- `RSS_FEED_URLS`: 구독할 RSS 피드 URL (쉼표로 구분)
- `OPENROUTER_API_KEY`: OpenRouter API 키
- `OPENROUTER_MODEL`: 사용할 AI 모델 (ex: `google/gemini-2.5-flash`)
- `SITE_COLORS`: 사이트별 Embed 색상 (선택사항, HEX 코드 사용)

**Discord 채널 ID 찾는 방법:**
1. Discord 설정 → 고급 → 개발자 모드 활성화
2. 원하는 채널 우클릭 → ID 복사

---

## 🎮 실행 방법

```bash
python main.py
```

봇이 정상적으로 시작되면 다음과 같은 메시지가 표시됩니다:
```
봇 시작 중...
봇 로그인: YourBotName (ID: 123456789)
등록된 채널 ID: [123456789012345678]
등록된 RSS 피드 수: 2
봇이 준비되었습니다. 10초 후 첫 RSS 피드 확인을 시작합니다.
```

---

## 📝 기능 설명

### AI 냥냥 요약

### 중복 방지
- URL 정규화로 동일 기사 재전송 방지
- 제목 유사도 계산 (Jaccard 유사도 80% 이상 시 중복 판단)
- 최대 5,000개의 기사 기록 유지

### 이미지 처리
다음 순서로 이미지를 자동 탐색 및 첨부:
1. RSS enclosures
2. media:thumbnail
3. media:content

---

## 📊 파일 구조

```
NyanRSS/
├── main.py                # 메인 봇 코드
├── requirements.txt       # Python 의존성
├── .env                   # 환경 변수
└── sent_articles.yaml     # 전송된 기사 기록
```

---

## 🐛 문제 해결

#### 봇이 메시지를 보내지 않을 때
1. Discord Developer Portal에서 `MESSAGE CONTENT INTENT` 활성화 확인
2. 봇이 해당 채널에 접근 권한이 있는지 확인
3. 채널 ID가 올바른지 확인

#### API 오류가 발생할 때
1. OpenRouter API 키가 유효한지 확인
2. 크레딧 잔액 확인
3. 모델 이름이 올바른지 확인 ([OpenRouter Models](https://openrouter.ai/models))

#### RSS 피드가 파싱되지 않을 때
1. RSS URL이 유효한지 브라우저에서 확인
2. 봇 로그에서 상세 오류 메시지 확인
3. 방화벽이나 네트워크 문제 확인

---

## 🎉 완료!

설정이 제대로 완료되었다면, Discord 채널에 귀여운 고양이 말투로 뉴스 요약이 자동으로 올라옵니다!

냥냥! 🐱📰

---

## 📜 라이선스

이 프로젝트는 BSD 3-Clause License로, 저작자 고지 후 사용하실 수 있습니다.
더 자세한 사항은 LICENSE 파일을 참고해주세요.
다만 너무 귀여운 냥냥거림으로 인한 정신적 피해는 책임지지 않습니다. 😸

---

**Made with 💖 and 😺 by MiRoo**
