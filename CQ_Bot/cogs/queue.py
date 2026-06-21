"""Queue reminder system (unified, single queue).

There is ONE shared queue (one NeatQueue channel, one lock bit). NA and EU are
not separate queues — they are two daily *opening windows* for the same queue:
  - NA window: opens 23:00 America/New_York (EST/EDT auto via zoneinfo) ≈ KST 12:00
  - EU window: opens 23:00 Europe/Berlin     (CET/CEST auto via zoneinfo) ≈ KST 06:00
Each window stays open ~3h. Anyone can play in either window. The queue is
UNLOCKED when either window opens and LOCKED again only when BOTH have closed.

Per window the bot auto-fires reminders from a tasks.loop(minutes=1):
  - T-2h    : heads-up, no ping
  - T-30min : Queue Ping role mentioned, RSVP count shown
  - T-0 LIVE: Queue Ping role mentioned, points players to the Join Queue button
              in QUEUE_JOIN_CHANNEL_ID (owned by NeatQueue, not this bot).

The reminder embed is a UNIFIED view: regardless of which window triggered it,
it always shows BOTH windows' times and the SINGLE shared RSVP roster. So a
player who joins via the NA-window reminder is counted in the EU-window panel too.

RSVP model: this bot tracks a *soft* RSVP roster (intent to play) on disk, keyed
by date only (no session dimension). It does NOT own queue joins — players still
join via NeatQueue's interactive panel. The count is shown as
"X reserved · Y to fill the next 10-player lobby", emphasizing the CoD 5v5 /
multiple-of-10 cliff (unlike F1's soft cap, ours is a hard step).

NeatQueue does NOT expose a "current queue size" read endpoint (verified Phase 0:
9 candidate GETs all 404), so RSVP is the sole count source. No external coupling.

Patterns reused:
  - tasks.loop + before_loop(wait_until_ready)            : cogs/season.py
  - on-disk JSON dedup/state (restart-safe)               : cogs/mmr.py
  - persistent View + footer-stashed state + edit-in-place: cogs/verify.py
  - is_staff()                                            : every cog
"""
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import core

logger = logging.getLogger("CQ_Bot.queue")

# --- Opening windows (wall-clock, DST-safe via zoneinfo named zones) ---
# Each window: open time in its own timezone. zoneinfo handles EST<->EDT, CET<->CEST.
# These are WINDOWS into one shared queue, not separate queues.
WINDOWS = [
    {"key": "na", "tz": ZoneInfo("America/New_York"), "hour": 23, "minute": 0, "label": "NA"},
    {"key": "eu", "tz": ZoneInfo("Europe/Berlin"), "hour": 23, "minute": 0, "label": "EU"},
]
# Each window stays open this long once opened. The queue is UNLOCKED when a window
# opens and LOCKED again only when NO window is currently active (union semantics).
WINDOW_HOURS = 3

# (phase_key, minutes_offset_from_open). Negative = before open (reminders);
# 0 = open (LIVE message + unlock); positive = after open (lock candidate).
# Order = chronological for a given window.
PHASES = [
    ("t2h", -120),     # 2h before: heads-up reminder
    ("t30", -30),      # 30min before: final reminder + ping
    ("live", 0),       # open: LIVE message + ping + NeatQueue UNLOCK
    ("lock", WINDOW_HOURS * 60),  # window end: NeatQueue LOCK (skipped if other window still open)
]

PLAYERS_PER_LOBBY = 10  # CoD 5v5 hard step

FOOTER_PREFIX = "date:"  # embed footer stash marker, e.g. "date:2026-06-20 • CQ Reminder"


def is_staff(interaction: discord.Interaction):
    """Helper to check if a user is staff or admin."""
    if interaction.user.guild_permissions.administrator:
        return True
    roles = [r.name.lower() for r in interaction.user.roles]
    return any("staff" in r or "admin" in r for r in roles)


# ============================ State persistence (mmr.py pattern) ============================

def _load_state():
    """Returns dict with 'rsvp' ({date: [discord_id]}) and 'fired' (set-like list).

    The RSVP roster is SHARED across windows — keyed by date only, no session
    dimension, because there is only one queue."""
    try:
        with open(core.QUEUE_STATE_FILE) as f:
            data = json.load(f)
        data.setdefault("rsvp", {})
        data.setdefault("fired", [])
        return data
    except Exception:
        return {"rsvp": {}, "fired": []}


