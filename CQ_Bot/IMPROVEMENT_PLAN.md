# CQ Stats Bot — 구조 분석 및 개선 계획

> 작성일: 2026-06-11
> 참고: STATUS.md는 서버 빌드 스크립트(setup/finish) 일지이며, 이 폴더의 봇(main.py)과는 별개. 이 문서가 봇 본체의 현황/계획 문서.

---

## 1. 현재 구조

```
#results 채널에 스크린샷 2장 업로드
        │
        ▼
main.py  on_message → handle_results_screenshots
        │
        ▼
ocr_prompt.py  →  OpenAI gpt-4.1 vision (roster 힌트 포함)
        │            모드(HP/SND)·맵·10인 스탯 JSON 추출
        ▼
matcher.py  3단계 매칭 (정규화 exact → Jaro-Winkler fuzzy → review/no_match)
        │            fuzzy 확정 시 Aliases에 자동 학습
        ▼
Airtable  Players / HP / SND / Aliases 4테이블에 기록
        +  45초 reconcile 루프(미연결 레코드 재매칭 안전망)

명령어: !ign(등록) / !changeign / !stats(DM)
파일: main.py(432줄, 전부 한 파일) · matcher.py · ocr_prompt.py · _smoke_test.py(오프라인 페이크 테스트)
배포: SparkedHost (DEPLOY_GUIDE 참고), .env로 비밀키 분리됨
```

**설계상 잘 된 점**: idempotent 중복 방지(Match ID), Airtable 쓰기 직렬화 lock, 자기학습 alias, OCR 프롬프트에 roster 힌트, 페이크 테이블 스모크 테스트.

---

## 2. 발견된 버그 (Phase 1에서 수정)

| # | 위치 | 문제 |
|---|---|---|
| B1 | `reconcile_once` | 필터가 `{Player}=''`뿐이라 **review/unmatched 레코드를 45초마다 같은 Status로 반복 update** → 불필요한 Airtable 쓰기 무한 반복. 필터에 Status 조건 추가하거나 변경 시에만 update해야 함 |
| B2 | `!ign` | **IGN 중복 검사 없음** — 두 유저가 같은 IGN 등록 가능. alias 캐시는 `setdefault`라 먼저 등록한 쪽만 매칭됨 |
| B3 | `Matcher` 캐시 | 봇 내부 등록/변경 시에만 reload. **Airtable에서 운영자가 직접 수동 연결/선수 추가하면 봇 재시작 전까지 반영 안 됨** → 주기적 reload 필요 |
| B4 | `ingest_match` | 선수 10명을 **건별 create(10회 API 호출)** → `batch_create`로 1회에 처리 가능 (rate limit 여유 확보) |
| B5 | review 상태 | "Needs Review"로 표시만 되고 **사람이 처리할 동선이 없음** (알림도, 해소 명령어도 없음) |

---

## 3. 개선 로드맵

### Phase 0 — 정리 (30분)
- [ ] `git init` + `.gitignore` (.env, __pycache__, *.bak)
- [ ] `main.py.bak`, `matcher.py.bak`, `__pycache__` 삭제
- [ ] STATUS.md를 서버일지/봇일지로 분리하거나 이 문서로 일원화

### Phase 1 — 버그 수정 (반나절)
- [ ] B1: reconcile 필터를 `AND({Player}='', {Status}='')` 형태로 바꾸고, Status 동일하면 skip
- [ ] B2: `!ign`에서 Primary IGN/Aliases 중복 검사 후 거부
- [ ] B3: reconcile 루프 시작 시(또는 N분마다) `matcher.reload()` 호출
- [ ] B4: `table.batch_create()`로 전환
- [ ] 수정 후 `_smoke_test.py` 통과 확인 + B1/B2 케이스를 테스트에 추가

