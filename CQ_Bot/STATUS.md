# Champion's Queue — Discord 서버 자동화 진행 현황

> 작성일: 2026-06-11
> 대상 서버: **Champion's Queue** (Guild ID: `1512319088146255982`)
> 자동화 스크립트: [setup_champions_queue.py](setup_champions_queue.py), [finish_champions_queue.py](finish_champions_queue.py)

---

## 1. 프로젝트 맥락

**Champion's Queue**는 Call of Duty: Mobile 초청제 랭크 환경을 운영하기 위한 Discord 서버다.

- **운영 컨셉**: 폐쇄형 멤버십, 주말 한정 스펙테이팅 랭크 시리즈(Bo3), NeatQueue 봇 기반 매칭
- **티어 구조**: Contender → Challenger → Elite → Master → Champion
- **자기 분류 역할**: 무기 클래스(AR/SMG/LMG/Shotgun/Marksman/Sniper), 지역(NA/LATAM, EU, APAC, MENA), Queue Ping 알림
- **접근 통제**: `Verified Player` 역할이 있어야 큐/커뮤니티 카테고리 접근 가능
- **운영 원칙**: 셀프봇 ToS 위반을 피해 공식 Discord Bot API로 서버 빌드를 자동화

스크립트는 **idempotent**(재실행 안전)로 설계되어 있어, 같은 이름의 역할/채널/메시지/규칙은 건너뛴다.

---

## 2. 두 스크립트의 역할 구분

| 파일 | 용도 | 동작 |
|---|---|---|
| [setup_champions_queue.py](setup_champions_queue.py) | **초기 빌드** | 역할·카테고리·채널·권한·공지·웰컴스크린·AutoMod·온보딩까지 처음부터 생성 |
| [finish_champions_queue.py](finish_champions_queue.py) | **마감 작업** | 서버가 이미 구성된 상태에서 토픽·핀·웰컴스크린·AutoMod·온보딩만 적용 (생성 없음, 이름 기준 조회) |

---

## 3. 이번 세션에서 한 일

### 3-1. 환경 준비
- Python 3.13 환경에 `discord.py 2.7.1`, `aiohttp 3.14.0` 등 의존성 신규 설치
  ```
  python -m pip install -U discord.py aiohttp
  ```

### 3-2. setup 스크립트 실행 (1차)
- 봇이 Gateway에 정상 연결, 길드 `Champion's Queue` 인식 성공
- **역할 → 카테고리 → 채널 → 권한 오버라이트 → server-rules/verify 텍스트 게시 및 핀 → 웰컴스크린**까지 완료
- AutoMod 단계에서 `AttributeError: module 'discord' has no attribute 'AutoModPresetType'` 로 중단
  - discord.py 2.7에서 enum 이름이 `AutoModPresetType` → `AutoModPresets`로 변경됨

### 3-3. setup 스크립트 실행 (2차)
- AutoMod 호출에서 또 다른 API 변경 발견
- `AutoModTrigger(presets=[...])`는 리스트가 아니라 **단일 `AutoModPresets` 객체**를 요구
- 수정 후 정상 진행, **AutoMod 두 규칙(Profanity & Slurs / Mention Spam) 생성 성공**

### 3-4. finish 스크립트 실행 (1차)
- Topics, Pins, AutoMod는 통과
- 두 가지 실패:
  - **Welcome screen**: `welcome_channels.0.description: Must be between 1 and 50 in length`
    - `verify` 채널 설명 56자 → Discord 50자 제한 초과
  - **Onboarding**: `prompts.[n].id: BASE_TYPE_REQUIRED`
    - Discord API 변경으로 각 prompt와 option에 `id` 필드 필수

### 3-5. finish 스크립트 실행 (2차) — **성공**
- `verify` 설명 단축 ("Request access - referral or application.", 41자)
- 모든 prompt/option에 고유 ID 부여 (`_next_id()` 카운터 추가)
- 모든 마감 작업 정상 적용

---

## 4. 적용된 항목 정리

