"""Queue reminder system.

Two independent daily sessions, each opens at 23:00 in its own wall-clock timezone:
  - NA: 23:00 America/New_York (EST/EDT auto via zoneinfo)
  - EU: 23:00 Europe/Berlin     (CET/CEST auto via zoneinfo)
Each session runs ~3h. Per session the bot posts three reminders:
  - T-2h    : heads-up, no ping
  - T-30min : Queue Ping role mentioned, RSVP count shown
  - T-0 LIVE: Queue Ping role mentioned, points players to the Join Queue button
              in QUEUE_JOIN_CHANNEL_ID (owned by NeatQueue, not this bot).

RSVP model: this bot tracks a *soft* RSVP roster (intent to play) on disk. It does
NOT own queue joins — players still join via NeatQueue's interactive panel. The
count is shown as "X reserved · Y to fill the next 10-player lobby", emphasizing
the CoD 5v5 / multiple-of-10 cliff (unlike F1's soft cap, ours is a hard step).

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

# --- Session schedule (wall-clock, DST-safe via zoneinfo named zones) ---
# Each session: open time in its own timezone. zoneinfo handles EST<->EDT, CET<->CEST.
SESSIONS = [
    {"key": "na", "tz": ZoneInfo("America/New_York"), "hour": 23, "minute": 0, "label": "NA"},
    {"key": "eu", "tz": ZoneInfo("Europe/Berlin"), "hour": 23, "minute": 0, "label": "EU"},
]
# Each session runs this long once opened. The queue is UNLOCKED at T-0 and
# LOCKED again at T+SESSION_WINDOW_HOURS (the session's own wall-clock tz).
SESSION_WINDOW_HOURS = 3

# (phase_key, minutes_offset_from_open). Negative = before open (reminders);
# 0 = open (LIVE message + unlock); positive = after open (lock).
# Order = chronological for a given session.
PHASES = [
    ("t2h", -120),     # 2h before: heads-up reminder
    ("t30", -30),      # 30min before: final reminder + ping
    ("live", 0),       # open: LIVE message + ping + NeatQueue UNLOCK
    ("lock", SESSION_WINDOW_HOURS * 60),  # session end: NeatQueue LOCK
]

PLAYERS_PER_LOBBY = 10  # CoD 5v5 hard step

FOOTER_PREFIX = "session:"  # embed footer stash marker, e.g. "session:na|2026-06-20"


def is_staff(interaction: discord.Interaction):
    """Helper to check if a user is staff or admin."""
    if interaction.user.guild_permissions.administrator:
        return True
    roles = [r.name.lower() for r in interaction.user.roles]
    return any("staff" in r or "admin" in r for r in roles)


# ============================ State persistence (mmr.py pattern) ============================

def _load_state():
    """Returns dict with 'rsvp' ({session: {date: [discord_id]}}) and 'fired' (set-like list)."""
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


def _rsvp_list(state, session_key, date_str):
    """List of discord IDs (strings) RSVP'd for a session on a given date."""
    return state["rsvp"].get(session_key, {}).get(date_str, [])


def _set_rsvp_list(state, session_key, date_str, ids):
    state["rsvp"].setdefault(session_key, {})[date_str] = ids


def _fire_key(session_key, phase_key, date_str):
    return f"{session_key}_{phase_key}_{date_str}"


# ============================ Time helpers ============================

def _session_date_and_open_utc(session):
    """For "today" in the session's tz, return (date_str_in_tz, open_dt_utc).

    Computed fresh each loop tick from datetime.now(timezone.utc) so DST is correct.
    """
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(session["tz"])
    date_str = now_local.strftime("%Y-%m-%d")
    # Build open time in local tz, then convert to UTC.
    open_local = now_local.replace(
        hour=session["hour"], minute=session["minute"], second=0, microsecond=0)
    open_utc = open_local.astimezone(timezone.utc)
    return date_str, open_utc


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


def _footer_for(session_key, date_str):
    return f"{FOOTER_PREFIX}{session_key}|{date_str} • CQ Reminder"


def _parse_footer_session(embed):
    """Recover (session_key, date_str) from a stashed footer. Returns (None, None) if absent."""
    if not embed or not embed.footer or not embed.footer.text:
        return None, None
    text = embed.footer.text
    if not text.startswith(FOOTER_PREFIX):
        return None, None
    try:
        rest = text[len(FOOTER_PREFIX):]
        head = rest.split(" • ", 1)[0]
        session_key, date_str = head.split("|", 1)
        return session_key, date_str
    except Exception:
        return None, None


