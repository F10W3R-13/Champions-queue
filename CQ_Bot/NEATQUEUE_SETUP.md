# NeatQueue 설정 — 랜덤 팀 / 맵 선택 / 오퍼레이터 스킬 픽

> 2026-06-12. 근거: CODM_2026_Esports_Settings.md + NeatQueue 공식 문서.
> 모든 명령은 큐 채널에서 실행. 적용 후 `/simulate`로 검증 권장.

---

## 1. 팀 선택 랜덤

```
/teamselection set        → Random 선택
```

- 기존 설정(Balanced)을 Random으로 교체.
- 역할 슬롯(`/roles`)은 그대로 유지됨 — 역할 구성 안에서 랜덤 배정.

## 2. 맵 선택 (Esports Map Pool 등록 + 선택 방식 활성화)

현재 `/map selection disabled` 상태이므로 두 단계 필요.

### 2-1. 맵 풀 등록 (모드 태그 포함)

```
/map add map_name: Summit        game_modes: Hardpoint
/map add map_name: Hacienda      game_modes: Hardpoint
/map add map_name: Combine       game_modes: Hardpoint
/map add map_name: Takeoff       game_modes: Hardpoint
/map add map_name: Arsenal       game_modes: Hardpoint
/map add map_name: Tunisia       game_modes: Search and Destroy
/map add map_name: Firing Range  game_modes: Search and Destroy
/map add map_name: Coastal       game_modes: Search and Destroy
/map add map_name: Slums         game_modes: Search and Destroy
/map add map_name: Meltdown      game_modes: Search and Destroy
```

(Control까지 운영하면 Raid, Standoff, Crossroads Strike 추가)

### 2-2. 선택 방식 켜기 — 두 가지 중 택1

```
/map voting     → 플레이어 투표로 맵 결정 (간단, 캐주얼)
/map bans       → 밴/베토 방식 (esports 규정의 Veto Process와 유사)
```

- 정식 규정(BO3 Veto: 양팀 번갈아 밴 → 남은 맵 확정)에 가깝게 하려면 `/map bans`
- 빠른 진행이 우선이면 `/map voting`
- `/map selection` 으로 선택 모드 세부 조정

## 3. 오퍼레이터 스킬 픽 (팀 내 중복 금지)

NeatQueue의 **Heroes** 기능 사용 — 허용 오퍼레이터 스킬 10종을 "hero"로 등록.

```
/hero add hero_name: Annihilator
/hero add hero_name: Claw
/hero add hero_name: Death Machine
/hero add hero_name: Equalizer
/hero add hero_name: Gravity Spikes
/hero add hero_name: Gravity Vortex Gun
/hero add hero_name: Purifier
/hero add hero_name: Sparrow
/hero add hero_name: Tempest
/hero add hero_name: War Machine
```

활성화:

```
/hero voting    → 팀 생성 후 각 플레이어가 스킬 선택
```

- 규정 근거: 같은 팀 두 명이 동일 오퍼레이터 스킬 장착 금지 (위반 시 해당 맵 몰수패)
- 10종 = 2026 허용 목록 전체. 향후 금지/허용 변경 시 `/hero add`/`/hero remove`로 갱신
- ⚠️ 팀 내 중복 차단이 강제되는지는 `/simulate`로 1회 확인할 것. 강제가 안 되면 픽 현황 공개용으로 쓰고 중복 금지는 규정(몰수패)으로 운영

---

## 적용 후 검증 체크리스트

- [ ] `/info` — teamselection이 Random, maps/heroes 등록 확인
- [ ] `/simulate` — 가짜 플레이어로 큐 풀가동: 역할 1명씩 분배 + 맵 선택 + 스킬 픽 흐름 확인
- [ ] 실제 첫 매치에서 결과 메시지가 #results에 정상 게시되는지 확인

---

## 챔피언십 전용 큐 + MMR 통합

Champs 역할 보유자만 입장하는 2번째 큐(동시 경기용)와 MMR 통합 방법은
`SELFROLES_SETUP.md` B 섹션 참고. 핵심: 채널 권한으로 Champs만 입장 + 두 큐에
`/leaderboardconfig sharedstats set: "Champions Queue"` (동일 이름)로 MMR/전적 공유 +
결과는 같은 #results로 보내 스탯 통합.
