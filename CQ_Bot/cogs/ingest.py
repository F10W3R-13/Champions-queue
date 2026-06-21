import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio

import core

logger = logging.getLogger("CQ_Bot.ingest")

def is_staff(interaction: discord.Interaction):
    """Helper to check if a user is staff or admin."""
    if interaction.user.guild_permissions.administrator:
        return True
    roles = [r.name.lower() for r in interaction.user.roles]
    return any("staff" in r or "admin" in r for r in roles)

class Ingest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
            
            # Send review alerts to staff log channel if there are any review items (Phase 2)
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
            # Phase 2 staff notification for exceptions
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

    @tasks.loop(seconds=45)
    async def reconcile_loop(self):
        """Safety-net loop. Normal path is inline-matched at ingest, so usually 0.

        reconcile_once runs every 45s (cheap: B1 guard = 0 writes in steady state,
        and the unmatched formula returns ~0 records). matcher.reload() is gated
        by a 5-min TTL inside reload_matcher_if_stale() - it's a full Players+Aliases
        scan and only needs to catch direct Airtable UI edits (bot-driven mutations
        refresh the cache eagerly)."""
        try:
            async with core.airtable_lock:
                # B3: reload matcher cache (TTL-gated) to capture manual Airtable edits
                reloaded = await asyncio.to_thread(core.reload_matcher_if_stale)
                s = await asyncio.to_thread(core.reconcile_once)
            if reloaded or s["matched"] or s["review"]:
                logger.info("reconcile: reload=%s matched=%d review=%d unmatched=%d"
                            % (reloaded, s["matched"], s["review"], s["unmatched"]))
        except Exception as e:
            logger.error("reconcile error: %s" % e, exc_info=True)

    @app_commands.command(name="review", description="View recent records that need review.")
    async def review_list(self, interaction: discord.Interaction):
        if not is_staff(interaction):
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
        if not is_staff(interaction):
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
                records = await asyncio.to_thread(
                    core.players_table.all,
                    formula=f"{{Discord ID}} = '{discord_id}'",
                    max_records=1
                )
                if not records:
                    await interaction.followup.send(f"❌ Discord member **{member.display_name}** is not registered. They must run `/ign` first.")
                    return
                player_record_id = records[0]["id"]
                player_name = records[0]["fields"].get("Primary IGN", member.display_name)
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
            record = None
            table = None
            mode = ""
            
            try:
                record = await asyncio.to_thread(core.hp_table.get, record_id)
                table = core.hp_table
                mode = "HP"
            except Exception:
                try:
                    record = await asyncio.to_thread(core.snd_table.get, record_id)
                    table = core.snd_table
                    mode = "SND"
                except Exception:
                    pass
                    
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

    @app_commands.command(name="unlink", description="Unlink a player from a record (resets status to Unmatched).")
    @app_commands.describe(record_id="The Airtable record ID to unlink")
    async def unlink_record(self, interaction: discord.Interaction, record_id: str):
        if not is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=False)
        
        try:
            record = None
            table = None
            mode = ""
            
            try:
                record = await asyncio.to_thread(core.hp_table.get, record_id)
                table = core.hp_table
                mode = "HP"
            except Exception:
                try:
                    record = await asyncio.to_thread(core.snd_table.get, record_id)
                    table = core.snd_table
                    mode = "SND"
                except Exception:
                    pass
                    
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
                
            await interaction.followup.send(f"✅ Unlinked player from `{mode}` record `{record_id}` (`{raw_ign}`).")
            await core.send_staff_log(
                self.bot,
                content=f"🔓 Staff **{interaction.user.name}** unlinked `{mode}` record `{record_id}` (`{raw_ign}`)."
            )
        except Exception as e:
            logger.error("Error unlinking record %s: %s", record_id, e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}")

    @app_commands.command(name="reject", description="Mark a record as Unmatched (clears player link).")
    @app_commands.describe(record_id="The Airtable record ID to reject")
    async def reject_record(self, interaction: discord.Interaction, record_id: str):
        if not is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=False)
        
        try:
            record = None
            table = None
            mode = ""
            
            try:
                record = await asyncio.to_thread(core.hp_table.get, record_id)
                table = core.hp_table
                mode = "HP"
            except Exception:
                try:
                    record = await asyncio.to_thread(core.snd_table.get, record_id)
                    table = core.snd_table
                    mode = "SND"
                except Exception:
                    pass
                    
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
            
            await interaction.followup.send(f"✅ Rejected `{mode}` record `{record_id}` (`{raw_ign}`) (marked Unmatched).")
            await core.send_staff_log(
                self.bot,
                content=f"❌ Staff **{interaction.user.name}** rejected `{mode}` record `{record_id}` (`{raw_ign}`)."
            )
        except Exception as e:
            logger.error("Error rejecting record %s: %s", record_id, e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}")

async def setup(bot):
    await bot.add_cog(Ingest(bot))

