# Champion's Queue 봇 — Sparked Host 24/7 배포 가이드

초보자용. 위에서부터 순서대로 따라 하면 됩니다. 예상 소요: 20~30분.

올릴 파일/폴더 (`CQ_Bot` 폴더 안): `main.py`, `core.py`, `matcher.py`, `ocr_prompt.py`, `requirements.txt`, `cogs/` 폴더 전체(7개 .py), 그리고 `.env`.

> ⚠️ `core.py`와 `cogs/` 폴더는 **반드시** 올려야 합니다. `main.py`가 임포트하므로 빠지면 봇이 켜지지 않습니다.

---

## 1단계 — 계정 만들고 플랜 주문

1. https://sparkedhost.com/discord-bot-hosting 접속
2. **Discord Bot Hosting**에서 **Basic ($1/월)** 선택 → 주문/결제
3. 결제하면 이메일로 패널(Apollo Panel) 로그인 정보가 옵니다. 패널에 로그인.

> Basic은 봇 1개·약 1GB RAM. 이 봇엔 충분합니다.

---

## 2단계 — 서버(인스턴스) 기본 설정

패널에서 방금 만든 서버를 클릭한 뒤:

1. **Settings(설정)** 또는 **Startup** 탭으로 이동
2. **언어/이미지**를 **Python**으로 지정 (버전 선택이 있으면 **3.11** 권장)
3. **시작 파일(Startup file / Main file)** 칸에 `main.py` 입력
4. **requirements 자동 설치** 옵션이 있으면 **켜기** (또는 시작 명령이 `pip install -r requirements.txt && python main.py` 형태인지 확인)

저장.

---

## 3단계 — 파일 업로드

1. 서버 화면에서 **Files(파일 관리자)** 탭 클릭
2. 다음 파일/폴더를 **드래그해서 업로드**:
   - `main.py`
   - `core.py`  ← **필수** (main.py가 import)
   - `matcher.py`
   - `ocr_prompt.py`
   - `requirements.txt`
   - `cogs/` 폴더 전체 (7개 .py: ingest, mmr, registration, season, selfroles, stats, verify)  ← **필수**
   - `.env`  ← 이게 토큰·API 키가 든 파일입니다. 같이 올려야 봇이 키를 읽습니다.

> `.bak` 파일이나 `_smoke_test.py`, `__pycache__` 폴더, `bot.log`, `mmr_state.json`은 **올리지 마세요.** 불필요합니다.

> `cogs/` 폴더 업로드 시, 폴더째 끌어다 놓거나(패널이 지원하면), 폴더 안의 .py 7개를 `cogs/` 하위 폴더에 넣어야 합니다. 최상위 경로에 .py가 있으면 안 됩니다 — 반드시 `cogs/` 폴더 안에.

`.env` 안에 최소 이 변수들이 들어있는지 확인 (4개뿐이면 부팅 실패):
```
DISCORD_TOKEN=...
AIRTABLE_API_KEY=...
AIRTABLE_BASE_ID=...
OPENAI_API_KEY=...
RESULTS_CHANNEL_ID=...
STAFF_LOGS_CHANNEL_ID=...
REGISTERED_ROLE_ID=...
CURRENT_SEASON=S1
SEASON_START=2026-06-13
SEASON_END=2026-08-09
```
> 옵션(기본값 있음, 안 넣어도 부팅은 됨): `OCR_MODEL`, `LEADERBOARD_MIN_GAMES`, `PLACEMENT_GAMES`, `SEASON_CACHE_TTL`, `VERIFIED_ROLE_NAME`, `CHAMPS_ROLE_ID`, `CHAMPS_ROLE_NAME`, `NEATQUEUE_TOKEN`, `NEATQUEUE_QUEUE_CHANNEL_ID`, `WEEKLY_LEADERBOARD_CHANNEL_ID`, `MATCHER_RELOAD_TTL`.

---

## 4단계 — 라이브러리 설치 (필요 시)

2단계에서 자동 설치를 켰다면 5단계로. 안 켜졌거나 모르겠으면:

1. **Console(콘솔)** 탭으로 이동
2. 입력창에 아래를 치고 엔터:
   ```
   pip install -r requirements.txt
   ```
3. 설치가 끝날 때까지 기다립니다(여러 줄 출력 후 멈춤).

---

## 5단계 — 시작

1. 패널 상단의 **Start(시작)** 버튼 클릭
2. **Console**에 이런 줄이 뜨면 성공:
   ```
   Logged in as: ... 
   CQ Stats Bot online (registration + stats + OCR ingestion).
   ```

---

## 6단계 — ⚠️ 노트북 봇 끄기 (가장 중요)

호스트에서 봇이 켜졌으면, **노트북에서 돌리던 봇은 반드시 끄세요** (`Ctrl+C`).

> 같은 봇 토큰으로 두 곳에서 동시에 돌리면, 명령에 **두 번 답하고** 스코어보드를 **두 번 처리**합니다. 항상 **한 곳에서만** 켜져 있어야 합니다.

---

## 7단계 — 동작 확인

디스코드에서 (모두 **슬래시 커맨드** — `!` prefix 명령은 없습니다):
- `/ign ign_name: 테스트IGN` → 정상 응답? (슬래시 메뉴가 떠야 함)
- `/stats` → DM 옴?
- `#results`에 스샷 2장(한 메시지) → ✅ 반응 + 요약?

다 되면 24/7 운영 완료입니다. 노트북을 꺼도 봇은 계속 돕니다.

---

## 8단계 — Make 끄기 (✅ 2026-06-19 완료)

봇이 주말 실경기를 문제없이 처리하는 걸 확인했으므로 **Make.com은 완전 폐기**:
- Make.com 시나리오 4개(AI stats reade, Sending stats DM, IGN Register, Integration Airtable) **전부 비활성화**
- Make.com **결제 해지** (Free 플랜으로 다운그레이드, 시나리오는 보존)
- 이제 수집·등록·조회는 **봇이 단독 처리** (이중 호출로 인한 OpenAI 비용 2배 낭비도 해소)

> 봇의 `match_id_exists()` 중복 방지가 있어, 만약 Make를 다시 켜도 레코드 중복은 안 생깁니다. 하지만 단일 시스템이 더 깔끔합니다.

---

## 코드를 고쳤을 때 (✅ GitHub 자동배포 구축 완료)

**2026-06-19 GitHub 자동배포 연결 완료.** 이제 파일 업로드 방식은 필요 없습니다.

워크플로:
1. 로컬에서 코드/문서 수정
2. 랩탑 cmd에서:
   ```
   cd /d "C:\Users\0616y\Downloads\Champion's Queue"
   git add -A && git commit -m "변경 내용 요약" && git push
   ```
3. Apollo 패널에서 **Restart** → startup 명령어가 `git pull`을 자동 실행 → 새 코드 반영

> `.env`는 GitHub에 없으므로(gitignore), push해도 호스트의 `.env`는 그대로 유지됩니다.
> startup file은 `CQ_Bot/main.py` (Apollo Startup Settings에서 설정).

---

## 막히면

콘솔에 빨간 에러가 뜨면 그 줄을 그대로 복사해서 물어보세요. 자주 나오는 것:
- `ModuleNotFoundError` → 4단계(`pip install`) 안 한 것.
- `Improper token` → `.env`의 `DISCORD_TOKEN`이 틀림.
- 봇은 켜졌는데 명령 무반응 → 디스코드 개발자 포털에서 **Message Content / Server Members 인텐트**가 꺼졌거나, 노트북 봇이 같이 켜져 있는 것.
