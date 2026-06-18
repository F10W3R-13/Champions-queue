"""Phase 7-1 round 3: discover player-field name + stat keys (uses value=0 no-op only).
Run:  python _neatqueue_api_test.py   then paste the output.
"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("NEATQUEUE_TOKEN")
SERVER = "1512319088146255982"
B = "https://api.neatqueue.com"
H = {"Authorization": TOKEN, "Content-Type": "application/json"}
TEST_PLAYER = "358618874528399360"  # F10W3R

# 1. queue channels -> channel_id to use
r = requests.get(f"{B}/api/v1/queuechannels/{SERVER}", headers=H, timeout=15)
print("=== 1. queuechannels:", r.status_code)
print(r.text[:500])
try:
    data = r.json()
    chans = data if isinstance(data, list) else data.get("channels") or list(data)
    CH = str(chans[0]) if isinstance(chans[0], (str, int)) else str(chans[0].get("channel_id") or chans[0].get("id"))
except Exception as e:
    print("could not parse channel id:", e)
    CH = input("enter queue channel id manually: ").strip()
print("using channel_id:", CH)
print()

# 2. single player stats -> see stat key names (mmr? rating? wins?)
r = requests.get(f"{B}/api/v1/playerstats/{SERVER}/{TEST_PLAYER}", headers=H, timeout=15)
print("=== 2. playerstats single:", r.status_code)
print(r.text[:1200])
print()

# 3. add/stats with no player field -> app should tell us what's missing
body = {"channel_id": int(CH), "stat": "mmr", "value": 0}
r = requests.post(f"{B}/api/v2/add/stats", headers=H, json=body, timeout=15)
print("=== 3. add/stats without player:", r.status_code)
print(r.text[:400])
print()

# 4. try candidate player-field names with a 0-value no-op
for key in ["user_id", "player_id", "player", "user", "member"]:
    body = {"channel_id": int(CH), "stat": "mmr", "value": 0, key: int(TEST_PLAYER)}
    r = requests.post(f"{B}/api/v2/add/stats", headers=H, json=body, timeout=15)
    print(f"=== 4. add/stats with '{key}':", r.status_code, r.text[:250].replace(chr(10), " "))

print("\nDONE - paste everything above back to Claude.")
