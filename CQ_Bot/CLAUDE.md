# CLAUDE.md — Agent Context for CQ_Bot

> Read this first. It replaces the need to re-scan every file.
> Last updated: 2026-06-14 (self-roles panel + Teams table + Champs-only queue).

## What this is

Discord stats bot for **Champion's Queue** — an invite-only CODM ranked community
(Guild `1512319088146255982`). Players post 2 scoreboard screenshots in #results →
GPT-4.1 vision OCR → fuzzy IGN matching → Airtable. NeatQueue (3rd-party bot) handles
queues/MMR; this bot handles identity, stats, seasons. Hosted 24/7 on SparkedHost
(Apollo panel, Python 3.11, startup file `CQ_Bot/main.py`, GitHub autodeploy via Setup Git).
Make.com ingestion retired 2026-06-19 — the bot now handles all OCR ingestion itself
(`cogs/ingest.py` on_message + `core.run_ocr`).

## File map

| File | Role |
|---|---|
| `main.py` | Entry. Logging setup, loads 7 cogs, tree.sync on_ready |
| `core.py` | Shared: env/config, Airtable tables, Matcher init, OCR call, ingest_match (batch_create + Season tag), reconcile_once, season aggregation engine + TTL caches, send_staff_log |
| `matcher.py` | 3-stage IGN matching: normalize-exact → JaroWinkler fuzzy (T_HIGH .92 / T_LOW .75 / MARGIN .08) → review/no_match. Self-learning aliases |
| `ocr_prompt.py` | Vision prompt (HP/SND schema, map whitelist, roster hint injection) |
| `cogs/registration.py` | /ign /changeign /syncroles + on_member_update (Verified→DM guide if unregistered) + Registered role grant |
| `cogs/stats.py` | /stats (DM-only, self-only: no member arg, ephemeral reply + DMs the embed; career rollups + Advanced from Airtable formula fields) + /leaderboard (career=rollups, season=bot aggregation, advanced=Airtable fields, hp_dpk sorts ASCENDING) |
| `cogs/ingest.py` | on_message screenshot handler, 45s reconcile loop (+matcher.reload), /review /link /unlink /reject, staff alerts |
| `cogs/season.py` | /season /seasonreport /weeklyreport + weekly top-10 loop (Mon 12:00 UTC, reads precomputed Players fields, 1 table scan) |
| `cogs/mmr.py` | Phase 7 Impact-MMR modifier loop (10-min, NeatQueue add/stats) + /applymodifiers. DRYRUN default |
| `cogs/selfroles.py` | /rolepanel posts a persistent button panel (region/weapon/team). Team pick → Champs role + `[TAG]` nickname + Players.Team. Region pick also writes Players.Region. Roles resolved by NAME (auto-create). Options: region from `REGION_ROLE_NAMES`, weapon from `WEAPON_ROLE_NAMES`, teams live from Teams table |
| `cogs/verify.py` | /verifypanel posts #verify panel with **Request Access** button → modal (Name/Route/Supporting info) → bot posts application to STAFF_LOGS channel (mention shown, no ping) with staff Approve/Reject (Approve grants `VERIFIED_ROLE_NAME` → registration onboarding DM) AND **Select Team** button → `selfroles.open_team_picker` → Champs role (championship-queue path; no-team players still get Verified→main queue). Persistent views; applicant id from embed footer |
| `_smoke_test.py` | Offline test harness (fake Airtable/OpenAI). Run after every change |

Docs (root, ko): `STATUS.md` server-build log (separate setup scripts, NOT this bot) ·
`IMPROVEMENT_PLAN.md` roadmap/phases · `DEPLOY_GUIDE_SparkedHost.md` hosting ·
`NEATQUEUE_SETUP.md` queue config commands · `COMMANDS_GUIDE.md` user-facing guide (en) ·
`CODM_2026_Esports_Settings.md` ruleset reference ·
`SELFROLES_SETUP.md` self-roles panel + Champs-only queue + shared-MMR setup.

## Design principle (owner directive)

