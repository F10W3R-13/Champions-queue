import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio

import core

logger = logging.getLogger("CQ_Bot.stats")

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Privately check your own player stats (sent to your DMs).")
    async def get_stats(self, interaction: discord.Interaction):
        # Self-only: no member parameter, so a player can only ever pull their own stats.
        target_user = interaction.user
        discord_id = str(target_user.id)

        # ephemeral: the command reply is visible only to the caller; the stats card is DM'd.
        await interaction.response.defer(ephemeral=True)

        try:
            records = await asyncio.to_thread(
                core.players_table.all,
                formula=f"{{Discord ID}} = '{discord_id}'",
                max_records=1
            )
            if not records:
                await interaction.followup.send(
                    "❌ You are not registered yet. Register your IGN with `/ign [Your_IGN]` first.",
                    ephemeral=True)
                return

            fields = records[0]['fields']
            discord_handle = fields.get('Discord Handle', target_user.name)
            primary_ign = fields.get('Primary IGN', 'Unknown')
            
            # HP Stats
            hp_games = fields.get('HP Games', 0)
            hp_kd = core.get_val(fields, 'HP Avg K/D')
            hp_obj = core.get_val(fields, 'HP Avg OBJ')
            hp_impact = core.get_val(fields, 'HP Avg Impact')
            hp_damage = core.get_val(fields, 'HP Avg Total Damage')
            hp_cap_kill = core.get_val(fields, 'HP Avg Capture Kill')
            
            # SND Stats
            snd_games = fields.get('SND Games', 0)
            snd_kd = core.get_val(fields, 'SND Avg K/D')
            snd_impact = core.get_val(fields, 'SND Avg Impact')
            snd_adr = core.get_val(fields, 'SND Avg ADR')
            snd_fk = core.get_val(fields, 'SND Avg First Kill')
            snd_lw = core.get_val(fields, 'SND Avg Lone Wolf Win')

            # Create a beautiful embed
            embed = discord.Embed(
                title=f"🏆 Champion's Queue Stats",
                description=f"Player Profile: **{discord_handle}** (IGN: `{primary_ign}`)",
                color=0xD4AF37 # Premium Gold
            )
            
            if target_user.avatar:
                embed.set_thumbnail(url=target_user.avatar.url)
            
            # Hardpoint Section
            hp_details = (
                f"🎮 **Games Played**: {hp_games}\n"
                f"⚔️ **K/D Ratio**: `{hp_kd}`\n"
                f"⏱️ **OBJ (Sec)**: `{hp_obj}`\n"
                f"💥 **Avg Impact**: `{hp_impact}`\n"
                f"🩸 **Avg Damage**: `{hp_damage}`\n"
                f"🎯 **Capture Kills**: `{hp_cap_kill}`"
            )
            embed.add_field(name="🔥 HARDPOINT", value=hp_details, inline=True)
            
            # Search & Destroy Section
            snd_details = (
                f"🎮 **Games Played**: {snd_games}\n"
                f"⚔️ **K/D Ratio**: `{snd_kd}`\n"
                f"💥 **Avg Impact**: `{snd_impact}`\n"
                f"🎯 **Avg ADR**: `{snd_adr}`\n"
                f"⚡ **First Kills**: `{snd_fk}`\n"
                f"🐺 **Lone Wolf Wins**: `{snd_lw}`"
            )
            embed.add_field(name="🕵️ SEARCH & DESTROY", value=snd_details, inline=True)

            # Advanced metrics - precomputed by Airtable formula fields (zero extra API calls)
            adv_lines = []
            if hp_games:
                adv_lines.append(
                    f"**HP** — DPD: `{core.get_val(fields, 'HP DPD')}` • DPK: `{core.get_val(fields, 'HP DPK')}` • "
                    f"ZCS: `{core.get_val(fields, 'HP ZCS')}` • Assist: `{core.get_val(fields, 'HP Assist %')}%`"
                )
            if snd_games:
                adv_lines.append(f"**SND** — Assist: `{core.get_val(fields, 'SND Assist %')}%`")
            if adv_lines:
                embed.add_field(name="📐 Advanced", value="\n".join(adv_lines), inline=False)

            embed.set_footer(text="CQ Stats System • Data updated automatically")

            # Send privately via DM instead of posting in the channel.
            try:
                await target_user.send(embed=embed)
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ I couldn't DM you. Enable **Direct Messages from server members** "
                    "(right-click the server → Privacy Settings) and run `/stats` again.",
                    ephemeral=True)
                return

            await interaction.followup.send("📬 Your stats have been sent to your DMs.", ephemeral=True)

        except Exception as e:
            logger.error("Error fetching stats for %s: %s", target_user.name, e, exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while fetching your data. Please try again later.", ephemeral=True)

    @app_commands.command(name="leaderboard", description="View the top 10 players for a specific game mode and metric.")
    @app_commands.describe(mode="The game mode (HP or SND)")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Hardpoint (HP)", value="HP"),
        app_commands.Choice(name="Search & Destroy (SND)", value="SND")
    ])
    @app_commands.describe(metric="The metric to sort the leaderboard by")
    @app_commands.choices(metric=[
        app_commands.Choice(name="K/D Ratio", value="kd"),
        app_commands.Choice(name="Impact", value="impact"),
        app_commands.Choice(name="Games Played", value="games"),
        # HP specific
        app_commands.Choice(name="OBJ / Time (HP)", value="hp_obj"),
        app_commands.Choice(name="Damage (HP)", value="hp_damage"),
        # SND specific
        app_commands.Choice(name="ADR (SND)", value="snd_adr"),
        app_commands.Choice(name="First Kills (SND)", value="snd_fk"),
        # Advanced metrics (computed from match records)
        app_commands.Choice(name="Damage per Death (HP)", value="hp_dpd"),
        app_commands.Choice(name="Damage per Kill - lower is better (HP)", value="hp_dpk"),
        app_commands.Choice(name="Zone Control Score (HP)", value="hp_zcs"),
        app_commands.Choice(name="Assist % (non-kill contribution)", value="assist_pct")
    ])
    @app_commands.describe(season="Season to rank (e.g. S1). Use 'career' for all-time. Defaults to the current season.")
    async def get_leaderboard(self, interaction: discord.Interaction, mode: app_commands.Choice[str],
                              metric: app_commands.Choice[str], season: str = None):
        await interaction.response.defer(ephemeral=False)

        mode_val = mode.value
        metric_val = metric.value
        scope = (season or core.CURRENT_SEASON).strip()
        is_career = scope.lower() in ("career", "all", "alltime", "all-time")
        
        # Validate metric matches mode
        if metric_val.startswith("hp_") and mode_val != "HP":
            await interaction.followup.send("❌ The selected metric is only valid for Hardpoint (HP).")
            return
        if metric_val.startswith("snd_") and mode_val != "SND":
            await interaction.followup.send("❌ The selected metric is only valid for Search & Destroy (SND).")
            return

        # Map metric choice to Airtable field names and labels
        mapping = {
            "kd": (f"{mode_val} Avg K/D", "Avg K/D", True),
            "impact": (f"{mode_val} Avg Impact", "Avg Impact", True),
            "games": (f"{mode_val} Games", "Games", False),
            "hp_obj": ("HP Avg OBJ", "Avg OBJ (s)", True),
            "hp_damage": ("HP Avg Total Damage", "Avg Damage", True),
            "snd_adr": ("SND Avg ADR", "Avg ADR", True),
            "snd_fk": ("SND Avg First Kill", "Avg First Kills", True)
        }
        
        ADVANCED_METRICS = {"hp_dpd", "hp_dpk", "hp_zcs", "assist_pct"}
        is_advanced = metric_val in ADVANCED_METRICS
        # Advanced metrics are precomputed by Airtable formula fields on the Players table.
        # Read them directly unless a specific past season was explicitly requested.
        if is_advanced and season is None:
            is_career = True

        mapping.update({
            "hp_dpd": ("HP DPD", "Dmg per Death", False),
            "hp_dpk": ("HP DPK", "Dmg per Kill", False),
            "hp_zcs": ("HP ZCS", "Zone Control Score", False),
            "assist_pct": (f"{mode_val} Assist %", "Assist %", False),
        })
        field_name, metric_label, is_rollup = mapping[metric_val]
        games_field = f"{mode_val} Games"

        # Map metric choice to season-aggregation keys (core.season_player_stats output)
        season_key_map = {
            "kd": "kd", "impact": "Impact", "games": "games",
            "hp_obj": "OBJ", "hp_damage": "Total Damage",
            "snd_adr": "ADR", "snd_fk": "First Kill",
            "hp_dpd": "DPD", "hp_dpk": "DPK", "hp_zcs": "ZCS", "assist_pct": "AssistPct",
        }

        try:
            leaderboard_data = []

            if is_career:
                # Career: use Airtable rollup fields on the Players table
                players = await asyncio.to_thread(core.players_table.all)

                def get_numeric(fields, key, is_rollup_field):
                    val = core.get_val(fields, key, 0) if is_rollup_field else fields.get(key, 0)
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        return 0.0

                for p in players:
                    fields = p["fields"]
                    games = fields.get(games_field, 0)
                    ign = fields.get("Primary IGN")
                    handle = fields.get("Discord Handle")

                    if games >= core.LEADERBOARD_MIN_GAMES and ign:
                        score = get_numeric(fields, field_name, is_rollup)
                        leaderboard_data.append({
                            "ign": ign,
                            "handle": handle,
                            "games": games,
                            "score": score
                        })
            else:
                # Season: aggregate directly from match records tagged with the season (TTL-cached)
                stats_map = await asyncio.to_thread(core.season_player_stats_cached, mode_val, scope)
                directory = await asyncio.to_thread(core.player_directory_cached)
                season_key = season_key_map[metric_val]

                for pid, s in stats_map.items():
                    if s["games"] < core.LEADERBOARD_MIN_GAMES:
                        continue
                    ign, handle = directory.get(pid, ("Unknown", ""))
                    leaderboard_data.append({
                        "ign": ign,
                        "handle": handle,
                        "games": s["games"],
                        "score": float(s.get(season_key, 0) or 0)
                    })
            
            # Sort: Damage per Kill is ascending (lower = more efficient), everything else descending
            if metric_val == "hp_dpk":
                leaderboard_data = [e for e in leaderboard_data if e["score"] > 0]
                leaderboard_data.sort(key=lambda x: x["score"])
            else:
                leaderboard_data.sort(key=lambda x: x["score"], reverse=True)
            top_10 = leaderboard_data[:10]
            
            scope_label = "Career (All-Time)" if (is_career or scope == "__ALL__") else scope
            if not top_10:
                await interaction.followup.send(
                    f"No leaderboard data available for {mode.name} - {metric.name} ({scope_label}). "
                    f"(Players need at least {core.LEADERBOARD_MIN_GAMES} games to qualify.)")
                return

            # Create a beautiful embed
            embed = discord.Embed(
                title=f"🏆 Leaderboard - {mode.name}",
                description=f"Sorted by: **{metric.name}** • Scope: **{scope_label}**",
                color=0x3498DB # Premium Blue
            )
            
            lines = []
            for idx, entry in enumerate(top_10, 1):
                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"`#{idx:02d}`"
                # Formatting scores to 2 decimal places if they are float
                score_str = f"{entry['score']:.2f}" if isinstance(entry['score'], float) and not entry['score'].is_integer() else f"{int(entry['score'])}"
                lines.append(f"{medal} **{entry['ign']}** ({entry['handle']}) — `{score_str}` ({entry['games']}g)")
                
            embed.add_field(name="Top Players", value="\n".join(lines), inline=False)
            embed.set_footer(text=f"CQ Leaderboard System • Min. {core.LEADERBOARD_MIN_GAMES} games to qualify")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error("Error generating leaderboard: %s", e, exc_info=True)
            await interaction.followup.send("❌ An error occurred while generating the leaderboard.")

async def setup(bot):
    await bot.add_cog(Stats(bot))
