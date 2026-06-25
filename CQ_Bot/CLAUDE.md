# CLAUDE.md — Champion's Queue Bot

> **단일 진실 원천 (Single Source of Truth).** 이 파일이 프로젝트의 기준점이다.
> 다른 문서(IMPROVEMENT_PLAN.md, COMMANDS_GUIDE.md, DEPLOY_GUIDE 등)는 각각 특정 용도(roadmap, 사용자용 복붙, 배포)만 담당하며, 여기와 중복되는 내용이 충돌하면 **이 파일이 우선**이다.
>
> **Last updated: 2026-06-25**

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
- **큐 리마인더 + 잠금 자동화**: T-2h/T-30min/LIVE 알림, 3시간 윈도우 잠금 제어, RSVP
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
    ├── core.py                    (650줄) # 공유: config/env, Airtable, matcher, OCR, reconcile, season, NeatQueue API, is_staff()
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
    │   ├── selfroles.py             # /rolepanel, region/weapon/team pickers, /clearteam, on_member_update tag cleanup
    │   ├── verify.py                # /verifypanel, access application flow
    │   └── queue.py                 # reminder_loop (매분), RSVP 패널, lock/unlock, manual-open 보호, /queuepanel
    ├── _smoke_test.py                      # 오프라인 테스트 harness
    ├── _neatqueue_api_test.py              # NeatQueue API 탐색 스크립트 (수동 실행용)
    ├── Team list_EU.txt, Team list_NA.txt  # 팀 로스터 seed data
    └── docs:
        ├── CLAUDE.md                       # ← 이 파일 (진실 원천)
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
| `AIRTABLE_BASE_ID` | `appm2BhtqdgYGFCMH` |
| `OPENAI_API_KEY` | GPT-4.1 vision OCR용 |
| `NEATQUEUE_TOKEN` | NeatQueue REST API (raw token, Bearer 없음) |

### 채널/역할 ID
| 변수 | 기본값 | 용도 |
|---|---|---|
| `RESULTS_CHANNEL_ID` | `1512331781758652546` | #results — 스크린샷 업로드 + MMR 공개 미러 |
| `STAFF_LOGS_CHANNEL_ID` | `1512332329735950386` | staff 로그/알림 |
| `WEEKLY_LEADERBOARD_CHANNEL_ID` | `0` (→ staff logs) | 주간 리더보드 |
| `MMR_PUBLIC_CHANNEL_ID` | `0` (비활성) | MMR modifier 공개 요약 미러 |
| `IGN_HELP_CHANNEL_ID` | `0` | #ign — 등록 가이드 패널 |
| `QUEUE_JOIN_CHANNEL_ID` | `1514827048885948516` | #queue-2026champs — NeatQueue join 버튼 |
| `QUEUE_REMINDER_CHANNEL_ID` | `0` (→ join 채널) | 리마인더/RSVP 발화 채널 |
| `QUEUE_PING_ROLE_ID` | `0` | "Queue Ping" 역할 (T-30min/LIVE 핑) |
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

### 큐 설정
| 변수 | 기본값 | 용도 |
|---|---|---|
| `QUEUE_STATE_FILE` | `queue_state.json` | RSVP + dedup 영속화 |
| `QUEUE_REMINDER_ENABLED` | `1` | 0 = 루프 비활성 |

---

## 5. 슬래시 명령 (19개)

### Player (5)
| 명령 | 설명 |
|---|---|
| `/ign [name]` | IGN 등록 + Registered 역할 부여 |
| `/changeign [new]` | IGN 변경 |
| `/stats` | 본인 통계 (DM) |
| `/leaderboard` | 리더보드 |
| `/season` | 현재 시즌 정보 |

### Staff (14)
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
| `/ignhelp` | IGN 등록 가이드 패널 게시 |

---

## 6. 기능별 상세

### 6.1 IGN 등록 & 인증
- `/ign` → Airtable Players 행 생성 + Aliases 행 + `relink_records` (과거 unmatched 연결) + Registered 역할 부여
- **`/link` 후 자동 MMR backfill**: 신규 연결 플레이어의 과거 매치 modifier 소급 적용 (per-player, `applied` 셋으로 중복 방지)
- **`/ignhelp` 패널**: `#ign`에 등록 가이드 상시 게시 + "How do I register?" 버튼
- **NeatQueue rejection auto-helper**: `on_message`로 NeatQueue "not registered" 거부 감지 → `#ign`으로 유도하는 답장 자동 추가

### 6.2 통계 & 시즌
- `/stats` (DM 전용), `/leaderboard` (임베드)
- `/season`, `/seasonreport`, `/weeklyreport` + 주간 루프 (월요일 12:00 UTC)
- Advanced 지표: DPD, DPK, ZCS, Assist % (HP Games ≥ 1일 때만 표시)

### 6.3 OCR 수집
- `on_message`가 #results의 이미지 2장 감지 → GPT-4.1 vision OCR → JSON → Airtable
- 45초 reconcile loop: unmatched 레코드 재매칭 (matcher TTL 5분)
- matcher: 3-stage (exact → fuzzy auto → needs review)
- `/review`, `/link`, `/unlink`, `/reject` 스태프 워크플로

