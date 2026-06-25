# CQ Stats Bot — Command Guide (Discord 게시용)

> 아래 두 블록을 그대로 복사해 사용. 블록 1은 공개 채널(#welcome, #roles 등), 블록 2는 스태프 채널(#staff-commands)에 게시 권장.
> 현재 시스템의 진실 원천은 **CLAUDE.md**. 이 문서는 사용자용 복붙 블록.

---

## Block 1 — Player Commands (public)

```
## 📊 CQ Stats Bot — Player Commands

**Getting Started**
> `/ign` — Register your in-game name with the bot. Required before anything else.
> Example: `/ign ign_name: F10W3R`
> ⚠️ Enter your IGN *exactly* as it appears in-game (case, tags, symbols). One registration per player.

> `/changeign` — Update your registered IGN after an in-game name change.
> Your match history stays linked — past and future stats are tracked under one profile.

**Stats**
> `/stats` — Privately view **your own** career stats card (Hardpoint & Search and Destroy averages + advanced metrics).
> Sent to your DMs only — you can only ever see your own stats (no member option, by design).
> Enable "Direct Messages from server members" in your privacy settings or it can't reach you.

> `/leaderboard` — Top 10 players by mode and metric.
> Pick a mode (HP / SND) and a metric:
> **Basic** — K/D, Impact, Games, OBJ/Time (HP), Damage (HP), ADR (SND), First Kills (SND)
> **Advanced** — Damage per Death (HP), Damage per Kill (HP, lower = better), Zone Control Score (HP), Assist % (non-kill contribution)
> Optionally pass `season:` (e.g. `S1`, or `career` for all-time). Defaults to the current season.

**Match Results — automatic**
Post **both scoreboard screenshots in ONE message** in #results.
The bot reacts:
> ⏳ reading → ✅ logged (stats updated automatically)
> ♻️ means that match was already recorded (duplicate, safely skipped).
> No reaction + an error message = the screenshots couldn't be read — re-post clearer ones.
No command needed. If a name can't be matched, staff will review it — your stats will appear once resolved.

**Notes**
• Registered your IGN after playing? The bot links your past unmatched games automatically.
• Wrong stats or missing games? Ping a staff member.
```

---

## Block 2 — Staff Commands (staff channel only)

```
## 🛠️ CQ Stats Bot — Staff Commands

> `/review` — List records the bot couldn't auto-match (max 20, with record IDs).

> `/link` — Manually link a review record to a player.
> Usage: `/link record_id: rec... member: @Player` (or `ign: F10W3R` instead of member — pick one).
> The bot also learns the misread name as an alias, so the same OCR error auto-matches next time.

> `/unlink` — Remove a wrong player link from a record (resets it to Unmatched).

> `/reject` — Mark a record as Unmatched without linking anyone (e.g. unreadable / invalid entry).

**Alerts**
The bot posts to the staff log channel automatically when:
• ⚠️ a match contains names needing review (with Airtable links)
• 🚨 an OCR ingestion error occurs
• 🔗 a staff member links/unlinks/rejects a record (audit trail)

**MMR & Queue Management**
> `/applymodifiers` — Force-process new NeatQueue matches for Impact MMR modifiers now (normally runs every 10 min).

> `/backfillmodifiers` — Backfill missed MMR modifiers onto recent processed matches (count: 1–20, default 2). Use after enabling live mode or fixing a pipeline bug. Safe to re-run (skips already-applied).

> `/queuepanel` — Post the RSVP queue panel manually (normally auto-fired 2h before each session window). Use for testing.

> `/ignhelp` — Post the IGN registration guide panel in the current channel. Pin it in #ign so blocked players can find help.

> `/clearteam` — Strip a player's team membership completely: removes the Champs role, clears their Airtable Team field, and removes the [TAG] prefix from their nickname. Use when someone falsely claimed a team.

> `/rolepanel` — Re-post the self-roles panel (region / weapon / team selectors) if the old one is lost.

> `/verifypanel` — Re-post the access-request / verify panel.

> `/seasonreport` — Generate and post the full season report (top 10 per mode + awards).

> `/weeklyreport` — Force-post the weekly leaderboard (normally auto-posted Monday 12:00 UTC).

> `/syncroles` — Bulk-grant the Registered role to everyone who has a Players record. Use after a migration or if roles are out of sync.
```