**If Airtable can compute it, Airtable computes it.** Bot only reads precomputed
rollup/formula fields. Bot-side aggregation (`season_player_stats`) exists ONLY for
season-scoped queries (rollups can't filter by season dynamically): /leaderboard with
explicit season, /seasonreport, /season placement. Everything else reads Players fields.

## Airtable (base `appm2BhtqdgYGFCMH` "Champion's Queue Stats")

- **Players** `tbl2sN1bXNlpcUBhV`: Discord ID (key), Discord Handle, Primary IGN, `Region`
  (singleSelect: NA/LATAM, EU, APAC, MENA — written by /rolepanel), `Team` (link→Teams,
  `fldHOWyDLpf741RZg`, set by /rolepanel), links to Aliases/Records.
  Career rollups: `HP Games`, `HP Avg K/D|Kills|Deaths|OBJ|Score|Impact|Total Damage|Capture Kill`,
  `SND Games`, `SND Avg K/D|Kills|Deaths|Assists|Score|Impact|ADR|First Kill|Lone Wolf Win`.
  **Formula fields (created via MCP, auto-update)**: `HP DPD`, `HP DPK`, `HP Assist %`, `HP ZCS`, `SND Assist %`.
  (sum-ratio == avg-ratio trick: SUM(A)/SUM(B) ≡ Avg(A)/Avg(B) over same record set)
- **Records_HP** `tblDp5p1XTzdeFmWm` / **Records_SND** `tblZePZqGRJS5tLbG`: per-player-per-map rows.
  Fields: IGN as read, Player(link), Kills/Deaths/(Assists)/K/D/Score/Impact + mode metrics,
  Date, Map(select), Match ID(=discord msg id, dedup key), Status(Matched/Needs Review/Unmatched), **Season**(text).
- **Aliases** `tblHd3q0MNm1186hH`: IGN variant → Player. Source: Primary/Name Change/OCR Auto.
- **Teams** `tblnTq4qEFuMzZt7i`: `Name` (primary = menu label), `Tag` (nickname prefix, e.g. FLC — stored
  WITHOUT brackets, bot adds them), `Active` (checkbox; only Active rows appear in the /rolepanel team menu),
  `Region` (singleSelect NA/EU; team menu is split into one dropdown per region to stay under Discord's
  25-option cap), `Players` (reverse link). Seeded with 32 teams (16 NA + 16 EU). Staff-maintained roster;
  self-select is unverified by design (owner confirms membership manually).
- Airtable MCP connector is available — use it for schema/field changes instead of guiding the user.

## Env (.env)

DISCORD_TOKEN, AIRTABLE_API_KEY, AIRTABLE_BASE_ID, OPENAI_API_KEY, OCR_MODEL(gpt-4.1),
RESULTS_CHANNEL_ID, STAFF_LOGS_CHANNEL_ID, LEADERBOARD_MIN_GAMES(5), REGISTERED_ROLE_ID,
CURRENT_SEASON(S1), SEASON_START/END(ISO), PLACEMENT_GAMES(5), SEASON_CACHE_TTL(600),
VERIFIED_ROLE_NAME(Verified Player), WEEKLY_LEADERBOARD_CHANNEL_ID(0→staff logs).
Self-roles: CHAMPS_ROLE_ID(1515951370987896852 — resolved first, no dup), CHAMPS_ROLE_NAME(Champs fallback), SELFROLES_AUTO_CREATE(1).
NeatQueue MMR modifier: NEATQUEUE_TOKEN, NEATQUEUE_QUEUE_CHANNEL_ID, MMR_MODIFIER_MAX(10),
MMR_IMPACT_MIN(60)/MMR_IMPACT_MAX(200) (absolute Impact band: MIN→−MAX, MAX→+MAX, neutral=midpoint),
MMR_MODIFIER_DRYRUN(1).

## Slash commands (15)

Player: /ign /changeign /stats /leaderboard /season
Staff: /syncroles /review /link /unlink /reject /seasonreport /weeklyreport /applymodifiers /rolepanel /verifypanel

## Workflows

- **Verify changes**: `python -m py_compile <files>` + `python _smoke_test.py` → must end
  "ALL SMOKE TESTS PASSED". Add test cases for new core logic.
- **Deploy**: upload changed files via Apollo panel Files tab → Restart → console shows
  "Synced N slash command(s)". Never run the bot locally while hosted copy runs (double-respond).
- **Session quirk (Cowork)**: the bash-side mirror of this folder can serve STALE/TRUNCATED
  copies of files edited via Edit/Write tools (Windows-side file is always correct).
  NEVER trust bash reads of recently-edited files; NEVER bash-write/move/git-commit inside
  this folder. To verify: reconstruct files in /tmp (heredoc or patch script) and compile/test there.
- **git**: repo initialized, .gitignore ok (.env/__pycache__/*.bak/*.log), but ZERO commits.
  Owner should commit from their own machine (`git add -A && git commit`) — not from the sandbox (stale mirror risk).

## Known pitfalls

- Airtable formula strings: always brace field names `{Player}`. Numeric-only interpolation is injection-safe; quote-strip user input otherwise.
- `tree.sync()` runs on every on_ready (reconnects) — known minor issue, fix = once-flag.
- reconcile loop reloads matcher every 45s (full Players+Aliases scan) — **2026-06-19 fixed**: reload is now TTL-gated via `core.reload_matcher_if_stale()` (5-min default, `MATCHER_RELOAD_TTL` env). reconcile_once still runs every 45s (cheap, B1 guard = 0 writes). reload() and reconcile_once() both use `fields=` projection. Eager-reload sites (/ign, /changeign, /link via relink_records) bypass the TTL. Airtable Api has `timeout=(5,30)` + urllib3 Retry(429/5xx).
- discord.py pitfalls hit before: AutoModPresets API rename, onboarding prompts need `id`s, welcome-screen desc ≤50 chars.
- DPK leaderboard = ascending sort + zero-filter (lower is better). Don't "fix" it to descending.
- `/stats` career section uses rollups; Advanced section reads formula fields — both from the single Players record fetch.
- selfroles: persistent panel needs `bot.add_view(SelfRolePanel())` at load (done in `setup()`) or buttons die after restart. Bot needs **Manage Roles** (role ABOVE every assignable role) + **Manage Nicknames**; cannot rename owner / higher-role members (those keep role+Airtable, skip nick). Team menu is split into one dropdown per `Region` (≤24 teams each + "leave" row); max 5 regions per panel (Discord 5-component limit).
- Champs-only queue is gated by **channel permissions** (only the Champs role can view the queue channel) + a 2nd NeatQueue queue in that channel sharing stats via `/leaderboardconfig sharedstats set: "<name>"`. No bot code for the gate — only the Champs role grant (selfroles) matters. Route its #results to the same RESULTS_CHANNEL_ID so ingest/stats stay unified.

## Pending / roadmap (IMPROVEMENT_PLAN.md)

- **Phase 7 DONE (dry-run)**: `cogs/mmr.py` polls `GET /api/v1/history/{guild}` every 10 min,
  matches screenshots via Match ID snowflake timestamps (4h window), applies Impact modifier
  via `POST /api/v2/add/stats` `{channel_id, stat:"mmr", value, user_id}`.
  **NeatQueue auth = RAW token in Authorization header, NO "Bearer"** (verified live).
  `MMR_MODIFIER_DRYRUN=1` default — flip to 0 after reviewing one weekend of staff-log reports.
  State persisted in `mmr_state.json` on host. NeatQueue base MMR change is NOT flat ±25
  (observed ±31.7 — variance/multipliers on). /applymodifiers = manual trigger (15 slash cmds total).
- MMR soft reset at season end ((old+1000)/2) — now unblocked; build on nq_history + add/stats
  (read each player's MMR from /api/v1/playerstats, apply delta via add/stats).
- Players "Dashboard" grid view in Airtable — manual, cosmetic, may not exist yet.
- main.py sync-once flag; reconcile reload interval; pytest migration.
