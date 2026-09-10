# CLAUDE.md — Champion's Queue Bot

> **단일 진실 원천 (Single Source of Truth).** 이 파일이 프로젝트의 기준점이다.
> 다른 문서(IMPROVEMENT_PLAN.md, COMMANDS_GUIDE.md, DEPLOY_GUIDE 등)는 각각 특정 용도(roadmap, 사용자용 복붙, 배포)만 담당하며, 여기와 중복되는 내용이 충돌하면 **이 파일이 우선**이다.
>
> **Last updated: 2026-09-10**

---

## 1. 프로젝트 개요

**Champion's Queue (CQ)** — Call of Duty Mobile 5v5 경쟁 큐 커뮤니티를 위한 Discord 봇.

- **정체성**: 신원 관리(IGN 등록), 경기 통계(OCR 수집), 시즌 운영, 성과 기반 MMR modifier, 큐 리마인더/잠금 자동화
- **운영 형태**: 파일럿 단계, 1인 운영 (owner: F10W3R)
- **설계 원칙**: **Airtable-first** — 모든 데이터는 Airtable에 저장되고, 봇은 그 위의 자동화 계층
- **서버**: EN/ES 사용자 기반 (기본 언어: 영어)
- **호스팅**: SparkedHost (Apollo Panel / Pterodactyl), always-on 24/7

---

## 2. 아키텍처 — 역할 분담

### NeatQueue (외부 3rd-party 봇)이 소유하는 것
- 큐 생성/개폐, matchmaking (5v5 fill-and-pop), base MMR (승패 ±25), 큐 채널 잠금 상태
- `#queue` (`1512331710736633906`)와 `#queue-2026champs` (`1514827048885948516`) 두 큐 채널 운영

### 이 봇이 소유하는 것
- **신원**: IGN 등록(`/ign`), Verified → Registered 역할 게이트
- **통계**: OCR 스크린샷 수집 → Airtable → `/stats`, `/leaderboard`
- **시즌**: 시즌 기간, 주간 리더보드, 시즌 리포트
- **MMR modifier**: Impact 기반 ±10 추가 점수 (NeatQueue base 위에)
- **큐 리마인더 + 잠금 자동화**: T-30min/LIVE 알림 (LIVE 시 RSVP 5+면 NA 핑 추가), 9시간 윈도우 잠금 제어, RSVP
- **휴면 부식 & 800 자격 게이트**: 7일 이상 휴면 MMR 가속 감점(700 하한), 800 미만 Registered 역할 박탈/자동 복구, 매치 후 준실시간 훅
- **자가역할**: region/weapon/team 셀렉터, `/clearteam`

### 데이터 흐름
```
플레이어가 #results에 스크린샷 2장 업로드
  → on_message 감지 → GPT-4.1 vision OCR → JSON 파싱
  → matcher (3-stage: exact → fuzzy → review)가 IGN → player record 연결
  → Airtable Records_HP / Records_SND에 행 생성
  → /stats, /leaderboard에서 집계 (rollup/formula 필드)
  → NeatQueue 매치 종료 시 base MMR ±25 즉시 부여
  → 10분 루프가 impact 읽어 modifier ±10 추가 부여
```

---

## 3. 폴더 구조

