# Mexicanos en Europa — High Recall Update

This project still scans all tracked players every run.

Changes:
- 6-hour rolling safety window
- inspect up to 25 Google News RSS entries per player
- process max 6 fresh unseen Google articles per player total
- GDELT requests 15 results and processes max 6 fresh unseen candidates
- smart deduplication tightened to a 24-hour window

Replace `main.py`, `config.json`, and `README.md`.
