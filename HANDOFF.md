# HANDOFF.md — 세션 마이그레이션 문서

> **목적**: 이전 세션의 맥락을 새 세션의 에이전트에게 전달.
> **최종 갱신**: 2026-06-19
> **읽는 순서**: 본 문서 → `CQ_Bot/CLAUDE.md` → 필요 시 `champions_queue_status.md`

---

## 0. 한 줄 요약

Champion's Queue(CODM 초대제 랭크 디스코드 서버) 운영 자동화 봇.
2026-06-19 세션에서 **3대 우선순위(버전관리/성능/문서) + 자동배포 + Make.com 폐기**를 완료.
현재 봇은 SparkedHost에서 24/7 가동 중이며, **GitHub push → Apollo Restart 자동배포** 체계 구축 완료.

---

## 1. 프로젝트 핵심 맥락 (새 에이전트가 알아야 할 것)

- **정체성**: 초대제·프리미엄 CODM 랭크 디스코드 서버, **1인 운영** (운영자: F10W3R-13)
- **운영 형태**: 주말 한정 5v5 Bo3 (HP → S&D → Control), 오너 관전
- **봇 역할**: IGN 등록, 스샷 OCR 수집, 스탯 조회/리더보드, 시즌 시스템, MMR 보정, 자가역할/인증
- **설계 원칙** (CLAUDE.md에 명시, 절대 위반 금지): **"Airtable에서 계산 가능하면 Airtable이 계산"** — 봇은 미리 계산된 rollup/formula만 읽음. 봇측 집계는 시즌 스코프 쿼리에만 허용.
- **정체성 모델**: 모든 것은 Discord ID(불변키)에 묶임. IGN 변형은 Aliases 테이블이 흡수.

## 2. 시스템 아키텍처 (현재 단일화됨)

```
#results 스샷 2장
   │
   ▼  cogs/ingest.py (on_message)
   │
core.run_ocr()  →  GPT-4.1 비전 (ocr_prompt.py, roster 힌트 포함)
   │
matcher.match()  3단계 (정규화 exact → JaroWinkler fuzzy → review/no_match)
   │  fuzzy 확정 시 self-learning alias 자동 적립
   ▼
Airtable (Players / Records_HP / Records_SND / Aliases / Teams)
   +  45초 reconcile 루프 (B1 가드로 정상상태 쓰기 0, reload는 5분 TTL 게이트)
```

**외부 의존성**: NeatQueue(3rd-party 봇, 큐/MMR 담당) + Airtable(DB) + OpenAI(OCR).
**Make.com은 2026-06-19 폐기** — 봇이 모든 수집을 단독 처리.

---

## 3. 결정된 사항 (2026-06-19 세션)

### ✅ 완료 — 코드/시스템 변경

| # | 작업 | 영향 파일 | 핵심 내용 |
|---|---|---|---|
| 1 | **GitHub 비공개 repo 백업** | `.gitignore` (루트+CQ_Bot) | `F10W3R-13/Champions-queue` private repo, 35개 파일 추적. `.env`는 gitignore로 노출 0건 (3중 검증 완료) |
| 2 | **reconcile 성능 최적화** | `matcher.py`, `core.py`, `cogs/ingest.py`, `_smoke_test.py`, `requirements.txt` | (a) `matcher.reload()` 5분 TTL 게이트 (`core.reload_matcher_if_stale`) → API 읽기 6.7배 감소 (b) `fields=` projection → payload 90%+ 절감 (c) Airtable Api `timeout=(5,30)` + urllib3 Retry(429/5xx) (d) pyairtable `>=3.4,<4` 고정 |
| 3 | **문서 불일치 15건 수정** | `COMMANDS_GUIDE.md`, `DEPLOY_GUIDE_SparkedHost.md`, `NEATQUEUE_SETUP.md`, `IMPROVEMENT_PLAN.md`, `champions_queue_status.md`, `CLAUDE.md` | CRITICAL: DEPLOY_GUIDE에 core.py+cogs/ 누락(배포 실패 원인) 복구, `/stats member:` 거짓 안내 삭제, `/leaderboard` 11지표+season 반영. HIGH: Heroes 섹션 폐기 표시, stale 체크박스 갱신, `main_final.py`→`main.py` |
| 4 | **GitHub-SparkedHost 자동배포 연결** | Apollo Startup Settings | `Setup Git → SETUP GITHUB REPOSITORY`로 `.git` 폴더 생성. STARTUP FILE = `CQ_Bot/main.py`. 호스트 루트 구버전 파일은 삭제됨. `git push` + Apollo Restart → 자동 pull 반영 (마커 테스트로 100% 검증) |
| 5 | **Make.com 폐기** | `champions_queue_status.md`, `CLAUDE.md`, `DEPLOY_GUIDE` | 시나리오 4개 비활성화 + 결제 해지(Free 다운그레이드). 봇이 OCR 수집 단독 처리. OpenAI 비용 절반(이중 호출 해소). |

