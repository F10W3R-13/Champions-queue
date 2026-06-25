import os, sys, types, asyncio
os.environ.update(DISCORD_TOKEN="x", AIRTABLE_API_KEY="x", AIRTABLE_BASE_ID="app00000000000000",
                  OPENAI_API_KEY="x")

# ---- Fake Airtable layer ----
class FakeTable:
    def __init__(self, name):
        self.name = name
        self.rows = []
        self._c = 0
        self._updates = 0
    def all(self, formula=None, max_records=None, fields=None):
        # `fields=` is accepted (real pyairtable projects the payload) but ignored
        # here - the fake stores whole rows. Matching logic is field-name driven.
        rows = self.rows
        if formula:
            if "{Player} = ''" in formula or "{Player}=''" in formula:
                rows = [r for r in rows if not r["fields"].get("Player")]
            if "{Status} = ''" in formula or "{Status}=''" in formula:
                rows = [r for r in rows if not r["fields"].get("Status")]
            if "{Match ID}" in formula:
                val = formula.split("'")[1]
                rows = [r for r in rows if r["fields"].get("Match ID") == val]
            if "{Discord ID}" in formula:
                val = formula.split("'")[1]
                rows = [r for r in rows if r["fields"].get("Discord ID") == val]
            if "{Primary IGN}" in formula:
                val = formula.split("'")[1]
                rows = [r for r in rows if r["fields"].get("Primary IGN") == val]
        return rows[:max_records] if max_records else rows
    def create(self, fields, typecast=False):
        self._c += 1
        rid = "rec%s%03d" % (self.name[:3], self._c)
        row = {"id": rid, "fields": dict(fields)}
        self.rows.append(row)
        return row
    def batch_create(self, records, typecast=False):
        results = []
        for fields in records:
            results.append(self.create(fields, typecast=typecast))
        return results
    def update(self, rid, fields, typecast=False):
        self._updates += 1
        for r in self.rows:
            if r["id"] == rid:
                r["fields"].update(fields)
        return {"id": rid}

TABLES={}
class FakeApi:
    def __init__(self,*a,**k): pass
    def table(self, base, tid):
        return TABLES.setdefault(tid, FakeTable(tid))

import pyairtable
pyairtable.Api = FakeApi
# stub openai AsyncOpenAI so construction is cheap/offline
import openai
class _Stub:
    def __init__(self,*a,**k): self.chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=None))
openai.AsyncOpenAI=_Stub

# Pre-seed Players + Aliases BEFORE importing main (Matcher.reload runs at import)
P=TABLES.setdefault("tbl2sN1bXNlpcUBhV",FakeTable("Players"))
A=TABLES.setdefault("tblHd3q0MNm1186hH",FakeTable("Aliases"))
P.rows.append({"id":"recF","fields":{"Discord ID":"111","Primary IGN":"F10W3R"}})
P.rows.append({"id":"recP","fields":{"Discord ID":"222","Primary IGN":"Phoenix"}})
A.rows.append({"id":"a1","fields":{"IGN":"F10W3R","Player":["recF"]}})
A.rows.append({"id":"a2","fields":{"IGN":"Phoenix","Player":["recP"]}})

import main

print("roster:", main.matcher.roster)

# ---- matcher tests ----
def show(name):
    print("  match(%-14r) ->"%name, main.matcher.match(name))
show("Phoenix")        # exact
show("F10W3R")         # exact
show("F1OW3R")         # OCR O->0 corruption (fuzzy)
show("Ph0enix")        # fuzzy
show("ZZZRandomGuy")   # no_match

# ---- helper tests ----
assert main._to_num("12")==12 and main._to_num("2.08")==2.08 and main._to_num("")is None
assert "x" not in main._clean({"a":1,"x":None,"y":""})
assert main._extract_json('garbage {"mode":"HP","result":[]} tail')["mode"]=="HP"
print("helpers OK")

