"""
matcher.py - Champion's Queue Stats OCR correction engine

Role: compare the OCR-read 'IGN as read' against the Players/Aliases master
      and classify as (confirmed / review / no-match).

3-stage gate:
  1) normalized exact match       -> exact      (confirmed)
  2) fuzzy match (score + margin)  -> fuzzy_auto (confirmed) / review
  3) below threshold               -> no_match   (new / unlinked, awaiting self-report)

Dependency: pip install rapidfuzz
"""

import re
import unicodedata
from rapidfuzz.distance import JaroWinkler

# -- tuning knobs (calibrate with 1-2 weeks of live data) --
T_HIGH = 0.92    # at/above this score + margin -> auto-confirm
T_LOW  = 0.75    # below this score -> no match (new candidate)
MARGIN = 0.08    # if top1 - top2 (different players) < this -> conflict -> review queue
# ----------------------------------------------------------


def normalize(s: str) -> str:
    """Strip notation noise. Removes case/fullwidth/clan-tags/separators.
    Preserves CJK characters (Hangul/Katakana) for exact match."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)               # fullwidth -> halfwidth etc.
    s = s.lower()
    s = re.sub(r"[\[\(<{].*?[\]\)>}]", "", s)          # remove [clan] (tag)
    s = re.sub(r"[\s.\-_+~/|]+", "", s)                # remove common separators
    s = re.sub(r"[^\w]", "", s, flags=re.UNICODE)      # remove remaining symbols
    return s.replace("_", "")


class Matcher:
    """Keeps Players(Primary IGN) + Aliases(all variants) in memory and
    matches with rapidfuzz. Call reload() to refresh the cache."""

    def __init__(self, players_table, aliases_table):
        self.players_table = players_table
        self.aliases_table = aliases_table
        self.exact = {}        # normalized_ign -> player_record_id
        self.candidates = []   # [(normalized_ign, player_record_id), ...]
        self.roster = []       # original Primary IGN spellings (layer-1 prompt hint)
        self.reload()

    def reload(self):
        """Load the whole master into memory. Call on boot + on new registration.

        Field projection (fields=) trims the payload to only what matching needs.
        The Players table carries ~19 rollup/formula fields per row that matching
        never reads; projecting to just "Primary IGN" cuts that payload ~95%.
        The Aliases table is thin, but we still skip the unused "Source" field.
        """
        self.exact.clear()
        self.candidates.clear()
        self.roster.clear()

        # 1) Players' Primary IGN (only this one field is read)
        for p in self.players_table.all(fields=["Primary IGN"]):
            pid = p["id"]
            ign = p["fields"].get("Primary IGN")
            if ign:
                self.roster.append(ign)            # keep original spelling (OCR hint)
                n = normalize(ign)
                if n:
                    self.exact.setdefault(n, pid)
                    self.candidates.append((n, pid))

        # 2) All Aliases variants (incl. OCR-confirmed corruptions)
        for a in self.aliases_table.all(fields=["IGN", "Player"]):
            ign = a["fields"].get("IGN")
            players = a["fields"].get("Player") or []
            if ign and players:
                n = normalize(ign)
                pid = players[0]["id"] if isinstance(players[0], dict) else players[0]
                if n:
                    self.exact.setdefault(n, pid)
                    self.candidates.append((n, pid))

    def add_learned(self, normalized_ign: str, player_id: str):
        """self-learning: reflect a newly confirmed variant into the cache immediately."""
        self.exact.setdefault(normalized_ign, player_id)
        self.candidates.append((normalized_ign, player_id))

    def match(self, ign_as_read: str):
        """Returns (player_id or None, score, method)
        method in {'exact','fuzzy_auto','review','no_match'}"""
        n = normalize(ign_as_read)
        if not n:
            return (None, 0.0, "no_match")

        # stage 1: exact
        if n in self.exact:
            return (self.exact[n], 1.0, "exact")

        # stage 2: fuzzy (Jaro-Winkler weights name prefix)
        if not self.candidates:
            return (None, 0.0, "no_match")

        # Best score PER PLAYER. A player can appear many times (Primary IGN +
        # its own aliases); those duplicates must NOT count as a "conflict".
        best = {}
        for cand, pid in self.candidates:
            sc = JaroWinkler.similarity(n, cand)
            if pid not in best or sc > best[pid]:
                best[pid] = sc
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)  # [(pid, score)]
        top_pid, top_score = ranked[0]
        # margin = gap to the best-scoring DIFFERENT player
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = top_score - second

        if top_score >= T_HIGH and margin >= MARGIN:
            return (top_pid, top_score, "fuzzy_auto")
        if top_score < T_LOW:
            return (None, top_score, "no_match")
        return (top_pid, top_score, "review")   # borderline or conflict -> human review
