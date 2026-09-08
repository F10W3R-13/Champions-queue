# 알려진 함정 — 상세 (CLAUDE.md §9에서 분리)

> 진실 원천은 **CLAUDE.md**. CLAUDE.md §9에 한 줄 요약 목록이 있고, 이 문서가 전체 설명이다.
> 관련 코드(MMR·decay·OCR·NeatQueue API)를 수정하기 전 반드시 해당 항목을 읽을 것.
> 새 함정 발견 시: 여기에 상세 등록 + CLAUDE.md §9에 한 줄 추가.

1. **Airtable formula brace**: formula 문자열에서 필드명은 반드시 `{Field}` 중괄호. 누락 시 422.
2. **`tree.sync()` 재실행**: `on_ready`마다 도므로 재연결 시마다 sync. known minor issue.
3. **NeatQueue "User not found"**: 매치 history엔 있지만 NeatQueue DB엔 없는 플레이어 → 400 영구 에러, graceful skip.
4. **Impact 시간창 lookback + 겹침**: 시리즈 종료(mtime) 전에 올라온 게임별 스크린샷을 잡으려 `[mtime-2h, mtime+4h]` 사용. 단 두 매치 mtime이 가까우면 창이 겹쳐 한 선수의 다른-매치 impact가 평균을 왜곡함 → `impacts_in_window`의 `participant_pids`(참가자 필터) + `target_mtime`(±30분 시리즈 클러스터링)으로 보완. NeatQueue match ↔ Airtable records 간 공유 ID가 없어 시간이 유일한 연결고리임. 회귀 테스트는 `_smoke_test.py` 의 "impact window overlap contamination" 항목.
5. **NeatQueue value 정수만**: `nq_add_mmr`의 value는 반드시 정수. 소수점 → 422.
6. **`.env` autodeploy 미전달**: gitignored라 서버 수동 설정 필수. 빠지면 기본값(=dry-run, 채널 폴백)으로 동작.
7. **`/clearteam` description ≤ 100자**: Discord 제한. 초과 시 `tree.sync()` 전체 실패.
8. **MMR modifier 이중적용 (회귀 원인)**: `apply_modifiers_for_match`는 `nq_add_mmr` 호출 **직후**에 `self.applied.add()` 로 (player, match) 를 기록하지만, **그 뒤 embed 생성 단계에서 예외가 나면** `process_new_matches`가 중단되어 `processed.add()` 까지 도달 못 함 → 다음 루프가 같은 매치를 재처리. per-match 루프가 `applied` 셋을 **읽지 않았던** 시절에는 같은 선수에게 modifier가 반복 적용되어 MMR이 비정상 급등. **3중 방어**: (a) per-match 루프도 적용 전 `applied` 체크, (b) `process_new_matches`에 per-match try/except로 1개 매치 크래시가 전체 패스 중단을 막음, (c) 매치는 processed 마킹하여 재진입 차단. 회귀 테스트는 `_smoke_test.py` 의 "MMR double-apply regression" 항목.
9. **MMR dry-run + `applied` 셋 부적절 마킹**: per-player backfill이 dry-run 중에도 `applied.add()` 했던 과거 버그. 실제로는 아무것도 적용하지 않았으므로, 나중에 LIVE 전환 시 그 (player, match) 가 영구 누락됨. **dry-run일 땐 절대 `applied` 에 쓰지 않는다** (neutral `mod==0` 는 예외 — 0은 적용 여부와 무관).
10. **Decay 이중감점 / dry-run `decay_applied` 마킹**: decay 코그도 §8·§9와 동일한 위험을 가짐. (a) 같은 날 재실행(재시작·수동 트리거) 시 같은 플레이어가 두 번 깎이면 안 됨 → `decay_applied` 셋(키 `{date}|{discord_id}`)로 하루 1회 강제. (b) dry-run 중에 이 셋에 쓰면 LIVE 전환 후 그 날짜-플레이어가 영구 누락 → **dry-run엔 절대 쓰지 않는다**. (c) 역할 토글은 `below_threshold` diff로 상태가 바뀐 사람만 → 매번 전체 remove_roles 중복 방지. 회귀 테스트는 `_smoke_test.py` 의 "Decay double-apply" / "dry-run stamp" / "floor protection" 항목.
11. **NeatQueue `points` ≠ 큐 MMR**: `GET /api/v1/playerstats` 응답의 top-level `points`(보통 1000)는 authoritative 큐 MMR이 아님 — `queues[DECAY_QUEUE_NAME].mmr`를 읽어야 함. sharedstats 통합으로 여러 큐 entry가 응답에 중첩되므로 큐 이름 매핑 주의. (2026-06-26 프로브로 확인: F10W3R `points=1000` vs `queues["Champion's Queue"].mmr=1023`)
12. **Decay dead-day 동적 grace — 큐가 죽은 기간에 grace를 소모하면 부당 감점**: 큐가 비어 아무도 뛸 수 없었던 날(dead-day)에 decay를 부과하면 '구조적 불가' 상태의 플레이어를 부당하게 벌줌. **해결**: `nq_recent_match_count(24)==0`이면 그 날 전원 면제 + `dead_days` 증가 → `effective_grace = base_grace + dead_days`로 grace를 연장. 매치 발생 시 `dead_days=0` 리셋. **dry-run엔 dead_days도 미기록** (§9/§10과 동일 원리, LIVE 전환 시 누락 방지). 회귀 테스트는 `_smoke_test.py` 의 "Dead-day exemption" 항목.
13. **Decay 계층 분기 — 하나의 MMR 풀 + 의무/비의무 계층 역설**: 일반큐와 참가팀큐가 sharedstats로 **하나의 MMR 풀**을 공유. 비-참가팀(미성년자)을 decay에서 완전 면제하면 같은 풀에서 '놀고먹음' 역불공정, 전체 적용하면 '뛸 수 없는데 벌' 부당. **해결**: Champs 보유자(대회 의무)는 정상 감점, 비-Champs는 관대 감점(면죄 21일/−5/일). 800 자격 게이트도 **Champs 보유자에게만** 적용 (비-Champs는 경쟁 풀 밖). `_member_has_champs`는 `get_member` None이면 비-Champs 취급 (보수적). 회귀 테스트는 `_smoke_test.py` 의 "Tier differential" / "Gate Champs-only" 항목.
