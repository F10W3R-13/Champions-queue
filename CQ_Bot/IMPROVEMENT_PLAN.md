# CQ Stats Bot — 구조 분석 및 개선 계획

> 작성일: 2026-06-11 · 최종 갱신: 2026-06-25
> 이 문서는 roadmap 전용. 현재 시스템의 진실 원천은 **CLAUDE.md**.
> 참고: STATUS.md는 삭제됨 (orphan — 존재하지 않는 setup script 참조).

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

명령어: /ign(등록) / /changeign / /stats(DM) — 모두 슬래시 커맨드
파일: main.py + core.py + matcher.py + ocr_prompt.py + cogs/ (7개 cog) + _smoke_test.py(오프라인 페이크 테스트)
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
- [x] `git init` + `.gitignore` (.env, __pycache__, *.bak) — 2026-06-18 완료 (GitHub private repo `F10W3R-13/Champions-queue` push까지)
- [x] `main.py.bak`, `matcher.py.bak`, `__pycache__` 삭제
- [x] STATUS.md 삭제 (orphan — 존재하지 않는 setup script 참조). CLAUDE.md로 일원화.

### Phase 1 — 버그 수정 (반나절)
- [x] B1: reconcile 필터를 `AND({Player}='', {Status}='')` 형태로 바꾸고, Status 동일하면 skip
- [x] B2: `/ign`에서 Primary IGN/Aliases 중복 검사 후 거부
- [x] B3: reconcile 루프에서 `matcher.reload()` 호출 — **TTL 게이트 적용** (45s 루프는 유지하되 reload는 5분 주기로, `core.reload_matcher_if_stale()` 경유). bot-driven 변형(`/ign`·`/changeign`·`/link`·OCR auto-learn)은 기존대로 즉시 갱신.
- [x] B4: `table.batch_create()`로 전환
- [x] 수정 후 `_smoke_test.py` 통과 확인 + B1/B2 케이스를 테스트에 추가

### Phase 2 — 관측성 (반나절)
- [x] `print` → `logging` 모듈 (파일 로그 + 레벨) — main.py에 logging.basicConfig 적용
- [x] OCR 실패·예외 발생 시 `#logs`(스태프 채널)로 알림 전송 — `core.send_staff_log` + ingest 예외 핸들러
- [x] ingest 결과에 review 건이 있으면 스태프 채널에 해당 레코드 링크 멘션

### Phase 3 — Review 처리 워크플로 (1일)
- [x] `/review` — Needs Review 목록 조회 (스태프 전용)
- [x] `/link <record> <member|ign>` — 수동 연결 + alias 학습 + 캐시 갱신
- [x] `/unlink` / `/reject` — 오매칭 해제
- [x] 처리 결과 즉시 matcher 캐시 반영 (`/link`가 reload + reconcile 수행)

### Phase 4 — UX / 비용 (1~2일)
- [x] prefix 명령(!) → 슬래시 커맨드(app_commands) 이전 — 전체 15개 명령 슬래시화 완료
- [x] `/stats`를 embed로 개선, `/leaderboard` 추가 (11개 지표 + season 옵션)
- [ ] OCR 모델 `gpt-4.1` vs `gpt-4.1-mini` 정확도/비용 비교 → 환경변수로 이미 전환 가능(`OCR_MODEL`)
- [ ] matcher 임계값(T_HIGH 0.92 / T_LOW 0.75 / MARGIN 0.08)을 실데이터 1~2주치로 보정 (matcher.py 주석의 원래 계획)

### Phase 5 — 구조 개선 (여유 있을 때)
- [x] main.py를 cog 단위로 분리 — `cogs/` (7개 cog). (원래 계획명 `config.py`는 실제 파일명 `core.py`로 반영됨)
- [ ] `_smoke_test.py` → pytest 기반으로 확장 (normalize/fuzzy 경계값 단위 테스트)
- [ ] 배포: 재시작 시 자동 복구 확인, requirements 버전 고정(lock) — pyairtable `>=3.4,<4`로 상한 고정 완료, 나머지는 진행 중
- [x] **reconcile reload 최적화 (2026-06-19)**: `matcher.reload()`를 5분 TTL 게이트(`core.reload_matcher_if_stale`)로 감싸 API 읽기를 시간당 320→~48회로 감소. `matcher.reload()`와 `reconcile_once`에 `fields=` projection 적용해 payload 90%+ 절감. Airtable API에 `timeout=(5,30)` + urllib3 Retry(429/5xx, backoff 0.5) 명시 설정. pyairtable 상한 `>=3.4,<4`로 고정. _smoke_test에 TTL/projection 테스트 추가.

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

