# HoldUp

**English** · [Русский](USER_GUIDE.ru.md)

Not sure you will remember a card? HoldUp schedules extra practice at a time you
choose, alongside your normal Anki reviews. For example, Anki may schedule a word
for eight days from now while you would like to see it again tomorrow.

## Install

If another copy of this add-on is installed, disable it in **Tools → Add-ons**
and restart Anki. Install [the archive](https://github.com/Asmoday7/holdup-anki-addon/raw/refs/heads/main/dist/holdup-0.5.0-dev.ankiaddon)
through **Tools → Add-ons → Install from file**, then restart Anki again.

Cards and practice appointments remain in the collection. Choose your preferred
interval again if needed; local preferences are not automatically copied from
another installation. Keep only one copy enabled.

## Schedule extra practice

1. Show the answer to a card.
2. Use **⋯** to choose time, then press **HoldUp**. A checkmark confirms the appointment.
3. Choose **Again**, **Hard**, **Good**, or **Easy** for the original card.
   This is your normal Anki answer: it updates the regular schedule and counts
   towards the daily new-card limit.

The extra appearance keeps its own deadline independently of that rating.
No note or card is duplicated. Each **HoldUp** press adds a separate extra
appearance with its own deadline, including for a previously marked card.

If the same card returns through normal study before its extra appearance,
pressing **HoldUp** again adds another extra appearance. For example, if the first
is due at 15:00 and you press HoldUp for one hour again at 14:20, both **15:00
and 15:20** remain scheduled. The waiting count increases by one. **Undo** removes
only the last addition; **Redo** restores it with the same deadline.
Appearances with identical deadlines also remain separate, including those
scheduled for the next Anki study day.

## Choose when to practise

Enter an interval from **1 second to 24 hours**, or use a preset.

- **1 day** means exactly 24 hours after the action.
- **Next Anki study day** means the next start of a study day from Anki's preferences.
  If the day starts at 04:00, scheduling at 23:00 or 02:00 makes practice ready
  at the next 04:00.

Your selection applies to subsequent actions. Existing appointments retain their
dates, including after a change to Anki's day-start setting.

## Review extra practice

Once its deadline arrives, practice can appear between cards in the usual review
screen. Finish the current card normally. Open Anki and study the relevant deck
to review it; a deadline means readiness, not an interrupting alarm.

Extra appearances are labelled **HoldUp · practice without an FSRS rating**.
After showing the answer, choose:

- **Again in …** to reschedule only the current extra appearance.
- **Next study day** to use the next study-day boundary when that mode is selected.
- **Done** to finish only the current extra appearance.
- **⋯** to choose time for subsequent appointments.

These actions do not record FSRS ratings. The original continues through Anki's
normal schedule. Seeing the same word through both schedules within the same study day is expected.

## See what is waiting

During study, **HoldUp: waiting N** shows future extra appointments. Ready practice
is included in the green review count; its tooltip shows the Anki and HoldUp portions.
Counts refer to appearances: the same card can occupy several places in the queue.

On **Decks**, a **HoldUp · N** clock badge shows ready practice. Open the deck by
its usual name. A parent includes its subdecks; parent and child numbers overlap.
The three standard deck counts remain Anki's counts and can show zero while a
HoldUp badge shows ready practice. Future appointments do not show a ready badge.

## Undo and clear

Use Anki's standard **Undo** to undo an appointment, repeat or completion.

If you press **HoldUp**, choose a normal rating and then use **Undo**, Anki cancels
only the normal rating and returns the original card. Its extra practice deadline
remains scheduled. This also applies when the extra practice is already ready:
it does not replace the original card returned by Undo.

A second Undo cancels the earlier HoldUp appointment if no other collection action
intervened. Undoing **Again in …**, **Next study day** or **Done** changes only the
practice appointment; the original's normal rating stays in place.

If a repeat or **Done** took you to the finished-for-today overview, Undo returns
ready practice to the same reviewer. Undo from **Decks** updates its ready badge
without starting study automatically.

**Tools → HoldUp: clear all practice** removes extra appointments across the open
collection. It does not delete cards or undo normal ratings.

## Language and devices

HoldUp follows Anki's language: Russian for Russian, English for other languages.
Restart Anki after changing the language.

HoldUp runs in desktop Anki. AnkiDroid does not run desktop Python add-ons, so it
does not provide this button or practice interface. Cross-device synchronisation
of practice appointments has not yet been verified.
