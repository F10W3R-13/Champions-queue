"""Self-service roles panel.

A dedicated channel hosts one persistent message with three buttons:
  🌍 Region  (single-select)   -> Discord role + writes Players.Region in Airtable
  🔫 Weapon  (multi-select)    -> Discord roles only
  🏆 Team    (single-select)   -> Players.Team link + Champs role + [TAG] nickname

Clicking a button opens an ephemeral dropdown so members can (re)pick anytime,
not just during onboarding. Team options are read live from the Airtable Teams
table, so staff manage the roster there.

Discord perms the bot needs: Manage Roles (+ its role ABOVE every assignable
role) and Manage Nicknames. It cannot rename the server owner or anyone holding
a role higher than the bot — those cases keep the role/Airtable change and just
skip the nickname.
"""
import re
import logging
import asyncio

import discord
from discord.ext import commands
from discord import app_commands

import core

logger = logging.getLogger("CQ_Bot.selfroles")

_TAG_RE = re.compile(r"^\[[^\]]*\]\s*")          # strips a leading "[XXX] " tag
NICK_MAX = 32                                     # Discord nickname length limit

# Reused user-facing strings
ROLE_PERM_ERROR = "❌ Couldn't update your roles. The bot needs **Manage Roles** and a high enough role position."
GUILD_ONLY = "This can only be used inside the server."


def is_staff(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    roles = [r.name.lower() for r in interaction.user.roles]
    return any("staff" in r or "admin" in r for r in roles)


async def _get_or_create_role(guild: discord.Guild, name: str):
    """Find a role by exact name; optionally create it if missing."""
    role = discord.utils.get(guild.roles, name=name)
    if role is None and core.SELFROLES_AUTO_CREATE:
        try:
            role = await guild.create_role(name=name, reason="CQ self-roles auto-create")
            logger.info("Auto-created role '%s'", name)
        except discord.Forbidden:
            logger.error("Cannot create role '%s' (missing Manage Roles).", name)
            return None
    return role


async def _get_champs_role(guild: discord.Guild):
    """Resolve the Champs role by ID first (exact, no duplicates), then by name."""
    if core.CHAMPS_ROLE_ID:
        role = guild.get_role(core.CHAMPS_ROLE_ID)
        if role:
            return role
    return await _get_or_create_role(guild, core.CHAMPS_ROLE_NAME)


def _strip_tag(name: str) -> str:
    return _TAG_RE.sub("", name).strip()


async def _apply_tag(member: discord.Member, tag: str) -> str:
    """Set/replace/remove the [TAG] prefix on a member's nickname.
    Returns "" on success, or a user-facing warning string on failure."""
    base = _strip_tag(member.display_name)
    if tag:
        nick = f"[{tag}] {base}"[:NICK_MAX]
    else:
        nick = None if base == member.name else base[:NICK_MAX]
    try:
        await member.edit(nick=nick, reason="CQ team tag")
        return ""
    except discord.Forbidden:
        return "\n⚠️ Couldn't update your nickname (you're the server owner or have a role above the bot)."
    except Exception as e:
        logger.error("Nickname edit failed for %s: %s", member, e)
        return "\n⚠️ Something went wrong while updating your nickname."


# --------------------------------------------------------------------------- #
#  Ephemeral select menus (built on demand when a panel button is clicked)
# --------------------------------------------------------------------------- #

class RegionSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=label, value=label)
                   for label in core.REGION_ROLE_NAMES]
        super().__init__(placeholder="Select your region...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        member, guild = interaction.user, interaction.guild
        chosen = self.values[0]
        target_name = core.REGION_ROLE_NAMES[chosen]
        managed = set(core.REGION_ROLE_NAMES.values())

        try:
            to_remove = [r for r in member.roles if r.name in managed and r.name != target_name]
            if to_remove:
                await member.remove_roles(*to_remove, reason="CQ region change")
            role = await _get_or_create_role(guild, target_name)
            if role and role not in member.roles:
                await member.add_roles(role, reason="CQ region select")
        except discord.Forbidden:
            await interaction.followup.send(ROLE_PERM_ERROR, ephemeral=True)
            return

        try:
            await asyncio.to_thread(core.set_player_region, str(member.id), chosen, member.name)
        except Exception as e:
            logger.error("set_player_region failed for %s: %s", member.id, e)

        await interaction.followup.send(f"✅ Region set: **{chosen}**", ephemeral=True)


class WeaponSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=label, value=label)
                   for label in core.WEAPON_ROLE_NAMES]
        super().__init__(placeholder="Select your weapon class(es) — multiple allowed; clear all to remove...",
                         min_values=0, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        member, guild = interaction.user, interaction.guild
        chosen = set(self.values)

        add, remove = [], []
        for label, role_name in core.WEAPON_ROLE_NAMES.items():
            role = discord.utils.get(guild.roles, name=role_name)
            if label in chosen:
                if role is None:
                    role = await _get_or_create_role(guild, role_name)
                if role and role not in member.roles:
                    add.append(role)
            elif role and role in member.roles:
                remove.append(role)

        try:
            if add:
                await member.add_roles(*add, reason="CQ weapon select")
            if remove:
                await member.remove_roles(*remove, reason="CQ weapon deselect")
        except discord.Forbidden:
            await interaction.followup.send(ROLE_PERM_ERROR, ephemeral=True)
            return

        label = ", ".join(sorted(chosen)) if chosen else "None"
        await interaction.followup.send(f"✅ Weapons: **{label}**", ephemeral=True)


class TeamSelect(discord.ui.Select):
    NONE_VALUE = "__none__"

    def __init__(self, teams, region_label=None):
        # teams: [(record_id, name, tag, region), ...] - Discord allows max 25 options/menu
        self._teams = {rid: (name, tag) for rid, name, tag, *_ in teams}
        options = [
            discord.SelectOption(label=name[:100], value=rid,
                                 description=(f"[{tag}]" if tag else None))
            for rid, name, tag, *_ in teams[:24]
        ]
        options.append(discord.SelectOption(
            label="❌ No team / Remove", value=self.NONE_VALUE, emoji="🚪"))
        placeholder = f"Select your team ({region_label})..." if region_label else "Select your team..."
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        member, guild = interaction.user, interaction.guild
        champs = await _get_champs_role(guild)
        value = self.values[0]

        if value == self.NONE_VALUE:
            try:
                await asyncio.to_thread(core.set_player_team, str(member.id), None, member.name)
            except Exception as e:
                logger.error("clear team failed for %s: %s", member.id, e)
            try:
                if champs and champs in member.roles:
                    await member.remove_roles(champs, reason="CQ team cleared")
            except discord.Forbidden:
                pass
            nick_msg = await _apply_tag(member, "")
            await interaction.followup.send("✅ Removed from your team." + nick_msg, ephemeral=True)
            return

        name, tag = self._teams.get(value, ("?", ""))
        try:
            await asyncio.to_thread(core.set_player_team, str(member.id), value, member.name)
        except Exception as e:
            logger.error("set_player_team failed for %s: %s", member.id, e)
            await interaction.followup.send("❌ Couldn't save your team. Please try again shortly.", ephemeral=True)
            return

        try:
            if champs and champs not in member.roles:
                await member.add_roles(champs, reason="CQ team select")
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ Saved your team, but couldn't grant the **Champs** role (check the bot's role position).",
                ephemeral=True)
            return

        nick_msg = await _apply_tag(member, tag)
        await interaction.followup.send(
            f"✅ Team: **{name}** · you've received the **{core.CHAMPS_ROLE_NAME}** role." + nick_msg,
            ephemeral=True)


