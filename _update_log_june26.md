@everyone

# :loudspeaker: Update Log — June 26
Everything below is now live.

## :chart_with_upwards_trend: Performance MMR — Fixed & Hardened

> The Impact-based MMR modifier (the bonus/penalty on top of NeatQueue's base win/loss) had a bug that caused **one match's modifiers to be applied repeatedly** for the players in it, inflating their MMR.
>
> **What happened.** On June 21, a code change introduced a crash that fired *after* the modifier was sent to NeatQueue but *before* the match was marked as processed. The 10-minute loop then re-ran that same match every tick for ~8 hours — re-applying the modifier each time. We caught it, audited the **full NeatQueue roster** against the correct numbers, and corrected everyone affected.
>
> **Impact.** 9 players received an inflated MMR and have been rolled back to their correct value. 1 additional player is pending manual adjustment due to a NeatQueue database inconsistency on their account — we'll handle it directly. No other players were affected.
>
> **What's fixed (so it can't happen again):**
> - The loop now records a modifier as "applied" and refuses to re-apply the same player-match combo, even if a later step crashes.
> - A single bad match can no longer block the rest of the loop.
> - Impact data from neighbouring matches can no longer leak into the wrong match's average.
>
> If your MMR looks off, ping a staff member — we have the full audit and can verify yours.

## :mirror: MMR Adjustments Now Public

> When performance modifiers are applied, a compact **📊 Performance MMR Adjustments** summary is posted to **#results** so you can see who earned bonus MMR (and who lost extra). The detailed breakdown stays in staff logs.

## :link: Faster Stats After Registration

> When you `/ign` or get `/link`ed, the bot now backfills your **past match modifiers automatically** — no more missing bonuses from games played before you were registered, and no double-counting.

## :tickets: Queue Reminders & RSVP

> The bot now watches each session window and posts reminders automatically: **T-2h** (get ready), **T-30 min** (Queue Ping role), then a **LIVE** message when the queue opens.
>
> The shared RSVP roster covers **both NA and EU windows** in one place, and the moment a session goes live, the bot **DMs everyone on the list** to jump in.
>
> Manually opened the queue? The auto-lock timer now respects that and won't shut it down on you for 24 hours.

## :wastebasket: Clean Team Removal

> Removing a team from a player is now consistent no matter how it's done — staff `/clearteam`, a manual role removal, or a kick all strip the **`[TAG]` from the nickname** and clear the Airtable team in one shot.

## :mailbox_with_mail: Smoother Onboarding

> New to the server? There's now a **registration guide panel** in **#ign** that walks you through `/ign` step by step.
>
> And if NeatQueue ever rejects you from the queue for not being registered, the bot catches it and **points you straight to #ign** — no more guessing why you can't join.

## :mag_right: Stats Under the Hood

> `/stats` still drops into your **DMs** (your numbers, your eyes only), and the IGN matching / OCR pipeline is more reliable after several stability fixes (retry-on-missing-data, integer MMR values, graceful handling of players not in NeatQueue).

---

Ping a staff member if you have any questions — especially about MMR, we'd rather over-explain than leave anyone guessing.
