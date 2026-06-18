# Champion's Queue — 프로젝트 종합 정리

> 초대제·프리미엄 CODM(콜오브듀티 모바일) 경쟁 디스코드 서버의 운영 시스템 구축 현황.
> 작성 기준: 지금까지의 대화 전체 회고.

---

## 1. 궁극적 목표

**"고티어 플레이어만 초대되는 프리미엄 CODM 커뮤니티를, 1인이 지속 가능하게 운영할 수 있도록 자동화하는 것."**

구체적으로:

- **주말 한정** 운영 (주 1회, 2~3시간 오픈), **1판 ~10분**, 5v5 Bo3(HP → S&D → Control), 오너가 관전.
- 모든 경기의 **개인 스탯을 자동으로 수집·집계**하고, 플레이어가 **언제든 자기 기록을 조회**할 수 있게.
- MMR 기반 랭크(I~V)와 리더보드로 **경쟁 동기**를 부여.
- 커스텀 디스코드 봇 코드 없이 시작했으나, 최종적으로 **Python 봇 + 클라우드 호스팅**으로 수렴.
- 신규 멤버가 **들어오자마자 등록→플레이까지의 여정**을 한눈에 이해하도록 서버 가이드 정비.

핵심 제약: **1인 운영** → 손이 적게 가고, 끊기지 않고, 오래 가는 구조가 최우선.

---

## 2. 시스템 아키텍처 (4대 엔진)

| 엔진 | 역할 | 현재 구현 위치 |
|---|---|---|
| ① 입장(Verify) | 초대·검증 게이트 (수동 큐레이션) | 디스코드 `#verify` (수동) |
| ② 등록(Registration) | 플레이어 IGN 등록, Discord ID에 매핑 | **Python 봇** (`/ign`, `/changeign`) |
| ③ 수집(Ingestion) | 스코어보드 스샷 → AI OCR → DB 적재 | **Python 봇** (`cogs/ingest.py`, Make.com은 선택적 폴백) |
| ④ 조회(Stats) | 본인 스탯 DM 조회 | **Python 봇** (`/stats`) |

정체성 모델: 모든 것이 **Discord ID(불변 키)** 에 묶임. IGN 변형은 **Aliases 테이블**이 Discord ID로 흡수. 즉 닉네임이 바뀌거나 OCR이 살짝 틀려도 한 사람으로 수렴.

---

## 3. 데이터베이스 (Airtable)

**Base: "Champion's Queue Stats"** (`appm2BhtqdgYGFCMH`) — 4개 테이블.

- **Players** — Discord ID(기본키), Discord Handle, Primary IGN, Region. + HP/SND 각 지표의 Rollup(게임수·평균 K/D·Impact·OBJ·Damage·ADR 등) 완비. **추가 Formula 필드**(Airtable이 자동 계산): `HP DPD`, `HP DPK`, `HP Assist %`, `HP ZCS`, `SND Assist %`.
- **Aliases** — IGN(기본키), Player(링크), Source(Verify seed / Self-added / Staff-linked / Primary / Name Change / OCR Auto), **Created Time**.
- **Records_HP** — IGN as read, Player(링크), Kills/Deaths/K-D/OBJ/Score/Impact/Total Damage/Capture Kill, Date, Map, Match ID, **Status(Matched/Unmatched/+Needs Review 예정)**.
- **Records_SND** — IGN as read, Player(링크), Kills/Deaths/Assists/K-D/Score/Impact/ADR/First Kill/Lone Wolf Win, Date, Map, Match ID, Status.

대시보드/리더보드 **뷰**는 UI에서 수동 생성 (API로 뷰 생성 불가). `/leaderboard`는 11개 지표(K/D, Impact, Games, OBJ, Damage, ADR, First Kills + DPD/DPK/ZCS/Assist%) + season 스코프(career 포함)를 지원.

---

## 4. AI 수집 파이프라인

`#results`에 스코어보드 **2장** 게시 → **GPT-4.1 비전**(temp 0, JSON 강제)이 두 장을 **IGN 기준 병합**, 모드(HP/SND)·맵 판별, 10명 전원 추출 → inline matcher(3단계)로 Matched/Review/Unmatched 분류 → Airtable 적재.