async def open_team_picker(interaction: discord.Interaction):
    """Send the caller the ephemeral region-grouped team-select menus.
    Shared by /rolepanel (selfroles) and the #verify panel."""
    if interaction.guild is None:
        await interaction.response.send_message(GUILD_ONLY, ephemeral=True)
        return
    try:
        teams = await asyncio.to_thread(core.list_teams, True)
    except Exception as e:
        logger.error("list_teams failed: %s", e)
        teams = []
    if not teams:
        await interaction.response.send_message(
            "No teams are available yet. Please contact staff.", ephemeral=True)
        return
    # group by region so each menu stays under Discord's 25-option cap (1 menu per region)
    groups = {}
    for t in teams:
        groups.setdefault(t[3] or "Other", []).append(t)
    order = [r for r in ("NA", "EU") if r in groups] + [r for r in groups if r not in ("NA", "EU")]
    view = discord.ui.View(timeout=180)
    for region in order[:5]:   # Discord allows max 5 components per message
        view.add_item(TeamSelect(groups[region], region_label=region))
    await interaction.response.send_message(
        "Select your team (one menu per region):", view=view, ephemeral=True)


# --------------------------------------------------------------------------- #
#  Persistent panel (one message with three buttons, survives restarts)
# --------------------------------------------------------------------------- #

class SelfRolePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(GUILD_ONLY, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Region", emoji="🌍", style=discord.ButtonStyle.secondary, custom_id="selfroles:region")
    async def region_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        view = discord.ui.View(timeout=120)
        view.add_item(RegionSelect())
        await interaction.response.send_message("Pick your region:", view=view, ephemeral=True)

    @discord.ui.button(label="Weapon", emoji="🔫", style=discord.ButtonStyle.secondary, custom_id="selfroles:weapon")
    async def weapon_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        view = discord.ui.View(timeout=120)
        view.add_item(WeaponSelect())
        await interaction.response.send_message("Pick your weapon class(es):", view=view, ephemeral=True)

    @discord.ui.button(label="Team", emoji="🏆", style=discord.ButtonStyle.primary, custom_id="selfroles:team")
    async def team_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_team_picker(interaction)


class SelfRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rolepanel",
                          description="Post the self-roles (region / weapon / team) panel in this channel (staff only).")
    async def rolepanel(self, interaction: discord.Interaction):
        if not is_staff(interaction):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🎚️ Role Selection",
            description=(
                "Use the buttons below to manage your own roles anytime.\n\n"
                "🌍 **Region** — pick one\n"
                "🔫 **Weapon** — pick any (multiple allowed)\n"
                "🏆 **Team** — championship players: pick your team to receive the "
                "**Champs** role and a name tag"
            ),
            color=0x5865F2,
        )
        await interaction.channel.send(embed=embed, view=SelfRolePanel())
        await interaction.response.send_message("✅ Self-roles panel posted.", ephemeral=True)


async def setup(bot):
    bot.add_view(SelfRolePanel())   # re-register persistent buttons after restart
    await bot.add_cog(SelfRoles(bot))
