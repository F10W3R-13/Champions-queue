"""Inactivity MMR decay + 800-point queue eligibility gate (tiered hybrid).

Two independent concerns, run by one daily loop + one near-realtime hook:

1. **Decay** - players idle beyond a grace window lose MMR each day, escalating
   after a threshold. MMR never drops below DECAY_FLOOR. NeatQueue's own decay is
   OFF (verified 2026-06-26), so there's no double-penalty.

2. **Eligibility gate** - a Champs-holder whose MMR falls below DECAY_THRESHOLD
   loses the Registered role (which NeatQueue uses to gate queue joins).
   Recovering re-grants it automatically.

TIERING (the core design decision). The general queue and the champs-only queue
share ONE MMR pool (sharedstats). Non-Champs can't be fully exempt from decay -
that would let them freeload in the same ranking as obligated tournament players.
But non-Champs (minors, general members) are structurally unable to play when only
the champs queue is running, so they decay at a GENTLER rate than Champs holders
(who have a tournament obligation). Both still decay, just differently.

DEAD-DAY EXEMPTION. Any day with no completed matches in the last 24h is a "dead
day" - nobody could have played, so decay is skipped for everyone, and the
accumulated dead_days extends every player's grace window. This makes "structurally
unable to play" (empty queue) fair instead of punitive.

Idempotency (mirrors cogs/mmr.py's applied-set pattern):
  - decay_applied: per-(date, discord_id) keys - decay applied at most once per
    player per day, surviving restarts and mid-pass crashes.
  - below_threshold: Champs discord_ids currently role-revoked (toggle diff).
  - dead_days: running count of consecutive dead days (grace extension).
  - DECAY_DRYRUN never writes any of these (mmr.py 9.9 lesson: a dry-run that
    marks state would silently drop that player-day forever once LIVE).

Exemptions: players under PLACEMENT_GAMES total games are skipped entirely.
Not-in-NeatQueue players are INFO-skipped.
"""
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
import json
from datetime import datetime, timezone, timedelta, time as dtime

import core

logger = logging.getLogger("CQ_Bot.decay")


def load_state():
    """Returns (decay_applied set, below_threshold set, dead_days int). (sync)

    dead_days is backwards-compatible: absent in older state files -> 0."""
    try:
        with open(core.DECAY_STATE_FILE) as f:
            data = json.load(f)
        return (set(data.get("decay_applied", [])),
                set(data.get("below_threshold", [])),
                int(data.get("dead_days", 0)))
    except Exception:
        return set(), set(), 0


def save_state(decay_applied, below_threshold, dead_days):
    try:
        with open(core.DECAY_STATE_FILE, "w") as f:
            json.dump({
                "decay_applied": list(decay_applied)[-2000:],
                "below_threshold": list(below_threshold),
                "dead_days": int(dead_days),
            }, f)
    except Exception as e:
        logger.error("Could not save decay state: %s", e)


def _decay_key(date_str, discord_id):
    """Per-(day, player) idempotency key for the decay_applied set."""
    return f"{date_str}|{discord_id}"


def compute_daily_decay(idle_days, mmr, *, grace, rate, escalate_after, escalate_rate):
    """Integer MMR to subtract for one day, given tier parameters and current mmr.

    `grace` is the EFFECTIVE grace (base grace + dead_days extension). Returns 0
    if within grace. Base tier loses `rate`/day; beyond `escalate`,
    `escalate_rate`/day. Clamped by DECAY_FLOOR so a player near the floor only
    loses down to it."""
    if idle_days <= grace:
        return 0
    r = escalate_rate if idle_days >= escalate_after else rate
    headroom = max(0, int(mmr) - core.DECAY_FLOOR)
    return min(r, headroom)


def _tier_for(is_champs):
    """Return (grace, rate, escalate_after, escalate_rate) for a tier.

    Centralizes tier constants. The returned grace is BASE only - callers add
    self.dead_days for the effective grace."""
    if is_champs:
        return (core.DECAY_GRACE_DAYS, core.DECAY_RATE,
                core.DECAY_ESCALATE_AFTER_DAYS, core.DECAY_ESCALATE_RATE)
    return (core.DECAY_GRACE_DAYS_NONCHAMPS, core.DECAY_RATE_NONCHAMPS,
            core.DECAY_ESCALATE_AFTER_DAYS_NONCHAMPS, core.DECAY_ESCALATE_RATE_NONCHAMPS)