async def build_reminder_embed(bot, session, phase_key, phase_label, date_str, state):
    """Construct the embed for a given session/phase. Reads live RSVP from state.
    phase_label is for logging only; the per-phase copy is keyed on phase_key."""
    open_local_str = f"{session['hour']:02d}:{session['minute']:02d} {session['tz'].key if hasattr(session['tz'], 'key') else ''}"
    rsvp_ids = _rsvp_list(state, session["key"], date_str)

    def member_lookup(uid):
        guild = bot.get_guild(int(core.GUILD_ID)) if core.GUILD_ID else None
        return guild.get_member(int(uid)) if guild else None

    if phase_key == "live":
        title = f"🔴 LIVE — {session['label']} Queue Open"
        desc = (f"The **{session['label']}** session is now open!\n\n"
                f"👉 Go to {bot.get_channel(core.QUEUE_JOIN_CHANNEL_ID).mention if bot.get_channel(core.QUEUE_JOIN_CHANNEL_ID) else '<#'+str(core.QUEUE_JOIN_CHANNEL_ID)+'>'} "
                f"and press the **Join Queue** button to get in.")
        color = 0x2ECC71  # green = live
    elif phase_key == "t30":
        title = f"⏰ {session['label']} Queue — 30 min"
        desc = (f"The **{session['label']}** session opens in **30 minutes** at "
                f"**{session['hour']:02d}:{session['minute']:02d}** local.\n"
                f"Lock in your spot below.")
        color = 0xF1C40F  # yellow = soon
    else:  # t2h
        title = f"📣 {session['label']} Queue — 2 hours"
        desc = (f"The **{session['label']}** session opens in **2 hours** at "
                f"**{session['hour']:02d}:{session['minute']:02d}** local.\n"
                f"Reserve your spot below so we can fill the first lobby fast.")
        color = 0x5865F2  # blurple = heads-up

    embed = discord.Embed(title=title, description=desc, color=color)
    embed.add_field(name="🎟️ RSVP", value=_rsvp_field_value(rsvp_ids, member_lookup), inline=False)

    # Show the session's open time in both NA and EU tz for cross-region clarity.
    na_tz = next(s["tz"] for s in SESSIONS if s["key"] == "na")
    eu_tz = next(s["tz"] for s in SESSIONS if s["key"] == "eu")
    _, open_utc_real = _session_date_and_open_utc(session)
    open_na = open_utc_real.astimezone(na_tz).strftime("%H:%M")
    open_eu = open_utc_real.astimezone(eu_tz).strftime("%H:%M")
    embed.add_field(
        name="🌍 Session time",
        value=f"🇺🇸 **{open_na}** NA (ET) · 🇪🇺 **{open_eu}** EU (CET)",
        inline=False)

    embed.set_footer(text=_footer_for(session["key"], date_str))
    embed.timestamp = datetime.now(timezone.utc)
    return embed


# ============================ RSVP panel (verify.py pattern) ============================

