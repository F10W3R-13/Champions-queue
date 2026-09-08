# 기능별 상세 (CLAUDE.md §6에서 분리)

> 진실 원천은 **CLAUDE.md**. 이 문서는 §6의 상세 버전 — 해당 기능을 수정할 때만 읽으면 된다.
> 기능 변경 시 이 문서와 CLAUDE.md §6 요약을 함께 갱신할 것.

## 1. IGN 등록 & 인증
- `/ign` → Airtable Players 행 생성 + Aliases 행 + `relink_records` (과거 unmatched 연결) + Registered 역할 부여
- **`/link` 후 자동 MMR backfill**: 신규 연결 플레이어의 과거 매치 modifier 소급 적용 (per-player, `applied` 셋으로 중복 방지)
- **`/ignhelp` 패널**: `#ign`에 등록 가이드 상시 게시 + "How do I register?" 버튼
- **NeatQueue rejection auto-helper**: `on_message`로 NeatQueue "not registered" 거부 감지 → `#ign`으로 유도하는 답장 자동 추가

## 2. 통계 & 시즌
- `/stats` (DM 전용), `/leaderboard` (임베드)
- `/season`, `/seasonreport`, `/weeklyreport` + 주간 루프 (월요일 12:00 UTC)
- Advanced 지표: DPD, DPK, ZCS, Assist % (HP Games ≥ 1일 때만 표시)

## 3. OCR 수집
- `on_message`가 #results의 이미지 2장 감지 → GPT-4.1 vision OCR → JSON → Airtable
- 45초 reconcile loop: unmatched 레코드 재매칭 (matcher TTL 5분)
- matcher: 3-stage (exact → fuzzy auto → needs review)
- `/review`, `/link`, `/unlink`, `/reject` 스태프 워크플로

## 4. MMR modifier
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

## 5. 큐 리마인더 & 잠금 자동화
- **reminder_loop** (매분): NA 23:00 ET / EU 23:00 CET 윈도우 감시
- **Phases**: T-2h (준비) → T-30min (Queue Ping) → LIVE (메시지 + unlock + RSVP DM) → lock (+3h)
- **RSVP 패널**: 공유 명단 (NA/EU 분리 없음), Join/Leave/Refresh 버튼, "X reserved — Y more to fill next 5v5 lobby"
- **LIVE DM**: RSVP 명단에게 "지금 들어가!" 디엠 (unlock 완료 후)
- **잠금 동기화**: LIVE 메시지와 NeatQueue unlock을 같은 tick에
- **union 로직**: 어느 윈도우든 열려 있으면 lock 스킵
- **수동 /unlock 보호**: `on_interaction`으로 감지, `manual_open` 플래그로 자동 lock 스킵 (24h 안전장치)
- **KST 미표기**: 서버가 EN/ES 기반이므로 각 윈도우 현지 시간만 표시

## 6. 자가역할 & 팀
- `/rolepanel`: region/weapon/team 셀렉터 (persistent View)
- `/clearteam`: 역할 + Airtable Team + 닉네임 [TAG] 한 번에 제거
- `on_member_update`: Champs 역할 제거 시 자동 닉네임 태그 제거 (이중 안전망)

## 7. 휴면 MMR 부식 & 800 자격 게이트 (하이브리드)
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
- **이중적용 방지 (decay_applied 셋)**: 키 `{date}|{discord_id}`로 하루 1회 부식 강제. **dry-run엔 decay_applied·dead_days 모두 미기록** (PITFALLS.md §9와 동일 원리 — LIVE 전환 시 누락 방지).
- **`DECAY_DRYRUN=0` (LIVE)**: `MMR_MODIFIER_DRYRUN`과 독립. 1로 두면 부식·역할 토글·dead_days 증가 모두 리포트만.
- **DM 알림**: 박탈/복구 시 플레이어에게 디엠 (registration.py DM 패턴).
