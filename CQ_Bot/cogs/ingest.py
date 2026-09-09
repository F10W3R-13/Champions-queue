import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
import os
import time

import core

logger = logging.getLogger("CQ_Bot.ingest")

# --- Airtable monthly-quota guard ---------------------------------------
# Airtable Free/Team plans have a HARD monthly API call budget (1K / 100K).
# The old 45s reconcile polling burned ~5,000 calls/day (~150K/month) and
# exhausted the workspace quota while the community was idle. Reconcile is a
# SAFETY NET (normal path matches inline at ingest), so:
#   - default period is now 6h (env-tunable, e.g. RECONCILE_PERIOD_SECONDS=45
#     to restore the old behaviour for active seasons);
#   - when Airtable returns the monthly-limit error (429 billing), the loop
#     backs off to once every 24h until the quota resets (1st of month UTC).
RECONCILE_PERIOD_SECONDS = int(os.getenv('RECONCILE_PERIOD_SECONDS', '43200'))  # 12h
QUOTA_BACKOFF_SECONDS = int(os.getenv('QUOTA_BACKOFF_SECONDS', '86400'))        # 24h
_BILLING_LIMIT_MARKERS = ("PUBLIC_API_BILLING_LIMIT_EXCEEDED", "billing plan limit")


def _looks_like_billing_limit(exc: Exception) -> bool:
    """True if an Airtable exception smells like the monthly quota error."""
    return any(m in str(exc) for m in _BILLING_LIMIT_MARKERS)


async def _find_record(record_id):
    """Fetch a record from HP, then SND. Returns (record, table, mode) or (None, None, "")."""
    for table, mode in ((core.hp_table, "HP"), (core.snd_table, "SND")):
        try:
            record = await asyncio.to_thread(table.get, record_id)
            return record, table, mode
        except Exception:
            continue
    return None, None, ""


