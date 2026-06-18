# CQ Stats Bot — Command Guide (Discord 게시용)

> 아래 두 블록을 그대로 복사해 사용. 블록 1은 공개 채널(#welcome, #roles 등), 블록 2는 스태프 채널(#staff-commands)에 게시 권장.

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
> `/stats` — View your career stats card (Hardpoint & Search and Destroy averages).
> Add a member to view someone else's stats: `/stats member: @Player`

> `/leaderboard` — Top 10 players by mode and metric.
> Pick a mode (HP / SND) and a metric (K/D, Impact, Games, OBJ, Damage, ADR, First Kills).

**Match Results — automatic**
Post **both scoreboard screenshots in ONE message** in #results.
The bot reacts:
> ⏳ reading → ✅ logged → stats updated automatically
> ♻️ means that match was already recorded.
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
> Usage: `/link record_id: rec... member: @Player` or `/link record_id: rec... ign: F10W3R`
> The bot also learns the misread name as an alias, so the same OCR error auto-matches next time.

> `/unlink` — Remove a wrong player link from a record (resets it to Unmatched).

> `/reject` — Mark a record as Unmatched without linking anyone (e.g. unreadable / invalid entry).

**Alerts**
The bot posts to the staff log channel automatically when:
• ⚠️ a match contains names needing review (with Airtable links)
• 🚨 an OCR ingestion error occurs
• 🔗 a staff member links/unlinks/rejects a record (audit trail)
```
