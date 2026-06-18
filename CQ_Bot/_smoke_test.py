import os, sys, types
os.environ.update(DISCORD_TOKEN="x", AIRTABLE_API_KEY="x", AIRTABLE_BASE_ID="app00000000000000",
                  OPENAI_API_KEY="x")

# ---- Fake Airtable layer ----
class FakeTable:
    def __init__(self, name):
        self.name = name
        self.rows = []
        self._c = 0
        self._updates = 0
    def all(self, formula=None, max_records=None):
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

print("\nALL SMOKE TESTS PASSED")
