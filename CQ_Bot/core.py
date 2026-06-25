import os
import re
import json
import time
import asyncio
import logging
from dotenv import load_dotenv
from pyairtable import Api
from urllib3.util.retry import Retry
from openai import AsyncOpenAI

from matcher import Matcher, normalize
from ocr_prompt import build_prompt

# 1. Logging Setup
logger = logging.getLogger("CQ_Bot.core")


def is_staff(interaction):
    """Check if a user is staff or admin. Shared by all cogs (was copy-pasted 7×)."""
    if interaction.user.guild_permissions.administrator:
        return True
    roles = [r.name.lower() for r in interaction.user.roles]
    return any("staff" in r or "admin" in r for r in roles)


# 2. Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
AIRTABLE_API_KEY = os.getenv('AIRTABLE_API_KEY')
BASE_ID = os.getenv('AIRTABLE_BASE_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
RESULTS_CHANNEL_ID = int(os.getenv('RESULTS_CHANNEL_ID', '1512331781758652546'))
STAFF_LOGS_CHANNEL_ID = int(os.getenv('STAFF_LOGS_CHANNEL_ID', '1512332329735950386'))
LEADERBOARD_MIN_GAMES = int(os.getenv('LEADERBOARD_MIN_GAMES', '5'))
REGISTERED_ROLE_ID = int(os.getenv('REGISTERED_ROLE_ID', '0'))  # role granted on /ign; required by NeatQueue to join queue

# --- Season settings ---
CURRENT_SEASON = os.getenv('CURRENT_SEASON', 'S1')
SEASON_START = os.getenv('SEASON_START', '')  # ISO date, e.g. 2026-06-13
SEASON_END = os.getenv('SEASON_END', '')      # ISO date, e.g. 2026-08-09
PLACEMENT_GAMES = int(os.getenv('PLACEMENT_GAMES', '5'))
SEASON_CACHE_TTL = int(os.getenv('SEASON_CACHE_TTL', '600'))  # seconds; season aggregation cache
VERIFIED_ROLE_NAME = os.getenv('VERIFIED_ROLE_NAME', 'Verified Player')
WEEKLY_LEADERBOARD_CHANNEL_ID = int(os.getenv('WEEKLY_LEADERBOARD_CHANNEL_ID', '0'))  # 0 = staff logs channel
# Public channel to mirror MMR modifier summaries (player-facing). 0 = disabled.
# Staff-logs still receives the full detailed report; this channel gets a compact
# "who got what" summary so players can see the impact-based adjustments.
MMR_PUBLIC_CHANNEL_ID = int(os.getenv('MMR_PUBLIC_CHANNEL_ID', '0'))

# --- NeatQueue API (Impact-based MMR modifier) ---
NEATQUEUE_TOKEN = os.getenv('NEATQUEUE_TOKEN', '')
NEATQUEUE_BASE = "https://api.neatqueue.com"
GUILD_ID = os.getenv('GUILD_ID', '1512319088146255982')
NEATQUEUE_QUEUE_CHANNEL_ID = int(os.getenv('NEATQUEUE_QUEUE_CHANNEL_ID', '1512331710736633906'))
MMR_MODIFIER_MAX = float(os.getenv('MMR_MODIFIER_MAX', '10'))    # +/- max performance modifier
# Absolute Impact-score band: impact MMR_IMPACT_MIN -> -MAX, MMR_IMPACT_MAX -> +MAX, linear in between
# (neutral = midpoint). Replaces the old lobby-relative MMR_IMPACT_SCALE model.
MMR_IMPACT_MIN = float(os.getenv('MMR_IMPACT_MIN', '60'))
MMR_IMPACT_MAX = float(os.getenv('MMR_IMPACT_MAX', '200'))
MMR_MODIFIER_DRYRUN = os.getenv('MMR_MODIFIER_DRYRUN', '1') == '1'  # 1 = report only, don't apply

# --- Self-roles panel (region / weapon group / championship team) ---
# Discord role granted when a player picks a championship team (also gates the Champs-only queue).
# ID takes priority over name (avoids creating a duplicate role); name is the fallback.
CHAMPS_ROLE_ID = int(os.getenv('CHAMPS_ROLE_ID', '1515951370987896852'))
CHAMPS_ROLE_NAME = os.getenv('CHAMPS_ROLE_NAME', 'Champs')
# --- Registration help (cogs/registration.py) ---
# Channel that hosts the persistent "how to register" guide panel (#ign). The
# auto-helper also replies here (or in the queue channels) when NeatQueue rejects
# a player for lacking the Registered role. 0 = feature disabled.
IGN_HELP_CHANNEL_ID = int(os.getenv('IGN_HELP_CHANNEL_ID', '0'))
# NeatQueue's bot user id — used by the auto-helper to recognize NeatQueue's
# "not registered" rejection messages. 0 = fall back to name matching.
NEATQUEUE_BOT_ID = int(os.getenv('NEATQUEUE_BOT_ID', '0'))
# 1 = bot auto-creates any missing region/weapon/champs role on first use.
SELFROLES_AUTO_CREATE = os.getenv('SELFROLES_AUTO_CREATE', '1') == '1'
# Region options for the single-select menu. Labels MUST match the Airtable Players.Region
# singleSelect choices so the panel can also write the Region field. value = Discord role name.
REGION_ROLE_NAMES = {
    "NA/LATAM": "NA/LATAM",
    "EU": "EU",
    "APAC": "APAC",
    "MENA": "MENA",
}
# Weapon-group options for the multi-select menu (label -> Discord role name). Pure Discord roles.
WEAPON_ROLE_NAMES = {
    "AR": "AR",
    "SMG": "SMG",
    "Sniper": "Sniper",
    "LMG": "LMG",
    "Shotgun": "Shotgun",
    "Marksman": "Marksman",
}

# --- Queue reminder (cogs/queue.py) ---
# Discord role to ping on T-30min / T-0 LIVE reminders. Created by setup scripts
# ("Queue Ping"); ID resolved from .env.
QUEUE_PING_ROLE_ID = int(os.getenv('QUEUE_PING_ROLE_ID', '0'))
# Channel where players actually JOIN the queue (NeatQueue's interactive panel).
# Verified queue channels via GET /api/v1/queuechannels: "queue" and "queue-2026champs".
# Default = queue-2026champs (pilot channel). Set QUEUE_JOIN_CHANNEL_ID to override.
QUEUE_JOIN_CHANNEL_ID = int(os.getenv('QUEUE_JOIN_CHANNEL_ID', '1514827048885948516'))
# Channel where the bot posts reminder messages. Recommended: #announcements.
# 0 = fall back to QUEUE_JOIN_CHANNEL_ID.
QUEUE_REMINDER_CHANNEL_ID = int(os.getenv('QUEUE_REMINDER_CHANNEL_ID', '0'))
# On-disk persistence for RSVP rosters + dedup keys (restart-safe). Same dir as mmr_state.json.
QUEUE_STATE_FILE = os.getenv('QUEUE_STATE_FILE', 'queue_state.json')
# 1 = enable the scheduled reminder loop. Set 0 to disable without uninstalling the cog.
QUEUE_REMINDER_ENABLED = os.getenv('QUEUE_REMINDER_ENABLED', '1') == '1'

# --- Airtable Table IDs ---
PLAYERS_TABLE_ID = 'tbl2sN1bXNlpcUBhV'
HP_TABLE_ID = 'tblDp5p1XTzdeFmWm'
SND_TABLE_ID = 'tblZePZqGRJS5tLbG'
ALIASES_TABLE_ID = 'tblHd3q0MNm1186hH'
TEAMS_TABLE_ID = 'tblnTq4qEFuMzZt7i'

# --- Airtable Field Names ---
RAW_IGN_FIELD = 'IGN as read'
LINKED_PLAYER_FIELD = 'Player'

# 3. Connect Airtable API
# Timeout = (connect, read) in seconds. Default is unlimited, which can hang
# the reconcile loop indefinitely on a stalled network. Retry explicitly covers
# 429 (rate limit) and 5xx with exponential backoff (pyairtable 3.x uses urllib3 Retry).
_airtable_retry = Retry(
    total=5,
    status_forcelist=(429, 500, 502, 503, 504),
    backoff_factor=0.5,        # 0, 0.5, 1, 2, 4, 8 seconds between retries
    respect_retry_after_header=True,
    allowed_methods=frozenset(["GET", "POST", "PATCH", "PUT", "DELETE"]),
)
airtable_api = Api(AIRTABLE_API_KEY, timeout=(5, 30), retry_strategy=_airtable_retry)
players_table = airtable_api.table(BASE_ID, PLAYERS_TABLE_ID)
hp_table = airtable_api.table(BASE_ID, HP_TABLE_ID)
snd_table = airtable_api.table(BASE_ID, SND_TABLE_ID)
aliases_table = airtable_api.table(BASE_ID, ALIASES_TABLE_ID)
teams_table = airtable_api.table(BASE_ID, TEAMS_TABLE_ID)

# OpenAI (vision OCR)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
OCR_MODEL = os.getenv('OCR_MODEL', 'gpt-4.1')

# --- Status option values (must match the base) ---
STATUS_MATCHED = "Matched"
STATUS_REVIEW = "Needs Review"
STATUS_UNMATCHED = "Unmatched"

RECORD_TABLES = [
    ("HP", hp_table, RAW_IGN_FIELD),
    ("SND", snd_table, RAW_IGN_FIELD),
]

# Periodic reconcile formula: only unprocessed records (no Player, no Status)
PERIODIC_UNMATCHED_FORMULA = "AND({Player} = '', {Status} = '')"

# --- Matcher reload TTL ---
# The reconcile loop runs every 45s but reloads the matcher (full Players+Aliases
# scan) only when the cache is older than this. Bot-driven mutations (/ign, /link,
# OCR auto-learn) refresh the cache eagerly and bypass this TTL via force=True.
# Only "operator edited Airtable directly in the UI" waits up to this TTL.
MATCHER_RELOAD_TTL = int(os.getenv('MATCHER_RELOAD_TTL', '300'))  # 5 minutes

# Serialize Airtable write sections
airtable_lock = asyncio.Lock()

# Initialize Matcher
matcher = Matcher(players_table, aliases_table)

# Last time matcher.reload() ran (monotonic-ish: wall clock is fine for a TTL gate).
_matcher_reload_cache = {"t": 0.0}


def reload_matcher_if_stale(force=False):
    """TTL-gated matcher.reload(). MUST be called inside core.airtable_lock
    (reload mutates matcher.roster/candidates in place; keeping it under the
    lock serializes it against ingest's matcher.match() and run_ocr's roster read).

    Returns True if a reload actually ran, False if it was skipped (cache fresh).

    force=True bypasses the TTL - use at eager-refresh sites (/ign, /changeign,
    /link) where a mutation just happened and the cache MUST reflect it now.
    """
    now = time.time()
    if not force and _matcher_reload_cache["t"] and now - _matcher_reload_cache["t"] < MATCHER_RELOAD_TTL:
        return False  # cache still fresh
    matcher.reload()
    _matcher_reload_cache["t"] = now
    return True


def get_val(fields, key, default="-"):
    val = fields.get(key, default)
    if isinstance(val, list) and len(val) > 0:
        return val[0]
    return val


def _learn_alias(raw_ign, player_id):
    """self-learning: store a fuzzy-confirmed variant so next time stage-1 catches it."""
    n = normalize(raw_ign)
    if not n or n in matcher.exact:
        return
    try:
        aliases_table.create(
            {"IGN": raw_ign, "Player": [player_id], "Source": "OCR Auto"},
            typecast=True,
        )
        matcher.add_learned(n, player_id)
        logger.info("Learned alias: %s -> player %s", raw_ign, player_id)
    except Exception as e:
        logger.error("Failed to learn alias %s: %s", raw_ign, e, exc_info=True)


def check_duplicate_ign(ign_name, exclude_player_id=None):
    """Check if the normalized IGN already exists in the system (Primary or Alias) for another player."""
    n = normalize(ign_name)
    if not n:
        return False
    if n in matcher.exact:
        owner_id = matcher.exact[n]
        if exclude_player_id and owner_id == exclude_player_id:
            return False
        return True
    return False


def reconcile_once(formula=None):
    """Scan unmatched-only records and correct. (sync - call via to_thread)"""
    # Default to periodic unmatched formula if none is provided
    if formula is None:
        formula = PERIODIC_UNMATCHED_FORMULA

    stats = {"matched": 0, "review": 0, "unmatched": 0}
    for _mode, table, ign_field in RECORD_TABLES:
        # Field projection: reconcile reads only Player, Status, and IGN as read.
        # HP/SND records also carry ~10-14 stat fields (Kills/Deaths/Score/Impact/...)
        # that reconcile never touches - projecting them out trims the payload heavily.
        for rec in table.all(formula=formula, fields=[LINKED_PLAYER_FIELD, "Status", ign_field]):
            f = rec["fields"]
            if f.get(LINKED_PLAYER_FIELD):
                continue
            raw = f.get(ign_field)
            if not raw:
                continue
            pid, score, method = matcher.match(raw)
            
            # Determine target status and fields to update
            if method in ("exact", "fuzzy_auto"):
                new_status = STATUS_MATCHED
                update_fields = {LINKED_PLAYER_FIELD: [pid], "Status": STATUS_MATCHED}
            elif method == "review":
                new_status = STATUS_REVIEW
                update_fields = {"Status": STATUS_REVIEW}
            else:
                new_status = STATUS_UNMATCHED
                update_fields = {"Status": STATUS_UNMATCHED}

            # Skip updating if the Status in Airtable is already the same
            if f.get("Status") == new_status:
                continue

            table.update(rec["id"], update_fields, typecast=True)
            if method == "fuzzy_auto":
                _learn_alias(raw, pid)
                
            if method in ("exact", "fuzzy_auto"):
                stats["matched"] += 1
            elif method == "review":
                stats["review"] += 1
            else:
                stats["unmatched"] += 1
    return stats


def relink_records(ign_name, player_record_id):
    """Refresh cache + one reconcile pass over all unlinked records. (sync)"""
    matcher.reload()
    # When relinking due to player registration/change, scan ALL unlinked records
    return reconcile_once(formula="{Player} = ''")["matched"]


def matcher_alias_exists(ign_name):
    n = normalize(ign_name)
    return bool(n) and n in matcher.exact


def _extract_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


async def run_ocr(url1, url2):
    """Two scoreboards -> merged JSON via OpenAI vision. (async, non-blocking)"""
    prompt = build_prompt(matcher.roster)
    resp = await openai_client.chat.completions.create(
        model=OCR_MODEL,
        temperature=0,
        top_p=0,
        max_tokens=2048,
        response_format={"type": "json_object"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": url1, "detail": "auto"}},
                {"type": "image_url", "image_url": {"url": url2, "detail": "auto"}},
            ],
        }],
    )
    return _extract_json(resp.choices[0].message.content)