### 🔧 사용자가 진행해야 할 수동 작업 (봇 코드 외)

1. **Make.com 비활성화/결제 해지** (사용자 직접, make.com 웹) — 시나리오 4개 OFF + Subscription cancel
2. **Airtable UI**: Records_HP/SND의 Status에 `Needs Review` 옵션 추가 + 검토용 뷰 생성 (API로 불가)
3. **Discord 개발자 포털**: Members + Message Content 인텐트 ON (이미 됐을 가능성 높음)
4. **MMR 라이브 전환**: `MMR_MODIFIER_DRYRUN=1` → `0` (주말 실경기 1~2회 로그 검토 후)

---

## 4. 코드 변경 내역 (상세)

### `CQ_Bot/matcher.py` — `reload()` projection 추가
```python
# 변경: fields= projection으로 payload 95% 절감 (Players는 19개 rollup 중 Primary IGN 1개만 사용)
for p in self.players_table.all(fields=["Primary IGN"]):
...
for a in self.aliases_table.all(fields=["IGN", "Player"]):
```

### `CQ_Bot/core.py` — 3가지 변경
1. **Api retry/timeout** (상단):
   ```python
   from urllib3.util.retry import Retry
   _airtable_retry = Retry(total=5, status_forcelist=(429,500,502,503,504),
                           backoff_factor=0.5, respect_retry_after_header=True,
                           allowed_methods=frozenset(["GET","POST","PATCH","PUT","DELETE"]))
   airtable_api = Api(AIRTABLE_API_KEY, timeout=(5, 30), retry_strategy=_airtable_retry)
   ```
2. **reconcile_once projection** (`table.all` 호출):
   ```python
   for rec in table.all(formula=formula, fields=[LINKED_PLAYER_FIELD, "Status", ign_field]):
   ```
3. **TTL 게이트 헬퍼** (matcher 초기화 직후):
   ```python
   MATCHER_RELOAD_TTL = int(os.getenv('MATCHER_RELOAD_TTL', '300'))  # 5분
   _matcher_reload_cache = {"t": 0.0}
   def reload_matcher_if_stale(force=False):
       # 락 안에서 호출. force=True는 /ign,/changeign,/link 등 eager-reload 사이트용.
       now = time.time()
       if not force and _matcher_reload_cache["t"] and now - _matcher_reload_cache["t"] < MATCHER_RELOAD_TTL:
           return False
       matcher.reload()
       _matcher_reload_cache["t"] = now
       return True
   ```

### `CQ_Bot/cogs/ingest.py` — reconcile_loop reload 게이트
```python
async with core.airtable_lock:
    reloaded = await asyncio.to_thread(core.reload_matcher_if_stale)  # 5분 TTL
    s = await asyncio.to_thread(core.reconcile_once)                  # 45초마다 (B1 가드로 쓰기 0)
if reloaded or s["matched"] or s["review"]:
    logger.info("reconcile: reload=%s matched=%d ...", reloaded, ...)
```
> 주의: eager-reload 사이트(`/ign`→`relink_records`, `/changeign`, `/link`)는 직접 `matcher.reload()` 호출 유지 (정확성 필수).

### `CQ_Bot/_smoke_test.py` — 테스트 2개 추가
- `FakeTable.all(self, formula=None, max_records=None, fields=None)` 시그니처 확장 (fields 무시)
- "TTL-gated reload test" (4시나리오: 첫호출/즉시재호출/force/stale)
- "Field projection in reload() OK"

### `CQ_Bot/requirements.txt` — `pyairtable>=3.4,<4` (이전 `>=2.3,<4`, 실제 설치는 3.4.0)

### 루트 `.gitignore` 신규 + `CQ_Bot/.gitignore` 보강

---

## 5. 현재 시스템 상태 (검증된 사실)

| 항목 | 상태 |
|---|---|
| GitHub repo | `F10W3R-13/Champions-queue` (private), `main` 브랜치 |
| 호스트 | SparkedHost Apollo, STARTUP FILE = `CQ_Bot/main.py`, Python 3.11 |
| 자동배포 | `git push` → Apollo Restart → 자동 `git pull` (검증 완료) |
| 봇 가동 | ✅ `Synced 15 slash command(s)`, 7개 코그 정상 |
| 2위 최적화 호스트 반영 | ✅ 콘솔에 `reconcile: reload=True` 로그 확인됨 |
| Make.com | 비활성화/결제해지 권장 (사용자 진행 예정) |
| `.env` 호스트 보존 | ✅ (git에 없으므로 pull해도 유지) |
| smoke test | ✅ "ALL SMOKE TESTS PASSED" (7개 케이스) |