- [x] **7-1. NeatQueue API 검증**: Authorization = raw token, `POST /api/v2/add/stats` body `{channel_id, stat:"mmr", value(int), user_id}`, `GET /api/v1/history/{server}`로 매치/변동치 조회. lock/unlock도 `POST /api/v2/lock|unlock` body `{channel_id}`. (2026-06-22 검증 완료)
- [x] **7-2. 승패/팀 정보 확보**: NeatQueue history의 `teams[].players[].id` + `mmr_change` 부호로 승패/팀 정보 확보. 별도 메시지 파싱 불필요.
- [x] **7-3. 매치 연동**: 시간 윈도우 `[mtime-2h, mtime+4h]`로 OCR impact와 연결 (lookback 추가: 시리즈 종료 전 스크린샷 포함). Bo3 맵별 평균은 여전히 TODO.
- [x] **7-4. 보정값 계산**: `modifier = round((impact - 130) / 70 * 10)` — 절대 Impact 밴드 (MIN 60 → -10, MAX 200 → +10). `compute_modifier()` 헬퍼로 분리.
- [x] **7-5. 적용 + 감사 로그**: `nq_add_mmr`로 적용, 스태프 채널 + `MMR_PUBLIC_CHANNEL_ID` 공개 채널에 게시.

### Phase 9 — 시즌 시스템 ✅ 구현 완료 (2026-06-12)
- ingest 시 `Season` 자동 태깅 (`.env`의 `CURRENT_SEASON`)
- `core.season_player_stats()` — 시즌 스코프 집계 엔진 (K/D는 킬/데스 합산, 나머지는 평균)
- `/leaderboard`에 `season` 옵션 추가 (기본=현재 시즌, `career` 입력 시 전체 커리어 rollup)
- `/season` — 시즌 정보 + 본인 배치 진행도 (`PLACEMENT_GAMES`, 기본 5)
- `/seasonreport` (스태프) — 모드별 Top 10 + 어워드 8종 + Grinder 결산 초안을 스태프 채널에 게시
- 신규 파일: `cogs/season.py` / 수정: `core.py`, `main.py`, `cogs/stats.py`
- ⚠️ 선행 조건: Airtable HP/SND 테이블에 `Season` 필드(Single line text) 추가 필수
- 보류: MMR 소프트 리셋 (Phase 7-1 NeatQueue API 검증에 종속)
- ✅ 비활동 decay는 Phase 11에서 봇이 직접 구현 (NeatQueue 자체 decay는 비활성 — 이중 감점 없음)

### Phase 10 — 고급 지표 + Airtable 이관 ✅ 구현 완료 (2026-06-12)
- DPD/DPK/Assist%/ZCS를 Airtable **수식 필드**로 생성 (Players: `HP DPD`, `HP DPK`, `HP Assist %`, `HP ZCS`, `SND Assist %`)
- 봇은 계산하지 않고 미리 계산된 값만 출력 (설계 원칙: Airtable에서 계산 가능하면 Airtable에서)
- `/stats` Advanced 섹션, `/leaderboard` 지표 4종 추가(DPK는 오름차순), 주간 Top10 자동 포스트(월 21:00 KST) + `/weeklyreport`
- Verified 역할 수령 시 미등록자 DM 안내 (`on_member_update`)
- 봇 측 시즌 집계 엔진은 과거 시즌 조회·시즌 결산 전용으로 유지
- 에이전트 컨텍스트 문서 `CLAUDE.md` 추가 (구조·스키마·운영 절차·함정 총정리)

### Phase 8 — Champs 전용 큐 (NeatQueue, 코드 변경 불필요)
> 2026-06-19 갱신: 메커니즘이 "동일 큐 이름"에서 **`/leaderboardconfig sharedstats`** 기반으로 변경됨.
- [x] Champs 역할 보유자만 입장 가능한 큐 채널 (채널 권한으로 게이트, 봇 코드 없음)
- [x] 두 큐 간 MMR/전적 공유: 각 큐 채널에서 `/leaderboardconfig sharedstats set: "Champions Queue"` (동일 sharedstats 이름)
- [x] 결과는 같은 `#results`로 라우팅 (`/resultschannel`) → 스탯 ingest 통일
- [x] ~~(선택) 동시 경기용 2번째 큐 운영~~ — 통합 단일 큐 설계(cogs/queue.py)로 superseded
- 상세: SELFROLES_SETUP.md B 섹션 참고

---

## 4. 권장 착수 순서

**Phase 1(B1~B4)은 완료됨.** 그 다음으로 효율적인 순서: Phase 2(문제가 생겨도 보이게) → Phase 3(운영 동선) → Phase 5(reconcile reload 최적화는 2026-06-19 완료, 나머지 구조 개선은 여유 있을 때).

---

## Session 2 (2026-06-22 ~ 2026-06-25) — 큐 자동화 + MMR 수정 + 문서화

