# CLAUDE.md — Champion's Queue Bot

> **단일 진실 원천 (Single Source of Truth).** 이 파일이 프로젝트의 기준점이다.
> 다른 문서(IMPROVEMENT_PLAN.md, COMMANDS_GUIDE.md, DEPLOY_GUIDE 등)는 각각 특정 용도(roadmap, 사용자용 복붙, 배포)만 담당하며, 여기와 중복되는 내용이 충돌하면 **이 파일이 우선**이다.
>
> **Last updated: 2026-06-26**

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
    │   ├── decay.py                 # 휴면 MMR 부식(일일 루프) + 800 자격 게이트(Registered 역할 토글), /decaystatus /decayrun, 준실시간 훅
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

### 부식 & 자격 게이트 설정
| 변수 | 기본값 | 용도 |
|---|---|---|
| `DECAY_ENABLED` | `1` | 0 = 루프 비활성 |
| `DECAY_DRYRUN` | `1` (dry-run) | 1 = 리포트만 (적용·역할 박탈 안 함) |
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
| `DECAY_QUEUE_NAME` | `Champion's Queue` | sharedstats 통합 큐 이름 (MMR 읽기 소스) |
| `DECAY_STATE_FILE` | `decay_state.json` | decay_applied / below_threshold 영속화 |

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
| `/ignhelp` | IGN 등록 가이드 패널 게시 |
| `/decaystatus [member]` | 플레이어 MMR/휴면일/부식 상태 조회 |
| `/decayrun` | 일일 부식 & 자격 스윕 즉시 실행 |

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
- **겹침 방지 (참가자 필터 + 시리즈 클러스터링)**: 두 매치의 시간창이 겹칠 때 한 선수의 다른-매치 impact가 평균을 왜곡하지 않도록 2단계로 걸러냄. (1) `impacts_in_window(participant_pids=...)` 로 이 매치에 실제 참가하지 않은 선수의 레코드를 배제. (2) `target_mtime` 클러스터링으로 같은 참가자의 레코드 중 가장 가까운 것에서 ±`SERIES_CLUSTER_MINUTES`(30분) 이내만(=같은 Bo3 시리즈) 남김. NeatQueue match ↔ Airtable records 사이에 공유 ID가 없어 시간이 유일한 연결고리이므로, 이 필터로 보완.
- **재시도**: impact 데이터 없으면 processed에 넣지 않고 10분마다 재시도 (최대 48h)
- **이중적용 방지 (3중)**: per-match 루프는 적용 전 `applied` 셋(`{did}|{match_key}`) 체크 → `process_new_matches`는 per-match try/except로 1개 매치 크래시가 전체 패스 중단/재진입을 막음 → 매치는 processed 마킹. dry-run일 땐 `applied` 에 쓰지 않음 (LIVE 전환 후 누락 방지).
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

### 6.7 휴면 MMR 부식 & 800 자격 게이트 (하이브리드)
- **계층별 차등 감점 (TIERING)**: 일반큐와 참가팀큐는 sharedstats로 **하나의 MMR 풀**을 공유. 비-참가팀(미성년자/일반 멤버)은 참가팀큐에 구조적 접근 불가이므로 **완전 면제**하면 같은 풀에서 '놀고먹음' 역불공정. 따라서 Champs 보유자(대회 의무)는 **정상 감점**, 비-Champs는 **관대 감점**(면죄 21일, −5/일). 두 가치(MMR 통합 유지 + 놀고먹음 방지)를 동시 충족.
- **dead-day 전원 면제**: 매일 스윕 시작 시 `nq_recent_match_count(24)`로 최근 24h 매치 수 확인 → 0건이면 그 날은 **전원 decay 면제** + `dead_days` 증가. "뛸 수 없었으니 깎을 수 없다" (큐가 비어 있으면 누구도 뛸 수 없음).
- **동적 grace (dead_days 연장)**: `effective_grace = base_grace + dead_days`. 큐가 N일 연속 죽었으면 grace도 N일 연장 → 부당 감점 원천 차단. 매치 발생 시 `dead_days=0` 리셋.
- **부식 규칙 (Champs)**: 마지막 매치 후 `DECAY_GRACE_DAYS`(7일) 면죄 → 8일차~13일 매일 `−DECAY_RATE`(10) → 14일차부터 매일 `−DECAY_ESCALATE_RATE`(20). `DECAY_FLOOR`(700) 이하로는 안 떨어짐.
- **부식 규칙 (비-Champs)**: 면죄 `DECAY_GRACE_DAYS_NONCHAMPS`(21일) → 그 후 매일 `−DECAY_RATE_NONCHAMPS`(5) → 35일차부터 `−DECAY_ESCALATE_RATE_NONCHAMPS`(10). 하한 동일 700.
- **NeatQueue decay 비활성 확인**: NQ 자체 decay는 꺼져 있어 이중 감점 없음 (2026-06-26 검증).
- **자격 게이트 (Champs만)**: `DECAY_THRESHOLD`(800) 미만 → `Registered` 역할 제거 (NeatQueue 큐 입장 게이트). 800 이상 회복 → 자동 재부여. **Champs 보유자에게만 적용** (비-Champs는 경쟁 풀 밖). `below_threshold` 셋 diff로 상태가 바뀐 사람만 토글.
- **준실시간 훅**: `cogs/mmr.py`의 `apply_modifiers_for_match` 말미에서 매치 참가자 각각에 대해 `Decay.check_threshold_for_player` 호출. 단 Champs 보유자만 게이트 (부식은 일일 루프 전담).
- **면제**: `PLACEMENT_GAMES` 미만(기본 5경기)은 부식·박탈 모두 제외 (신규가입자 보호).
- **MMR 읽기**: `GET /api/v1/playerstats` → `queues["Champion's Queue"].mmr` (top-level `points`가 아님). 마지막 매치 시각은 `last_match_end`.
- **이중적용 방지 (decay_applied 셋)**: 키 `{date}|{discord_id}`로 하루 1회 부식 강제. **dry-run엔 decay_applied·dead_days 모두 미기록** (§9.9와 동일 원리 — LIVE 전환 시 누락 방지).
- **`DECAY_DRYRUN=1` 기본**: `MMR_MODIFIER_DRYRUN`과 독립. dry-run에선 부식·역할 토글·dead_days 증가 모두 리포트만.
- **DM 알림**: 박탈/복구 시 플레이어에게 디엠 (registration.py DM 패턴).

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
- `queue_state.json` — RSVP 명단 / `fired` 키 / `manual_open` / `live_dmed`