def _member_has_champs(guild, champs_role, discord_id):
    """True if the member holds the Champs role. (sync, in-cache lookup).

    A member not in the cache returns False - treated as non-Champs (conservative,
    matching selfroles/registration patterns)."""
    if champs_role is None:
        return False
    member = guild.get_member(int(discord_id))
    if member is None:
        return False
    return champs_role in member.roles


class Decay(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.decay_applied, self.below_threshold, self.dead_days = load_state()

    def cog_unload(self):
        self.daily_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not core.DECAY_ENABLED:
            logger.info("Decay loop disabled (DECAY_ENABLED=0).")
            return
        if not core.NEATQUEUE_TOKEN:
            logger.warning("Decay loop not starting - NEATQUEUE_TOKEN unset.")
            return
        if not self.daily_loop.is_running():
            self.daily_loop.start()
            mode = "DRY-RUN" if core.DECAY_DRYRUN else "LIVE"
            logger.info("Decay loop started (%s mode).", mode)

    @tasks.loop(time=dtime(hour=0, minute=5, tzinfo=timezone.utc))
    async def daily_loop(self):
        try:
            await self.run_sweep()
        except Exception as e:
            logger.error("Decay loop error: %s", e, exc_info=True)

    @daily_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ---------- core sweep ----------

    async def run_sweep(self):
        """One daily pass: decay idle players (tiered), then reconcile the gate.

        Dead-day detection runs first: if no matches in the last 24h, everyone is
        exempt and dead_days accrues."""
        guild = self.bot.get_guild(int(core.GUILD_ID)) if core.GUILD_ID else None
        if guild is None:
            logger.warning("Decay sweep: guild %s not found.", core.GUILD_ID)
            return 0

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # ---- dead-day detection (structural-impossibility fairness) ----
        recent = await asyncio.to_thread(core.nq_recent_match_count, 24)
        if recent == 0:
            if not core.DECAY_DRYRUN:
                self.dead_days += 1
                save_state(self.decay_applied, self.below_threshold, self.dead_days)
            await self._report_dead_day(self.dead_days, now)
            return 0
        if recent > 0 and self.dead_days:
            if not core.DECAY_DRYRUN:
                self.dead_days = 0

        did_map = await asyncio.to_thread(core.discord_id_map)
        champs_role = guild.get_role(core.CHAMPS_ROLE_ID) if core.CHAMPS_ROLE_ID else None

        decay_lines = []
        decay_count = 0
        skipped_exempt = 0
        skipped_notinq = 0
        errors = 0

        for did in did_map:
            try:
                info = await asyncio.to_thread(core.nq_get_mmr, did)
            except Exception as e:
                logger.error("nq_get_mmr failed for %s: %s", did, e)
                errors += 1
                continue
            if info is None:
                skipped_notinq += 1
                continue
            mmr, last_match_unix, total_games = info

            if total_games < core.PLACEMENT_GAMES:
                skipped_exempt += 1
                continue

            # ---- tier selection ----
            is_champs = _member_has_champs(guild, champs_role, did)
            base_grace, rate, escalate_after, escalate_rate = _tier_for(is_champs)
            effective_grace = base_grace + self.dead_days

            # ---- decay step ----
            if last_match_unix > 0:
                last_dt = datetime.fromtimestamp(last_match_unix, tz=timezone.utc)
                idle_days = int((now - last_dt).total_seconds() // 86400)
            else:
                idle_days = effective_grace + 1

            key = _decay_key(date_str, did)
            if key in self.decay_applied:
                continue

            amount = compute_daily_decay(
                idle_days, mmr,
                grace=effective_grace, rate=rate,
                escalate_after=escalate_after, escalate_rate=escalate_rate)
            if amount <= 0:
                continue

            tier_label = "Champs" if is_champs else "non-Champs"
            if core.DECAY_DRYRUN:
                decay_lines.append(
                    f"`{did}` ({tier_label}): dry-run (would be -{amount}, idle {idle_days}d)")
                continue
            try:
                await asyncio.to_thread(core.nq_add_mmr, did, -amount)
                self.decay_applied.add(key)
                decay_count += 1
                decay_lines.append(
                    f"`{did}` ({tier_label}): **-{amount}** (idle {idle_days}d, was {mmr:.0f})")
            except Exception as e:
                msg = str(e)
                if "not found" in msg.lower():
                    skipped_notinq += 1
                    logger.info("Decay skipped %s - not in NeatQueue DB.", did)
                else:
                    errors += 1
                    logger.error("nq_add_mmr (decay) failed for %s: %s", did, e)

        # ---- eligibility gate step (Champs holders only) ----
        gate_actions = await self._reconcile_gate(did_map, guild, champs_role)

        if decay_lines or decay_count or gate_actions or not core.DECAY_DRYRUN:
            save_state(self.decay_applied, self.below_threshold, self.dead_days)

        await self._report_sweep(decay_lines, decay_count, skipped_exempt,
                                 skipped_notinq, errors, gate_actions, now)
        return decay_count

    async def _reconcile_gate(self, did_map, guild, champs_role):
        """Recompute which CHAMPS HOLDERS should be below threshold and toggle
        roles for the diff. Non-Champs are never gated."""
        if not core.REGISTERED_ROLE_ID:
            return []
        role = guild.get_role(core.REGISTERED_ROLE_ID)
        if role is None:
            logger.warning("Registered role %d not found.", core.REGISTERED_ROLE_ID)
            return []

        currently_below = set()
        mmr_cache = {}
        for did in did_map:
            if not _member_has_champs(guild, champs_role, did):
                continue
            try:
                info = await asyncio.to_thread(core.nq_get_mmr, did)
            except Exception:
                continue
            if info is None:
                continue
            mmr, _last, total_games = info
            mmr_cache[did] = mmr
            if total_games < core.PLACEMENT_GAMES:
                continue
            if mmr < core.DECAY_THRESHOLD:
                currently_below.add(did)

        to_ban = currently_below - self.below_threshold
        to_restore = self.below_threshold - currently_below

        actions = []
        if core.DECAY_DRYRUN:
            for did in to_ban:
                actions.append(f"`{did}`: dry-run (would revoke, mmr {mmr_cache.get(did, 0):.0f})")
            for did in to_restore:
                actions.append(f"`{did}`: dry-run (would restore, mmr {mmr_cache.get(did, 0):.0f})")
            return actions

        for did in to_ban:
            ok = await self._revoke(guild, role, did)
            if ok:
                actions.append(f"revoked `{did}` (mmr {mmr_cache.get(did, 0):.0f} < {core.DECAY_THRESHOLD})")
        for did in to_restore:
            ok = await self._restore(guild, role, did)
            if ok:
                actions.append(f"restored `{did}` (mmr {mmr_cache.get(did, 0):.0f} >= {core.DECAY_THRESHOLD})")

        self.below_threshold = currently_below
        return actions

    async def _revoke(self, guild, role, discord_id):
        """Remove the Registered role and DM the player. Never raises."""
        member = guild.get_member(int(discord_id))
        if member is None:
            return False
        try:
            if role in member.roles:
                await member.remove_roles(role, reason=f"MMR below {core.DECAY_THRESHOLD} (decay gate)")
            await self._dm(
                member,
                "Your MMR dropped below **%d**, so your queue access is temporarily revoked. "
                "Play matches to raise it back above **%d** and access will be restored automatically."
                % (core.DECAY_THRESHOLD, core.DECAY_THRESHOLD))
            return True
        except discord.Forbidden:
            logger.error("Missing permission to remove Registered role from %s.", discord_id)
            return False
        except Exception as e:
            logger.error("Revoke failed for %s: %s", discord_id, e)
            return False

    async def _restore(self, guild, role, discord_id):
        """Re-grant the Registered role and DM the player. Never raises."""
        member = guild.get_member(int(discord_id))
        if member is None:
            return False
        try:
            if role not in member.roles:
                await member.add_roles(role, reason=f"MMR recovered above {core.DECAY_THRESHOLD} (decay gate)")
            await self._dm(
                member,
                "Your MMR is back above **%d** - queue access restored. GLHF!" % core.DECAY_THRESHOLD)
            return True
        except discord.Forbidden:
            logger.error("Missing permission to grant Registered role to %s.", discord_id)
            return False
        except Exception as e:
            logger.error("Restore failed for %s: %s", discord_id, e)
            return False

    async def _dm(self, member, content):
        """Best-effort DM; closed DMs are logged but never fatal."""
        try:
            await member.send(content)
        except discord.Forbidden:
            logger.info("DM to %s skipped - DMs closed.", member.id)
        except Exception as e:
            logger.warning("DM to %s failed: %s", member.id, e)

    async def _report_dead_day(self, dead_days, now):
        """Staff-log note when the queue was dead and everyone was exempt."""
        embed = discord.Embed(
            title="Decay Sweep - Dead Day",
            description=(f"{now.strftime('%Y-%m-%d %H:%M')} UTC\n"
                         f"No matches in last 24h - everyone exempt today.\n"
                         f"Accumulated dead days: **{dead_days}** (grace +{dead_days}d)."),
            color=0x95A5A6)
        await core.send_staff_log(self.bot, embed=embed)

    async def _report_sweep(self, decay_lines, decay_count, skipped_exempt,
                            skipped_notinq, errors, gate_actions, now):
        """Staff-log summary of the sweep."""
        mode = "DRY-RUN" if core.DECAY_DRYRUN else "LIVE"
        summary = (f"Decay: **{decay_count}** applied - {skipped_exempt} exempt - "
                   f"{skipped_notinq} not in NQ - {errors} errors\n"
                   f"Gate actions: **{len(gate_actions)}** - dead_days: **{self.dead_days}**")
        embed = discord.Embed(
            title="Daily Decay & Eligibility Sweep",
            description=f"{mode} - {now.strftime('%Y-%m-%d %H:%M')} UTC\n{summary}",
            color=0xF1C40F if core.DECAY_DRYRUN else 0x2ECC71)
        if decay_lines:
            embed.add_field(name="MMR decay", value="\n".join(decay_lines)[:1024], inline=False)
        if gate_actions:
            embed.add_field(name="Eligibility gate", value="\n".join(gate_actions)[:1024], inline=False)
        if not decay_lines and not gate_actions:
            embed.add_field(name="Result", value="Nothing to do - no idle players and no gate changes.", inline=False)
        embed.set_footer(
            text=(f"Champs: grace {core.DECAY_GRACE_DAYS}+{self.dead_days}d - "
                  f"rate {core.DECAY_RATE}->{core.DECAY_ESCALATE_RATE} @ {core.DECAY_ESCALATE_AFTER_DAYS}d | "
                  f"non-Champs: grace {core.DECAY_GRACE_DAYS_NONCHAMPS}+{self.dead_days}d - "
                  f"rate {core.DECAY_RATE_NONCHAMPS}->{core.DECAY_ESCALATE_RATE_NONCHAMPS} "
                  f"@ {core.DECAY_ESCALATE_AFTER_DAYS_NONCHAMPS}d | "
                  f"floor {core.DECAY_FLOOR} - threshold {core.DECAY_THRESHOLD} (Champs only)"))
        await core.send_staff_log(self.bot, embed=embed)

    # ---------- near-realtime hook (called from cogs/mmr.py) ----------

    async def check_threshold_for_player(self, discord_id):
        """Single-player threshold check after a match modifier. Only the 800
        gate, and ONLY for Champs holders. Never raises."""
        try:
            if not core.REGISTERED_ROLE_ID or not core.GUILD_ID:
                return
            guild = self.bot.get_guild(int(core.GUILD_ID))
            if guild is None:
                return
            champs_role = guild.get_role(core.CHAMPS_ROLE_ID) if core.CHAMPS_ROLE_ID else None
            if not _member_has_champs(guild, champs_role, discord_id):
                return
            info = await asyncio.to_thread(core.nq_get_mmr, discord_id)
            if info is None:
                return
            mmr, _last, total_games = info
            if total_games < core.PLACEMENT_GAMES:
                return

            should_be_below = mmr < core.DECAY_THRESHOLD
            is_below = discord_id in self.below_threshold
            if should_be_below == is_below:
                return
            if core.DECAY_DRYRUN:
                return

            role = guild.get_role(core.REGISTERED_ROLE_ID)
            if role is None:
                return
            if should_be_below:
                await self._revoke(guild, role, discord_id)
                self.below_threshold.add(discord_id)
            else:
                await self._restore(guild, role, discord_id)
                self.below_threshold.discard(discord_id)
            save_state(self.decay_applied, self.below_threshold, self.dead_days)
        except Exception as e:
            logger.error("check_threshold_for_player(%s) failed: %s", discord_id, e)

    # ---------- staff commands ----------

    @app_commands.command(name="decaystatus",
                          description="Check a player's MMR, idle days, and decay status (staff only).")
    @app_commands.describe(member="The player to inspect (defaults to yourself).")
    async def decay_status(self, interaction: discord.Interaction, member: discord.Member = None):
        if not core.is_staff(interaction):
            await interaction.response.send_message("This command is restricted to Staff.", ephemeral=True)
            return
        target = member or interaction.user
        discord_id = str(target.id)
        await interaction.response.defer(ephemeral=True)
        try:
            info = await asyncio.to_thread(core.nq_get_mmr, discord_id)
            if info is None:
                await interaction.followup.send(f"No NeatQueue record for **{target.display_name}**.", ephemeral=True)
                return
            mmr, last_match_unix, total_games = info
            now = datetime.now(timezone.utc)
            if last_match_unix > 0:
                last_dt = datetime.fromtimestamp(last_match_unix, tz=timezone.utc)
                idle_days = int((now - last_dt).total_seconds() // 86400)
                idle_str = f"{idle_days} day(s) (last match {last_dt.strftime('%Y-%m-%d')})"
            else:
                idle_days = core.DECAY_GRACE_DAYS + self.dead_days + 1
                idle_str = "no match on record"

            champs_role = (interaction.guild.get_role(core.CHAMPS_ROLE_ID)
                           if interaction.guild and core.CHAMPS_ROLE_ID else None)
            is_champs = bool(champs_role and champs_role in target.roles)
            base_grace, rate, escalate_after, escalate_rate = _tier_for(is_champs)
            effective_grace = base_grace + self.dead_days
            next_decay = compute_daily_decay(
                idle_days, mmr,
                grace=effective_grace, rate=rate,
                escalate_after=escalate_after, escalate_rate=escalate_rate)
            gated = discord_id in self.below_threshold
            exempt = total_games < core.PLACEMENT_GAMES

            embed = discord.Embed(
                title=f"Decay status - {target.display_name}",
                color=0xE67E22 if gated else 0x2ECC71)
            embed.add_field(name="MMR", value=f"{mmr:.0f}", inline=True)
            embed.add_field(name="Total games", value=str(total_games), inline=True)
            embed.add_field(name="Idle", value=idle_str, inline=True)
            embed.add_field(
                name="Tier",
                value=("Champs" if is_champs else "non-Champs") + f" (grace {effective_grace}d)",
                inline=True)
            embed.add_field(
                name="Next decay",
                value="exempt (placement)" if exempt
                      else ("none (within grace)" if next_decay <= 0 else f"-{next_decay}/day"),
                inline=True)
            access = ("revoked (< %d)" % core.DECAY_THRESHOLD if gated
                      else "granted" if not exempt else "(exempt)")
            if not is_champs:
                access += " (non-Champs: not gated)"
            embed.add_field(name="Queue access", value=access, inline=True)
            embed.set_footer(text=f"Threshold {core.DECAY_THRESHOLD} (Champs only) - floor {core.DECAY_FLOOR} - dead_days {self.dead_days}")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error("decaystatus error: %s", e, exc_info=True)
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="decayrun",
                          description="Run the daily decay & eligibility sweep now (staff only).")
    async def decay_run(self, interaction: discord.Interaction):
        if not core.is_staff(interaction):
            await interaction.response.send_message("This command is restricted to Staff.", ephemeral=True)
            return
        if not core.NEATQUEUE_TOKEN:
            await interaction.response.send_message("`NEATQUEUE_TOKEN` is not configured.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            n = await self.run_sweep()
            mode = "dry-run" if core.DECAY_DRYRUN else "LIVE"
            await interaction.followup.send(
                f"Sweep complete ({mode}): **{n}** player(s) decayed. Details posted to staff log.",
                ephemeral=True)
        except Exception as e:
            logger.error("decayrun error: %s", e, exc_info=True)
            await interaction.followup.send(f"Error: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Decay(bot))