class Ingest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._quota_backoff_until = 0.0  # monotonic-ish wall clock; 0 = no backoff

    def cog_unload(self):
        self.reconcile_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.reconcile_loop.is_running():
            self.reconcile_loop.start()
            logger.info("Reconcile loop started.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.channel.id == core.RESULTS_CHANNEL_ID and message.attachments:
            imgs = [a for a in message.attachments
                    if (a.content_type or "").startswith("image")
                    or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
            if len(imgs) >= 2:
                await self.handle_results_screenshots(message, imgs[0], imgs[1])

    async def handle_results_screenshots(self, message, img1, img2):
        try:
            await message.add_reaction("⏳")  # hourglass
        except discord.HTTPException:
            pass
        try:
            data = await core.run_ocr(img1.url, img2.url)
            if not data or "result" not in data:
                await message.channel.send(
                    "Couldn't read the scoreboard. Please post two clear screenshots in the same message.")
                return
            mode = str(data.get("mode", "")).upper()
            if mode not in ("HP", "SND"):
                await message.channel.send("Could not determine the game mode (HP/SND).")
                return
            match_id = str(message.id)
            date_str = message.created_at.date().isoformat()
            async with core.airtable_lock:
                if await asyncio.to_thread(core.match_id_exists, mode, match_id):
                    await message.add_reaction("♻️")  # already ingested
                    return
                summary = await asyncio.to_thread(core.ingest_match, data, match_id, date_str)
            await message.add_reaction("✅")
            mp = (data.get("map") or "?").strip() or "?"
            await message.channel.send(
                "**%s** | %s - logged **%d** players (matched %d / review %d / unmatched %d)."
                % (mode, mp, summary["created"], summary["matched"],
                   summary["review"], summary["unmatched"]))
            
            # Send review alerts to staff log channel if there are any review items
            review_records = [r for r in summary["records"] if r["fields"].get("Status") == core.STATUS_REVIEW]
            if review_records:
                table_id = core.SND_TABLE_ID if mode == "SND" else core.HP_TABLE_ID
                links = []
                for r in review_records:
                    ign = r["fields"].get(core.RAW_IGN_FIELD, "Unknown")
                    link = f"https://airtable.com/{core.BASE_ID}/{table_id}/{r['id']}"
                    links.append(f"- **{ign}**: [Airtable Record]({link})")
                
                mentions_str = "\n".join(links)
                await core.send_staff_log(
                    self.bot,
                    content=f"⚠️ **Needs Review** in Match {match_id} ({mode} - {mp}):\n{mentions_str}"
                )
        except Exception as e:
            logger.error("OCR ingest error: %s", e, exc_info=True)
            await message.channel.send(
                "An error occurred while reading the scoreboard. Re-post the two screenshots in one message, "
                "or an admin can check the logs.")
            # Staff notification for exceptions
            import traceback
            tb = traceback.format_exc()
            await core.send_staff_log(
                self.bot,
                content=f"🚨 **OCR Ingestion Exception** on Message {message.id} ({message.jump_url}):\n```py\n{tb[:1800]}\n```"
            )
        finally:
            try:
                await message.remove_reaction("⏳", self.bot.user)
            except discord.HTTPException:
                pass

    @tasks.loop(seconds=RECONCILE_PERIOD_SECONDS)
    async def reconcile_loop(self):
        """Safety-net loop. Normal path is inline-matched at ingest, so usually 0.

        Period is env-tunable (default 6h — see RECONCILE_PERIOD_SECONDS). This
        is a quota-preservation measure: Airtable's monthly API budget is hard,
        and the old 45s cadence burned it while idle. On the monthly-limit
        error (429 billing) the loop backs off to once every 24h until the
        quota resets. matcher.reload() stays TTL-gated (5 min) inside
        reload_matcher_if_stale() — bot-driven mutations refresh eagerly."""
        if time.time() < self._quota_backoff_until:
            return  # monthly quota exhausted — minimal probing only
        try:
            async with core.airtable_lock:
                if not core.matcher.roster and not core.matcher.candidates:
                    # Cold boot fell back to an empty cache (Airtable was
                    # down/quota-dead at import). Keep retrying eagerly —
                    # ignoring the TTL — until the backend answers, then the
                    # normal TTL cadence takes over.
                    reloaded = await asyncio.to_thread(
                        core.reload_matcher_if_stale, True)
                    if reloaded:
                        logger.info("Matcher cache recovered after cold-boot fallback.")
                else:
                    reloaded = await asyncio.to_thread(core.reload_matcher_if_stale)
                s = await asyncio.to_thread(core.reconcile_once)
            if reloaded or s["matched"] or s["review"]:
                logger.info("reconcile: reload=%s matched=%d review=%d unmatched=%d"
                            % (reloaded, s["matched"], s["review"], s["unmatched"]))
        except Exception as e:
            if _looks_like_billing_limit(e):
                self._quota_backoff_until = time.time() + QUOTA_BACKOFF_SECONDS
                logger.warning(
                    "Airtable monthly quota exceeded — reconcile backing off for %ds. "
                    "Inline ingest matching still works; safety-net resumes after reset.",
                    QUOTA_BACKOFF_SECONDS)
            else:
                logger.error("reconcile error: %s" % e, exc_info=True)

    @app_commands.command(name="review", description="View recent records that need review.")
    async def review_list(self, interaction: discord.Interaction):
        if not core.is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        
        try:
            hp_reviews = await asyncio.to_thread(
                core.hp_table.all,
                formula=f"{{Status}} = '{core.STATUS_REVIEW}'",
                max_records=10
            )
            snd_reviews = await asyncio.to_thread(
                core.snd_table.all,
                formula=f"{{Status}} = '{core.STATUS_REVIEW}'",
                max_records=10
            )
            
            embed = discord.Embed(
                title="🔍 Records Needing Review",
                description="List of player stats records that could not be auto-matched.",
                color=0xE74C3C
            )
            
            lines = []
            for r in hp_reviews:
                ign = r["fields"].get(core.RAW_IGN_FIELD, "Unknown")
                date = r["fields"].get("Date", "Unknown")
                lines.append(f"• **HP** | `{r['id']}` - IGN: `{ign}` ({date})")
                
            for r in snd_reviews:
                ign = r["fields"].get(core.RAW_IGN_FIELD, "Unknown")
                date = r["fields"].get("Date", "Unknown")
                lines.append(f"• **SND** | `{r['id']}` - IGN: `{ign}` ({date})")
                
            if not lines:
                await interaction.followup.send("✅ No records currently need review!")
                return
                
            embed.add_field(name="Records (Max 20)", value="\n".join(lines[:20]), inline=False)
            embed.set_footer(text="Use /link <record_id> to manually link a record.")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error("Error fetching review list: %s", e, exc_info=True)
            await interaction.followup.send("❌ Error fetching review list.")

    @app_commands.command(name="link", description="Link a review record to a player.")
    @app_commands.describe(record_id="The Airtable record ID to link (e.g. rec...)")
    @app_commands.describe(member="The Discord member to link to")
    @app_commands.describe(ign="Alternatively, the Primary IGN to link to")
    async def link_record(self, interaction: discord.Interaction, record_id: str, member: discord.Member = None, ign: str = None):
        if not core.is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
            
        if not member and not ign:
            await interaction.response.send_message("❌ Please specify either a `member` or an `ign`.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=False)
        
        try:
            player_record_id = None
            player_name = ""
            
            if member:
                # Find by discord ID
                discord_id = str(member.id)
                rec = await asyncio.to_thread(core.player_record_by_discord, discord_id)
                if not rec:
                    await interaction.followup.send(f"❌ Discord member **{member.display_name}** is not registered. They must run `/ign` first.")
                    return
                player_record_id = rec["id"]
                player_name = rec["fields"].get("Primary IGN", member.display_name)
            else:
                # Find by IGN
                n = core.normalize(ign)
                if n in core.matcher.exact:
                    player_record_id = core.matcher.exact[n]
                    player_name = ign
                else:
                    # check Airtable directly
                    records = await asyncio.to_thread(
                        core.players_table.all,
                        formula=f"{{Primary IGN}} = '{ign}'",
                        max_records=1
                    )
                    if not records:
                        await interaction.followup.send(f"❌ Primary IGN `{ign}` not found in registration.")
                        return
                    player_record_id = records[0]["id"]
                    player_name = ign
            
            # Find the record in HP or SND
            record, table, mode = await _find_record(record_id)
            if not record:
                await interaction.followup.send(f"❌ Record ID `{record_id}` not found in HP or SND tables.")
                return
                
            raw_ign = record["fields"].get(core.RAW_IGN_FIELD)
            
            # Update Airtable
            await asyncio.to_thread(
                table.update,
                record_id,
                {core.LINKED_PLAYER_FIELD: [player_record_id], "Status": core.STATUS_MATCHED},
                typecast=True
            )
            
            # Learn alias automatically
            if raw_ign:
                await asyncio.to_thread(core._learn_alias, raw_ign, player_record_id)
                
            # Reload matcher & run a safety reconcile to catch any other records
            async with core.airtable_lock:
                await asyncio.to_thread(core.matcher.reload)
                await asyncio.to_thread(core.reconcile_once, formula="{Player} = ''")
                
            await interaction.followup.send(
                f"✅ Linked `{mode}` record `{record_id}` (`{raw_ign}`) to player **{player_name}**."
            )
            await core.send_staff_log(
                self.bot,
                content=f"🔗 Staff **{interaction.user.name}** linked `{mode}` record `{record_id}` (`{raw_ign}`) to player **{player_name}**."
            )

            # After linking, backfill this player's MMR modifier for past matches
            # where they were previously unmatched. Runs in background so /link
            # doesn't block. Resolves discord_id from the member if given, else
            # from Airtable.
            mmr_cog = self.bot.get_cog("MMRModifier")
            if mmr_cog:
                target_did = str(member.id) if member else None
                if not target_did:
                    # member wasn't given; look up Discord ID from the player record
                    try:
                        pr = await asyncio.to_thread(
                            core.players_table.get, player_record_id)
                        target_did = str((pr.get("fields") or {}).get("Discord ID") or "") or None
                    except Exception:
                        target_did = None
                if target_did:
                    asyncio.create_task(mmr_cog.apply_modifiers_for_player(target_did, player_name))
            
        except Exception as e:
            logger.error("Error linking record %s: %s", record_id, e, exc_info=True)
            await interaction.followup.send(f"❌ Error linking record: {e}")

    async def _clear_record_link(self, interaction: discord.Interaction, record_id: str, verb: str):
        """Shared body for /unlink and /reject: clear a record's player link and
        reset Status to Unmatched. Kept as one code path — the two commands
        previously had identical bodies (pruning 2026-09)."""
        record, table, mode = await _find_record(record_id)
        if not record:
            await interaction.followup.send(f"❌ Record ID `{record_id}` not found.")
            return

        raw_ign = record["fields"].get(core.RAW_IGN_FIELD)

        await asyncio.to_thread(
            table.update,
            record_id,
            {core.LINKED_PLAYER_FIELD: [], "Status": core.STATUS_UNMATCHED},
            typecast=True
        )

        async with core.airtable_lock:
            await asyncio.to_thread(core.matcher.reload)

        await interaction.followup.send(f"✅ {verb.capitalize()} `{mode}` record `{record_id}` (`{raw_ign}`).")
        await core.send_staff_log(
            self.bot,
            content=f"❌ Staff **{interaction.user.name}** {verb} `{mode}` record `{record_id}` (`{raw_ign}`)."
        )

    @app_commands.command(name="unlink", description="Remove a player link from a record (resets to Unmatched).")
    @app_commands.describe(record_id="The Airtable record ID to unlink")
    async def unlink_record(self, interaction: discord.Interaction, record_id: str):
        if not core.is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        try:
            await self._clear_record_link(interaction, record_id, "unlinked")
        except Exception as e:
            logger.error("Error unlinking record %s: %s", record_id, e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}")

    @app_commands.command(name="reject", description="Reject a record: clear its player link (alias of /unlink).")
    @app_commands.describe(record_id="The Airtable record ID to reject")
    async def reject_record(self, interaction: discord.Interaction, record_id: str):
        if not core.is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        try:
            await self._clear_record_link(interaction, record_id, "rejected")
        except Exception as e:
            logger.error("Error rejecting record %s: %s", record_id, e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}")

async def setup(bot):
    await bot.add_cog(Ingest(bot))