---

## 9. 알려진 함정

1. **Airtable formula brace**: formula 문자열에서 필드명은 반드시 `{Field}` 중괄호. 누락 시 422.
2. **`tree.sync()` 재실행**: `on_ready`마다 도므로 재연결 시마다 sync. known minor issue.
3. **NeatQueue "User not found"**: 매치 history엔 있지만 NeatQueue DB엔 없는 플레이어 → 400 영구 에러, graceful skip.
4. **Impact 시간창 lookback + 겹침**: 시리즈 종료(mtime) 전에 올라온 게임별 스크린샷을 잡으려 `[mtime-2h, mtime+4h]` 사용. 단 두 매치 mtime이 가까우면 창이 겹쳐 한 선수의 다른-매치 impact가 평균을 왜곡함 → `impacts_in_window`의 `participant_pids`(참가자 필터) + `target_mtime`(±30분 시리즈 클러스터링)으로 보완. NeatQueue match ↔ Airtable records 간 공유 ID가 없어 시간이 유일한 연결고리임. 회귀 테스트는 `_smoke_test.py` 의 "impact window overlap contamination" 항목.
5. **NeatQueue value 정수만**: `nq_add_mmr`의 value는 반드시 정수. 소수점 → 422.
6. **`.env` autodeploy 미전달**: gitignored라 서버 수동 설정 필수. 빠지면 기본값(=dry-run, 채널 폴백)으로 동작.
7. **`/clearteam` description ≤ 100자**: Discord 제한. 초과 시 `tree.sync()` 전체 실패.
8. **MMR modifier 이중적용 (회귀 원인)**: `apply_modifiers_for_match`는 `nq_add_mmr` 호출 **직후**에 `self.applied.add()` 로 (player, match) 를 기록하지만, **그 뒤 embed 생성 단계에서 예외가 나면** `process_new_matches`가 중단되어 `processed.add()` 까지 도달 못 함 → 다음 루프가 같은 매치를 재처리. per-match 루프가 `applied` 셋을 **읽지 않았던** 시절에는 같은 선수에게 modifier가 반복 적용되어 MMR이 비정상 급등. **3중 방어**: (a) per-match 루프도 적용 전 `applied` 체크, (b) `process_new_matches`에 per-match try/except로 1개 매치 크래시가 전체 패스 중단을 막음, (c) 매치는 processed 마킹하여 재진입 차단. 회귀 테스트는 `_smoke_test.py` 의 "MMR double-apply regression" 항목.
9. **MMR dry-run + `applied` 셋 부적절 마킹**: per-player backfill이 dry-run 중에도 `applied.add()` 했던 과거 버그. 실제로는 아무것도 적용하지 않았으므로, 나중에 LIVE 전환 시 그 (player, match) 가 영구 누락됨. **dry-run일 땐 절대 `applied` 에 쓰지 않는다** (neutral `mod==0` 는 예외 — 0은 적용 여부와 무관).
10. **Decay 이중감점 / dry-run `decay_applied` 마킹**: decay 코그도 §9.8·§9.9와 동일한 위험을 가짐. (a) 같은 날 재실행(재시작·수동 트리거) 시 같은 플레이어가 두 번 깎이면 안 됨 → `decay_applied` 셋(키 `{date}|{discord_id}`)로 하루 1회 강제. (b) dry-run 중에 이 셋에 쓰면 LIVE 전환 후 그 날짜-플레이어가 영구 누락 → **dry-run엔 절대 쓰지 않는다**. (c) 역할 토글은 `below_threshold` diff로 상태가 바뀐 사람만 → 매번 전체 remove_roles 중복 방지. 회귀 테스트는 `_smoke_test.py` 의 "Decay double-apply" / "dry-run stamp" / "floor protection" 항목.
11. **NeatQueue `points` ≠ 큐 MMR**: `GET /api/v1/playerstats` 응답의 top-level `points`(보통 1000)는 authoritative 큐 MMR이 아님 — `queues[DECAY_QUEUE_NAME].mmr`를 읽어야 함. sharedstats 통합으로 여러 큐 entry가 응답에 중첩되므로 큐 이름 매핑 주의. (2026-06-26 프로브로 확인: F10W3R `points=1000` vs `queues["Champion's Queue"].mmr=1023`)
12. **Decay dead-day 동적 grace — 큐가 죽은 기간에 grace를 소모하면 부당 감점**: 큐가 비어 아무도 뛸 수 없었던 날(dead-day)에 decay를 부과하면 '구조적 불가' 상태의 플레이어를 부당하게 벌줌. **해결**: `nq_recent_match_count(24)==0`이면 그 날 전원 면제 + `dead_days` 증가 → `effective_grace = base_grace + dead_days`로 grace를 연장. 매치 발생 시 `dead_days=0` 리셋. **dry-run엔 dead_days도 미기록** (LIVE 전환 시 누락 방지, §9.9/§9.10과 동일 원리). 회귀 테스트는 `_smoke_test.py` 의 "Dead-day exemption" 항목.
13. **Decay 계층 분기 — 하나의 MMR 풀 + 의무/비의무 계층 역설**: 일반큐와 참가팀큐가 sharedstats로 **하나의 MMR 풀**을 공유. 비-참가팀(미성년자)을 decay에서 완전 면제하면 같은 풀에서 '놀고먹음' 역불공정, 전체 적용하면 '뛸 수 없는데 벌' 부당. **해결**: Champs 보유자(대회 의무)는 정상 감점, 비-Champs는 관대 감점(면죄 21일/−5/일). 800 자격 게이트도 **Champs 보유자에게만** 적용 (비-Champs는 경쟁 풀 밖). `_member_has_champs`는 `get_member` None이면 비-Champs 취급 (보수적). 회귀 테스트는 `_smoke_test.py` 의 "Tier differential" / "Gate Champs-only" 항목.