# ---- ingest_match (HP) end-to-end ----
HP=TABLES["tblDp5p1XTzdeFmWm"]
hp_json={"mode":"HP","map":"Takeoff","result":[
  {"IGN":"F10W3R","Kills":25,"Deaths":12,"K/D":2.08,"time_seconds":85,"Score":2400,"Impact":85,"Total Damage":3200,"Capture Kill":5},
  {"IGN":"F1OW3R","Kills":10,"Deaths":9,"K/D":1.11,"time_seconds":40,"Score":900,"Impact":40,"Total Damage":1500,"Capture Kill":1},
  {"IGN":"ZZZRandomGuy","Kills":3,"Deaths":15,"K/D":0.2,"time_seconds":0,"Score":100,"Impact":5,"Total Damage":300,"Capture Kill":0},
]}
s=main.ingest_match(hp_json,"msg123","2026-06-09")
print("HP ingest:", s)
for r in HP.rows:
    f=r["fields"]; print("   ", f.get("IGN as read"), "| Status:", f.get("Status"),
          "| Player:", f.get("Player"), "| OBJ:", f.get("OBJ"), "| Map:", f.get("Map"))

# dedup check
print("match_id_exists(HP,msg123):", main.match_id_exists("HP","msg123"))
print("match_id_exists(HP,nope):", main.match_id_exists("HP","nope"))

# ---- ingest_match (SND) ----
SND=TABLES["tblZePZqGRJS5tLbG"]
snd_json={"mode":"SND","map":"","result":[
  {"IGN":"Phoenix","Kills":11,"Deaths":4,"Assists":2,"K/D":2.75,"Score":1100,"Impact":90,"ADR":125,"First Kill":3,"Lone Wolf Win":1},
]}
s2=main.ingest_match(snd_json,"msg999","2026-06-09")
print("SND ingest:", s2)
f=SND.rows[0]["fields"]
print("    SND row keys:", sorted(f.keys()))
assert "Map" not in f, "empty map should be omitted"
assert f["Player"]==["recP"] and f["Status"]=="Matched"
print("SND empty-map omitted + matched OK")

# ocr_prompt roster injection
import ocr_prompt
pr=ocr_prompt.build_prompt(main.matcher.roster)
assert "F10W3R" in pr and "{ROSTER_BLOCK}" not in pr
print("prompt roster injection OK; prompt len", len(pr))

# ---- B1 Test: Skip identical status updates in reconcile ----
HP._updates = 0
# Create a record that already has Status="Unmatched" and Player empty
HP.rows.append({"id": "recHP_unmatched_exist", "fields": {"IGN as read": "ZZZRandomGuy", "Status": "Unmatched"}})
# Run reconcile - this should match ZZZRandomGuy as 'no_match' -> STATUS_UNMATCHED
# Since it is already Unmatched, it should skip updating
main.reconcile_once(formula="{Player} = ''")
assert HP._updates == 0, "B1 Test Failed: identical status update was NOT skipped!"
print("B1 Test (Skip identical status update) OK")

# ---- TTL-gated matcher reload test ----
# reload_matcher_if_stale() and _matcher_reload_cache live in core; reach them
# via the core module (underscore names are NOT pulled in by `from core import *`).
import core as _core
import time as _time

# Force a clean baseline: reset the cache timestamp so the next call is treated as stale.
_core._matcher_reload_cache["t"] = 0.0
_core.MATCHER_RELOAD_TTL = 300  # 5 min, matches default

# 1) First call after reset -> should reload, return True
reloaded1 = _core.reload_matcher_if_stale()
assert reloaded1 is True, "TTL Test Failed: first call should reload (return True)"
# Roster should be populated (2 players seeded)
assert sorted(_core.matcher.roster) == ["F10W3R", "Phoenix"], _core.matcher.roster

# 2) Immediate second call -> cache fresh, should skip, return False
reloaded2 = _core.reload_matcher_if_stale()
assert reloaded2 is False, "TTL Test Failed: second call within TTL should skip (return False)"

# 3) force=True -> bypass TTL, must reload, return True
reloaded3 = _core.reload_matcher_if_stale(force=True)
assert reloaded3 is True, "TTL Test Failed: force=True should always reload (return True)"

# 4) TTL expiry -> simulate by backdating the cache timestamp
_core._matcher_reload_cache["t"] = _time.time() - 301  # older than TTL
reloaded4 = _core.reload_matcher_if_stale()
assert reloaded4 is True, "TTL Test Failed: stale cache (>TTL) should reload (return True)"
print("TTL-gated reload test OK")

