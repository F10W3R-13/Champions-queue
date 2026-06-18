# Champion's Queue 봇 — Sparked Host 24/7 배포 가이드

초보자용. 위에서부터 순서대로 따라 하면 됩니다. 예상 소요: 20~30분.

올릴 파일 4개 (`CQ_Bot` 폴더 안): `main.py`, `matcher.py`, `ocr_prompt.py`, `requirements.txt`, 그리고 `.env`.

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
2. 다음 5개 파일을 **드래그해서 업로드**:
   - `main.py`
   - `matcher.py`
   - `ocr_prompt.py`
   - `requirements.txt`
   - `.env`  ← 이게 토큰·API 키가 든 파일입니다. 같이 올려야 봇이 키를 읽습니다.

> `.bak` 파일이나 `_smoke_test.py`, `__pycache__` 폴더는 **올리지 마세요.** 불필요합니다.

`.env` 안에 이 4줄이 들어있는지 확인:
```
DISCORD_TOKEN=...
AIRTABLE_API_KEY=...
AIRTABLE_BASE_ID=...
OPENAI_API_KEY=...
```

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

디스코드에서:
- `!ign 테스트IGN` → 정상 응답?
- `!stats` → DM 옴?
- `#results`에 스샷 2장(한 메시지) → ✅ 반응 + 요약?

다 되면 24/7 운영 완료입니다. 노트북을 꺼도 봇은 계속 돕니다.

---

## 8단계 — Make 끄기 (1~2번 세션 검증 후)

호스트 봇이 주말 실경기 1~2회를 문제없이 처리하는 걸 확인한 뒤:
- Make.com에서 `CQ - AI stats reade` 시나리오를 **OFF**로 두면 됩니다.
- (Match ID 중복 방지가 있어 잠깐 둘 다 켜져도 기록 중복은 안 생깁니다. 하지만 검증 끝나면 꺼서 단일 시스템으로.)

---

## 코드를 고쳤을 때 (나중에)

파일 관리자에서 바뀐 파일만 다시 업로드 → **Restart(재시작)**.

> 더 편하게 하려면 GitHub 저장소를 만들고 Apollo 패널의 **Git 자동 배포**를 연결하면, 깃에 push만 해도 자동 반영됩니다. (이땐 `.env`는 깃에 올리지 말고 패널 변수로 넣어야 합니다.) 지금 당장은 파일 업로드 방식으로 충분합니다.

---

## 막히면

콘솔에 빨간 에러가 뜨면 그 줄을 그대로 복사해서 물어보세요. 자주 나오는 것:
- `ModuleNotFoundError` → 4단계(`pip install`) 안 한 것.
- `Improper token` → `.env`의 `DISCORD_TOKEN`이 틀림.
- 봇은 켜졌는데 명령 무반응 → 디스코드 개발자 포털에서 **Message Content / Server Members 인텐트**가 꺼졌거나, 노트북 봇이 같이 켜져 있는 것.
