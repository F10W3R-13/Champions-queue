"""Impact-based MMR modifier.

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
from datetime import datetime, timezone, timedelta

import core

logger = logging.getLogger("CQ_Bot.mmr")

STATE_FILE = "mmr_state.json"
DISCORD_EPOCH_MS = 1420070400000
MATCH_WINDOW_HOURS = 4      # screenshots for a match must be posted within this window
# Look BACK this far from mtime when scanning for impact records. NeatQueue's
# mtime is the SERIES end (e.g. the Bo3-clinching game), but OCR screenshots are
# posted after each individual game — which can be earlier than the series end.
# Without this lookback, game-1/game-2 screenshots fall before the window and
# the modifier sees no data.
MATCH_WINDOW_LOOKBACK = 2
MAX_MATCH_AGE_HOURS = 48    # ignore matches older than this (startup backlog guard)
# When a player has multiple impact records in a window (because two close
# NeatQueue matches have overlapping windows AND the player played in both),
# only cluster the records from the SAME series. Games within one Bo3 are
# typically posted 30-90 min apart; a record farther than this from the match
# mtime belongs to a different match and must not pollute the average.
SERIES_CLUSTER_MINUTES = 30


def snowflake_dt(message_id):
    """Discord snowflake -> aware datetime (records' Match ID is a message id)."""
    ms = (int(message_id) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def load_state():
    """Returns (processed_set, backfilled_set, applied_set).
    - processed/backfilled: match-level dedup, keyed by match_key().
    - applied: player+match-level dedup, keyed by '{discord_id}|{match_key}'.
      Tracks exactly which (player, match) combos have received a modifier, so a
      newly-linked player can be backfilled without double-applying to the other 9.
    All absent in older state files -> empty sets (backwards compatible)."""
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        processed = set(data.get("processed", []))
        backfilled = set(data.get("backfilled", []))
        applied = set(data.get("applied", []))
        return processed, backfilled, applied
    except Exception:
        return set(), set(), set()


def save_state(processed, backfilled, applied):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "processed": list(processed)[-500:],
                "backfilled": list(backfilled)[-500:],
                # player+match keys are numerous; cap to keep the file bounded.
                "applied": list(applied)[-2000:],
            }, f)
    except Exception as e:
        logger.error("Could not save MMR state: %s", e)


def _applied_key(discord_id, match_key):
    """Per-(player, match) idempotency key for the applied set."""
    return f"{discord_id}|{match_key}"


def compute_modifier(impact):
    """Map a single impact value to an integer MMR modifier (±MMR_MODIFIER_MAX).

    Absolute Impact band: MIN -> -MAX, MAX -> +MAX, linear; neutral = midpoint.
    Factored out so both the per-match loop and the per-player backfill use the
    exact same formula."""
    lo, hi, cap = core.MMR_IMPACT_MIN, core.MMR_IMPACT_MAX, core.MMR_MODIFIER_MAX
    mid = (lo + hi) / 2.0
    half = (hi - lo) / 2.0 or 1.0
    imp_clamped = max(lo, min(hi, impact))
    return int(round((imp_clamped - mid) / half * cap))


def impacts_in_window(start_dt, end_dt, participant_pids=None, target_mtime=None):
    """{player_record_id: [impact, ...]} from HP+SND records posted in the window. (sync)

    Two optional disambiguators prevent cross-match contamination when windows
    overlap (two NeatQueue matches within ~6h of each other):

    - participant_pids: if given (a set of Airtable player record ids), only
      records belonging to players in THIS match are returned. A player who
      appeared in a neighbouring match but not this one is excluded.
    - target_mtime: if given, a player's records are clustered to the SAME
      series — only those whose snowflake time is within SERIES_CLUSTER_MINUTES
      of target_mtime are kept. This drops a participant's records that actually
      belong to a different (nearby) match, so their impact isn't averaged with
      the wrong game.

    With neither argument the behaviour is identical to the original (whole-
    window scan), preserving the per-player backfill's single-player use case.
    """
    out = {}
    # pid -> list of (impact, timestamp) so we can cluster after collecting.
    raw = {}
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
            if participant_pids is not None and pid not in participant_pids:
                continue
            raw.setdefault(pid, []).append((float(imp), ts))

    cluster = timedelta(minutes=SERIES_CLUSTER_MINUTES)
    for pid, pairs in raw.items():
        if target_mtime is not None and len(pairs) > 1:
            # Keep only records from the same series as the closest one to mtime.
            closest = min(pairs, key=lambda it: abs((it[1] - target_mtime).total_seconds()))
            pairs = [p for p in pairs if abs((p[1] - closest[1]).total_seconds()) <= cluster.total_seconds()]
        out[pid] = [imp for imp, _ts in pairs]
    return out