---

## 10. 업데이트 지침 (이 문서를 유지하는 규칙)

**이 섹션은 CLAUDE.md를 단일 진실 원천으로 유지하기 위한 규칙이다.**

> **핵심 원칙 — 능동적 기록**: 이 문서는 살아있는 단일 진실 원천이다. 주요 코드·기능·설정·스키마 변경을 할 때마다, 작업자(에이전트 포함)는 **별도 지시를 기다리지 않고 스스로 판단하여** 이 문서의 알맞은 섹션에 변경사항을 구조에 맞게 기록한다. 아래 체크리스트는 '어디에 기록할지'의 가이드일 뿐, 기록 자체는 **모든 주요 업데이트에서 의무적**이다. 기록이 누락된 변경은 완료로 간주하지 않는다.

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

### 능동적 갱신 원칙
- **모든 주요 작업(기능 추가·버그 수정·설정/스키마 변경·리팩터) 종료 전**, 작업자가 스스로 이 문서의 관련 섹션을 점검하고 갱신한다. 커밋 전 단계이며, 누군가 지시하기를 기다리지 않는다.
- 큰 기능 추가 후: §6에 새 섹션 추가 + §5 명령 + §4 환경변수 점검 + 형제 문서(IMPROVEMENT_PLAN.md 로드맵, COMMANDS_GUIDE.md 사용자용 블록) 동기화.
- 버그 수정 후: §9에 함정으로 등록 (재발 방지) + 해당 회귀에 대한 `_smoke_test.py` 항목 점검.
- 시즌 전환 시: §7 스키마 변경사항 반영.
- **판단 기준**: 변경이 이 문서의 어느 섹션에도 영향을 주지 않는다고 확신할 때만 기록을 생략한다. 확신이 없으면 기록한다.

---

## 11. 로드맵

상세는 `IMPROVEMENT_PLAN.md` 참조. 주요 진행 중 항목:
- ~~Bo3 시리즈별 impact 정확 집계 (현재: 시간창 평균)~~ → **참가자 필터 + 시리즈 클러스터링(`SERIES_CLUSTER_MINUTES=30`)으로 완화**. 잔여 한계: NeatQueue match ↔ Airtable records 간 공유 ID가 없어 시간 기반 추정에 의존. 매치 간격이 30분 이내인 극단적 케이스는 여전히 분리 불가.
- NeatQueue 매치 ID ↔ OCR 레코드 실제 ID 연결 (근본 해결: 위 겹침 문제의 완전 제거는 이 연결고리가 있어야 가능)
- `_smoke_test.py` → pytest 마이그레이션
- `main.py` sync-once 플래그
