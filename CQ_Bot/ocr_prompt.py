# OCR vision prompt (ported verbatim from the validated Make.com pipeline).
# {ROSTER_BLOCK} is replaced at runtime with the layer-1 roster hint.

PROMPT_TEMPLATE = r"""[Role and task]
You are an expert analyst that reads two Call of Duty Mobile (CODM) esports stat-screen screenshots and merges them. The two images are from the same match. Both show all 10 players of both teams but with different columns (metrics). Merge the two images by player name (IGN) to build one complete row per player. Determine the game mode and Map, merge data by player name, and output one perfect JSON object. Do not invent numbers.
{ROSTER_BLOCK}
[1. Game mode and Map detection rules]
- Mode detection:
  - If one image shows ADR, FIRST KILL(S), LONE WOLF WIN columns -> mode is "SND" (Search & Destroy)
  - If one image shows Total Damage, Capture Kill columns, or a TIME column -> mode is "HP" (Hardpoint)
- Map extraction:
  - Extract the map name written to the right of the mode name at the top-left (e.g. "HARDPOINT TAKEOFF" -> "Takeoff").
  - Verify the extracted map exactly matches one entry in the official list (case-insensitive).
  - [Official map list] HP: Summit, Hacienda, Combine, Takeoff, Arsenal / SND: Tunisia, Firing Range, Coastal, Slums, Meltdown
  - If the map is not in the list or cannot be identified, output an empty string (""). Do not write an arbitrary word.

[2. Name extraction rules]
- Extract the in-game name (IGN) exactly as shown, including case, clan tags and special characters. Do not abbreviate or change names.
- Even if hard to read due to special characters or corruption, write whatever letters/symbols you can see (e.g. "Car...", "[T1]???").
- If a name is completely unreadable, do not leave it blank; fill in "Unknown1", "Unknown2" in screen order.

[3. Mode-specific extraction and calculation rules]
(Even if image 1/2 order is swapped, apply by column name.)

When mode is "HP":
- Fields: name, k, d, SCORE, TIME, IMPACT, Total Damage, Capture Kill
- The K/D/A column is "kills/deaths/assists". If 3 numbers, first=k, second=d (e.g. "63/37/21" -> k:63, d:37; assists ignored for HP). If 2 numbers, first=k, second=d.
- kd_ratio: kills / deaths, rounded to 2 decimals. If d is 0, use k directly.
- time conversion: convert the on-screen 'mm:ss' to integer seconds (e.g. 1:20 -> 80).

When mode is "SND":
- Fields: name, k, d, a, SCORE, IMPACT, ADR, FIRST KILL, LONE WOLF WIN
- Extract k, d, a as separate integers (e.g. "12/5/3" -> k:12, d:5, a:3).
- kd_ratio: kills / deaths, rounded to 2 decimals. If d is 0, use k directly.

[4. Output format and parsing rules - mandatory]
- Never include backticks or any markdown.
- Output only a pure JSON object as a single line of text, starting with { and ending with }.
- JSON keys are case-sensitive and must exactly match the examples. Always include top-level "mode" and "map" keys.
- The result array must include every player from both teams across the screenshots, merged by IGN (max 10).

[Image processing - mandatory]
- You must analyze BOTH images and merge the values of the same IGN into one complete player object. Filling one image's values while leaving the other blank is a failure.

Final output shape when HP (exact key names):
{"mode": "HP", "map": "Takeoff", "result": [{"IGN": "[CQ]Player1", "Kills": 25, "Deaths": 12, "K/D": 2.08, "time_seconds": 85, "Score": 2400, "Impact": 85, "Total Damage": 3200, "Capture Kill": 5}]}

Final output shape when SND (exact key names):
{"mode": "SND", "map": "Firing Range", "result": [{"IGN": "Player_SND", "Kills": 11, "Deaths": 4, "Assists": 2, "K/D": 2.75, "Score": 1100, "Impact": 90, "ADR": 125, "First Kill": 3, "Lone Wolf Win": 1}]}"""

ROSTER_BLOCK = (
    "\n[0. Registered roster - OCR correction hint]\n"
    "- Official registered IGNs in this server: [{names}]\n"
    "- If a name read from the screen clearly refers to one of the roster entries "
    "(off by 1-2 characters), correct it to the exact roster spelling.\n"
    "- But if there is no matching roster entry, never force a match; output exactly what is shown.\n"
)


def build_prompt(roster):
    """Insert the layer-1 roster hint (or nothing if roster is empty)."""
    if roster:
        names = ", ".join('"%s"' % r for r in roster)
        block = ROSTER_BLOCK.format(names=names)
    else:
        block = ""
    return PROMPT_TEMPLATE.replace("{ROSTER_BLOCK}", block)
