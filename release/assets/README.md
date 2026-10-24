# Actual Anki screenshots

These PNGs are captured from the installed candidate in a disposable English
Anki profile on Linux/Qt, using synthetic vocabulary. They are actual application
captures, not mockups or Windows validation evidence.
They were captured from rc.1; rc.3 changes only version metadata and validation scripts.

1. `01-normal-review.png`: normal Anki ratings with the fifth HoldUp button.
2. `02-interval.png`: interval presets and Next Anki study day.
3. `03-extra-practice.png`: extra practice in the same reviewer.
4. `04-deck-indicator.png`: two ready appearances on the deck list.

Capture again with:

```bash
QT_QPA_PLATFORM=offscreen python tools/capture_screenshots.py \
  dist/holdup-1.0.0-rc.3.ankiaddon .dev/new-demo-profile release/assets
```

Use a fresh profile directory. The script refuses an existing one and does not
open a personal profile. It requires the desktop dependencies from
`requirements-gui-26.09.txt` or `requirements-gui.txt`.
