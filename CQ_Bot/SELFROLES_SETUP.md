# 셀프 역할 패널 + 챔피언십 전용 큐 설정

> 2026-06-14. `cogs/selfroles.py` + Airtable `Teams` 테이블 기준.
> 코드 배포(파일 업로드+재시작) 후, 아래 디스코드/NeatQueue 설정만 하면 동작합니다.

---

## A. 셀프 역할 패널 (지역 / 무기군 / 팀)

전용 채널에 버튼 패널 1개를 띄우면, 멤버가 언제든 스스로 역할을 바꿀 수 있습니다.
온보딩과 같은 역할을 재사용하므로 입장 후 변경이 자유로워집니다.

### 1. 봇 권한 (필수)

- **역할 관리(Manage Roles)** + 봇 역할을 **부여 대상 역할들보다 위로** 드래그
- **닉네임 관리(Manage Nicknames)** — 팀 태그 `[FLC]`를 닉네임 앞에 붙이기 위함
- 제약: **서버 소유자**와 **봇보다 높은 역할을 가진 멤버**는 닉네임을 못 바꿉니다.
  이 경우 역할·Airtable 기록은 정상 처리하고 닉네임만 건너뜁니다(사용자에게 안내됨).

### 2. 역할 준비

- 지역: `NA/LATAM`, `EU`, `APAC`, `MENA` (Airtable Region 선택지와 동일)
- 무기군: `AR`, `SMG`, `Sniper`, `LMG`
- 팀: `Champs` (팀 선택 시 부여되는 단일 역할) — 역할 ID `1515951370987896852`로 고정됨
  (`core.py`의 `CHAMPS_ROLE_ID`). 봇이 이 ID를 먼저 찾으므로 중복 역할이 생기지 않습니다.
- 지역/무기군 역할이 없으면 봇이 **자동 생성**합니다(`SELFROLES_AUTO_CREATE=1` 기본). 색/순서를
  직접 관리하려면 미리 만들어 두세요. 이름이 위와 다르면 `core.py`의 `REGION_ROLE_NAMES` /
  `WEAPON_ROLE_NAMES`를 맞춰 수정하면 됩니다.

### 3. 팀 목록 (Airtable `Teams` 테이블) — 이미 32팀 입력됨

NA 16 + EU 16, 총 32팀이 입력돼 있습니다. 팀 추가/수정 시 1행당:

- **Name** — 메뉴에 보일 팀 이름 (예: SYBARITES)
- **Tag** — 닉네임 앞 약어 (대괄호 없이 `SY`로 저장 → 봇이 `[SY] 닉네임`으로 표시)
- **Active** — 체크해야 선택 메뉴에 노출 (미참가/대기 팀은 체크 해제)
- **Region** — `NA` 또는 `EU`. 팀 메뉴를 지역별로 나눠 디스코드 25개 옵션 제한을 피함

> 자기 팀을 누구나 고를 수 있는 자유 선택 방식입니다(검증 없음). 실제 소속 여부는 운영진이
> 직접 확인하세요. 팀 메뉴는 **지역(Region)별 드롭다운**으로 분리되며, 각 지역 24팀 이하·
> 최대 5개 지역까지 한 패널에 표시됩니다.

### 4. 패널 게시

1. 전용 채널을 만들고(예: `#역할-설정`), 일반 멤버는 메시지 전송을 막아도 됩니다.
2. 그 채널에서 운영진이 **`/rolepanel`** 실행 → 버튼 패널이 게시됩니다.
3. 봇 재시작 후에도 버튼은 계속 동작합니다(persistent view). 팀 목록을 바꾼 뒤 패널을
   새로 고치고 싶으면 `/rolepanel`을 다시 실행해 새 메시지를 올리세요.

동작: 🌍 지역(택1, Region 필드에도 기록) · 🔫 무기군(복수) · 🏆 팀(택1 → Champs 역할 +
닉네임 태그 + Players.Team 기록, "팀 없음"으로 해제 가능).

---

## B. 챔피언십 전용 큐 + MMR 통합

목표: Champs만 들어가는 큐를 추가해 **동시에 여러 경기**를 돌리되, MMR/전적은 기존 큐와
**하나로 합치기**.

### 1. 동시 경기

NeatQueue 큐 하나는 인원이 차는 대로 매치를 계속 팝합니다(첫 경기 진행 중에도 다음 10명이
별도 매치로 시작). 즉 동시 다중 경기를 위해 채널을 여러 개 만들 필요는 없고, **Champs 전용
큐 채널 1개**면 됩니다. (`/simulate`로 1회 확인 권장)

### 2. 입장 게이팅 (채널 권한)

새 큐 채널을 만들고 채널 권한에서 `@everyone` 보기 거부 + `Champs` 역할만 보기/입장 허용.
NeatQueue는 그 채널에서 큐를 돌리면 됩니다. (이중 안전이 필요하면 NeatQueue 큐 설정의
required-role에도 `Champs`를 추가)

### 3. MMR/전적 통합

두 큐 채널 각각에서 같은 공유 스탯 이름을 지정:

```
/leaderboardconfig sharedstats set: "Champions Queue"
```

(서버 전체 통합이면 `/leaderboardconfig sharedstats serverwide`) — 같은 이름을 쓰는 큐끼리
MMR·전적이 한 풀로 묶입니다. 공유로 묶으면 `cogs/mmr.py`의 Impact 모디파이어도 기존
channel_id 그대로 공유 풀에 반영됩니다.

### 4. 스탯 파이프라인 통합

Champs 큐의 NeatQueue 결과 메시지를 **기존 #results 채널(`RESULTS_CHANNEL_ID`)** 로
보내도록 설정하면, 봇 OCR/ingest가 그대로 잡아 Airtable 스탯이 자동 통합됩니다(봇 코드 수정
불필요). 다른 채널로 보내면 ingest가 못 잡으니 주의.

---

## 검증 체크리스트

- [ ] 봇에 Manage Roles(위계) + Manage Nicknames 부여
- [ ] Teams 테이블에 팀 입력 + Active 체크
- [ ] 전용 채널에서 `/rolepanel` → 지역/무기군/팀 버튼 각각 동작
- [ ] 팀 선택 시 Champs 역할 + `[TAG]` 닉네임 + Airtable Team/Region 기록 확인
- [ ] Champs 큐 채널 권한이 Champs 역할로 제한되는지
- [ ] 두 큐에 `sharedstats` 동일 이름 → `/leaderboard`가 합산되는지
- [ ] Champs 큐 결과가 #results에 게시되어 `/stats`에 반영되는지