파이프라인은 원래 Make.com으로 구축됐으나, 지금은 **봇 자체에 내장**(`cogs/ingest.py`의 `on_message` 핸들러 + `core.run_ocr`). Make.com 시나리오는 검증용 선택적 폴백으로만 남아있고, 운영 안정화 후 OFF 처리 예정. 프롬프트에는 모드/맵 판별 규칙, "이름은 깨져도 보이는 그대로", K/D/A 파싱, 시간(분:초→초) 변환, 등록 로스터 힌트 등 상세 규칙이 박혀 있음. **검증 완료·가동 중.**

---

## 5. OCR 오인식 보정 시스템 (핵심 난제 해결)

**문제:** AI가 `F10W3R`을 `F1OW3R`로 읽는 등 글자 오인식 → 레코드가 사람과 연결 안 됨. 팀 운영 땐 수동 Alias로 메웠으나, 전체 공개 운영엔 품이 너무 큼.

**해결 (3단 + self-learning, `matcher.py` + 봇 통합):**

1. **정규화 후 정확 일치** → 즉시 확정.
2. **퍼지 매칭(Jaro-Winkler)** → 점수 높고 2등과 격차 크면 자동 확정, 애매하면 검토 큐.
3. **미달** → 미연결(자진신고/검토 대기).
- **Self-learning:** 퍼지로 확정된 깨진 표기를 Alias(`Source=OCR Auto`)로 적립 → 다음엔 1단계 즉시 매칭. 쓸수록 똑똑해짐.
- **백그라운드 reconcile 루프**(45초)가 미연결 레코드를 자동으로 따라잡음 → 봇이 꺼져 있어도 재가동 시 소급 처리(데이터 유실 없음, 지연만). 2026-06-19 최적화: `matcher.reload()`는 5분 TTL 게이트로 주기를 늦추고, `fields=` projection으로 payload 90% 절감.

**미적용 보강(선택):** OCR 단계에서 **로스터(등록 명단)를 프롬프트에 강제**해 오인식을 원천 감소(layer-1). 초대제라 "정답 명단"이 항상 존재한다는 점을 활용.

---

## 6. NeatQueue (매치메이킹 봇) 설정

- 기본: 5v5, Balanced, 결과 → `#results`, 맵 선택은 수동 Bo3 veto로 대체.
- **랭크 I~V 자동 부여:** `/autoroles stats set [role] [MMR] [lower] [upper]` ×5, `only_one_allowed`로 최고 랭크 하나만 유지. 리더보드 업데이트 시 갱신(`/autoroles refresh`).
- **MMR 설계(주말·소수 판수 반영):** 시작 1000, 고정 ±25/판, 구간 폭 100(=1랭크 순승 4판). `/mmr change set`으로 폭·모드(고정 vs 동적) 설정.
- **주의:** 초대제 고수풀 + 밸런스 매칭이면 MMR이 가운데 뭉쳐 랭크가 안 벌어질 수 있음 → 동적 MMR 또는 중앙 구간 좁히기, 시즌 소프트리셋 고려.
- **히어로/오퍼레이터 스킬 기능: 폐기 결정.** NeatQueue 히어로는 "팀 단위 밴 드래프트"라 "각자 픽 기록" 의도와 안 맞음.

---

## 7. 디스코드 서버 정비

채널: INFORMATION(welcome/verify/about/rules/setting/announcements) · CHAMPIONS-QUEUE(how-to-use/queue/results/leaderboard/ign/stats) · COMMUNITY(general/Lounge) · STAFF(admin-log/bot-config).

작성 완료 카피(영문, "By invitation. By merit." 브랜딩):
- **서버 가이드** — 환영 표지판 / 새 멤버 할 일 5스텝(verify→rules→setting→ign→how-to-use) / 리소스 페이지(about·rules·how-to-use·setting).
- **`#about`** 초안, **외부인 초대 안내**("by referral only, DM staff"), **전체 여정 한눈에(START HERE)** 글, **스탯 시스템 소개**(AI+DB 자랑) 카피.
- 읽기 전용 채널 = @everyone "메시지 보내기" 권한 해제(카테고리 단위 동기화) + 스태프만 예외.

---

## 8. 진행 상황 요약