```
Champion's Queue/                         # repo root
├── .gitignore                            # secrets, runtime state, OS artifacts
├── _push_to_github.bat                   # deploy helper (Windows)
├── _setup_git_and_commit.bat             # deploy helper (Windows)
├── Staff/                                # staff manuals (.docx EN/ES)
└── CQ_Bot/                               # ← THE BOT
    ├── main.py                           # entry point: 8 cogs 로드, tree.sync
    ├── core.py                    (750줄) # 공유: config/env, Airtable, matcher, OCR, reconcile, season, NeatQueue API, is_staff()
    ├── matcher.py                          # 3-stage IGN 매칭 (exact → fuzzy → review)
    ├── ocr_prompt.py                       # GPT-4.1 vision 프롬프트
    ├── requirements.txt                    # discord.py, pyairtable, python-dotenv, rapidfuzz, openai
    ├── .env                               # LIVE SECRETS (gitignored)
    ├── .gitignore                          # 2nd layer
    ├── cogs/
    │   ├── registration.py          # /ign /changeign /syncroles, /ignhelp, NeatQueue rejection auto-helper
    │   ├── stats.py                 # /stats (DM), /leaderboard
    │   ├── ingest.py                # on_message OCR, 45s reconcile loop, /review /link /unlink /reject
    │   ├── season.py                # /season /seasonreport /weeklyreport, weekly leaderboard loop
    │   ├── mmr.py                   # Impact-MMR 10min loop, /applymodifiers, /backfillmodifiers, per-player backfill, public mirror
    │   ├── decay.py                 # 휴면 MMR 부식(일일 루프) + 800 자격 게이트(Registered 역할 토글), /decaystatus /decayrun, 준실시간 훅
    │   ├── selfroles.py             # /rolepanel, region/weapon/team pickers, /clearteam, on_member_update tag cleanup
    │   ├── verify.py                # /verifypanel, access application flow
    │   └── queue.py                 # reminder_loop (매분), RSVP 패널, lock/unlock, manual-open 보호, /queuepanel
    ├── _smoke_test.py                      # 오프라인 테스트 harness
    ├── _neatqueue_api_test.py              # NeatQueue API 탐색 스크립트 (수동 실행용)
    ├── Team list_EU.txt, Team list_NA.txt  # 팀 로스터 seed data
    └── docs:
        ├── CLAUDE.md                       # ← 이 파일 (진실 원천)
        ├── FEATURES_DETAIL.md             # §6 기능별 상세 전문
        ├── PITFALLS.md                     # §9 알려진 함정 전문
        ├── IMPROVEMENT_PLAN.md             # roadmap (체크박스)
        ├── COMMANDS_GUIDE.md              # 사용자용 명령 복붙 블록
        ├── DEPLOY_GUIDE_SparkedHost.md    # 배포 가이드
        ├── NEATQUEUE_SETUP.md             # NeatQueue 큐 설정 런북
        ├── SELFROLES_SETUP.md             # 자가역할 설정 런북
        └── CODM_2026_Esports_Settings.md  # 게임 룰셋 참조
```

---

## 4. 환경 변수 (.env)

`.env`는 **gitignored** — GitHub autodeploy로 전달되지 않음. 서버에서 수동 설정 필요.

### 필수 (시크릿)
| 변수 | 용도 |
|---|---|
| `DISCORD_TOKEN` | 봇 토큰 |
| `AIRTABLE_API_KEY` | Airtable Personal Access Token |
| `AIRTABLE_BASE_ID` | `appm2BhtqdgYGFCMH` | (쿼터 고갈 시 신규 워크스페이스 복제본으로 교체 가능 — `AIRTABLE_QUOTA_RUNBOOK.md` 참조. 테이블 ID도 `*_TABLE_ID` env로 덮어쓰기 가능) |
| `OPENAI_API_KEY` | GPT-4.1 vision OCR용 |
| `NEATQUEUE_TOKEN` | NeatQueue REST API (raw token, Bearer 없음) |

