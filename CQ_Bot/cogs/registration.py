import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import time

import core

logger = logging.getLogger("CQ_Bot.registration")

# --- NeatQueue rejection auto-helper tuning ---
# Recognize a NeatQueue "not registered" rejection by these (case-insensitive)
# keywords appearing in the message content or any embed field/description.
_NQ_REJECT_KEYWORDS = ("not registered", "not allowed to queue", "missing role",
                       "does not have", "requires the", "register")
# Don't reply again to a rejection message we've already handled (TTL, seconds).
_NQ_REPLY_CACHE_TTL = 600
# Channels where the auto-helper listens for rejections (queue + ign channels).
# Resolved lazily from core at handler time so config stays single-source.


def is_staff(interaction: discord.Interaction):
    """Helper to check if a user is staff or admin."""
    if interaction.user.guild_permissions.administrator:
        return True
    roles = [r.name.lower() for r in interaction.user.roles]
    return any("staff" in r or "admin" in r for r in roles)


class Registration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # In-memory de-dup for the NeatQueue rejection auto-helper:
        # {message_id: timestamp}. Pruned to last _NQ_REPLY_CACHE_TTL seconds.
        self._replied_rejections = {}

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """When a member receives the Verified role, DM them an IGN registration guide
        if they haven't registered yet (so they know how to unlock the queue)."""
        if before.roles == after.roles:
            return
        added = [r for r in after.roles if r not in before.roles]
        if not any(r.name == core.VERIFIED_ROLE_NAME for r in added):
            return
        try:
            existing = await asyncio.to_thread(
                core.players_table.all,
                formula=f"{{Discord ID}} = '{after.id}'",
                max_records=1
            )
            if existing:
                return  # already registered - nothing to do
            ign_chan = (self.bot.get_channel(core.IGN_HELP_CHANNEL_ID)
                        if core.IGN_HELP_CHANNEL_ID else None)
            ign_link = ign_chan.mention if ign_chan else "#ign"
            await after.send(
                "👋 **Welcome to Champion's Queue!**\n\n"
                "You're verified — one step left to unlock the queue:\n"
                f"1️⃣ Go to {ign_link} and run `/ign Your_In_Game_Name` "
                "(exactly as it appears in CODM)\n"
                "2️⃣ You'll automatically receive the **Registered** role\n"
                "3️⃣ Hit **Join Queue** and play!\n\n"
                "Your match stats are tracked automatically — check them anytime with `/stats`."
            )
            logger.info("Sent IGN registration reminder DM to %s", after.name)
        except discord.Forbidden:
            logger.info("Could not DM %s (DMs closed).", after.name)
        except Exception as e:
            logger.error("Error in verified-member reminder: %s", e, exc_info=True)

    async def _grant_registered_role(self, interaction: discord.Interaction) -> bool:
        """Grant the Registered role (queue access) after a successful IGN registration.
        Returns True if the user has/got the role, False if not configured or failed."""
        if not core.REGISTERED_ROLE_ID or not interaction.guild:
            return False
        try:
            role = interaction.guild.get_role(core.REGISTERED_ROLE_ID)
            if not role:
                logger.warning("Registered role %d not found in guild.", core.REGISTERED_ROLE_ID)
                return False
            if role not in interaction.user.roles:
                await interaction.user.add_roles(role, reason="IGN registered (CQ Stats Bot)")
                logger.info("Granted Registered role to %s", interaction.user.name)
            return True
        except discord.Forbidden:
            logger.error("Missing permission to grant Registered role (check Manage Roles + role hierarchy).")
            return False
        except Exception as e:
            logger.error("Failed to grant Registered role: %s", e, exc_info=True)
            return False

    @app_commands.command(name="ign", description="Register your primary In-Game Name (IGN) with the bot.")
    @app_commands.describe(ign_name="Your exact Call of Duty Mobile in-game name")
    async def register_ign(self, interaction: discord.Interaction, ign_name: str):
        discord_id = str(interaction.user.id)
        discord_handle = str(interaction.user.name)
        
        await interaction.response.defer(ephemeral=False)
        
        try:
            # B2: Check duplicate IGN first
            if core.check_duplicate_ign(ign_name):
                await interaction.followup.send(
                    f"❌ **Registration Rejected**: The IGN `{ign_name}` (or a variation of it) is already registered by another player. "
                    "If you believe this is an error, please contact a staff member."
                )
                return

            existing = await asyncio.to_thread(
                core.players_table.all, 
                formula=f"{{Discord ID}} = '{discord_id}'", 
                max_records=1
            )
            existing_rec = existing[0] if existing else None
            if existing_rec and existing_rec['fields'].get('Primary IGN'):
                # Genuinely already registered: self-heal the queue-access role and stop.
                await self._grant_registered_role(interaction)
                await interaction.followup.send(
                    f"You are already registered. (Current IGN: **{existing_rec['fields']['Primary IGN']}**)")
                return

            if existing_rec:
                # A stub record exists with no IGN — created when the player picked a team/region
                # (#verify Select Team / self-roles) before registering. Complete it instead of bailing.
                player_record_id = existing_rec['id']
                await asyncio.to_thread(
                    core.players_table.update, player_record_id,
                    {"Discord Handle": discord_handle, "Primary IGN": ign_name},
                )
            else:
                new_player = await asyncio.to_thread(
                    core.players_table.create,
                    {
                        "Discord ID": discord_id,
                        "Discord Handle": discord_handle,
                        "Primary IGN": ign_name,
                    }
                )
                player_record_id = new_player['id']
            
            await asyncio.to_thread(
                core.aliases_table.create,
                {"IGN": ign_name, "Player": [player_record_id], "Source": "Primary"},
                typecast=True
            )
            
            async with core.airtable_lock:
                linked_count = await asyncio.to_thread(core.relink_records, ign_name, player_record_id)

            # If past records were linked, backfill this player's MMR modifier for
            # matches where they were previously unmatched. Runs in background so
            # /ign doesn't block.
            if linked_count > 0:
                mmr_cog = self.bot.get_cog("MMRModifier")
                if mmr_cog:
                    asyncio.create_task(
                        mmr_cog.apply_modifiers_for_player(str(interaction.user.id), ign_name))

            role_granted = await self._grant_registered_role(interaction)

            msg = f"**{discord_handle}**'s in-game name (**{ign_name}**) has been registered!\n"
            if linked_count > 0:
                msg += f"Found and linked **{linked_count}** past match record(s) this pass!\n"
            if role_granted:
                msg += "✅ Queue access granted - you can now join the queue.\n"
            msg += "You can now use `/stats` to check your records."
            await interaction.followup.send(msg)
            
        except Exception as e:
            logger.error("Error during registration for %s: %s", discord_handle, e, exc_info=True)
            await interaction.followup.send("An error occurred while registering. Please try again later or contact an admin.")

    @app_commands.command(name="changeign", description="Change your registered In-Game Name (IGN).")
    @app_commands.describe(new_ign="Your new Call of Duty Mobile in-game name")
    async def change_ign(self, interaction: discord.Interaction, new_ign: str):
        discord_id = str(interaction.user.id)
        discord_handle = str(interaction.user.name)
        
        await interaction.response.defer(ephemeral=False)
        
        try:
            records = await asyncio.to_thread(
                core.players_table.all,
                formula=f"{{Discord ID}} = '{discord_id}'",
                max_records=1
            )
            if not records:
                await interaction.followup.send("You are not registered yet. Register first with `/ign [Your_IGN]`.")
                return
                
            player = records[0]
            player_record_id = player["id"]
            current_ign = player["fields"].get("Primary IGN")
            
            if current_ign == new_ign:
                await interaction.followup.send(f"You are already using that IGN (**{new_ign}**).")
                return

            # B2: Check duplicate IGN first
            if core.check_duplicate_ign(new_ign, exclude_player_id=player_record_id):
                await interaction.followup.send(
                    f"❌ **Change Rejected**: The IGN `{new_ign}` (or a variation of it) is already registered by another player. "
                    "If you believe this is an error, please contact a staff member."
                )
                return

            await asyncio.to_thread(core.players_table.update, player_record_id, {"Primary IGN": new_ign})
            
            if not core.matcher_alias_exists(new_ign):
                await asyncio.to_thread(
                    core.aliases_table.create,
                    {"IGN": new_ign, "Player": [player_record_id], "Source": "Name Change"},
                    typecast=True
                )
                
            async with core.airtable_lock:
                linked_count = await asyncio.to_thread(core.relink_records, new_ign, player_record_id)
                
            msg = f"IGN changed: **{current_ign}** -> **{new_ign}**\n"
            if linked_count > 0:
                msg += f"Linked **{linked_count}** past match record(s) this pass."
            else:
                msg += "No unlinked past records found for this IGN."
            await interaction.followup.send(msg)
            
        except Exception as e:
            logger.error("Error during IGN change for %s: %s", discord_handle, e, exc_info=True)
            await interaction.followup.send("An error occurred while changing your IGN. Please try again later or contact an admin.")

    @app_commands.command(name="syncroles", description="Grant the Registered role to all players with a registered IGN (staff only).")
    async def sync_roles(self, interaction: discord.Interaction):
        if not is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
        if not core.REGISTERED_ROLE_ID:
            await interaction.response.send_message(
                "❌ `REGISTERED_ROLE_ID` is not configured in the bot's environment.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            role = interaction.guild.get_role(core.REGISTERED_ROLE_ID)
            if not role:
                await interaction.followup.send("❌ Registered role not found in this server. Check the role ID.")
                return

            players = await asyncio.to_thread(core.players_table.all)
            registered_ids = {p["fields"].get("Discord ID") for p in players if p["fields"].get("Discord ID")}

            added, already = 0, 0
            for member in interaction.guild.members:
                if str(member.id) in registered_ids:
                    if role in member.roles:
                        already += 1
                    else:
                        await member.add_roles(role, reason="IGN registered (backfill via /syncroles)")
                        added += 1

            await interaction.followup.send(
                f"✅ Sync complete: granted **{added}** member(s) the {role.mention} role "
                f"({already} already had it, {len(registered_ids)} registered players total).")
            await core.send_staff_log(
                self.bot,
                content=f"🔄 Staff **{interaction.user.name}** ran /syncroles: +{added} granted, {already} unchanged.")
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Missing permission. Give the bot **Manage Roles** and drag its role **above** the Registered role.")
        except Exception as e:
            logger.error("Error during role sync: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Error during sync: {e}")

    # ------------------------------------------------------------------
    # Registration help panel + NeatQueue rejection auto-helper
    # ------------------------------------------------------------------

    @app_commands.command(name="ignhelp",
                          description="Post the persistent 'how to register' guide panel (staff only).")
    async def ign_help_panel(self, interaction: discord.Interaction):
        if not is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
        try:
            embed = _build_ign_help_embed(self.bot)
            await interaction.channel.send(embed=embed, view=IgnHelpPanel())
            await interaction.response.send_message("✅ IGN help panel posted.", ephemeral=True)
            await core.send_staff_log(
                self.bot,
                content=f"📝 Staff **{interaction.user.name}** posted the IGN help panel in #{interaction.channel.name}.")
        except Exception as e:
            logger.error("Error in /ignhelp: %s", e, exc_info=True)
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Auto-helper: when NeatQueue rejects a player for lacking the Registered
        role, reply with a pointer to #ign and /ign. Heuristic (no hard format
        dependency) so it survives small NeatQueue copy changes."""
        # Prune the de-dup cache first.
        now = time.time()
        self._replied_rejections = {
            mid: ts for mid, ts in self._replied_rejections.items()
            if now - ts < _NQ_REPLY_CACHE_TTL
        }

        if not self._is_nq_rejection(message):
            return
        if message.id in self._replied_rejections:
            return
        self._replied_rejections[message.id] = now

        target = None
        # Prefer the user NeatQueue mentioned (the rejected player), if any.
        if message.mentions:
            target = message.mentions[0]
        # Only tag them if they actually lack the Registered role (avoid noise for
        # unrelated mentions).
        mention_str = ""
        if (target and core.REGISTERED_ROLE_ID and message.guild):
            member = message.guild.get_member(target.id)
            role = message.guild.get_role(core.REGISTERED_ROLE_ID)
            if member and role and role not in member.roles:
                mention_str = f"{member.mention} — "

        ign_chan = (self.bot.get_channel(core.IGN_HELP_CHANNEL_ID)
                    if core.IGN_HELP_CHANNEL_ID else None)
        ign_link = ign_chan.mention if ign_chan else "#ign"
        try:
            await message.reply(
                f"{mention_str}👋 You're blocked from the queue because your **IGN isn't registered** yet.\n"
                f"Go to {ign_link} and run:\n"
                f"```\n/ign YourExactInGameName\n```\n"
                f"That unlocks the queue in ~10 seconds. See the pinned guide in {ign_link} for details.",
                mention_author=bool(mention_str),
                allowed_mentions=discord.AllowedMentions(users=bool(mention_str)))
            logger.info("IGN auto-helper replied to NeatQueue rejection %d.", message.id)
        except discord.HTTPException as e:
            logger.warning("IGN auto-helper could not reply to %d: %s", message.id, e)

    def _is_nq_rejection(self, message: discord.Message) -> bool:
        """True if `message` looks like a NeatQueue 'not registered' rejection."""
        # Must be from a bot, in a queue/ign channel, matching the NeatQueue identity.
        if not message.author.bot:
            return False
        if core.NEATQUEUE_BOT_ID and message.author.id != core.NEATQUEUE_BOT_ID:
            return False
        if not core.NEATQUEUE_BOT_ID:
            name = (message.author.name or "").lower()
            if "neatqueue" not in name and "neat queue" not in name:
                return False

        watch_channels = {
            core.QUEUE_JOIN_CHANNEL_ID, core.NEATQUEUE_QUEUE_CHANNEL_ID,
            core.IGN_HELP_CHANNEL_ID,
        }
        if message.channel.id not in watch_channels or message.channel.id == 0:
            return False

        haystack = (message.content or "").lower()
        for emb in message.embeds:
            if emb.description:
                haystack += " " + emb.description.lower()
            for f in emb.fields:
                haystack += " " + (f.name or "").lower() + " " + (f.value or "").lower()
            if emb.footer and emb.footer.text:
                haystack += " " + emb.footer.text.lower()
        return any(kw in haystack for kw in _NQ_REJECT_KEYWORDS)


class IgnHelpPanel(discord.ui.View):
    """Persistent panel for the #ign channel. No state-changing buttons — just a
    static guide embed (mirrors /rolepanel / /verifypanel scaffolding)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="How do I register?", emoji="❓",
                       style=discord.ButtonStyle.primary, custom_id="ignhelp:howto")
    async def howto(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = _build_ign_help_embed(interaction.client)
        await interaction.response.send_message(embed=embed, ephemeral=True)


def _build_ign_help_embed(bot):
    """The persistent registration-guide embed. Posted by /ignhelp and shown
    again on the panel's button click."""
    desc = (
        "If you were blocked from the queue, it's because your **in-game name isn't registered** yet.\n"
        "This takes ~10 seconds:\n\n"
        "1️⃣ **In this channel (#ign)**, type:\n"
        "```\n/ign YourExactInGameName\n```\n"
        "Use the name **exactly** as it appears in Call of Duty.\n\n"
        "2️⃣ You'll automatically receive the **Registered** role.\n\n"
        "3️⃣ Go back to the queue channel and hit **Join Queue** — you're in.\n\n"
        "**Notes:**\n"
        "• One IGN per player. If yours is taken, use `/changeign` or contact staff.\n"
        "• Your match stats are tracked automatically — check them with `/stats` anytime."
    )
    embed = discord.Embed(
        title="📝 How to Register & Unlock the Queue",
        description=desc, color=0x5865F2)
    embed.set_footer(text="Champion's Queue • Registration Guide")
    embed.timestamp = discord.utils.utcnow()
    return embed


async def setup(bot):
    # Register the persistent IGN-help panel so its button survives restarts
    # (same pattern as /rolepanel and /verifypanel).
    bot.add_view(IgnHelpPanel())
    await bot.add_cog(Registration(bot))
