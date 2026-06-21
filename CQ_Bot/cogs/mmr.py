"""Phase 7 — Impact-based MMR modifier.

NeatQueue applies its own base win/loss MMR. This cog adds a performance modifier
on top (default ±10), scaled from each player's absolute Impact score: Impact
MMR_IMPACT_MIN (60) maps to −MAX, MMR_IMPACT_MAX (200) maps to +MAX, linear in
between (neutral = midpoint). Impact comes from the OCR'd scoreboards in Airtable.

Safety: MMR_MODIFIER_DRYRUN=1 (default) only REPORTS what it would do to the
staff log channel. Set it to 0 in .env to actually apply changes.
"""
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta

import core

logger = logging.getLogger("CQ_Bot.mmr")

STATE_FILE = "mmr_state.json"
DISCORD_EPOCH_MS = 1420070400000
MATCH_WINDOW_HOURS = 4      # screenshots for a match must be posted within this window
MAX_MATCH_AGE_HOURS = 48    # ignore matches older than this (startup backlog guard)
MIN_PLAYERS_WITH_DATA = 6   # need impact data for at least this many of the 10 players


def is_staff(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        return True
    roles = [r.name.lower() for r in interaction.user.roles]
    return any("staff" in r or "admin" in r for r in roles)


def snowflake_dt(message_id):
    """Discord snowflake -> aware datetime (records' Match ID is a message id)."""
    ms = (int(message_id) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def load_state():
    """Returns (processed_set, backfilled_set). Both keyed by match_key().
    'backfilled' is absent in older state files -> empty set (backwards compatible)."""
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        processed = set(data.get("processed", []))
        backfilled = set(data.get("backfilled", []))
        return processed, backfilled
    except Exception:
        return set(), set()


def save_state(processed, backfilled):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "processed": list(processed)[-500:],
                "backfilled": list(backfilled)[-500:],
            }, f)
    except Exception as e:
        logger.error("Could not save MMR state: %s", e)


def impacts_in_window(start_dt, end_dt):
    """{player_record_id: [impact, ...]} from HP+SND records posted in the window. (sync)"""
    out = {}
    formula = "AND({Season} = '%s', {Player} != '')" % core.CURRENT_SEASON.replace("'", "")
    for table in (core.hp_table, core.snd_table):
        for rec in table.all(formula=formula, fields=["Player", "Impact", "Match ID"]):
            f = rec["fields"]
            mid = f.get("Match ID")
            imp = f.get("Impact")
            players = f.get("Player") or []
            if not mid or not isinstance(imp, (int, float)) or not players:
                continue
            try:
                ts = snowflake_dt(mid)
            except (ValueError, TypeError):
                continue
            if not (start_dt <= ts <= end_dt):
                continue
            pid = players[0]["id"] if isinstance(players[0], dict) else players[0]
            out.setdefault(pid, []).append(float(imp))
    return out