### 6.4 MMR modifier
- **10분 루프**: NeatQueue history 폴링 → impact 읽기 → modifier 계산 → 적용
- **Impact 공식**: `modifier = round((impact - 130) / 70 * 10)`, 범위 ±10, impact 60→-10 / 130→0 / 200→+10
- **시간창**: `[mtime - 2h, mtime + 4h]` (lookback: 시리즈 종료 전 게임별 스크린샷 포함)
- **재시도**: impact 데이터 없으면 processed에 넣지 않고 10분마다 재시도 (최대 48h)
- **`/backfillmodifiers`**: dry-run 기간에 누락된 매치 modifier 소급 적용 (match-level `backfilled` 셋)
- **per-player backfill**: `/link`·`/ign` 후 그 플레이어만 소급 적용 (player+match `applied` 셋)
- **공개 미러**: `MMR_PUBLIC_CHANNEL_ID`에 플레이어용 요약 게시 (dry-run 아닐 때만)
- **NeatQueue "User not found"**: 영구 에러 → `⏭ not in NQ`로 graceful skip

### 6.5 큐 리마인더 & 잠금 자동화
- **reminder_loop** (매분): NA 23:00 ET / EU 23:00 CET 윈도우 감시
- **Phases**: T-2h (준비) → T-30min (Queue Ping) → LIVE (메시지 + unlock + RSVP DM) → lock (+3h)
- **RSVP 패널**: 공유 명단 (NA/EU 분리 없음), Join/Leave/Refresh 버튼, "X reserved — Y more to fill next 5v5 lobby"
- **LIVE DM**: RSVP 명단에게 "지금 들어가!" 디엠 (unlock 완료 후)
- **잠금 동기화**: LIVE 메시지와 NeatQueue unlock을 같은 tick에
- **union 로직**: 어느 윈도우든 열려 있으면 lock 스킵
- **수동 /unlock 보호**: `on_interaction`으로 감지, `manual_open` 플래그로 자동 lock 스킵 (24h 안전장치)
- **KST 미표기**: 서버가 EN/ES 기반이므로 각 윈도우 현지 시간만 표시

### 6.6 자가역할 & 팀
- `/rolepanel`: region/weapon/team 셀렉터 (persistent View)
- `/clearteam`: 역할 + Airtable Team + 닉네임 [TAG] 한 번에 제거
- `on_member_update`: Champs 역할 제거 시 자동 닉네임 태그 제거 (이중 안전망)

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
- `queue_state.json` — RSVP 명단 / `fired` 키 / `manual_open` / `live_dmed`

---

## 9. 알려진 함정

1. **Airtable formula brace**: formula 문자열에서 필드명은 반드시 `{Field}` 중괄호. 누락 시 422.
2. **`tree.sync()` 재실행**: `on_ready`마다 도므로 재연결 시마다 sync. known minor issue.
3. **NeatQueue "User not found"**: 매치 history엔 있지만 NeatQueue DB엔 없는 플레이어 → 400 영구 에러, graceful skip.
4. **Impact 시간창 lookback**: 시리즈 종료(mtime) 전에 올라온 게임별 스크린샷을 잡으려 `[mtime-2h, mtime+4h]` 사용.
5. **NeatQueue value 정수만**: `nq_add_mmr`의 value는 반드시 정수. 소수점 → 422.
6. **`.env` autodeploy 미전달**: gitignored라 서버 수동 설정 필수. 빠지면 기본값(=dry-run, 채널 폴백)으로 동작.
7. **`/clearteam` description ≤ 100자**: Discord 제한. 초과 시 `tree.sync()` 전체 실패.

---

## 10. 업데이트 지침 (이 문서를 유지하는 규칙)

**이 섹션은 CLAUDE.md를 단일 진실 원천으로 유지하기 위한 규칙이다.**

### 언제 업데이트하나
다음 상황이 발생하면 **커밋 전에 반드시** 해당 섹션을 갱신한다:
- 새 기능 추가 → §6 기능별 상세 + §5 명령 목록
- 새 슬래시 명령 추가 → §5
- 새 환경변수 추가 → §4
- Airtable 스키마 변경 → §7
- 새 함정/버그 발견 → §9
- 파일 추가/삭제/이동 → §3 폴더 구조
- 아키텍처 변경 → §2

### 원칙
- **CLAUDE.md가 유일한 진실 원천.** 다른 문서와 중복 금지.
- `IMPROVEMENT_PLAN.md`는 roadmap 전용 (체크박스).
- `COMMANDS_GUIDE.md`는 사용자용 복붙 블록 (플레이어에게 보여주는 형식).
- 다른 문서와 충돌하면 **CLAUDE.md가 우선**.
- 헤더의 **"Last updated" 날짜**를 매 업데이트마다 갱신.

### 주기적 업데이트
- **특정 태스크나 업무가 끝날 때마다** 이 문서의 관련 섹션을 확인하고 갱신한다.
- 큰 기능 추가 후: §6에 새 섹션 추가 + §5 명령 + §4 환경변수 점검.
- 버그 수정 후: §9에 함정으로 등록 (재발 방지).
- 시즌 전환 시: §7 스키마 변경사항 반영.

---

## 11. 로드맵

상세는 `IMPROVEMENT_PLAN.md` 참조. 주요 진행 중 항목:
- Bo3 시리즈별 impact 정확 집계 (현재: 시간창 평균)
- NeatQueue 매치 ID ↔ OCR 레코드 실제 ID 연결
- `_smoke_test.py` → pytest 마이그레이션
- `main.py` sync-once 플래그