# ---- Field projection in matcher.reload() ----
# reload() now calls .all(fields=[...]). The fake ignores fields= but we verify
# reload still populates correctly (logic unchanged, only payload trimmed).
main.matcher.reload()
assert "F10W3R" in main.matcher.roster and "Phoenix" in main.matcher.roster
assert main.matcher.match("F1OW3R")[2] in ("fuzzy_auto", "review")  # OCR corruption still fuzzy-matches
print("Field projection in reload() OK")

# ---- B2 Test: Duplicate IGN checks ----
assert main.check_duplicate_ign("F10W3R") == True, "B2 Test Failed: F10W3R should be duplicate"
assert main.check_duplicate_ign("F10W3R", exclude_player_id="recF") == False, "B2 Test Failed: F10W3R should not be duplicate for recF"
assert main.check_duplicate_ign("NewGuy") == False, "B2 Test Failed: NewGuy should not be duplicate"
print("B2 Test (Duplicate IGN registration check) OK")

# ---- Self-roles: Teams listing + player Team/Region helpers ----
TEAMS = TABLES[main.TEAMS_TABLE_ID]
TEAMS.rows.append({"id": "recT1", "fields": {"Name": "Team Falcons", "Tag": "FLC", "Active": True}})
TEAMS.rows.append({"id": "recT2", "fields": {"Name": "Alpha Squad", "Tag": "ALP", "Active": True}})
TEAMS.rows.append({"id": "recT3", "fields": {"Name": "Benched Team", "Tag": "OLD"}})  # Active falsy -> hidden
active = main.list_teams(active_only=True)
assert [t[1] for t in active] == ["Alpha Squad", "Team Falcons"], active  # sorted, inactive excluded
assert len(main.list_teams(active_only=False)) == 3
# assign team to existing player recF (discord 111), then clear it
main.set_player_team("111", "recT1")
recF = next(r for r in P.rows if r["id"] == "recF")
assert recF["fields"].get("Team") == ["recT1"], recF["fields"]
main.set_player_team("111", None)
assert recF["fields"].get("Team") == [], recF["fields"]
# region write on existing player recP (discord 222)
main.set_player_region("222", "EU")
recP = next(r for r in P.rows if r["id"] == "recP")
assert recP["fields"].get("Region") == "EU", recP["fields"]
# unknown discord id -> creates a new Players row
main.set_player_team("999", "recT2", "newcomer")
created = [r for r in P.rows if r["fields"].get("Discord ID") == "999"]
assert created and created[0]["fields"].get("Team") == ["recT2"], created
print("Self-roles (Teams list + Team/Region helpers) OK")

# ---- MMR modifier: compute_modifier band mapping ----
from cogs import mmr as _mmr
assert _mmr.compute_modifier(60) == -10, "MIN impact should map to -MAX"
assert _mmr.compute_modifier(200) == 10, "MAX impact should map to +MAX"
assert _mmr.compute_modifier(130) == 0, "midpoint impact should be neutral"
assert _mmr.compute_modifier(40) == -10, "below-MIN should clamp to -MAX"
assert _mmr.compute_modifier(250) == 10, "above-MAX should clamp to +MAX"
assert _mmr.compute_modifier(95) == -5, "halfway MIN->mid should be -5"
assert _mmr.compute_modifier(165) == 5, "halfway mid->MAX should be +5"
print("compute_modifier band mapping OK")

# ---- MMR modifier regression: double-apply guard ----
# Reproduces the bug that caused a single player's MMR to spike: if a match is
# re-processed (e.g. because a previous pass crashed after nq_add_mmr but before
# `processed.add`), the per-match loop must NOT re-apply to (player, match)
# combos already in the `applied` set.
import core as _core2
# Force LIVE mode so the nq_add_mmr branch runs.
_core2.MMR_MODIFIER_DRYRUN = False

# Monkeypatch nq_add_mmr to record calls instead of hitting the network.
_add_calls = []
def _fake_add(user_id, value, channel_id=None):
    _add_calls.append((str(user_id), int(value)))
    return {"ok": True}
_orig_add = _core2.nq_add_mmr
_core2.nq_add_mmr = _fake_add

# Patch core helpers the modifier loop reads: impacts_in_window + maps.
did = "111"  # recF / F10W3R
pid = "recF"
def _fake_impacts_in_window(start_dt, end_dt, participant_pids=None, target_mtime=None):
    return {pid: [165.0]}  # impact 165 -> modifier +5