def _save_state(state):
    try:
        # Cap 'fired' to avoid unbounded growth (keep last 500 keys).
        state["fired"] = list(state["fired"])[-500:]
        with open(core.QUEUE_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.error("Could not save queue state: %s", e)


def _rsvp_list(state, date_str):
    """Shared RSVP roster for a given date (across all windows)."""
    return state["rsvp"].get(date_str, [])


def _set_rsvp_list(state, date_str, ids):
    state["rsvp"][date_str] = ids


def _fire_key(window_key, phase_key, date_str):
    return f"{window_key}_{phase_key}_{date_str}"


# ============================ Time helpers ============================

def _window_date_and_open_utc(window):
    """For "today" in the window's tz, return (date_str_in_tz, open_dt_utc).

    Computed fresh each loop tick from datetime.now(timezone.utc) so DST is correct.
    """
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(window["tz"])
    date_str = now_local.strftime("%Y-%m-%d")
    # Build open time in local tz, then convert to UTC.
    open_local = now_local.replace(
        hour=window["hour"], minute=window["minute"], second=0, microsecond=0)
    open_utc = open_local.astimezone(timezone.utc)
    return date_str, open_utc


def _is_window_active(window, now_utc):
    """True if `now_utc` is inside this window's open..close range for today."""
    date_str, open_utc = _window_date_and_open_utc(window)
    close_utc = open_utc + timedelta(hours=WINDOW_HOURS)
    return open_utc <= now_utc < close_utc


def _any_window_active(now_utc):
    return any(_is_window_active(w, now_utc) for w in WINDOWS)


# ============================ Embed builders ============================

def _next_lobby_gap(n):
    """How many more players needed to fill the next 10-player lobby."""
    rem = n % PLAYERS_PER_LOBBY
    return PLAYERS_PER_LOBBY if rem == 0 else (PLAYERS_PER_LOBBY - rem)


def _rsvp_field_value(rsvp_ids, member_lookup):
    """Render the RSVP field: count + gap-to-next-10 + name list."""
    n = len(rsvp_ids)
    gap = _next_lobby_gap(n)
    lobbies = n // PLAYERS_PER_LOBBY
    parts = [
        f"🎫 **{n} reserved** — **{gap}** more to fill the next **5v5 lobby**",
        f"🎮 Expected lobbies: **{lobbies}**" + (" (none yet)" if lobbies == 0 else ""),
    ]
    if rsvp_ids:
        names = []
        for uid in rsvp_ids[:25]:  # Discord field cap safety
            m = member_lookup(uid)
            names.append(m.display_name if m else f"<@{uid}>")
        more = "" if len(rsvp_ids) <= 25 else f" …(+{len(rsvp_ids) - 25})"
        parts.append("**Players:** " + ", ".join(names) + more)
    else:
        parts.append("*No one reserved yet. Be the first to lock in a spot.*")
    return "\n".join(parts)


def _footer_for(date_str):
    return f"{FOOTER_PREFIX}{date_str} • CQ Reminder"


def _parse_footer_date(embed):
    """Recover date_str from a stashed footer. Returns None if absent."""
    if not embed or not embed.footer or not embed.footer.text:
        return None
    text = embed.footer.text
    if not text.startswith(FOOTER_PREFIX):
        return None
    try:
        rest = text[len(FOOTER_PREFIX):]
        return rest.split(" • ", 1)[0]
    except Exception:
        return None


def _window_times_line(now_utc):
    """One-line summary of both windows' open times in their own local tz, for the embed.

    Computed fresh so DST is always correct. Shows each window's open time in its
    own local tz (ET / CET)."""
    parts = []
    for w in WINDOWS:
        _, open_utc = _window_date_and_open_utc(w)
        local = open_utc.astimezone(w["tz"]).strftime("%H:%M")
        flag = "🇺🇸" if w["key"] == "na" else "🇪🇺"
        parts.append(f"{flag} **{w['label']} {local}** ET" if w["key"] == "na" else f"{flag} **{w['label']} {local}** CET")
    return " · ".join(parts)


async def build_reminder_embed(bot, phase_key, date_str, state):
    """Construct the UNIFIED embed for a phase. Reads the shared RSVP roster.

    Always shows both windows' times and the single shared roster, regardless of
    which window triggered this phase. phase copy is keyed on phase_key."""
    rsvp_ids = _rsvp_list(state, date_str)

    def member_lookup(uid):
        guild = bot.get_guild(int(core.GUILD_ID)) if core.GUILD_ID else None
        return guild.get_member(int(uid)) if guild else None

    join_ch = bot.get_channel(core.QUEUE_JOIN_CHANNEL_ID)
    join_mention = join_ch.mention if join_ch else f"<#{core.QUEUE_JOIN_CHANNEL_ID}>"

    if phase_key == "live":
        title = "🔴 LIVE — Queue Open"
        desc = (f"The queue is now **open**!\n\n"
                f"👉 Go to {join_mention} and press the **Join Queue** button to get in. "
                f"Anyone can play in either window.")
        color = 0x2ECC71  # green = live
    elif phase_key == "t30":
        title = "⏰ Queue — 30 min"
        desc = ("A queue window opens in **30 minutes**.\n"
                "Lock in your spot below — the roster is shared across both windows.")
        color = 0xF1C40F  # yellow = soon
    else:  # t2h
        title = "📣 Queue — 2 hours"
        desc = ("A queue window opens in **2 hours**.\n"
                "Reserve your spot below so we can fill the first lobby fast. "
                "The roster is shared — joining here counts for both windows.")
        color = 0x5865F2  # blurple = heads-up

    embed = discord.Embed(title=title, description=desc, color=color)
    embed.add_field(name="🎟️ RSVP", value=_rsvp_field_value(rsvp_ids, member_lookup), inline=False)

    embed.add_field(
        name="🌍 Today's windows",
        value=_window_times_line(datetime.now(timezone.utc)),
        inline=False)

    embed.set_footer(text=_footer_for(date_str))
    embed.timestamp = datetime.now(timezone.utc)
    return embed


# ============================ RSVP panel (verify.py pattern) ============================

class RsvpView(discord.ui.View):
    """Persistent RSVP buttons. The date is recovered from the embed footer so
    the buttons keep working across restarts. There is no session dimension —
    the roster is shared across all windows."""

    def __init__(self):
        super().__init__(timeout=None)

    def _resolve(self, interaction):
        """Return date_str or None."""
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        return _parse_footer_date(embed)

    async def _refresh_embed(self, interaction, date_str):
        """Reload state, rebuild the RSVP field, edit in place."""
        state = await asyncio.to_thread(_load_state)
        embed = interaction.message.embeds[0]
        # Rebuild only the RSVP field (index 0).
        def member_lookup(uid):
            guild = interaction.client.get_guild(int(core.GUILD_ID)) if core.GUILD_ID else None
            return guild.get_member(int(uid)) if guild else None
        rsvp_ids = _rsvp_list(state, date_str)
        embed.set_field_at(0, name="🎟️ RSVP", value=_rsvp_field_value(rsvp_ids, member_lookup), inline=False)
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.response.edit_message(embed=embed, view=self)
        return state

    @discord.ui.button(label="Join", emoji="✅",
                       style=discord.ButtonStyle.success, custom_id="queue:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        date_str = self._resolve(interaction)
        if date_str is None:
            await interaction.response.send_message("⚠️ This RSVP panel is stale.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        state = await asyncio.to_thread(_load_state)
        ids = list(_rsvp_list(state, date_str))
        if uid in ids:
            await interaction.response.send_message("You're already on the list. ✅", ephemeral=True)
            return
        ids.append(uid)
        _set_rsvp_list(state, date_str, ids)
        await asyncio.to_thread(_save_state, state)
        await self._refresh_embed(interaction, date_str)
        n = len(ids)
        gap = _next_lobby_gap(n)
        await interaction.followup.send(
            f"🎟️ You're in! **{n}** reserved — **{gap}** more to fill the next lobby.",
            ephemeral=True)

    @discord.ui.button(label="Leave", emoji="✖️",
                       style=discord.ButtonStyle.danger, custom_id="queue:leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        date_str = self._resolve(interaction)
        if date_str is None:
            await interaction.response.send_message("⚠️ This RSVP panel is stale.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        state = await asyncio.to_thread(_load_state)
        ids = [u for u in _rsvp_list(state, date_str) if u != uid]
        _set_rsvp_list(state, date_str, ids)
        await asyncio.to_thread(_save_state, state)
        await self._refresh_embed(interaction, date_str)
        await interaction.followup.send("You've been removed from the RSVP list.", ephemeral=True)

    @discord.ui.button(label="Refresh", emoji="🔄",
                       style=discord.ButtonStyle.secondary, custom_id="queue:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        date_str = self._resolve(interaction)
        if date_str is None:
            await interaction.response.send_message("⚠️ This RSVP panel is stale.", ephemeral=True)
            return
        await self._refresh_embed(interaction, date_str)


# ============================ Cog ============================

class Queue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def cog_unload(self):
        self.reminder_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not core.QUEUE_REMINDER_ENABLED:
            logger.info("Queue reminder loop disabled (QUEUE_REMINDER_ENABLED=0).")
            return
        if not self.reminder_loop.is_running():
            self.reminder_loop.start()
            logger.info("Queue reminder loop started.")

    # ---------- manual /unlock /lock detection ----------

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Detect staff running NeatQueue's native /unlock or /lock slash command
        in a queue channel, so the bot can protect a manually-opened queue from
        being overwritten by the scheduled auto-lock.

        We catch the interaction itself (not NeatQueue's ephemeral response, which
        we can't see) by inspecting command_name. This is independent of NeatQueue's
        response format and works whether or not the response is ephemeral."""
        try:
            cmd = getattr(interaction, "command_name", None)
        except Exception:
            return
        if cmd not in ("unlock", "lock"):
            return
        # Only watch the configured queue channels.
        watch = {core.QUEUE_JOIN_CHANNEL_ID, core.NEATQUEUE_QUEUE_CHANNEL_ID}
        if interaction.channel_id not in watch:
            return
        try:
            state = await asyncio.to_thread(_load_state)
            if cmd == "unlock":
                state["manual_open"] = True
                state["manual_open_since"] = datetime.now(timezone.utc).isoformat()
            else:  # lock
                state["manual_open"] = False
                state.pop("manual_open_since", None)
            await asyncio.to_thread(_save_state, state)
            logger.info("Manual /%s detected via on_interaction — manual_open=%s",
                        cmd, state["manual_open"])
        except Exception as e:
            logger.error("Failed to record manual /%s: %s", cmd, e)

    # ---------- channel resolution ----------

    def _reminder_channel(self):
        """Where reminders are posted. Falls back to join channel, then staff logs."""
        ch = None
        if core.QUEUE_REMINDER_CHANNEL_ID:
            ch = self.bot.get_channel(core.QUEUE_REMINDER_CHANNEL_ID)
        if ch is None and core.QUEUE_JOIN_CHANNEL_ID:
            ch = self.bot.get_channel(core.QUEUE_JOIN_CHANNEL_ID)
        if ch is None:
            ch = self.bot.get_channel(core.STAFF_LOGS_CHANNEL_ID)
        return ch

    def _queue_ping_mention(self):
        guild = self.bot.get_guild(int(core.GUILD_ID)) if core.GUILD_ID else None
        if guild and core.QUEUE_PING_ROLE_ID:
            role = guild.get_role(core.QUEUE_PING_ROLE_ID)
            if role:
                return role.mention
        return None

    # ---------- the scheduler ----------

    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        """Each minute, check if any (window, phase) boundary was crossed now.

        Phases (offset from window open):
          t2h (-120min), t30 (-30min), live (0), lock (+3h).
        Lock has UNION semantics: a window's lock is SKIPPED if any other window
        is still active, so the shared queue stays open as long as either window
        is in session. Reminder messages always render the unified view (both
        windows + shared roster)."""
        try:
            now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            state = await asyncio.to_thread(_load_state)
            dirty = False

            for window in WINDOWS:
                date_str, open_utc = _window_date_and_open_utc(window)
                for phase_key, minutes_offset in PHASES:
                    phase_utc = open_utc + timedelta(minutes=minutes_offset)
                    if phase_utc != now_utc:
                        continue
                    fkey = _fire_key(window["key"], phase_key, date_str)
                    if fkey in state["fired"]:
                        continue

                    # UNION guard for lock: if any OTHER window is currently active,
                    # skip this lock so the shared queue stays open.
                    if phase_key == "lock":
                        other_active = any(
                            _is_window_active(w, now_utc) and w["key"] != window["key"]
                            for w in WINDOWS)
                        if other_active:
                            logger.info("Lock for %s window skipped — another window is still open.",
                                        window["key"])
                            state["fired"].append(fkey)  # don't retry; union resolved it
                            dirty = True
                            continue

                        # MANUAL OPEN guard: if staff ran /unlock manually, don't let the
                        # scheduled auto-lock overwrite their open. Honor it for up to 24h,
                        # after which we expire the flag (safety net for forgotten opens).
                        if state.get("manual_open"):
                            since = state.get("manual_open_since")
                            expired = True
                            if since:
                                try:
                                    since_dt = datetime.fromisoformat(since.rstrip("Z"))
                                    expired = (now_utc - since_dt) >= timedelta(hours=24)
                                except Exception:
                                    expired = True
                            if expired:
                                logger.info("Manual open expired (>24h since %s) — proceeding with auto-lock.",
                                            since)
                                state["manual_open"] = False
                                state.pop("manual_open_since", None)
                                dirty = True
                            else:
                                logger.info("Auto-lock skipped — queue was manually opened at %s. Staying open until /lock.",
                                            since)
                                state["fired"].append(fkey)  # don't retry; honor manual open
                                dirty = True
                                continue

                    # NEW: clear manual_open when a new scheduled session starts, so a
                    # manual open from yesterday doesn't suppress today's auto-lock.
                    if phase_key == "live" and state.get("manual_open"):
                        logger.info("New scheduled session starting — clearing manual_open flag.")
                        state["manual_open"] = False
                        state.pop("manual_open_since", None)
                        dirty = True

                    fired_ok = await self._post_phase(window, phase_key, state, date_str)
                    # Only mark as fired if the action actually succeeded — this is
                    # the retry-on-next-minute safety net for transient NQ API errors.
                    if fired_ok:
                        state["fired"].append(fkey)
                        dirty = True

            if dirty:
                await asyncio.to_thread(_save_state, state)
        except Exception as e:
            logger.error("Queue reminder loop error: %s", e, exc_info=True)

    @reminder_loop.before_loop
    async def _before_loop(self):
        await self.bot.wait_until_ready()

    async def _post_phase(self, window, phase_key, state, date_str):
        """Execute a phase. Returns True if it completed successfully (so it gets
        marked fired), False otherwise (so it retries next minute)."""
        # ---- Lock/unlock: NeatQueue API calls, no embed ----
        if phase_key == "lock":
            return await self._call_lock(locked=True, window_key=window["key"])
        if phase_key == "live":
            # OPEN = post the LIVE message AND unlock the queue in the same tick,
            # so the "queue is open" announcement is never ahead of the actual unlock.
            msg_ok = await self._send_reminder(phase_key, state, date_str)
            unlock_ok = await self._call_lock(locked=False, window_key=window["key"])
            # After the queue is actually open, DM the RSVP roster so reserved
            # players get a head start. Never let a DM failure block the LIVE phase.
            try:
                await self._dm_rsvp_roster(state, date_str)
            except Exception as e:
                logger.error("RSVP DM step failed (non-fatal): %s", e)
            return msg_ok and unlock_ok

        # ---- Reminder phases (t2h, t30): unified embed + optional ping ----
        return await self._send_reminder(phase_key, state, date_str)

    async def _call_lock(self, locked, window_key):
        """Call NeatQueue lock/unlock on the join channel. Returns True on success.
        Errors are logged but not raised — the loop retries on the next minute
        because _post_phase returns False."""
        fn = core.nq_lock if locked else core.nq_unlock
        action = "lock" if locked else "unlock"
        try:
            await asyncio.to_thread(fn, core.QUEUE_JOIN_CHANNEL_ID)
            logger.info("NeatQueue %s on %s (triggered by %s window).",
                        action, core.QUEUE_JOIN_CHANNEL_ID, window_key)
            return True
        except Exception as e:
            logger.error("NeatQueue %s failed (%s window): %s", action, window_key, e)
            return False

    async def _send_reminder(self, phase_key, state, date_str):
        """Post the unified reminder embed for t2h/t30/live. Returns True on success."""
        channel = self._reminder_channel()
        if channel is None:
            logger.warning("Queue reminder: no channel configured to post in.")
            return False
        try:
            embed = await build_reminder_embed(self.bot, phase_key, date_str, state)
            content = None
            ping = self._queue_ping_mention()
            if phase_key in ("t30", "live") and ping:
                content = ping
            # LIVE phase: no RSVP buttons (it's action time — go to the join channel).
            view = None if phase_key == "live" else RsvpView()
            await channel.send(content=content, embed=embed, view=view,
                               allowed_mentions=discord.AllowedMentions(roles=bool(content)))
            logger.info("Queue reminder posted: %s for %s", phase_key, date_str)
            return True
        except Exception as e:
            logger.error("Failed to post %s reminder: %s", phase_key, e)
            return False

    async def _dm_rsvp_roster(self, state, date_str):
        """DM everyone on the shared RSVP roster for this date to tell them the
        queue is now open. This gives RSVP'd players a head start over people who
        only see the channel ping — softening (not eliminating) the 'seat stolen'
        problem, since the bot can't reserve slots in NeatQueue.

        DM failures (closed DMs, blocked) are logged but never abort the LIVE
        phase — the queue is open regardless. A per-user cap of one DM per date
        prevents duplicate pings if both NA and EU live phases fire same day."""
        rsvp_ids = _rsvp_list(state, date_str)
        if not rsvp_ids:
            return 0
        already_dmd = set(state.setdefault("live_dmed", {}).get(date_str, []))
        targets = [uid for uid in rsvp_ids if uid not in already_dmd]
        if not targets:
            return 0

        join_ch = self.bot.get_channel(core.QUEUE_JOIN_CHANNEL_ID)
        join_mention = join_ch.mention if join_ch else f"<#{core.QUEUE_JOIN_CHANNEL_ID}>"
        guild = self.bot.get_guild(int(core.GUILD_ID)) if core.GUILD_ID else None

        sent = 0
        for uid in targets:
            member = guild.get_member(int(uid)) if guild else None
            if member is None:
                continue
            try:
                await member.send(
                    f"🔴 **The queue is now open!**\n\n"
                    f"You reserved a spot — head to {join_mention} and press "
                    f"**Join Queue** now to lock it in. "
                    f"Reserved players get this heads-up before the channel ping.\n\n"
                    f"*This is a courtesy nudge, not a guaranteed slot — first to press "
                    f"Join Queue gets in.*")
                sent += 1
            except discord.Forbidden:
                logger.info("RSVP DM to %s skipped — DMs closed.", uid)
            except Exception as e:
                logger.warning("RSVP DM to %s failed: %s", uid, e)

        # Record who we DMed so the other window's live phase doesn't re-DM them.
        state.setdefault("live_dmed", {}).setdefault(date_str, []).extend(targets)
        logger.info("RSVP LIVE DM sent to %d/%d reserved players for %s.",
                    sent, len(targets), date_str)
        return sent

    # ---------- manual staff trigger ----------

    @app_commands.command(name="queuepanel",
                          description="Post the unified RSVP panel now (staff only).")
    async def queue_panel(self, interaction: discord.Interaction):
        if not is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            # Use the NA window's "today" as the date anchor (arbitrary; roster is shared).
            date_str, _ = _window_date_and_open_utc(WINDOWS[0])
            state = await asyncio.to_thread(_load_state)
            embed = await build_reminder_embed(self.bot, "t2h", date_str, state)
            channel = self._reminder_channel() or interaction.channel
            await channel.send(embed=embed, view=RsvpView())
            await interaction.followup.send(
                f"✅ Unified RSVP panel posted ({date_str}).", ephemeral=True)
        except Exception as e:
            logger.error("Error in /queuepanel: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


async def setup(bot):
    # Register the persistent RSVP view so buttons survive restarts (verify.py pattern).
    bot.add_view(RsvpView())
    await bot.add_cog(Queue(bot))