class MMRModifier(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.processed, self.backfilled = load_state()

    def cog_unload(self):
        self.modifier_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if core.NEATQUEUE_TOKEN and not self.modifier_loop.is_running():
            self.modifier_loop.start()
            mode = "DRY-RUN" if core.MMR_MODIFIER_DRYRUN else "LIVE"
            logger.info("MMR modifier loop started (%s mode).", mode)

    @tasks.loop(minutes=10)
    async def modifier_loop(self):
        try:
            await self.process_new_matches()
        except Exception as e:
            logger.error("MMR modifier loop error: %s", e, exc_info=True)

    @modifier_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ---------- core logic ----------

    @staticmethod
    def match_key(m):
        num = m.get("game_num") or m.get("match_num") or m.get("num")
        if num is not None:
            return f"g{num}"
        ids = sorted(str(p.get("id", "")) for team in (m.get("teams") or []) for p in team)
        return f"{m.get('time', '')}|{','.join(ids)}"

    @staticmethod
    def parse_match(m):
        """Returns (match_time, {discord_id: mmr_change}) or (None, None) if unusable."""
        try:
            mtime = datetime.strptime(m["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError, TypeError):
            # KeyError: missing 'time'; ValueError: bad format; TypeError: 'time' is None.
            return None, None
        changes = {}
        for team in (m.get("teams") or []):
            for p in team:
                did = str(p.get("id", ""))
                if did:
                    # keep the entry with the largest |mmr_change| (players can appear twice in payload)
                    ch = p.get("mmr_change")
                    if ch is not None and abs(ch) >= abs(changes.get(did, 0)):
                        changes[did] = ch
        return mtime, changes

    async def process_new_matches(self, announce_empty=False):
        history = await asyncio.to_thread(core.nq_history)
        if not isinstance(history, list):
            logger.warning("Unexpected history payload type: %s", type(history))
            return 0

        now = datetime.now(timezone.utc)
        handled = 0
        for m in history:
            if not isinstance(m, dict):
                continue
            key = self.match_key(m)
            if key in self.processed:
                continue
            mtime, changes = self.parse_match(m)
            if mtime is None:
                continue
            if now - mtime > timedelta(hours=MAX_MATCH_AGE_HOURS):
                self.processed.add(key)  # too old - never process
                continue
            if now - mtime < timedelta(minutes=30):
                continue  # match may still be running / screenshots incoming - retry next pass
            if not changes or all(not c for c in changes.values()):
                self.processed.add(key)  # cancelled / tie - nothing to modify
                continue

            result = await self.apply_modifiers_for_match(m, mtime, changes)
            if result == "retry":
                # OCR data not ready yet — do NOT mark as processed; retry next pass.
                # The 48h max-age guard (above) is the eventual backstop.
                continue
            self.processed.add(key)
            handled += 1
            if result:
                await core.send_staff_log(self.bot, embed=result)
        if handled:
            save_state(self.processed, self.backfilled)
        if announce_empty and not handled:
            return 0
        return handled

    async def apply_modifiers_for_match(self, m, mtime, changes):
        window_end = mtime + timedelta(hours=MATCH_WINDOW_HOURS)
        impacts = await asyncio.to_thread(impacts_in_window, mtime, window_end)
        did_map = await asyncio.to_thread(core.discord_id_map)          # discord_id -> pid
        directory = await asyncio.to_thread(core.player_directory_cached)  # pid -> (ign, handle)

        # average impact per discord id (only players in this match)
        player_imp = {}
        for did in changes:
            pid = did_map.get(did)
            if pid and impacts.get(pid):
                player_imp[did] = sum(impacts[pid]) / len(impacts[pid])

        if not player_imp:
            # Transient: OCR likely hasn't ingested the screenshots yet. Return a
            # sentinel so the caller does NOT mark this match as permanently
            # processed — it will be retried on the next loop pass (every 10 min)
            # until impact data appears or the 48h max-age guard drops it.
            await core.send_staff_log(
                self.bot,
                content=(f"ℹ️ MMR modifier waiting for match at `{m.get('time')}` — no impact data yet "
                         f"(screenshots not posted or unmatched). Retrying next pass."))
            return "retry"

        # Absolute Impact band: MIN -> -MAX, MAX -> +MAX, linear; neutral = midpoint.
        lo, hi, cap = core.MMR_IMPACT_MIN, core.MMR_IMPACT_MAX, core.MMR_MODIFIER_MAX
        mid = (lo + hi) / 2.0
        half = (hi - lo) / 2.0 or 1.0

        mode = "🧪 DRY-RUN (not applied)" if core.MMR_MODIFIER_DRYRUN else "✅ APPLIED"
        lines = []
        for did, imp in sorted(player_imp.items(), key=lambda kv: kv[1], reverse=True):
            imp_clamped = max(lo, min(hi, imp))
            # NeatQueue's add/stats requires an integer value; round the modifier
            # to the nearest whole point here so the embed shows exactly what gets applied.
            mod = int(round((imp_clamped - mid) / half * cap))
            pid = did_map.get(did)
            ign = directory.get(pid, ("?", ""))[0] if pid else "?"
            applied = ""
            if mod and not core.MMR_MODIFIER_DRYRUN:
                try:
                    await asyncio.to_thread(core.nq_add_mmr, did, mod)
                    applied = " ✔"
                except Exception as e:
                    applied = f" ⚠ failed: {e}"
                    logger.error("nq_add_mmr failed for %s: %s", did, e)
            sign = "+" if mod >= 0 else ""
            wl = "W" if changes.get(did, 0) > 0 else "L"
            lines.append(f"`{sign}{mod:>5}` **{ign}** ({wl}, impact {imp:.0f}){applied}")

        embed = discord.Embed(
            title="🎯 Impact MMR Modifier",
            description=(f"Match `{m.get('time')}` • queue `{m.get('game', '?')}`\n"
                         f"Impact {lo:g}→−{cap:g} … {hi:g}→+{cap:g} (neutral {mid:g}) • "
                         f"{len(player_imp)}/{len(changes)} with data\nMode: **{mode}**"),
            color=0xF1C40F if core.MMR_MODIFIER_DRYRUN else 0x2ECC71
        )
        embed.add_field(name="Modifiers", value="\n".join(lines)[:1024], inline=False)
        return embed

    # ---------- staff command ----------

    @app_commands.command(name="applymodifiers", description="Process new NeatQueue matches for Impact MMR modifiers now (staff only).")
    async def apply_now(self, interaction: discord.Interaction):
        if not is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
        if not core.NEATQUEUE_TOKEN:
            await interaction.response.send_message("❌ `NEATQUEUE_TOKEN` is not configured.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            n = await self.process_new_matches(announce_empty=True)
            mode = "dry-run" if core.MMR_MODIFIER_DRYRUN else "LIVE"
            if n:
                await interaction.followup.send(f"✅ Processed **{n}** new match(es) ({mode}). Reports posted to staff log.")
            else:
                await interaction.followup.send(f"No new completed matches to process ({mode}).")
        except Exception as e:
            logger.error("applymodifiers error: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}")

    @app_commands.command(name="backfillmodifiers",
                          description="Re-apply MMR modifiers to recent processed matches (staff only).")
    @app_commands.describe(count="Number of recent processed matches to backfill (1-20, default 2).")
    async def backfill_modifiers(self, interaction: discord.Interaction, count: int = 2):
        if not is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
        if not core.NEATQUEUE_TOKEN:
            await interaction.response.send_message("❌ `NEATQUEUE_TOKEN` is not configured.", ephemeral=True)
            return
        if not 1 <= count <= 20:
            await interaction.response.send_message("❌ `count` must be between 1 and 20.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            history = await asyncio.to_thread(core.nq_history)
            if not isinstance(history, list):
                await interaction.followup.send("❌ Could not fetch NeatQueue match history.")
                return

            # Select candidates: processed (handled once) but not yet backfilled.
            # Parse + sort by mtime descending so "most recent" wins.
            candidates = []
            for m in history:
                if not isinstance(m, dict):
                    continue
                key = self.match_key(m)
                if key not in self.processed or key in self.backfilled:
                    continue
                mtime, changes = self.parse_match(m)
                if mtime is None or not changes or all(not c for c in changes.values()):
                    continue
                candidates.append((mtime, key, m, changes))
            candidates.sort(key=lambda t: t[0], reverse=True)
            targets = candidates[:count]

            if not targets:
                await interaction.followup.send(
                    "ℹ️ No matches eligible for backfill (none in `processed` but not `backfilled`).")
                return

            mode = "DRY-RUN (global MMR_MODIFIER_DRYRUN=1)" if core.MMR_MODIFIER_DRYRUN else "LIVE"
            await interaction.followup.send(
                f"🔄 Backfilling up to **{len(targets)}** match(es) ({mode}). Reports to staff log shortly.")

            applied_matches = 0
            skipped_no_data = 0
            for mtime, key, m, changes in targets:
                # Re-run the full modifier pipeline (re-reads impact, recomputes, applies
                # unless global dry-run). apply_modifiers_for_match never returns "retry"
                # for a processed match with data present; "retry" here means transient
                # no-data — skip and leave it eligible for a later retry.
                result = await self.apply_modifiers_for_match(m, mtime, changes)
                if result == "retry" or result is None:
                    skipped_no_data += 1
                    logger.info("Backfill: match %s skipped (no impact data yet).", key)
                    continue
                self.backfilled.add(key)
                applied_matches += 1
                # Stamp the report as a backfill so staff can tell it apart.
                if isinstance(result, discord.Embed):
                    result.title = (result.title or "") + " (backfill)"
                    await core.send_staff_log(self.bot, embed=result)

            save_state(self.processed, self.backfilled)
            await interaction.followup.send(
                f"✅ Backfill complete: **{applied_matches}** match(es) processed, "
                f"{skipped_no_data} skipped (no impact data), {mode}.")
        except Exception as e:
            logger.error("backfillmodifiers error: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}")


async def setup(bot):
    await bot.add_cog(MMRModifier(bot))
