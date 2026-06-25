"""#verify access-request flow.

`/verifypanel` (staff) posts the access-request instructions plus a "Request Access"
button. Clicking opens a modal (Name / Route / Supporting info). On submit the bot
posts the application into the channel, pinging the applicant, with staff
**Approve / Reject** buttons. Approve grants the Verified Player role — which also
triggers the existing onboarding DM in registration.py.

All views are persistent (registered in setup) so the buttons survive restarts; the
applicant is recovered from the embed footer, not from in-memory state.
"""
import logging

import discord
from discord.ext import commands
from discord import app_commands

import core
from cogs import selfroles  # reuse the shared team picker

logger = logging.getLogger("CQ_Bot.verify")

ROUTES = ("Referral", "Application", "Credentials")


def _norm_route(raw: str) -> str:
    """Best-effort snap of free text to one of the three routes."""
    r = (raw or "").strip().lower()
    for opt in ROUTES:
        if r.startswith(opt[:4].lower()):
            return opt
    return (raw or "").strip() or "—"


def _applicant_id(message: discord.Message):
    """Recover the applicant's discord id from the embed footer 'applicant:<id>'."""
    for e in message.embeds:
        text = e.footer.text if e.footer else None
        if text and "applicant:" in text:
            try:
                return int(text.split("applicant:")[1].split()[0])
            except (ValueError, IndexError):
                return None
    return None


class VerifyModal(discord.ui.Modal, title="Requesting Access"):
    name = discord.ui.TextInput(
        label="Name", required=True, max_length=100, placeholder="Your name / in-game name")
    route = discord.ui.TextInput(
        label="Route", required=True, max_length=40,
        placeholder="Referral / Application / Credentials")
    info = discord.ui.TextInput(
        label="Supporting info", style=discord.TextStyle.paragraph, required=True, max_length=1000,
        placeholder="Referrer's name, tournament/team history, or relevant detail")

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        embed = discord.Embed(title="🛂 Access Request", color=0x5865F2)
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="Name", value=str(self.name)[:1024], inline=False)
        embed.add_field(name="Route", value=_norm_route(str(self.route)), inline=False)
        embed.add_field(name="Supporting info", value=str(self.info)[:1024], inline=False)
        embed.set_footer(text=f"applicant:{user.id} • Pending review")
        # Post the application to the staff review channel (not #verify) so the panel stays visible.
        review_channel = interaction.client.get_channel(core.STAFF_LOGS_CHANNEL_ID) or interaction.channel
        try:
            await review_channel.send(
                content=f"📨 New access request from {user.mention}",
                embed=embed, view=VerifyReviewView(),
                allowed_mentions=discord.AllowedMentions(users=False))  # show mention, don't ping
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Submission failed — the staff review channel is misconfigured. Please ping a staff member.",
                ephemeral=True)
            return
        await interaction.response.send_message(
            "✅ Your request has been submitted. A staff member will review and respond.",
            ephemeral=True)


class VerifyPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Request Access", emoji="🛂",
                       style=discord.ButtonStyle.primary, custom_id="verify:request")
    async def request(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message("Use this inside the server.", ephemeral=True)
            return
        await interaction.response.send_modal(VerifyModal())

    @discord.ui.button(label="Select Team", emoji="🏆",
                       style=discord.ButtonStyle.secondary, custom_id="verify:team")
    async def team(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Championship players: pick your team to receive the Champs role (championship-queue access).
        await selfroles.open_team_picker(interaction)


class VerifyReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _finish(self, interaction: discord.Interaction, approved: bool):
        if not core.is_staff(interaction):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return

        note = ""
        if approved:
            uid = _applicant_id(interaction.message)
            member = interaction.guild.get_member(uid) if uid else None
            if member is None:
                note = " · member not found"
            else:
                role = discord.utils.get(interaction.guild.roles, name=core.VERIFIED_ROLE_NAME)
                if role is None:
                    note = f" · role '{core.VERIFIED_ROLE_NAME}' missing"
                elif role in member.roles:
                    note = " · already verified"
                else:
                    try:
                        await member.add_roles(
                            role, reason=f"Verified via #verify by {interaction.user}")
                    except discord.Forbidden:
                        note = " · missing Manage Roles / hierarchy"

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        verdict = "✅ Approved" if approved else "❌ Rejected"
        embed.color = 0x2ECC71 if approved else 0xE74C3C
        embed.set_footer(text=f"{verdict} by {interaction.user}{note}")
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Approve", emoji="✅",
                       style=discord.ButtonStyle.success, custom_id="verify:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, True)

    @discord.ui.button(label="Reject", emoji="✖️",
                       style=discord.ButtonStyle.danger, custom_id="verify:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, False)


class Verify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="verifypanel",
        description="Post the access-request panel in this channel (staff only).")
    async def verifypanel(self, interaction: discord.Interaction):
        if not core.is_staff(interaction):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        embed = discord.Embed(
            title="Requesting Access",
            description=(
                "Champion's Queue is closed. Access is granted by verification through "
                "__**one of three routes below**__:\n\n"
                "**1 · Referral** — A verified member vouches for you. Name them in your request.\n"
                "**2 · Application** — Submit your record below for review.\n"
                "**3 · Credentials** — Provide verifiable tournament or roster history.\n\n"
                "Press **🛂 Request Access** and fill in the form. A staff member will review and respond. "
                "Approved players receive the **Verified Player** role and access to the main queue.\n\n"
                "__**Championship players**__\n"
                "Press **🏆 Select Team** to confirm your team — you'll receive the **Champs** role and "
                "access to the championship queue. Then run **`/ign`** to register your in-game name and "
                "unlock queueing."
            ),
            color=0x5865F2)
        await interaction.channel.send(embed=embed, view=VerifyPanel())
        await interaction.response.send_message("✅ Verify panel posted.", ephemeral=True)


async def setup(bot):
    bot.add_view(VerifyPanel())         # persistent: Request Access button
    bot.add_view(VerifyReviewView())    # persistent: Approve / Reject buttons
    await bot.add_cog(Verify(bot))