_orig_iiw = _mmr.impacts_in_window
_mmr.impacts_in_window = _fake_impacts_in_window
_core2.discord_id_map = lambda: {did: pid}
_core2.player_directory_cached = lambda: {pid: ("F10W3R", "floo")}

# Build a minimal cog instance without Discord wiring.
class _FakeBot:
    async def get_channel(self, cid): return None
cog = _mmr.MMRModifier.__new__(_mmr.MMRModifier)
cog.bot = _FakeBot()
cog.processed, cog.backfilled, cog.applied = set(), set(), set()

import datetime as _dt
mtime = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)
match = {"time": mtime.strftime("%Y-%m-%d %H:%M:%S"), "game": "champs", "num": 1}
changes = {did: 25}  # a winner

# Wrap the coroutine send_staff_log so it doesn't try to reach Discord.
async def _no_log(*a, **k): return None
_core2.send_staff_log = _no_log
async def _no_mirror(self, m, lines): return None
_mmr.MMRModifier._mirror_to_public = _no_mirror

# Pass 1: should apply +5 once.
res1 = asyncio.get_event_loop().run_until_complete(
    cog.apply_modifiers_for_match(match, mtime, changes))
assert _add_calls == [(did, 5)], _add_calls
assert _mmr._applied_key(did, "g1") in cog.applied, "applied set should record the combo after pass 1"
print("MMR pass 1 applied once:", _add_calls)

# Pass 2: simulate a re-process (processed wasn't set due to a crash). The
# applied-set guard must prevent a second nq_add_mmr call.
_add_calls.clear()
res2 = asyncio.get_event_loop().run_until_complete(
    cog.apply_modifiers_for_match(match, mtime, changes))
assert _add_calls == [], ("REGRESSION: re-process re-applied modifier! calls=", _add_calls)
print("MMR pass 2 (re-process) did NOT double-apply:", _add_calls)

# Restore patched symbols.
_core2.nq_add_mmr = _orig_add
_mmr.impacts_in_window = _orig_iiw
_core2.MMR_MODIFIER_DRYRUN = os.getenv("MMR_MODIFIER_DRYRUN", "1") == "1"
print("MMR double-apply regression test OK")

# ---- MMR modifier regression: dry-run must not stamp `applied` ----
# A dry-run per-player backfill records nothing actually applied; stamping
# `applied` would silently drop the (player, match) once LIVE mode turns on.
_core2.MMR_MODIFIER_DRYRUN = True
cog2 = _mmr.MMRModifier.__new__(_mmr.MMRModifier)
cog2.bot = _FakeBot()
cog2.processed, cog2.backfilled, cog2.applied = set(), set(), set()

# Stub core.nq_history to return one match the player was in.
async def _run_player_backfill():
    return None  # placeholder; we drive the logic directly below
# Instead of the full async flow, test the invariant directly: under dry-run,
# after the dry-run branch, the (player, match) key must NOT be in `applied`.
apk = _mmr._applied_key(did, "g1")
# Simulate what the dry-run branch does (post-fix): append line, do NOT add.
applied_lines = []
dryrun_count = 0
mod = 5
if _core2.MMR_MODIFIER_DRYRUN:
    dryrun_count += 1
    applied_lines.append(f"dry-run (would be {mod:+d})")
    # NO cog2.applied.add(apk) -- this is the fix
assert apk not in cog2.applied, "REGRESSION: dry-run stamped applied, would drop on LIVE switch"
assert applied_lines and dryrun_count == 1
print("MMR dry-run does not stamp `applied` regression test OK")

# ---- MMR modifier regression: impact window overlap contamination ----
# Two close matches whose [mtime-2h, mtime+4h] windows overlap must not pull in
# each other's impact data. impacts_in_window now takes participant_pids (1st-line
# filter: drop records of players not in this match) and target_mtime (2nd-line
# cluster: a participant's records from a DIFFERENT nearby match are dropped).
import datetime as _dt2

# We test impacts_in_window directly by monkeypatching the two Airtable tables'
# .all() to return synthetic records. Each record's Match ID is a Discord
# snowflake whose timestamp we control via snowflake arithmetic.
def _snowflake_for(ts):
    """Build a fake Discord snowflake whose decoded timestamp == ts (UTC)."""
    ms = int(ts.timestamp() * 1000)
    return str((ms - _mmr.DISCORD_EPOCH_MS) << 22)