### Phase 2 — 관측성 (반나절)
- [ ] `print` → `logging` 모듈 (파일 로그 + 레벨)
- [ ] OCR 실패·예외 발생 시 `#logs`(스태프 채널)로 알림 전송
- [ ] ingest 결과에 review 건이 있으면 스태프 채널에 해당 레코드 링크 멘션

### Phase 3 — Review 처리 워크플로 (1일)
- [ ] `!review` — Needs Review 목록 조회 (스태프 전용)
- [ ] `!link <record> <player>` — 수동 연결 + alias 학습 + 캐시 갱신
- [ ] `!unlink` / `!reject` — 오매칭 해제
- [ ] 처리 결과 즉시 matcher 캐시 반영

### Phase 4 — UX / 비용 (1~2일)
- [ ] prefix 명령(!) → 슬래시 커맨드(app_commands) 이전
- [ ] `!stats`를 embed로 개선, `!leaderboard` 추가 (NeatQueue 보드와 역할 분담 정의)
- [ ] OCR 모델 `gpt-4.1` vs `gpt-4.1-mini` 정확도/비용 비교 → 환경변수로 이미 전환 가능(`OCR_MODEL`)
- [ ] matcher 임계값(T_HIGH 0.92 / T_LOW 0.75 / MARGIN 0.08)을 실데이터 1~2주치로 보정 (matcher.py 주석의 원래 계획)

### Phase 5 — 구조 개선 (여유 있을 때)
- [ ] main.py를 cog 단위로 분리: `cogs/ingest.py`, `cogs/registration.py`, `cogs/stats.py`, `config.py`
- [ ] `_smoke_test.py` → pytest 기반으로 확장 (normalize/fuzzy 경계값 단위 테스트)
- [ ] 배포: 재시작 시 자동 복구 확인, requirements 버전 고정(lock)

---

## 신규 기능 로드맵 (2026-06-12 추가)

### Phase 6 — 리더보드 5게임 컷오프 ✅ 완료
- `core.py`에 `LEADERBOARD_MIN_GAMES`(기본 5, `.env`로 조정 가능) 추가
- `/leaderboard`에서 5게임 미만 선수 제외, footer에 기준 표기

### Phase 7 — Impact 기반 MMR 차등 ✅ 구현 완료 (2026-06-12, 드라이런 모드로 배포)
- **7-1 검증 결과**: 인증 = Authorization 헤더에 raw 토큰(Bearer 없음) / `POST /api/v2/add/stats` body `{channel_id, stat:"mmr", value, user_id}` / 승패·변동치는 `GET /api/v1/history/{server}` (mmr_change 부호로 승패 판별)
- `cogs/mmr.py`: 10분 주기로 history 폴링 → 신규 완료 매치마다 스샷 Impact(스노우플레이크 타임스탬프로 매치 윈도우 매칭) → `mod = clamp((본인−로비평균)/MMR_IMPACT_SCALE, ±MMR_MODIFIER_MAX)` → add/stats 적용 + 스태프 로그 감사
- 안전장치: `MMR_MODIFIER_DRYRUN=1`(기본) = 보고만, 처리상태는 `mmr_state.json` 영속화, 임팩트 데이터 6/10명 미만이면 스킵, `/applymodifiers`로 수동 실행
- 주의: NeatQueue 기본 변동이 ±25 고정이 아니라 가변(±31 관측) — variance 설정 확인 필요
**확정 설계**: NeatQueue가 승패 기본 ±25 처리(기존 설정 유지), 우리 봇이 Impact 보정 **±5**를 추가 적용 → 합계 ±20~30.