class MMRModifier(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.processed, self.backfilled, self.applied = load_state()

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

            try:
                result = await self.apply_modifiers_for_match(m, mtime, changes)
            except Exception as e:
                # A single match must never abort the whole pass — otherwise the
                # failure isn't marked `processed`, so the NEXT pass re-runs the
                # same match and re-applies every modifier (double/MMR-spike bug).
                # The applied-set guards against a true double-apply now, but we
                # still mark this match processed so one bad payload can't wedge
                # the loop forever.
                logger.error("apply_modifiers_for_match crashed for match %s: %s", key, e, exc_info=True)
                await core.send_staff_log(
                    self.bot,
                    content=(f"⚠️ MMR modifier crashed processing match at `{m.get('time')}` "
                             f"({key}): `{e}`. Marking processed to avoid a re-process loop; "
                             f"per-(player,match) `applied` set prevents any double-apply."))
                self.processed.add(key)
                continue
            if result == "retry":
                # OCR data not ready yet — do NOT mark as processed; retry next pass.
                # The 48h max-age guard (above) is the eventual backstop.
                continue
            self.processed.add(key)
            handled += 1
            if result:
                await core.send_staff_log(self.bot, embed=result)
        if handled:
            save_state(self.processed, self.backfilled, self.applied)
        if announce_empty and not handled:
            return 0
        return handled

    async def apply_modifiers_for_match(self, m, mtime, changes):
        # Window starts BEFORE mtime because NeatQueue's mtime is the series end
        # (e.g. Bo3 game-2 clinch), while OCR screenshots are posted after each
        # game ends — which can be earlier than the series end. Look back a couple
        # hours to catch game-1/game-2 screenshots, then forward 4h for late posts.
        window_start = mtime - timedelta(hours=MATCH_WINDOW_LOOKBACK)
        window_end = mtime + timedelta(hours=MATCH_WINDOW_HOURS)
        did_map = await asyncio.to_thread(core.discord_id_map)          # discord_id -> pid
        directory = await asyncio.to_thread(core.player_directory_cached)  # pid -> (ign, handle)
        # Restrict the impact scan to this match's actual participants (by Airtable
        # player record id) and cluster records to the same series. Without this,
        # overlapping windows between two close matches let one match's impact data
        # contaminate the other's average.
        participant_pids = {did_map[did] for did in changes if did in did_map}
        impacts = await asyncio.to_thread(
            impacts_in_window, window_start, window_end,
            participant_pids=participant_pids or None, target_mtime=mtime)

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
        mk = self.match_key(m)

        mode = "🧪 DRY-RUN (not applied)" if core.MMR_MODIFIER_DRYRUN else "✅ APPLIED"
        lines = []
        for did, imp in sorted(player_imp.items(), key=lambda kv: kv[1], reverse=True):
            mod = compute_modifier(imp)
            pid = did_map.get(did)
            ign = directory.get(pid, ("?", ""))[0] if pid else "?"
            applied = ""
            apk = _applied_key(did, mk)
            if mod and not core.MMR_MODIFIER_DRYRUN:
                if apk in self.applied:
                    # Already applied to this (player, match) — e.g. a previous pass
                    # crashed mid-way (see process_new_matches try/except) but had
                    # already sent the nq_add_mmr call. Skip to avoid double-applying.
                    applied = " ⊙ already applied"
                else:
                    try:
                        await asyncio.to_thread(core.nq_add_mmr, did, mod)
                        applied = " ✔"
                        # Record per-(player, match) so a later /link backfill — or a
                        # re-process of this match after a mid-pipeline crash — skips
                        # this combo and never double-applies.
                        self.applied.add(apk)
                    except Exception as e:
                        msg = str(e)
                        if "not found" in msg.lower():
                            # NeatQueue has no player record for this user (never queued, or
                            # cleaned up). This is permanent for this match — not a transient
                            # error, so downgrade from ERROR to INFO to avoid log noise.
                            applied = " ⏭ not in NQ"
                            logger.info("nq_add_mmr skipped %s in match %s — not in NeatQueue DB.", did, mk)
                        else:
                            applied = f" ⚠ failed: {e}"
                            logger.error("nq_add_mmr failed for %s: %s", did, e)
            sign = "+" if mod >= 0 else ""
            wl = "W" if changes.get(did, 0) > 0 else "L"
            lines.append(f"`{sign}{mod:>5}` **{ign}** ({wl}, impact {imp:.0f}){applied}")

        embed = discord.Embed(
            title="🎯 Impact MMR Modifier",
            description=(f"Match `{m.get('time')}` • queue `{m.get('game', '?')}`\n"
                         f"Impact {lo:g}→−{cap:g} … {hi:g}→+{cap:g} (neutral {(lo+hi)/2:g}) • "
                         f"{len(player_imp)}/{len(changes)} with data\nMode: **{mode}**"),
            color=0xF1C40F if core.MMR_MODIFIER_DRYRUN else 0x2ECC71
        )
        embed.add_field(name="Modifiers", value="\n".join(lines)[:1024], inline=False)

        # Mirror a compact, player-facing summary to the public channel (if set).
        # Only when modifiers were actually applied (not dry-run), so the public
        # channel never shows "DRY-RUN" noise. Staff-logs still gets the full embed.
        if not core.MMR_MODIFIER_DRYRUN and core.MMR_PUBLIC_CHANNEL_ID and lines:
            await self._mirror_to_public(m, lines)

        # Near-realtime 800-point eligibility hook: a loss here may have dropped a
        # player under the queue threshold, so let the decay cog act within minutes
        # instead of waiting for the daily sweep. Decay itself is NOT done here —
        # only the gate. Wrapped so a decay-cog failure can never poison the
        # modifier pipeline. The cog may be absent (not loaded) -> safe no-op.
        try:
            decay_cog = self.bot.get_cog("Decay")
            if decay_cog:
                for did in changes:
                    await decay_cog.check_threshold_for_player(did)
        except Exception as e:
            logger.error("Decay threshold hook failed (non-fatal): %s", e)

        return embed

    async def _mirror_to_public(self, m, lines):
        """Post a compact, player-facing modifier summary to the public channel.
        Failures are logged but never break the modifier pipeline."""
        try:
            channel = self.bot.get_channel(core.MMR_PUBLIC_CHANNEL_ID)
            if channel is None:
                return
            public = discord.Embed(
                title="📊 Performance MMR Adjustments",
                description=(f"Match `{m.get('time')}` — impact-based adjustments applied "
                             f"on top of the base win/loss MMR:"),
                color=0x2ECC71)
            public.add_field(name="Adjustments", value="\n".join(lines)[:1024], inline=False)
            public.set_footer(text="Well-played games earn bonus MMR · poor play loses extra")
            public.timestamp = datetime.now(timezone.utc)
            await channel.send(embed=public)
        except Exception as e:
            logger.error("Failed to mirror modifier summary to public channel: %s", e)

    # ---------- staff command ----------

    @app_commands.command(name="applymodifiers", description="Process new NeatQueue matches for Impact MMR modifiers now (staff only).")
    async def apply_now(self, interaction: discord.Interaction):
        if not core.is_staff(interaction):
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
        if not core.is_staff(interaction):
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

            save_state(self.processed, self.backfilled, self.applied)
            await interaction.followup.send(
                f"✅ Backfill complete: **{applied_matches}** match(es) processed, "
                f"{skipped_no_data} skipped (no impact data), {mode}.")
        except Exception as e:
            logger.error("backfillmodifiers error: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}")

    # ---------- per-player backfill (called after /link or /ign) ----------

    async def apply_modifiers_for_player(self, discord_id, player_name, count=20):
        """After a player's records are newly linked (via /link or /ign), find
        their recent NeatQueue matches and apply their Impact modifier — without
        re-applying to the other players in those matches.

        Idempotency is per (discord_id, match_key) via self.applied, so this is
        safe to call multiple times and never double-applies. A match where the
        player was previously unmatched (no Player link → invisible to the per-match
        loop) gets caught here now that they're linked.

        Runs as a background task from /link and /ign, so it must never raise."""
        try:
            history = await asyncio.to_thread(core.nq_history)
            if not isinstance(history, list):
                logger.warning("apply_modifiers_for_player: history not a list.")
                return

            # Find recent matches this player participated in (newest first).
            targets = []
            for m in history:
                if not isinstance(m, dict):
                    continue
                mtime, changes = self.parse_match(m)
                if mtime is None or discord_id not in changes:
                    continue
                mk = self.match_key(m)
                targets.append((mtime, mk, m))
            targets.sort(key=lambda t: t[0], reverse=True)
            targets = targets[:count]

            if not targets:
                logger.info("apply_modifiers_for_player(%s): no matches found.", player_name)
                return

            did_map = await asyncio.to_thread(core.discord_id_map)
            pid = did_map.get(discord_id)
            if not pid:
                logger.info("apply_modifiers_for_player(%s): player not in Airtable yet.", player_name)
                return

            applied_lines = []
            applied_count = 0
            skipped = 0
            dryrun_count = 0
            no_data = 0
            for mtime, mk, m in targets:
                apk = _applied_key(discord_id, mk)
                if apk in self.applied:
                    skipped += 1
                    continue
                # Look up this player's impact in the match's time window (same
                # method as the per-match loop — look back + forward window average,
                # scoped to this player and clustered to this match's series so a
                # nearby match the same player was in can't contaminate the average.
                window_start = mtime - timedelta(hours=MATCH_WINDOW_LOOKBACK)
                window_end = mtime + timedelta(hours=MATCH_WINDOW_HOURS)
                impacts = await asyncio.to_thread(
                    impacts_in_window, window_start, window_end,
                    participant_pids={pid}, target_mtime=mtime)
                imp_list = impacts.get(pid)
                if not imp_list:
                    # Player still has no impact data (screenshots not posted or
                    # still unmatched). Skip without marking applied — retryable
                    # on the next link/registration event.
                    no_data += 1
                    continue
                imp = sum(imp_list) / len(imp_list)
                mod = compute_modifier(imp)
                if mod == 0:
                    self.applied.add(apk)  # neutral; record so we don't recompute
                    continue
                if core.MMR_MODIFIER_DRYRUN:
                    # Do NOT stamp `applied`: nothing was actually written to
                    # NeatQueue, so a later LIVE run (or the per-match loop) must
                    # still be free to apply it. Marking it here would silently
                    # drop this (player, match) forever once dry-run ends.
                    dryrun_count += 1
                    applied_lines.append(f"`{m.get('time')}`: dry-run (would be {mod:+d})")
                    continue
                try:
                    await asyncio.to_thread(core.nq_add_mmr, discord_id, mod)
                    self.applied.add(apk)
                    applied_count += 1
                    applied_lines.append(f"`{m.get('time')}`: **{mod:+d}** (impact {imp:.0f})")
                except Exception as e:
                    logger.error("apply_modifiers_for_player nq_add_mmr failed (%s, %s): %s",
                                 player_name, mk, e)

            save_state(self.processed, self.backfilled, self.applied)

            # Staff-log summary (only if something happened).
            if applied_lines or skipped:
                bits = [f"applied to **{applied_count}**"]
                if dryrun_count:
                    bits.append(f"{dryrun_count} dry-run")
                bits.append(f"{skipped} already applied")
                bits.append(f"{no_data} no impact data")
                summary = (f"🔗 **{player_name}** (`{discord_id}`) linked — " + ", ".join(bits) + ".")
                detail = "\n".join(applied_lines) if applied_lines else "_(none — all already applied or no impact data)_"
                embed = discord.Embed(
                    title="🎯 Per-player MMR backfill",
                    description=summary,
                    color=0x2ECC71 if applied_count else 0xF1C40F)
                embed.add_field(name="Matches", value=detail[:1024], inline=False)
                await core.send_staff_log(self.bot, embed=embed)
            logger.info("apply_modifiers_for_player(%s): %d applied, %d dry-run, %d skipped, %d no data.",
                        player_name, applied_count, dryrun_count, skipped, no_data)
        except Exception as e:
            logger.error("apply_modifiers_for_player(%s) failed: %s", player_name, e, exc_info=True)


async def setup(bot):
    await bot.add_cog(MMRModifier(bot))