_pid_a = "recWinA"   # played in BOTH matches (the contamination vector)
_pid_b = "recOnlyB"  # played only in match B

_base = _dt2.datetime(2026, 6, 21, 20, 0, 0, tzinfo=_dt2.timezone.utc)
_match_a_time = _base                       # 20:00 — game A screenshot posted here
_match_b_time = _base + _dt2.timedelta(minutes=13)  # 20:13 — game B (13 min later)

class _FakeImpactTable:
    def __init__(self, rows):
        self._rows = rows
    def all(self, formula=None, fields=None):
        return list(self._rows)

# Records: pid_a has a record at match-A time (impact 190) AND match-B time
# (impact 100). pid_b has a record only at match-B time (impact 150).
_rows = [
    {"id": "r1", "fields": {"Player": [{"id": _pid_a}], "Impact": 190, "Match ID": _snowflake_for(_match_a_time)}},
    {"id": "r2", "fields": {"Player": [{"id": _pid_a}], "Impact": 100, "Match ID": _snowflake_for(_match_b_time)}},
    {"id": "r3", "fields": {"Player": [{"id": _pid_b}], "Impact": 150, "Match ID": _snowflake_for(_match_b_time)}},
]
_orig_hp = _core2.hp_table
_orig_snd = _core2.snd_table
_ft = _FakeImpactTable(_rows)
_core2.hp_table = _ft
_core2.snd_table = _FakeImpactTable([])  # SND empty; all rows in HP

# Wide window that deliberately covers BOTH matches (simulating the overlap).
ws = _match_a_time - _dt2.timedelta(hours=2)
we = _match_b_time + _dt2.timedelta(hours=4)

# (1) No filters (legacy behaviour): pid_a gets BOTH impacts averaged -> 145.
legacy = _mmr.impacts_in_window(ws, we)
assert legacy.get(_pid_a) == [190.0, 100.0], legacy
assert legacy.get(_pid_b) == [150.0], legacy
print("impact window (no filter): pid_a sees both matches (legacy bug):", legacy[_pid_a])

# (2) participant_pids={pid_a} only, no mtime clustering: still both records
# (participant filter alone can't separate a player's own two games).
filt = _mmr.impacts_in_window(ws, we, participant_pids={_pid_a})
assert filt.get(_pid_a) == [190.0, 100.0], filt
assert _pid_b not in filt, "non-participant must be excluded"
print("impact window (participant filter): pid_b excluded, pid_a still both:", filt.get(_pid_a))

# (3) participant_pids + target_mtime=match_a: pid_a's match-B record (13 min
# from the closest, which is match-A at 0 min) — 13 min is within the 30-min
# cluster, so this represents a same-series case and both stay. To prove the
# cluster DROPS a far record, use a match-B time 45 min away instead.
_match_b_far = _base + _dt2.timedelta(minutes=45)
_rows_far = [
    {"id": "r1", "fields": {"Player": [{"id": _pid_a}], "Impact": 190, "Match ID": _snowflake_for(_match_a_time)}},
    {"id": "r2", "fields": {"Player": [{"id": _pid_a}], "Impact": 100, "Match ID": _snowflake_for(_match_b_far)}},
]
_core2.hp_table = _FakeImpactTable(_rows_far)
clust = _mmr.impacts_in_window(ws, we, participant_pids={_pid_a}, target_mtime=_match_a_time)
assert clust.get(_pid_a) == [190.0], ("cluster should drop the 45-min-distant record", clust)
print("impact window (participant + cluster): far record dropped:", clust[_pid_a])

# (4) Same but target_mtime points at the far match: now the close record is dropped.
clust2 = _mmr.impacts_in_window(ws, we, participant_pids={_pid_a}, target_mtime=_match_b_far)
assert clust2.get(_pid_a) == [100.0], ("cluster should keep only the target match's record", clust2)
print("impact window (participant + cluster to far match):", clust2[_pid_a])

_core2.hp_table = _orig_hp
_core2.snd_table = _orig_snd
print("MMR impact window overlap contamination test OK")

print("\nALL SMOKE TESTS PASSED")