### 역할 (setup 1차에서 생성됨)
- `Admin` (Administrator 권한, hoist, 색상 #2B2D31)
- `Verified Player` (hoist, 색상 #C9A227)
- 랭크: `Contender`, `Challenger`, `Elite`, `Master`, `Champion` (hoist)
- 무기: `AR`, `SMG`, `LMG`, `Shotgun`, `Marksman`, `Sniper`
- 지역: `NA/LATAM`, `EU`, `APAC`, `MENA`
- 알림: `Queue Ping`

### 채널 트리 (setup 1차에서 생성됨)
| 카테고리 | 가시성 | 채널 |
|---|---|---|
| **INFORMATION** | public | `#welcome`, `#verify`, `#server-rules`, `#announcements`, `#roles` |
| **CHAMPIONS-QUEUE** | verified 전용 | `#ruleset`, `#queue`, `#results`, `#leaderboard`, 🔊 `Lobby` |
| **COMMUNITY** | verified 전용 | `#general`, `#clips`, 🔊 `Lounge` |
| **STAFF** | staff 전용 | `#staff-commands`, `#logs`, `#disputes` |

### 채널 토픽 (finish 1·2차에서 적용)
14개 텍스트 채널 모두 적절한 한 줄 설명 부여 완료.

### 핀 메시지 (setup 1차)
- `#server-rules` — *The Standard* 4단(Integrity / Conduct / Competition / Access)
- `#verify` — 인증 요청 양식 (Referral / Application / Credentials)

### 웰컴 스크린 (finish 2차)
- 설명: "A closed, spectated ranked environment for Call of Duty: Mobile's strongest players. Start below."
- 진입 채널 3개: 📩 `#verify`, 📜 `#server-rules`, 📢 `#announcements`

### AutoMod (setup 2차에서 생성)
- **CQ - Profanity & Slurs**: profanity / slurs / sexual_content 프리셋, 커스텀 차단 메시지
- **CQ - Mention Spam**: 한 메시지 멘션 5회 초과 차단

> 참고: finish 2차에서 AutoMod 생성을 다시 시도했지만 `AUTO_MODERATION_MAX_RULES_OF_TYPE_EXCEEDED` 에러로 거부됨 — 이는 정상 동작(이미 setup 단계에서 생성되어 있음을 확인).

### 온보딩 (finish 2차)
- 모드: Advanced
- 기본 채널: `#verify`, `#server-rules`, `#announcements`
- 프롬프트 3개:
  1. *Want to know when the queue opens?* → `Queue Ping` 역할 (다중 선택)
  2. *Which weapon class roles do you run? (up to two)* → 무기 6종 (다중 선택)
  3. *Where do you play from?* → 지역 4종 (단일 선택)

---

## 5. 수정된 코드 변경 사항

세션 중 두 스크립트에 다음 수정이 가해졌다 (discord.py 2.7 API 호환 / Discord API 검증 통과용):

### `setup_champions_queue.py`
- `discord.AutoModPresetType.*` → `discord.AutoModPresets.*` (1차 수정)
- `presets=[...]` (리스트) → `presets=discord.AutoModPresets(profanity=True, slurs=True, sexual_content=True)` (객체) (2차 수정)

### `finish_champions_queue.py`
- 동일한 AutoMod 시그니처 수정
- `WELCOME_CHANNELS`의 `verify` 설명을 50자 이내로 단축
- 온보딩 페이로드의 모든 prompt/option에 `id` 필드 추가 (`_next_id()` 헬퍼)

---

## 6. 남은 수동 작업

자동화로 처리할 수 없거나 의도적으로 분리한 단계.

### 6-1. 역할 우선순위 조정
- Discord에서 **NeatQueue 봇 역할을 rank/weapon/region 역할들보다 위로 드래그**
  - 그래야 NeatQueue가 이 역할들을 자동 부여 가능

### 6-2. NeatQueue 슬래시 커맨드 실행
**`#queue` 채널에서:**
```
/startqueue (size 5, teams 2)
/teamselection set        → Balanced only
/mmr change allow_disable → off
/startingmmr set 1000
/mmr change set amount:25
/resultschannel #results
/mvp toggle on
/map selection disabled
/lobbychannel set 🔊 Lobby
/readyup mode             → Ready Up Button
/staffchannel set #logs
/staffrole add @Admin
/lobbydetails set         (Bo3 템플릿 입력)
/tempchannels name        → cq-$
```

**`#leaderboard` 채널에서:**
```
/link #queue
/leaderboard              (top.gg 투표 후 잠금 해제)
```

**랭크 자동 부여 (NeatQueue 설정 끝난 뒤):**
```
/autoroles stats set <role> MMR <lower> <upper>   (5개 랭크에 대해)
/autoroles refresh
/autoroles notify
/ratinginname toggle
/ratinginname format
```

### 6-3. 주말 자동 운영
- `/schedule`, `/startqueue`, `/endqueue` 로 주말 윈도우 자동 개폐 설정

### 6-4. (선택) 주말 이벤트 자동 생성
- [setup_champions_queue.py:46](setup_champions_queue.py:46)의 `DO_WEEKEND_EVENT = False`를 `True`로 바꾸고
- `EVENT_START_UTC` / `EVENT_END_UTC` 를 실제 윈도우 시간으로 채운 뒤 재실행
- 재발(recurrence)은 Discord UI에서 수동 설정

---

## 7. 보안 노트

- 두 스크립트 모두 `TOKEN` 변수에 봇 토큰이 **평문으로** 박혀 있다.
- 이 파일들을 외부 저장소(GitHub 등)에 푸시할 경우 **토큰을 반드시 제거하거나 환경 변수로 분리**할 것.
- 토큰이 유출되면 즉시 [Discord Developer Portal](https://discord.com/developers/applications)에서 **Reset Token** 후 봇을 재배포해야 한다.

---

## 8. 재실행 가이드

서버 구성을 변경(역할 추가, 채널 토픽 수정 등)한 뒤 다시 적용하려면:

```powershell
python "C:\Users\0616y\Downloads\finish_champions_queue.py"
```

- 기존 항목은 자동 스킵되고, 새/변경된 토픽·핀·온보딩만 갱신된다.
- 이름이 변경된 역할/채널은 `NAME MISMATCHES` 섹션에 표시되므로 그에 맞춰 스크립트 상단 맵을 수정하거나 Discord 측 이름을 되돌리면 된다.