### 채널/역할 ID
| 변수 | 기본값 | 용도 |
|---|---|---|
| `RESULTS_CHANNEL_ID` | `1512331781758652546` | #results — 스크린샷 업로드 + MMR 공개 미러 |
| `STAFF_LOGS_CHANNEL_ID` | `1512332329735950386` | staff 로그/알림 |
| `WEEKLY_LEADERBOARD_CHANNEL_ID` | `0` (→ staff logs) | 주간 리더보드 |
| `MMR_PUBLIC_CHANNEL_ID` | `0` (비활성) | MMR modifier 공개 요약 미러. **실제 .env 값: `1512331781758652546` (#results) — 활성 상태** (2026-09-09 확인). modifier가 적용될 때마다 #results에 플레이어용 요약 게시 |
| `IGN_HELP_CHANNEL_ID` | `0` | #ign — 등록 가이드 패널 |
| `QUEUE_JOIN_CHANNEL_ID` | `1512331710736633906` | **#queue** — 라이브 큐 채널 (72명 MMR 풀의 실제 소유자; 2026-09-09 S2 전환. 이전 값 `1514827048885948516` #queue-2026champs는 매치 0건) |
| `QUEUE_REMINDER_CHANNEL_ID` | `0` (→ join 채널) | 리마인더/RSVP 발화 채널 |
| `QUEUE_PING_ROLE_ID` | `0` | "Queue Ping" 역할 (T-30min/LIVE 핑) |
| `QUEUE_NA_PING_ROLE_ID` | `1512533731838263576` | LIVE 때 RSVP가 `QUEUE_NA_PING_THRESHOLD` 이상이면 추가 핑하는 역할 (기본 = NA/LATAM 셀프롤, 0 = 비활성) |
| `QUEUE_NA_PING_THRESHOLD` | `5` | LIVE NA 핑 발동 RSVP 인원 기준 |
| `REGISTERED_ROLE_ID` | `0` | "Registered" — /ign 시 부여, NeatQueue 게이트 |
| `CHAMPS_ROLE_ID` | `1515951370987896852` | "Champs" — 팀 선택 시 부여 |
| `GUILD_ID` | `1512319088146255982` | 서버 ID |

### MMR 설정
| 변수 | 기본값 | 용도 |
|---|---|---|
| `MMR_MODIFIER_DRYRUN` | `1` (dry-run) | **`.env`에서 `0`으로 설정됨 (LIVE)** |
| `MMR_IMPACT_MIN` | `60` | impact 하한 (→ -MAX) |
| `MMR_IMPACT_MAX` | `200` | impact 상한 (→ +MAX) |
| `MMR_MODIFIER_MAX` | `10` | 최대 ±modifier |
| `MMR_STATE_FILE` | `mmr_state.json` | modifier 상태(processed/backfilled/applied) 영속화 |

### 큐 설정
| 변수 | 기본값 | 용도 |
|---|---|---|
| `QUEUE_STATE_FILE` | `queue_state.json` | RSVP + dedup 영속화 |
| `QUEUE_REMINDER_ENABLED` | `1` | 0 = 루프 비활성 |

### 부식 & 자격 게이트 설정
| 변수 | 기본값 | 용도 |
|---|---|---|
| `DECAY_ENABLED` | `1` | 0 = 루프 비활성 |
| `DECAY_DRYRUN` | `0` (LIVE) | 1 = 리포트만 (적용·역할 박탈 안 함) |
| `DECAY_GRACE_DAYS` | `7` | 마지막 매치 후 면죄 일수 |
| `DECAY_RATE` | `10` | 기본 티어 일일 감점량 |
| `DECAY_ESCALATE_AFTER_DAYS` | `14` | 이 일수부터 2배 티어 |
| `DECAY_ESCALATE_RATE` | `20` | Champs 가속 티어 일일 감점량 |
| `DECAY_GRACE_DAYS_NONCHAMPS` | `21` | 비-Champs(미성년자/일반) 면죄 일수 |
| `DECAY_RATE_NONCHAMPS` | `5` | 비-Champs 기본 티어 일일 감점량 |
| `DECAY_ESCALATE_AFTER_DAYS_NONCHAMPS` | `35` | 비-Champs 2단계 진입일 |
| `DECAY_ESCALATE_RATE_NONCHAMPS` | `10` | 비-Champs 가속 티어 일일 감점량 |
| `DECAY_FLOOR` | `700` | MMR 하한 (이 이하로는 안 떨어짐) |
| `DECAY_THRESHOLD` | `800` | 이 미만 = Registered 역할 박탈 |
| `DECAY_QUEUE_NAME` | `Champion's Queue - Inagural Season` | **실제 MMR 풀 큐 이름** (#queue 채널 소유, 72명 전원). 2026-09-09 교정 전 기본값 `Champion's Queue`는 1엔트리짜리 유령 큐였음 — decay/MMR 읽기가 몇 달간 잘못된 큐를 봄 |
| `DECAY_STATE_FILE` | `decay_state.json` | decay_applied / below_threshold 영속화 |
| `DECAY_EPOCH` | `''` (자동 핀) | **재가동 사면 기준일**. idle 일수는 max(마지막 매치, epoch)부터 계산 — 재가동 전 결장이 감점 절벽(−20/일)으로 이어지지 않게 하는 안전장치. 비어 있으면 배포 후 첫 스윕이 당일로 핀하고 state에 영속화. 명시적 ISO 날짜 지정 가능 |
| `DECAY_GATE_ENABLED` | `1` | 800 자격 게이트(Registered 박탈) 마스터 스위치. **게이트는 구조적 교착이 있다** — Registered 박탈 시 NeatQueue 입장이 막혀 매치로 MMR을 회복할 수 없음. 재가동 등 게이트를 중단할 때 `0` |
| `RECONCILE_PERIOD_SECONDS` | `43200` (12h) | reconcile 안전망 루프 주기. **Airtable 월간 API 쿼터 보호** — 기존 45초 폴링은 월 ~15만 호출을 소진시켜 워크스페이스 쿼터를 고갈시킴(Free 1,000/월 하드스톱, 매월 1일 리셋). 성시즌에 45로 되돌릴 수 있음 |
| `QUOTA_BACKOFF_SECONDS` | `86400` (24h) | Airtable 월간 한도(429 billing) 감지 시 reconcile 루프의 자동 백오프 주기 |
| `MATCH_RETRY_PASSES` | `6` | MMR impact 데이터 재시도 상한(패스 수, 10분 루프 기준 ~1시간). 무제한 48h 재시도가 쿼터를 갉아먹는 것을 방지 |

---

## 5. 슬래시 명령 (21개)

### Player (5)
| 명령 | 설명 |
|---|---|
| `/ign [name]` | IGN 등록 + Registered 역할 부여 |
| `/changeign [new]` | IGN 변경 |
| `/stats` | 본인 통계 (DM) |
| `/leaderboard` | 리더보드 |
| `/season` | 현재 시즌 정보 |

### Staff (16)
| 명령 | 설명 |
|---|---|
| `/syncroles` | 전체 Registered 역할 동기화 |
| `/review` | Needs Review 레코드 검토 |
| `/link [record_id] [member/ign]` | 레코드 → 플레이어 수동 연결 |
| `/unlink [record_id]` | 연결 해제 |
| `/reject [record_id]` | 레코드 거부 |
| `/seasonreport` | 시즌 리포트 |
| `/weeklyreport` | 주간 리더보드 수동 게시 |
| `/applymodifiers` | MMR modifier 즉시 처리 |
| `/backfillmodifiers [count]` | 과거 매치 modifier 소급 적용 |
| `/rolepanel` | 자가역할 패널 게시 |
| `/clearteam [member]` | 팀 제거 (역할+Airtable+닉네임 태그) |
| `/verifypanel` | 인증 패널 게시 |
| `/queuepanel` | RSVP 패널 수동 게시 (테스트용) |
| `/queuepause [on\|off]` | T-30min 리마인더 일시정지/재개 (정지 중 LIVE는 핑 없이 게시+언락 유지) |
| `/ignhelp` | IGN 등록 가이드 패널 게시 |
| `/decaystatus [member]` | 플레이어 MMR/휴면일/부식 상태 조회 |
| `/decayrun` | 일일 부식 & 자격 스윕 즉시 실행 |

---

## 6. 기능별 상세 (요약)

> 전체 상세는 **`FEATURES_DETAIL.md`** — 해당 기능을 수정할 때 반드시 먼저 읽을 것.

- **6.1 IGN 등록 & 인증**: `/ign` → Airtable+Registered 역할, `/link` 후 per-player MMR backfill, `/ignhelp` 패널, NeatQueue 거부 auto-helper
- **6.2 통계 & 시즌**: `/stats`(DM)·`/leaderboard`(**지표 5종으로 축소 — 2026-09: K/D, Impact, Games, OBJ(HP), ADR(SND). 고급 지표는 /seasonreport·주간 포스트로 이동**), 시즌/주간 리포트 + 월요일 12:00 UTC 루프(**주간 3섹션: ZCS·DPD·Assist%(SND)**), Advanced 지표(DPD/DPK/ZCS/Assist %)는 /stats 카드에 유지
- **6.3 OCR 수집**: #results 이미지 2장 → GPT-4.1 vision → Airtable, 45초 reconcile 루프, 3-stage matcher, `/review`·`/link`·`/unlink`·`/reject`
- **6.4 MMR modifier**: 10분 루프, impact 공식 `round((impact-130)/70*10)` ±10, 시간창 `[mtime-2h,+4h]` + 참가자 필터/시리즈 클러스터링, 3중 이중적용 방어, backfill, 공개 미러
- **6.5 큐 리마인더 & 잠금**: 매분 루프, **단일 창구 19:00–04:00 ET (9시간, 자정 넘김 — 앵커는 개장일, 스케줄러는 오늘/어제 앵커 이중 검사)**, **T-30min(18:30, Queue Ping)→LIVE(19:00, Queue Ping + RSVP 5명 이상 시 NA/LATAM 핑)→+9h 잠금(04:00)** — t2h(17:00) 제거 (2026-09-10: 하루 터치포인트 2개로 축소), RSVP 패널+LIVE DM, manual-open 보호(24h), `/queuepause on|off` 리마인더 정지 (정지 중 LIVE는 전체 핑 없이 게시+언락, `queue_state.json`의 `reminders_paused`로 영속)
- **6.6 자가역할 & 팀**: `/rolepanel`, `/clearteam`(역할+Airtable+닉네임 태그), `on_member_update` 태그 정리. **Weapon 셀렉터는 채택률 84%(137/163명, 2026-09-09 Discord 조사)로 KEEP 확정** — 통계에 안 쓰여도 소셜 표식으로 기능 중. 단순 "미사용=제거" 가설은 데이터로 기각된 사례
- **6.7 휴면 부식 & 800 게이트**: Champs 정상(7일 grace, −10/−20) vs 비-Champs 관대(21일, −5/−10), floor 700, dead-day 전원 면제+동적 grace, **재가동 사면(`DECAY_EPOCH` — idle을 max(마지막 매치, epoch)부터 계산, 첫 스윕에 자동 핀)**, 800 미만 Champs만 Registered 박탈/자동 복구(**`DECAY_GATE_ENABLED=0`으로 중단 가능** — 박탈되면 매치로 회복할 수 없는 교착 구조), placement 5경기 면제, escalate_after에도 dead-days 연장 적용

---

## 7. Airtable 스키마

Base: `appm2BhtqdgYGFCMH` ("Champion's Queue Stats")

| 테이블 | ID | 주요 필드 |
|---|---|---|
| **Players** | `tbl2sN1bXNlpcUBhV` | Discord ID, Discord Handle, Primary IGN, Team, Region, HP/SND Games, HP/SND Avg * (rollup) |
| **Records_HP** | `tblDp5p1XTzdeFmWm` | IGN as read, Player (link), Kills, Deaths, K/D, OBJ, Score, Impact, Total Damage, Capture Kill, Date, Map, Match ID, Season, Status |
| **Records_SND** | `tblZePZqGRJS5tLbG` | IGN as read, Player (link), Kills, Deaths, Assists, K/D, Score, Impact, ADR, First Kill, Lone Wolf Win, Date, Map, Match ID, Season, Status |
| **Aliases** | `tblHd3q0MNm1186hH` | IGN, Player (link), Source |
| **Teams** | `tblnTq4qEFuMzZt7i` | Name, Tag, Active, Region |

**Status 값**: `Matched` / `Needs Review` / `Unmatched` / `Rejected`
**Match ID**: Discord 메시지 snowflake (스크린샷 게시 메시지 ID)

---

## 8. 워크플로 (검증/배포)

### 로컬 검증
```bash
python -m py_compile cogs/*.py core.py main.py   # 구문 체크
python _smoke_test.py                             # 전체 회귀 테스트
```

### 배포 (GitHub autodeploy)
1. `git push origin main` → GitHub webhook → SparkedHost Apollo Restart
2. Apollo가 `git pull` → 코드 자동 업데이트 → 봇 재시작
3. **`.env`는 자동으로 안 감** — 서버 File Manager에서 수동 편집 후 Restart

### 상태 파일 (서버에만 존재, gitignored)
- `mmr_state.json` — `processed` / `backfilled` / `applied` 셋
- `decay_state.json` — `decay_applied` (하루 1회 부식 멱등) / `below_threshold` (Champs 현재 박탈 집합, 역할 토글 diff) / `dead_days` (누적 큐 비활성일, 동적 grace 연장)
- `queue_state.json` — RSVP 명단 / `fired` 키 / `manual_open` / `live_dmed` / `reminders_paused` (/queuepause 토글)

---

## 9. 알려진 함정 (요약)

> 전체 설명·회귀 테스트 매핑은 **`PITFALLS.md`** — MMR·decay·OCR·NeatQueue API 코드를 건드리기 전 해당 항목 필독.

1. Airtable formula 필드명은 `{Field}` 중괄호 필수 (누락 시 422)
2. `tree.sync()`가 `on_ready`마다 재실행됨 (known minor)
3. NeatQueue "User not found" = 400 영구 에러 → graceful skip
4. Impact 시간창 겹침 → 참가자 필터 + ±30분 시리즈 클러스터링으로 보완
5. `nq_add_mmr` value는 정수만 (소수점 → 422)
6. `.env`는 autodeploy로 전달 안 됨 → 서버 수동 설정
7. 명령 description ≤ 100자 (초과 시 `tree.sync()` 전체 실패)
8. MMR modifier 이중적용 회귀 → 3중 방어 (`applied` 체크 / per-match try/except / processed 마킹)
9. dry-run 중 `applied` 셋에 쓰지 말 것 (LIVE 전환 시 영구 누락)
10. Decay 이중감점 → `decay_applied` 하루 1회 강제, dry-run 미기록, `below_threshold` diff 토글
11. NeatQueue top-level `points` ≠ 큐 MMR → `queues[DECAY_QUEUE_NAME].mmr` 읽기
12. dead-day엔 전원 decay 면제 + `dead_days`로 grace 동적 연장 (dry-run 미기록)
13. Decay 계층 분기: Champs 정상 / 비-Champs 관대, 게이트는 Champs만 (`get_member` None → 비-Champs 취급)
14. **Airtable 월간 API 쿼터는 하드스톱** (Free 1,000/월, 매월 1일 리셋). 상시 폴링 루프(45초 reconcile 등)는 금지 — `RECONCILE_PERIOD_SECONDS`(기본 6h)와 429-billing 자동 백오프(`QUOTA_BACKOFF_SECONDS`) 준수. 쿼터 소진 시 봇의 모든 Airtable 읽기/쓰기가 그 달 내 실패함
15. **재가동/롱기크 후 decay 절벽**: `dead_days`는 첫 매치 다음 날 리셋되지만 결장 이력은 남는다 — idle은 반드시 `DECAY_EPOCH` 기준으로 클램프되어야 함 (smoke test G/G2 참조)
16. **부팅 경로에 Airtable 하드 의존 금지**: `core.py` import 시점의 `Matcher()` 콜드 로드가 429(쿼터 소진)로 죽으면 봇 전체가 exit 1 → Pterodactyl 크래시 루프. 2026-09-09 수정: 로드 실패 시 빈 `Matcher(eager=False)`로 폴백하고 reconcile 루프가 TTL 무시 재시도로 복구 (smoke test H). 새 모듈도 import 시점 API 호출 금지

---

## 10. 업데이트 지침 (이 문서를 유지하는 규칙)

**이 섹션은 CLAUDE.md를 단일 진실 원천으로 유지하기 위한 규칙이다.**

> **핵심 원칙 — 능동적 기록**: 이 문서는 살아있는 단일 진실 원천이다. 주요 코드·기능·설정·스키마 변경을 할 때마다, 작업자(에이전트 포함)는 **별도 지시를 기다리지 않고 스스로 판단하여** 이 문서의 알맞은 섹션에 변경사항을 구조에 맞게 기록한다. 아래 체크리스트는 '어디에 기록할지'의 가이드일 뿐, 기록 자체는 **모든 주요 업데이트에서 의무적**이다. 기록이 누락된 변경은 완료로 간주하지 않는다.

### 언제 업데이트하나
다음 상황이 발생하면 **커밋 전에 반드시** 해당 섹션을 갱신한다:
- 새 기능 추가 → FEATURES_DETAIL.md 상세 + §6 요약 한 줄 + §5 명령 목록
- 새 슬래시 명령 추가 → §5
- 새 환경변수 추가 → §4
- Airtable 스키마 변경 → §7
- 새 함정/버그 발견 → PITFALLS.md 상세 + §9 요약 한 줄
- 파일 추가/삭제/이동 → §3 폴더 구조
- 아키텍처 변경 → §2

### 원칙
- **CLAUDE.md가 유일한 진실 원천.** 다른 문서와 중복 금지.
- `IMPROVEMENT_PLAN.md`는 roadmap 전용 (체크박스).
- `COMMANDS_GUIDE.md`는 사용자용 복붙 블록 (플레이어에게 보여주는 형식).
- 다른 문서와 충돌하면 **CLAUDE.md가 우선**.
- 헤더의 **"Last updated" 날짜**를 매 업데이트마다 갱신.

### 능동적 갱신 원칙
- **모든 주요 작업(기능 추가·버그 수정·설정/스키마 변경·리팩터) 종료 전**, 작업자가 스스로 이 문서의 관련 섹션을 점검하고 갱신한다. 커밋 전 단계이며, 누군가 지시하기를 기다리지 않는다.
- 큰 기능 추가 후: FEATURES_DETAIL.md에 새 섹션 + §6 요약 + §5 명령 + §4 환경변수 점검 + 형제 문서(IMPROVEMENT_PLAN.md 로드맵, COMMANDS_GUIDE.md 사용자용 블록) 동기화.
- 버그 수정 후: PITFALLS.md + §9 요약에 함정으로 등록 (재발 방지) + 해당 회귀에 대한 `_smoke_test.py` 항목 점검.
- 시즌 전환 시: §7 스키마 변경사항 반영.
- **판단 기준**: 변경이 이 문서의 어느 섹션에도 영향을 주지 않는다고 확신할 때만 기록을 생략한다. 확신이 없으면 기록한다.

---

## 11. 로드맵

상세는 `IMPROVEMENT_PLAN.md` 참조. 주요 진행 중 항목:
- ~~Bo3 시리즈별 impact 정확 집계 (현재: 시간창 평균)~~ → **참가자 필터 + 시리즈 클러스터링(`SERIES_CLUSTER_MINUTES=30`)으로 완화**. 잔여 한계: NeatQueue match ↔ Airtable records 간 공유 ID가 없어 시간 기반 추정에 의존. 매치 간격이 30분 이내인 극단적 케이스는 여전히 분리 불가.
- NeatQueue 매치 ID ↔ OCR 레코드 실제 ID 연결 (근본 해결: 위 겹침 문제의 완전 제거는 이 연결고리가 있어야 가능)
- `_smoke_test.py` → pytest 마이그레이션
- `main.py` sync-once 플래그
