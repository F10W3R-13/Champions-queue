import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
from datetime import date, datetime, timezone

import core

logger = logging.getLogger("CQ_Bot.season")

# Weekly leaderboard post: Monday 12:00 UTC (= Monday 21:00 KST)
WEEKLY_POST_WEEKDAY = 0
WEEKLY_POST_HOUR_UTC = 12



def _parse_date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _season_period_lines():
    """Human-readable season period + remaining weeks."""
    start = _parse_date(core.SEASON_START)
    end = _parse_date(core.SEASON_END)
    today = date.today()
    lines = []
    if start and end:
        lines.append(f"📅 **Period**: {start.isoformat()} → {end.isoformat()}")
        if today < start:
            lines.append(f"⏳ Season starts in **{(start - today).days}** day(s).")
        elif today > end:
            lines.append("🏁 Season has **ended**. Final standings pending.")
        else:
            days_left = (end - today).days
            weeks_left = max(1, round(days_left / 7))
            lines.append(f"⏳ **{days_left}** day(s) left (~{weeks_left} week(s)).")
    else:
        lines.append("📅 Period: not configured (`SEASON_START` / `SEASON_END`).")
    return lines


class Season(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_weekly_post = None  # date of last automatic weekly post

    def cog_unload(self):
        self.weekly_leaderboard_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.weekly_leaderboard_loop.is_running():
            self.weekly_leaderboard_loop.start()
            logger.info("Weekly leaderboard loop started.")

    # ---------- Weekly advanced-metrics leaderboard ----------

    async def build_weekly_embed(self):
        """Top 10 rankings. Values are precomputed by Airtable formula fields
        on the Players table - this is a single table read, no bot-side math."""
        players = await asyncio.to_thread(core.players_table.all)

        def collect(games_field, value_field):
            rows = []
            for p in players:
                f = p["fields"]
                games = f.get(games_field, 0)
                ign = f.get("Primary IGN")
                if not ign or games < core.LEADERBOARD_MIN_GAMES:
                    continue
                try:
                    val = float(core.get_val(f, value_field, 0) or 0)
                except (TypeError, ValueError):
                    val = 0.0
                rows.append((ign, val, games))
            return rows

        def ranked_lines(rows, ascending=False, unit="", filter_positive=False):
            if filter_positive:
                rows = [r for r in rows if r[1] > 0]
            rows = sorted(rows, key=lambda r: r[1], reverse=not ascending)[:10]
            lines = []
            for idx, (ign, val, games) in enumerate(rows, 1):
                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"`#{idx:02d}`"
                lines.append(f"{medal} **{ign}** — `{val:g}{unit}` ({games}g)")
            return "\n".join(lines) if lines else None

        embed = discord.Embed(
            title=f"📊 Weekly Performance Rankings — Season {core.CURRENT_SEASON}",
            description=(
                "Advanced metrics, updated weekly.\n"
                "-# DPD: damage dealt per life • DPK: damage needed per kill (lower = better)\n"
                "-# ZCS: zone control contribution • Assist %: non-kill contribution share"
            ),
            color=0x2ECC71
        )
        sections = [
            ("🛡️ Zone Control Score (HP)", ranked_lines(collect("HP Games", "HP ZCS"))),
            ("🩸 Damage per Death (HP)", ranked_lines(collect("HP Games", "HP DPD"))),
            ("🎯 Damage per Kill (HP, lower = better)",
             ranked_lines(collect("HP Games", "HP DPK"), ascending=True, filter_positive=True)),
            ("🤝 Assist % (HP)", ranked_lines(collect("HP Games", "HP Assist %"), unit="%")),
            ("🤝 Assist % (SND)", ranked_lines(collect("SND Games", "SND Assist %"), unit="%")),
        ]
        has_content = False
        for title, value in sections:
            if value:
                embed.add_field(name=title, value=value, inline=False)
                has_content = True
        if not has_content:
            return None

        embed.set_footer(text=f"Min. {core.LEADERBOARD_MIN_GAMES} games to qualify • CQ Stats Bot")
        embed.timestamp = datetime.now(timezone.utc)
        return embed

    async def post_weekly_leaderboard(self):
        embed = await self.build_weekly_embed()
        if embed is None:
            logger.info("Weekly leaderboard: no qualified players yet, skipping post.")
            return False
        channel = None
        if core.WEEKLY_LEADERBOARD_CHANNEL_ID:
            channel = self.bot.get_channel(core.WEEKLY_LEADERBOARD_CHANNEL_ID)
        if channel is None:
            channel = self.bot.get_channel(core.STAFF_LOGS_CHANNEL_ID)
        if channel is None:
            logger.warning("Weekly leaderboard: no channel available to post in.")
            return False
        await channel.send(embed=embed)
        return True

    @tasks.loop(hours=1)
    async def weekly_leaderboard_loop(self):
        """Posts the weekly rankings once a week (very low load: 1 run/week)."""
        try:
            now = datetime.now(timezone.utc)
            if now.weekday() != WEEKLY_POST_WEEKDAY or now.hour != WEEKLY_POST_HOUR_UTC:
                return
            if self._last_weekly_post == now.date():
                return
            self._last_weekly_post = now.date()
            posted = await self.post_weekly_leaderboard()
            if posted:
                logger.info("Weekly leaderboard posted.")
        except Exception as e:
            logger.error("Weekly leaderboard loop error: %s", e, exc_info=True)

    @weekly_leaderboard_loop.before_loop
    async def _before_weekly(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="weeklyreport", description="Post the weekly advanced-metrics rankings now (staff only).")
    async def weekly_report(self, interaction: discord.Interaction):
        if not core.is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            posted = await self.post_weekly_leaderboard()
            if posted:
                await interaction.followup.send("✅ Weekly rankings posted.")
            else:
                await interaction.followup.send(
                    f"No qualified players yet (min {core.LEADERBOARD_MIN_GAMES} games), or no channel configured.")
        except Exception as e:
            logger.error("Error in /weeklyreport: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}")

    # ---------- Season info & report ----------

    @app_commands.command(name="season", description="Current season info and your placement progress.")
    async def season_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        try:
            embed = discord.Embed(
                title=f"🗓️ Champion's Queue — Season {core.CURRENT_SEASON}",
                color=0x9B59B6
            )
            embed.add_field(name="Season", value="\n".join(_season_period_lines()), inline=False)

            # Caller's placement progress
            discord_id = str(interaction.user.id)
            records = await asyncio.to_thread(
                core.players_table.all,
                formula=f"{{Discord ID}} = '{discord_id}'",
                max_records=1
            )
            if records:
                pid = records[0]["id"]
                hp = await asyncio.to_thread(core.season_player_stats_cached, "HP")
                snd = await asyncio.to_thread(core.season_player_stats_cached, "SND")
                hp_games = hp.get(pid, {}).get("games", 0)
                snd_games = snd.get(pid, {}).get("games", 0)
                total = hp_games + snd_games
                if total >= core.PLACEMENT_GAMES:
                    status = f"✅ **Placed** — {total} games this season (HP {hp_games} / SND {snd_games})"
                else:
                    status = (f"🔸 Placement: **{total}/{core.PLACEMENT_GAMES}** games "
                              f"(HP {hp_games} / SND {snd_games}) — play {core.PLACEMENT_GAMES - total} more to qualify")
            else:
                status = "❌ Not registered — use `/ign` first."
            embed.add_field(name="Your Progress", value=status, inline=False)
            embed.set_footer(text=f"Min. {core.LEADERBOARD_MIN_GAMES} games to appear on season leaderboards")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error("Error in /season: %s", e, exc_info=True)
            await interaction.followup.send("❌ An error occurred while fetching season info.")

    @app_commands.command(name="seasonreport", description="Generate season-end standings & awards draft (staff only).")
    @app_commands.describe(season="Season to report on (defaults to the current season)")
    async def season_report(self, interaction: discord.Interaction, season: str = None):
        if not core.is_staff(interaction):
            await interaction.response.send_message("❌ This command is restricted to Staff.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        scope = (season or core.CURRENT_SEASON).strip()
        try:
            hp = await asyncio.to_thread(core.season_player_stats, "HP", scope)
            snd = await asyncio.to_thread(core.season_player_stats, "SND", scope)
            directory = await asyncio.to_thread(core.player_directory)

            def name(pid):
                return directory.get(pid, ("Unknown", ""))[0]

            def qualified(stats_map):
                return {p: s for p, s in stats_map.items() if s["games"] >= core.LEADERBOARD_MIN_GAMES}

            hp_q, snd_q = qualified(hp), qualified(snd)

            if not hp_q and not snd_q:
                await interaction.followup.send(
                    f"No qualified players for season `{scope}` "
                    f"(min {core.LEADERBOARD_MIN_GAMES} games). Nothing to report.")
                return

            def top(stats_map, key, n=10):
                return sorted(stats_map.items(), key=lambda kv: kv[1].get(key, 0), reverse=True)[:n]

            def award_line(stats_map, key, label, unit=""):
                ranked = top(stats_map, key, 1)
                if not ranked:
                    return None
                pid, s = ranked[0]
                return f"{label}: **{name(pid)}** — {s.get(key, 0)}{unit} ({s['games']}g)"

            embed = discord.Embed(
                title=f"🏁 Season {scope} — Final Report (DRAFT)",
                description="Review and repost to #announcements when ready.",
                color=0xD4AF37
            )

            # Standings: top 10 by Impact per mode
            for label, smap in (("🔥 HARDPOINT — Top 10 (Avg Impact)", hp_q),
                                ("🕵️ SEARCH & DESTROY — Top 10 (Avg Impact)", snd_q)):
                if smap:
                    lines = []
                    for idx, (pid, s) in enumerate(top(smap, "Impact"), 1):
                        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"`#{idx:02d}`"
                        lines.append(f"{medal} **{name(pid)}** — {s['Impact']} ({s['games']}g, K/D {s['kd']})")
                    embed.add_field(name=label, value="\n".join(lines), inline=False)

            # Awards
            awards = []
            if hp_q:
                awards += filter(None, [
                    award_line(hp_q, "Impact", "💥 HP Impact King"),
                    award_line(hp_q, "kd", "⚔️ HP K/D Leader"),
                    award_line(hp_q, "OBJ", "⏱️ OBJ Master", "s"),
                    award_line(hp_q, "Total Damage", "🩸 Damage Leader"),
                    award_line(hp_q, "ZCS", "🛡️ Zone Control King"),
                    award_line(hp_q, "DPD", "💪 Damage per Death Leader"),
                ])
            if snd_q:
                awards += filter(None, [
                    award_line(snd_q, "Impact", "💥 SND Impact King"),
                    award_line(snd_q, "kd", "⚔️ SND K/D Leader"),
                    award_line(snd_q, "First Kill", "⚡ First Kill Leader"),
                    award_line(snd_q, "ADR", "🎯 ADR Leader"),
                ])
            # Grinder: most total games across both modes
            all_pids = set(hp.keys()) | set(snd.keys())
            if all_pids:
                grinder = max(all_pids,
                              key=lambda p: hp.get(p, {}).get("games", 0) + snd.get(p, {}).get("games", 0))
                g_total = hp.get(grinder, {}).get("games", 0) + snd.get(grinder, {}).get("games", 0)
                awards.append(f"🎮 The Grinder (Most Games): **{name(grinder)}** — {g_total} games")

            if awards:
                embed.add_field(name="🏆 Season Awards", value="\n".join(awards), inline=False)

            embed.set_footer(text=f"Qualification: min {core.LEADERBOARD_MIN_GAMES} games • Generated by CQ Stats Bot")

            await core.send_staff_log(self.bot, embed=embed)
            await interaction.followup.send(f"✅ Season `{scope}` report draft posted to the staff log channel.")
        except Exception as e:
            logger.error("Error in /seasonreport: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Error generating report: {e}")


async def setup(bot):
    await bot.add_cog(Season(bot))