- [ ] **7-1. NeatQueue API 검증 (선행 필수)**: 서버 API 토큰 발급 → 플레이어 MMR 증감 endpoint 실호출 테스트. 실패 시 폴백: 봇이 `/managestats increment` 명령 목록을 스태프 채널에 자동 게시(반자동)
- [ ] **7-2. 승패/팀 정보 확보**: NeatQueue가 #results에 올리는 결과 메시지(embed)를 봇이 파싱 → 승리팀·Discord ID 목록 추출. (웹훅 수신은 SparkedHost에서 인바운드 포트가 필요해 차선책)
- [ ] **7-3. 매치 연동**: OCR ingest(스샷)와 NeatQueue 결과 메시지를 시간 근접성으로 연결. Bo3 시리즈면 맵별 Impact 평균 사용
- [ ] **7-4. 보정값 계산**: `modifier = clamp(round((본인 Impact − 로비 평균 Impact) / scale), −5, +5)` — scale은 첫 주 데이터로 보정
- [ ] **7-5. 적용 + 감사 로그**: NeatQueue API로 증감 적용, 스태프 채널에 적용 내역 자동 게시

### Phase 9 — 시즌 시스템 ✅ 구현 완료 (2026-06-12)
- ingest 시 `Season` 자동 태깅 (`.env`의 `CURRENT_SEASON`)
- `core.season_player_stats()` — 시즌 스코프 집계 엔진 (K/D는 킬/데스 합산, 나머지는 평균)
- `/leaderboard`에 `season` 옵션 추가 (기본=현재 시즌, `career` 입력 시 전체 커리어 rollup)
- `/season` — 시즌 정보 + 본인 배치 진행도 (`PLACEMENT_GAMES`, 기본 5)
- `/seasonreport` (스태프) — 모드별 Top 10 + 어워드 8종 + Grinder 결산 초안을 스태프 채널에 게시
- 신규 파일: `cogs/season.py` / 수정: `core.py`, `main.py`, `cogs/stats.py`
- ⚠️ 선행 조건: Airtable HP/SND 테이블에 `Season` 필드(Single line text) 추가 필수
- 보류: MMR 소프트 리셋 (Phase 7-1 NeatQueue API 검증에 종속), 비활동 decay는 NeatQueue 설정으로 처리

### Phase 10 — 고급 지표 + Airtable 이관 ✅ 구현 완료 (2026-06-12)
- DPD/DPK/Assist%/ZCS를 Airtable **수식 필드**로 생성 (Players: `HP DPD`, `HP DPK`, `HP Assist %`, `HP ZCS`, `SND Assist %`)
- 봇은 계산하지 않고 미리 계산된 값만 출력 (설계 원칙: Airtable에서 계산 가능하면 Airtable에서)
- `/stats` Advanced 섹션, `/leaderboard` 지표 4종 추가(DPK는 오름차순), 주간 Top10 자동 포스트(월 21:00 KST) + `/weeklyreport`
- Verified 역할 수령 시 미등록자 DM 안내 (`on_member_update`)
- 봇 측 시즌 집계 엔진은 과거 시즌 조회·시즌 결산 전용으로 유지
- 에이전트 컨텍스트 문서 `CLAUDE.md` 추가 (구조·스키마·운영 절차·함정 총정리)

### Phase 8 — 큐 2개 동시 운영 (NeatQueue, 코드 변경 불필요)
- [ ] `#queue-2` 채널 생성 (CHAMPIONS-QUEUE 카테고리, verified 전용)
- [ ] `#queue-2`에서 `/startqueue` — **큐 이름을 기존 큐와 동일하게** 설정해야 MMR/스탯 공유됨 (이름이 다르면 별도 풀로 분리되니 주의)
- [ ] 기존 큐 설정 복제: 기존 큐에서 `/config save` → 새 채널에서 `/config load`
- [ ] 🔊 Lobby 음성채널 추가 (`/lobbychannel set`), `/resultschannel #results` 동일 지정
- [ ] 리더보드는 큐 이름이 같으면 기존 `#leaderboard` 하나로 충분

---

## 4. 권장 착수 순서

**Phase 1의 B1이 최우선** — 지금도 45초마다 불필요한 Airtable 쓰기가 돌고 있을 수 있음(rate limit·요금·기록 오염 위험). 그다음 B2(데이터 무결성) → Phase 2(문제가 생겨도 보이게) → Phase 3(운영 동선) 순서가 효율적.