def _to_num(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def _clean(d):
    return {k: v for k, v in d.items() if v not in (None, "")}


def match_id_exists(mode, match_id):
    """Check if this Match ID was already ingested (dedup vs Make / reprocessing)."""
    table = snd_table if str(mode).upper() == "SND" else hp_table
    return bool(table.all(formula="{Match ID} = '%s'" % match_id, max_records=1))


def _build_hp_fields(p, mp, match_id, date_str):
    return _clean({
        RAW_IGN_FIELD: p.get("IGN"),
        "Kills": _to_num(p.get("Kills")),
        "Deaths": _to_num(p.get("Deaths")),
        "K/D": _to_num(p.get("K/D")),
        "OBJ": _to_num(p.get("time_seconds")),
        "Score": _to_num(p.get("Score")),
        "Impact": _to_num(p.get("Impact")),
        "Total Damage": _to_num(p.get("Total Damage")),
        "Capture Kill": _to_num(p.get("Capture Kill")),
        "Date": date_str,
        "Map": (mp or None),
        "Match ID": match_id,
        "Season": CURRENT_SEASON,
    })


def _build_snd_fields(p, mp, match_id, date_str):
    return _clean({
        RAW_IGN_FIELD: p.get("IGN"),
        "Kills": _to_num(p.get("Kills")),
        "Deaths": _to_num(p.get("Deaths")),
        "Assists": _to_num(p.get("Assists")),
        "K/D": _to_num(p.get("K/D")),
        "Score": _to_num(p.get("Score")),
        "Impact": _to_num(p.get("Impact")),
        "ADR": _to_num(p.get("ADR")),
        "First Kill": _to_num(p.get("First Kill")),
        "Lone Wolf Win": _to_num(p.get("Lone Wolf Win")),
        "Date": date_str,
        "Map": (mp or None),
        "Match ID": match_id,
        "Season": CURRENT_SEASON,
    })


def ingest_match(data, match_id, date_str):
    """Ingest parsed match JSON + inline matching. (sync - call via to_thread)"""
    mode = str(data.get("mode", "")).upper()
    mp = (data.get("map") or "").strip()
    table = snd_table if mode == "SND" else hp_table
    build = _build_snd_fields if mode == "SND" else _build_hp_fields
    stats = {"created": 0, "matched": 0, "review": 0, "unmatched": 0}
    
    records_to_create = []
    fuzzy_autos = []
    
    for p in data.get("result", []):
        ign = (p.get("IGN") or "").strip()
        if not ign:
            continue
        fields = build(p, mp, match_id, date_str)
        pid, score, method = matcher.match(ign)
        if method in ("exact", "fuzzy_auto"):
            fields[LINKED_PLAYER_FIELD] = [pid]
            fields["Status"] = STATUS_MATCHED
            stats["matched"] += 1
        elif method == "review":
            fields["Status"] = STATUS_REVIEW
            stats["review"] += 1
        else:
            fields["Status"] = STATUS_UNMATCHED
            stats["unmatched"] += 1
            
        records_to_create.append(fields)
        if method == "fuzzy_auto":
            fuzzy_autos.append((ign, pid))
        stats["created"] += 1

    # Batch create player records to minimize API calls
    if records_to_create:
        created_records = table.batch_create(records_to_create, typecast=True)
        stats["records"] = created_records
    else:
        stats["records"] = []

    # Learn fuzzy aliases after ingestion batch completes
    for ign, pid in fuzzy_autos:
        _learn_alias(ign, pid)
        
    return stats


# ===== Season aggregation (computed from raw match records, not career rollups) =====
HP_SEASON_METRICS = ["Impact", "Total Damage", "Capture Kill", "OBJ", "Score"]
SND_SEASON_METRICS = ["Impact", "ADR", "First Kill", "Lone Wolf Win", "Score"]


def season_player_stats(mode, season=None):
    """Aggregate per-player stats for one mode within a season.
    Returns {player_id: {"games", "kd", <metric avgs>}}. (sync - call via to_thread)"""
    season = (season or CURRENT_SEASON).replace("'", "")
    mode = str(mode).upper()
    table = snd_table if mode == "SND" else hp_table
    metric_fields = SND_SEASON_METRICS if mode == "SND" else HP_SEASON_METRICS

    agg = {}
    if season.upper() in ("__ALL__", "CAREER", "ALL"):
        formula = "{Player} != ''"
    else:
        formula = "AND({Season} = '%s', {Player} != '')" % season
    for rec in table.all(formula=formula):
        f = rec["fields"]
        players = f.get(LINKED_PLAYER_FIELD) or []
        if not players:
            continue
        pid = players[0]["id"] if isinstance(players[0], dict) else players[0]
        a = agg.setdefault(pid, {
            "games": 0, "kills": 0, "deaths": 0,
            "sums": {m: 0.0 for m in metric_fields},
            "counts": {m: 0 for m in metric_fields},
        })
        a["games"] += 1
        a["kills"] += f.get("Kills") or 0
        a["deaths"] += f.get("Deaths") or 0
        for m in metric_fields:
            v = f.get(m)
            if isinstance(v, (int, float)):
                a["sums"][m] += v
                a["counts"][m] += 1

    out = {}
    for pid, a in agg.items():
        g = a["games"]
        kills, deaths = a["kills"], a["deaths"]
        stats = {
            "games": g,
            "kd": round(kills / deaths, 2) if deaths else float(kills),
        }
        for m in metric_fields:
            stats[m] = round(a["sums"][m] / a["counts"][m], 2) if a["counts"][m] else 0.0

        # --- Advanced metrics (sum-based, computed in the same single pass: zero extra API calls) ---
        td_sum = a["sums"].get("Total Damage", 0.0)
        score_sum = a["sums"].get("Score", 0.0)
        # Assist % = (SUM(Score) - SUM(Kills)*100) / SUM(Score) * 100
        stats["AssistPct"] = round(((score_sum - kills * 100) / score_sum) * 100, 1) if score_sum else 0.0
        if mode == "HP":
            # Damage per Death / Damage per Kill
            stats["DPD"] = round(td_sum / deaths, 1) if deaths else 0.0
            stats["DPK"] = round(td_sum / kills, 1) if kills else 0.0
            # ZCS = max(0, 1.1*avg(OBJ) + 8*avg(CK) + 4.1*(avg(K)-avg(CK)) - 5*avg(D))
            avg_k = kills / g if g else 0.0
            avg_d = deaths / g if g else 0.0
            avg_ck = stats.get("Capture Kill", 0.0)
            avg_obj = stats.get("OBJ", 0.0)
            stats["ZCS"] = round(max(0.0, avg_obj * 1.1 + avg_ck * 8 + (avg_k - avg_ck) * 4.1 - avg_d * 5), 1)
        out[pid] = stats
    return out


# --- TTL caches: /stats, /leaderboard and the weekly post share one aggregation pass ---
_season_cache = {}
_directory_cache = {"t": 0.0, "d": None}


def season_player_stats_cached(mode, season=None):
    """TTL-cached wrapper around season_player_stats (low Airtable load). (sync)"""
    key = (str(mode).upper(), (season or CURRENT_SEASON))
    now = time.time()
    hit = _season_cache.get(key)
    if hit and now - hit[0] < SEASON_CACHE_TTL:
        return hit[1]
    data = season_player_stats(key[0], key[1])
    _season_cache[key] = (now, data)
    return data


def player_directory_cached():
    """TTL-cached player directory. (sync)"""
    now = time.time()
    if _directory_cache["d"] is not None and now - _directory_cache["t"] < SEASON_CACHE_TTL:
        return _directory_cache["d"]
    d = player_directory()
    _directory_cache.update(t=now, d=d)
    return d


def player_directory():
    """{player_id: (Primary IGN, Discord Handle)}. (sync - call via to_thread)"""
    d = {}
    for p in players_table.all():
        f = p["fields"]
        d[p["id"]] = (f.get("Primary IGN", "Unknown"), f.get("Discord Handle", ""))
    return d


# ===== NeatQueue API client (sync - call via to_thread) =====
import requests as _rq


def _nq_headers():
    # NeatQueue expects the RAW token in Authorization (no "Bearer" prefix)
    return {"Authorization": NEATQUEUE_TOKEN, "Content-Type": "application/json"}


def nq_history():
    """Completed match history (teams, discord ids, mmr_change). Returns list."""
    r = _rq.get(f"{NEATQUEUE_BASE}/api/v1/history/{GUILD_ID}", headers=_nq_headers(), timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("data", data) if isinstance(data, dict) else data


def nq_add_mmr(user_id, value, channel_id=None):
    """Increment (or decrement, negative) a player's MMR. Verified working in 7-1.

    NeatQueue's /api/v2/add/stats requires `value` to be an INTEGER (422 otherwise).
    We round half-to-even at the API boundary so callers can pass floats freely.
    """
    body = {
        "channel_id": int(channel_id or NEATQUEUE_QUEUE_CHANNEL_ID),
        "stat": "mmr",
        "value": int(round(float(value))),
        "user_id": int(user_id),
    }
    r = _rq.post(f"{NEATQUEUE_BASE}/api/v2/add/stats", headers=_nq_headers(), json=body, timeout=20)
    r.raise_for_status()
    return r.json()


def nq_lock(channel_id=None):
    """Lock the queue channel (prevent players from joining). Schema verified:
    POST /api/v2/lock with body {"channel_id": int}. The matching /unlock endpoint
    accepts the same single field."""
    body = {"channel_id": int(channel_id or NEATQUEUE_QUEUE_CHANNEL_ID)}
    r = _rq.post(f"{NEATQUEUE_BASE}/api/v2/lock", headers=_nq_headers(), json=body, timeout=20)
    r.raise_for_status()
    return r.json()


def nq_unlock(channel_id=None):
    """Unlock the queue channel (allow players to join). Schema verified:
    POST /api/v2/unlock requires only {"channel_id": int}."""
    body = {"channel_id": int(channel_id or NEATQUEUE_QUEUE_CHANNEL_ID)}
    r = _rq.post(f"{NEATQUEUE_BASE}/api/v2/unlock", headers=_nq_headers(), json=body, timeout=20)
    r.raise_for_status()
    return r.json()


def discord_id_map():
    """{discord_id(str): player_record_id} from the Players table. (sync)"""
    out = {}
    for p in players_table.all(fields=["Discord ID"]):
        did = p["fields"].get("Discord ID")
        if did:
            out[str(did)] = p["id"]
    return out


def list_teams(active_only=True):
    """[(record_id, name, tag, region), ...] from the Teams table, sorted by name. (sync - call via to_thread)"""
    out = []
    for rec in teams_table.all():
        f = rec["fields"]
        name = f.get("Name")
        if not name:
            continue
        if active_only and not f.get("Active"):
            continue
        out.append((rec["id"], name, (f.get("Tag") or "").strip(), (f.get("Region") or "").strip()))
    out.sort(key=lambda t: t[1].lower())
    return out


def player_record_by_discord(discord_id):
    """The Players record for a discord id, or None. (sync)"""
    recs = players_table.all(formula=f"{{Discord ID}} = '{discord_id}'", max_records=1)
    return recs[0] if recs else None


def set_player_team(discord_id, team_record_id, discord_handle=None):
    """Link a player's Team (single link, or clear with None). Creates the Players row if missing. (sync)"""
    rec = player_record_by_discord(discord_id)
    value = [team_record_id] if team_record_id else []
    if rec:
        players_table.update(rec["id"], {"Team": value})
        return rec["id"]
    fields = {"Discord ID": str(discord_id), "Team": value}
    if discord_handle:
        fields["Discord Handle"] = str(discord_handle)
    return players_table.create(fields)["id"]


def set_player_region(discord_id, region, discord_handle=None):
    """Set a player's Region singleSelect (typecast adds the choice if needed). Creates row if missing. (sync)"""
    rec = player_record_by_discord(discord_id)
    if rec:
        players_table.update(rec["id"], {"Region": region}, typecast=True)
        return rec["id"]
    fields = {"Discord ID": str(discord_id), "Region": region}
    if discord_handle:
        fields["Discord Handle"] = str(discord_handle)
    return players_table.create(fields, typecast=True)["id"]


async def send_staff_log(bot, content=None, embed=None):
    """Send log messages or alerts to the designated staff logs channel."""
    try:
        channel = bot.get_channel(STAFF_LOGS_CHANNEL_ID)
        if channel:
            await channel.send(content=content, embed=embed)
        else:
            logger.warning("Staff logs channel %d not found.", STAFF_LOGS_CHANNEL_ID)
    except Exception as e:
        logger.error("Failed to send staff log: %s", e)
