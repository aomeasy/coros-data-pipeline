# COROS Data Pipeline

Local data pipeline for COROS smartwatch — syncs activities, sleep, and daily health data into SQLite.

## Web Dashboard

Live: [https://aomeasy.github.io/coros-data-pipeline/](https://aomeasy.github.io/coros-data-pipeline/)

## Architecture

```
COROS API (via COROS-MCP)
        │
        ▼
coros_daily_sync.py   ← runs daily via GitHub Actions
        │
        ▼
    SQLite DB
        │
        ├── activities
        ├── sleep_data
        └── daily_health
        │
        ▼
docs/data.json        ← exported by GitHub Actions
        │
        ▼
docs/index.html       ← static web UI (GitHub Pages)
```

## Files

| File | Purpose |
|------|---------|
| `coros_db.py` | SQLite layer |
| `coros_daily_sync.py` | Daily sync script |
| `docs/index.html` | Web dashboard (served by GitHub Pages) |
| `docs/data.json` | Exported data (auto-generated) |

## Data Export

GitHub Actions exports `coros_cache.db` → `docs/data.json` on every sync.

## License
MIT