### ✅ 완료
- Airtable 베이스·4테이블·Rollup·Formula(고급 지표)·리더보드 뷰 설계.
- 수집 파이프라인(GPT-4.1 OCR) — 원래 Make.com, 이제 봇 내장(`cogs/ingest.py`)으로 이전 완료. Make.com은 선택적 폴백.
- Python 봇: 등록(`/ign`/`/changeign`) + 조회(`/stats`) + `/leaderboard`(11지표·season) + 자동연결, 버그 2종(Source typecast, relink Status=Matched) 수정.
- OCR 보정 엔진(`matcher.py` 3단+self-learning) + reconcile 루프 통합(`cogs/ingest.py`, `main.py` + `core.py`). 2026-06-19: reload TTL 게이트 + fields projection + Airtable retry 적용.
- NeatQueue MMR/랭크 설계 + Impact 보정(`cogs/mmr.py`, 드라이런).
- 시즌 시스템(`/season`, `/seasonreport`, `/weeklyreport` + 주간 자동 포스트).
- 셀프역할 패널 + 챔피언십 전용 큐 게이트(`/rolepanel`, `/verifypanel`).
- 서버 가이드·온보딩·스탯소개 카피 일체.
- 2026-06-18: GitHub 비공개 repo 백업 (`F10W3R-13/Champions-queue`).

### 🔧 남은 작업 (배포 전 직접 할 일)
1. Airtable: Records_HP·SND의 Status에 **`Needs Review` 옵션 추가** + 검토용 뷰 생성(UI).
2. 로컬/호스트: `pip install -r requirements.txt` (rapidfuzz 포함), `main.py` + `core.py` + `cogs/` 배치, `.env` 확인.
3. Discord 개발자 포털: **Members + Message Content 인텐트 ON.**
4. 실행·검증(자동 보정·`/ign`·`/stats`).

### ⏳ 보류/선택
- 수집(③)을 Python으로 이전할지 → **봇이 클라우드에서 안정화된 뒤** 2단계로 포팅, 그때 인라인 matcher + 로스터 프롬프트까지 얹고 Make OFF. (지금은 하이브리드 유지)
- layer-1 로스터 강제 OCR 프롬프트.
- reconcile 효율화(미연결만 조회), 운영자 조회, 모드별 조회, 테스트 데이터 정리.

---

## 9. 열려 있는 핵심 결정 — 호스팅 (현재 지점)

**문제:** 봇이 로컬 노트북에서 돌아 노트북을 닫으면 등록·조회·보정이 멈춤(수집·큐는 클라우드라 유지). → 상시 가동 호스팅 필요.

**무료 PaaS 환상은 깨짐 (2026 기준):**
- Koyeb: 인수 후 신규 무료 가입 차단(유료 Eco ~$1.61/월).
- Fly.io: 2024년 무료 폐지, 트라이얼 후 ~$2~5/월 + 숨은 비용.
- Railway: 무료 없음, **Hobby $5/월(사용량 $5 포함)** = 소형 봇은 사실상 정액 $5.

**현실적 선택지:**
| 옵션 | 비용 | 성격 |
|---|---|---|
| Railway | ~$5/월 | 가장 쉽고 예측 가능, 함정 없음 |
| 봇 전용 호스트(PebbleHost 등) | ~$2/월 | 정액·저가, 패널식(파일 업로드+Start), git자동배포 아님 |
| Oracle Cloud Always Free | $0 | 진짜 무료지만 VPS, 유휴 회수·가입난이도·1인 관리 부담 |
| 노트북(주말만) | $0 | reconcile가 따라잡음, 평일 등록/조회는 멈춤 |

**현재 사용자 선택:** "한 푼이라도 아끼고 패널식 OK" → **봇 전용 호스트(~$2/월)** 방향을 탐색 중.
- '패널식' = SSH/리눅스 없이 웹 대시보드에서 파일 업로드·Start/Stop·콘솔 로그. 비개발자에겐 오히려 쉬움. 단 코드 수정 때마다 파일 재업로드+재시작.
- **다음 액션:** 평판 좋은 봇 전용 호스트 2~3곳을 현재 가격·사양·24/7 보장·Python 버전·환경변수 지원 기준으로 비교 → 선택 → 배포 가이드.

---

## 10. 결정 로그 (왜 이렇게 됐나)

- 수집은 Make 유지, 나머지는 Python — **한 번에 하나씩** 이전(리스크 최소).
- OCR 오인식은 수동 Alias가 아니라 **퍼지+self-learning 자동화**로 해결.
- 히어로 기능은 NeatQueue 설계 불일치로 **폐기**.
- 호스팅은 무료 PaaS가 사실상 사라져, **소액 PaaS(Railway) vs 봇전용호스트 vs Oracle vs 노트북**의 트레이드오프로 정리 → 현재 봇전용호스트 탐색.