### 완료 항목
- [x] **큐 리마인더 + 3시간 잠금해제 시스템** (`cogs/queue.py` 신규): NA 23:00 ET / EU 23:00 CET, T-2h/T-30min/LIVE/lock phases, RSVP 패널, DST-safe (zoneinfo)
- [x] **MMR modifier live 전환**: `MMR_MODIFIER_DRYRUN=0`, 재시도 로직, 422 정수 변환, TypeError 크래시 수정, 시간창 lookback (시리즈 종료 전 스크린샷 포함)
- [x] **`/backfillmodifiers`**: dry-run 기간 누락 매치 modifier 소급 적용 (match-level `backfilled` 셋)
- [x] **per-player MMR backfill**: `/link`·`/ign` 후 신규 연결 플레이어 modifier 소급 적용 (player+match `applied` 셋)
- [x] **IGN 등록 안내**: `/ignhelp` 패널 + NeatQueue rejection auto-helper + onboarding DM 강화
- [x] **수동 /unlock 보호**: `on_interaction` 감지, `manual_open` 플래그로 자동 lock 스킵 (24h 안전장치)
- [x] **RSVP LIVE DM**: 세션 시작 시 RSVP 명단에게 "지금 들어가!" 디엠
- [x] **NA/EU 통합**: 단일 공유 RSVP 명단, 통합 embed (두 윈도우 시간 표시)
- [x] **MMR 공개 미러**: `MMR_PUBLIC_CHANNEL_ID`에 플레이어용 요약 게시
- [x] **`/clearteam`**: 역할 + Airtable Team + 닉네임 [TAG] 한 번에 제거 + `on_member_update` 자동 태그 제거
- [x] **NeatQueue "User not found" graceful skip**: `⏭ not in NQ` 표시
- [x] **코드 정리**: 데드 코드 제거, `is_staff()` 7-way 중복 → `core.py` 단일 정의, stale 주석 정리 (Phase/B1-B4/Make.com 태그)
- [x] **문서 통합**: CLAUDE.md 재작성 (단일 진실 원천), HANDOFF.md/champions_queue_status.md/STATUS.md 삭제, IMPROVEMENT_PLAN/COMMANDS_GUIDE/DEPLOY_GUIDE 갱신

### 남은 항목 (Session 3+)
- [ ] Bo3 시리즈별 impact 정확 집계 (현재: 시간창 평균, 노이즈 가능)
- [ ] NeatQueue 매치 ID ↔ OCR 레코드 실제 ID 연결 (현재: 시간창 기반)
- [ ] `_smoke_test.py` → pytest 마이그레이션
- [ ] `main.py` `tree.sync()` sync-once 플래그
- [ ] matcher 임계값 실데이터 보정 (T_HIGH 0.92 / T_LOW 0.75 / MARGIN 0.08)
- [ ] OCR 모델 비교 (gpt-4.1 vs gpt-4.1-mini)
- [ ] MMR 소프트 리셋 (시즌 종료 시)

### Phase 11 — 휴면 MMR 부식 & 800 자격 게이트 (하이브리드) ✅ 구현 완료 (2026-06-26)
- **계층별 차등 감점**: Champs 보유자(대회 의무)는 정상 감점(7일 면죄 → −10/일 → 14일+ −20/일). 비-Champs(미성년자/일반)는 관대 감점(21일 면죄 → −5/일 → 35일+ −10/일). 일반/참가팀 큐가 하나의 MMR 풀(sharedstats)이라 완전 면제 시 '놀고먹음' 역불공정 → 관대하게만.
- **dead-day 전원 면제 + 동적 grace**: 최근 24h 매치 0건이면 전원 면제, `dead_days` 증가 → `effective_grace = base + dead_days`로 grace 연장 (큐가 죽은 기간엔 grace 안 소모). 매치 발생 시 리셋.
- **800 자격 게이트는 Champs만**: 800 미만 → `Registered` 역할 박탈, 회복 시 자동 복구. 단 Champs 보유자에게만 (비-Champs는 경쟁 풀 밖).
- 매치 후 준실시간 훅(cogs/mmr.py) + 매일 00:05 UTC 전수 스윕의 이중 안전망. 하한 700.
- 멱등성: `decay_applied` 셋(하루 1회), `below_threshold` diff(역할 토글 중복 방지), `dead_days`(grace 연장). dry-run엔 셋·dead_days 모두 미기록.
- 신규 파일: `cogs/decay.py` / 수정: `core.py`(nq_get_mmr, nq_recent_match_count 등), `cogs/mmr.py`(훅), `main.py`, `_smoke_test.py`, `CLAUDE.md`
- `DECAY_DRYRUN=0` (LIVE) 기본으로 배포 — 코드 기본값이 LIVE. dry-run이 필요하면 `.env`에서 `DECAY_DRYRUN=1`로 덮어쓰기.