class RsvpView(discord.ui.View):
    """Persistent RSVP buttons. State is recovered from the embed footer
    (session_key|date) so the buttons keep working across restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    def _resolve(self, interaction):
        """Return (session_key, date_str) or (None, None)."""
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        return _parse_footer_session(embed)

    async def _refresh_embed(self, interaction, session_key, date_str):
        """Reload state, rebuild the RSVP field, edit in place."""
        session = next((s for s in SESSIONS if s["key"] == session_key), None)
        if session is None:
            await interaction.response.send_message("⚠️ Could not resolve session.", ephemeral=True)
            return None
        state = await asyncio.to_thread(_load_state)
        embed = interaction.message.embeds[0]
        # Rebuild only the RSVP field (index 0).
        def member_lookup(uid):
            guild = interaction.client.get_guild(int(core.GUILD_ID)) if core.GUILD_ID else None
            return guild.get_member(int(uid)) if guild else None
        rsvp_ids = _rsvp_list(state, session_key, date_str)
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
        session_key, date_str = self._resolve(interaction)
        if session_key is None:
            await interaction.response.send_message("⚠️ This RSVP panel is stale.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        state = await asyncio.to_thread(_load_state)
        ids = list(_rsvp_list(state, session_key, date_str))
        if uid in ids:
            await interaction.response.send_message("You're already on the list. ✅", ephemeral=True)
            return
        ids.append(uid)
        _set_rsvp_list(state, session_key, date_str, ids)
        await asyncio.to_thread(_save_state, state)
        await self._refresh_embed(interaction, session_key, date_str)
        n = len(ids)
        gap = _next_lobby_gap(n)
        await interaction.followup.send(
            f"🎟️ You're in! **{n}** reserved — **{gap}** more to fill the next lobby.",
            ephemeral=True)

    @discord.ui.button(label="Leave", emoji="✖️",
                       style=discord.ButtonStyle.danger, custom_id="queue:leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        session_key, date_str = self._resolve(interaction)
        if session_key is None:
            await interaction.response.send_message("⚠️ This RSVP panel is stale.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        state = await asyncio.to_thread(_load_state)
        ids = [u for u in _rsvp_list(state, session_key, date_str) if u != uid]
        _set_rsvp_list(state, session_key, date_str, ids)
        await asyncio.to_thread(_save_state, state)
        await self._refresh_embed(interaction, session_key, date_str)
        await interaction.followup.send("You've been removed from the RSVP list.", ephemeral=True)

    @discord.ui.button(label="Refresh", emoji="🔄",
                       style=discord.ButtonStyle.secondary, custom_id="queue:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        session_key, date_str = self._resolve(interaction)
        if session_key is None:
            await interaction.response.send_message("⚠️ This RSVP panel is stale.", ephemeral=True)
            return
        await self._refresh_embed(interaction, session_key, date_str)


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
        """Each minute, check if any (session, phase) boundary was crossed now.

        Phases (offset from session open):
          t2h (-120min), t30 (-30min), live (0), lock (+3h).
        Lock fires in a later minute than open, and may land on the next UTC date,
        but its dedup key is anchored to the SESSION's open date (date_str) so it
        still maps to the right window. Reminder messages and lock/unlock all run
        in this single loop, so they can never drift apart."""
        try:
            now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            state = await asyncio.to_thread(_load_state)
            dirty = False

            for session in SESSIONS:
                date_str, open_utc = _session_date_and_open_utc(session)
                for phase_key, minutes_offset in PHASES:
                    phase_utc = open_utc + timedelta(minutes=minutes_offset)
                    if phase_utc != now_utc:
                        continue
                    fkey = _fire_key(session["key"], phase_key, date_str)
                    if fkey in state["fired"]:
                        continue
                    fired_ok = await self._post_phase(session, phase_key, state, date_str)
                    # Only mark as fired if the action actually succeeded — this is
                    # the retry-on-next-minute safety net for transient NQ API errors.
                    # (Reminder message sends that succeed return True; lock/unlock
                    # API calls return True only on a 2xx response.)
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

    async def _post_phase(self, session, phase_key, state, date_str):
        """Execute a phase. Returns True if it completed successfully (so it gets
        marked fired), False otherwise (so it retries next minute)."""
        # ---- Lock/unlock: NeatQueue API calls, no embed ----
        if phase_key == "lock":
            return await self._call_lock(session, locked=True)
        if phase_key == "live":
            # OPEN = post the LIVE message AND unlock the queue in the same tick,
            # so the "queue is open" announcement is never ahead of the actual unlock.
            msg_ok = await self._send_reminder(session, phase_key, state, date_str)
            unlock_ok = await self._call_lock(session, locked=False)
            return msg_ok and unlock_ok

        # ---- Reminder phases (t2h, t30): embed + optional ping ----
        return await self._send_reminder(session, phase_key, state, date_str)

    async def _call_lock(self, session, locked):
        """Call NeatQueue lock/unlock on the join channel. Returns True on success.
        Errors are logged but not raised — the loop retries on the next minute
        because _post_phase returns False."""
        fn = core.nq_lock if locked else core.nq_unlock
        action = "lock" if locked else "unlock"
        try:
            await asyncio.to_thread(fn, core.QUEUE_JOIN_CHANNEL_ID)
            logger.info("NeatQueue %s on %s (%s session).",
                        action, core.QUEUE_JOIN_CHANNEL_ID, session["key"])
            return True
        except Exception as e:
            logger.error("NeatQueue %s failed for %s session: %s", action, session["key"], e)
            return False

    async def _send_reminder(self, session, phase_key, state, date_str):
        """Post the reminder embed for t2h/t30/live. Returns True on success."""
        channel = self._reminder_channel()
        if channel is None:
            logger.warning("Queue reminder: no channel configured to post in.")
            return False
        phase_label = {"t2h": "2 hours", "t30": "30 min", "live": "LIVE"}[phase_key]
        try:
            embed = await build_reminder_embed(
                self.bot, session, phase_key, phase_label, date_str, state)
            content = None
            ping = self._queue_ping_mention()
            if phase_key in ("t30", "live") and ping:
                content = ping
            # LIVE phase: no RSVP buttons (it's action time — go to the join channel).
            view = None if phase_key == "live" else RsvpView()
            await channel.send(content=content, embed=embed, view=view,
                               allowed_mentions=discord.AllowedMentions(roles=bool(content)))
            logger.info("Queue reminder posted: %s %s for %s", session["key"], phase_key, date_str)
            return True
        except Exception as e:
            logger.error("Failed to post %s %s reminder: %s", session["key"], phase_key, e)
            return False

    # ---------- manual staff trigger (Phase 4) ----------

    @app_commands.command(name="queuepanel",
                          description="Post an RSVP panel for a session now (staff only).")
    @app_commands.choices(session=[
        app_commands.Choice(name="NA", value="na"),
        app_commands.Choice(name="EU", value="eu"),
    ])
    async def queue_panel(self, interaction: discord.Interaction,
                          session: app_commands.Choice[str]):
        if not is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
        sess = next((s for s in SESSIONS if s["key"] == session.value), None)
        if sess is None:
            await interaction.response.send_message("❌ Invalid session.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            date_str, _ = _session_date_and_open_utc(sess)
            state = await asyncio.to_thread(_load_state)
            embed = await build_reminder_embed(
                self.bot, sess, "t2h", "2 hours", date_str, state)
            channel = self._reminder_channel() or interaction.channel
            await channel.send(embed=embed, view=RsvpView())
            await interaction.followup.send(
                f"✅ RSVP panel posted for **{sess['label']}** ({date_str}).", ephemeral=True)
        except Exception as e:
            logger.error("Error in /queuepanel: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


async def setup(bot):
    # Register the persistent RSVP view so buttons survive restarts (verify.py pattern).
    bot.add_view(RsvpView())
    await bot.add_cog(Queue(bot))
