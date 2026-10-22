# HoldUp

**English** · [Русский](USER_GUIDE.ru.md)

Not sure you will remember a card? HoldUp schedules extra practice at a time you
choose, alongside your normal Anki reviews. For example, Anki may schedule a word
for eight days from now while you would like to see it again tomorrow.

## Install

If another copy of this add-on is installed, disable it in **Tools → Add-ons**
and restart Anki. Install [the archive](https://github.com/Asmoday7/holdup-anki-addon/raw/refs/heads/main/dist/holdup-0.4.1-dev.ankiaddon)
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
No note or card is duplicated. Each card can have one extra appointment;
scheduling it again replaces its previous extra deadline.

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

- **Again in …** to schedule another extra appearance.
- **Next study day** to use the next study-day boundary when that mode is selected.
- **Done** to finish this card's extra practice.
- **⋯** to choose time for subsequent appointments.

These actions do not record FSRS ratings. The original continues through Anki's
normal schedule. Seeing the same word through both schedules within the same study day is expected.

## See what is waiting

During study, **HoldUp: waiting N** shows future extra appointments. Ready practice
is included in the green review count; its tooltip shows the Anki and HoldUp portions.

On **Decks**, a **HoldUp · N** clock badge shows ready practice. Open the deck by
its usual name. A parent includes its subdecks; parent and child numbers overlap.
The three standard deck counts remain Anki's counts and can show zero while a
HoldUp badge shows ready practice. Future appointments do not show a ready badge.

## Undo and clear

Use Anki's standard **Undo** to undo an appointment, repeat or completion.
**Tools → HoldUp: clear all practice** removes extra appointments across the open
collection. It does not delete cards or undo normal ratings.

## Language and devices

HoldUp follows Anki's language: Russian for Russian, English for other languages.
Restart Anki after changing the language.

HoldUp runs in desktop Anki. AnkiDroid does not run desktop Python add-ons, so it
does not provide this button or practice interface. Cross-device synchronisation
of practice appointments has not yet been verified.