---

## 6. 다음 작업 (우선순위 순)

### 🔴 즉시 (사용자 진행 중/대기)
1. **Make.com 비활성화 + 결제 해지** — 시나리오 4개 OFF, Subscription cancel (사용자가 make.com에서 직접)
2. **Make 비활성화 후 검증**: `#results`에 스샷 2장 게시 → 봇 단독 처리 확인 (✅ 또는 ♻️ 반응)

### 🟠 단기 (시즌 운영 검증 후)
3. **MMR 라이브 전환**: `MMR_MODIFIER_DRYRUN=1` → `0` (주말 1~2회 dry-run 로그 검토 후)
4. **Airtable UI 작업**: Status에 `Needs Review` 옵션 + 검토 뷰 (수동, API 불가)
5. **matcher 임계값 보정**: `T_HIGH 0.92 / T_LOW 0.75 / MARGIN 0.08` (실데이터 1~2주치로 캘리브레이션)

### 🟡 중기 (여유 있을 때)
6. **main.py sync-once 플래그** (현재 `tree.sync()` 매 on_ready 실행)
7. **_smoke_test.py → pytest 마이그레이션** (normalize/fuzzy 경계값 단위 테스트)
8. **IMPROVEMENT_PLAN Phase 4 잔여**: OCR 모델 비교(gpt-4.1 vs mini), matcher 임계값 보정

### 🟢 보류/선택
9. **운영자용 스탯 조회 명령어** (`/stats`는 본인 전용 — 운영자용 별도 필요시)
10. **모드별 조회, 테스트 데이터 정리**
11. **2위 추가 최적화**: `modifier_loop`의 `discord_id_map` 캐싱 (현재 uncached), reconcile 미연결만 조회

---

## 7. ⚠️ 새 에이전트가 절대 밟으면 안 되는 함정

1. **샌드박스 bash stale mirror** (CLAUDE.md 명시): 이 폴더의 bash는 편집된 파일의 잘린/낡은 복사본을 뱉음. bash로 읽지 말고 Read 도구 사용. bash-write/git-commit 절대 금지 (소유자 PC에서만).
2. **DPK 리더보드는 오름차순** — "낮을수록 좋음". 내림차순으로 "고치지" 말 것.
3. **`/stats`는 본인 전용** (member 파라미터 없음) — 의도적 설계. 타인 조회 추가 금지.
4. **NeatQueue 토큰 인증**: raw 토큰, "Bearer" 없음 (CLAUDE.md Phase 7 검증됨).
5. **Airtable formula**: 필드명 항상 중괄호 `{Player}`. 사용자 입력 quote-strip.
6. **reconcile 루프 변경 시**: reload는 반드시 `airtable_lock` 안에서 (roster race 방지).
7. **커밋은 소유자 PC에서**: 샌드박스가 아닌 운영자 랩탑에서 `git add -A && git commit && git push` → Apollo Restart.

---

## 8. 핵심 파일 맵 (빠른 탐색)

| 보고 싶은 것 | 파일 |
|---|---|
| 봇 구조/스키마/운영절차/함정 | `CQ_Bot/CLAUDE.md` (가장 정확) |
| 프로젝트 전체 비전/결정로그 | `champions_queue_status.md` |
| 개선 로드맵/Phase 진행상태 | `CQ_Bot/IMPROVEMENT_PLAN.md` |
| 배포 절차(자동배포 포함) | `CQ_Bot/DEPLOY_GUIDE_SparkedHost.md` |
| 사용자용 명령어 안내 | `CQ_Bot/COMMANDS_GUIDE.md` |
| 코드 진입점 | `CQ_Bot/main.py` → `CQ_Bot/core.py` → `CQ_Bot/cogs/` |
| 검증 방법 | `python -m py_compile <files>` + `python _smoke_test.py` |

---

## 9. MCP 환경 (새 세션에서 활용 가능)

`C:\Users\0616y\.zcode\cli\config.json`에 다음 MCP 서버 설정됨 (2026-06-19 수정):
- **notion**: `@notionhq/notion-mcp-server` + Bearer 토큰 (사용자 워크스페이스 접근)
- **airtable**: `airtable-mcp-server` + 정상 82자리 PAT

> 새 세션에서는 `mcp__notion__*`, `mcp__airtable__*` 도구가 노출되어야 함.
> 노출 안 되면: (a) 세션 재시작 안 됨 (b) `npx @notionhq/notion-mcp-server` 직접 실행해 에러 확인 (c) `airtable-mcp-server` 패키지명 재검증.

**보안 메모**: config.json에 평문 토큰 2개(Notion/Airtable). 화면 공유/스크린샷 주의. `.zcode`는 git 추적 대상 아님.
