# COROS Data Pipeline

Local data pipeline for COROS smartwatch — syncs activities, sleep, and daily health data into SQLite for use with Hermes Agent skills.

## Architecture

```
COROS API (via COROS-MCP)
        │
        ▼
coros_daily_sync.py   ← runs daily via cron
        │
        ▼
    SQLite DB         ← single source of truth
        │
        ├── activities      (sport records)
        ├── sleep_data      (sleep analysis)
        └── daily_health    (steps, stress, HR, calories)
```

## Files

| File | Purpose |
|------|---------|
| `coros_db.py` | SQLite layer — schema, store/get functions |
| `coros_daily_sync.py` | Daily sync script — calls COROS-MCP, caches to DB |

## Setup

### Prerequisites

- [COROS-MCP](https://github.com/coroslab/COROS-MCP) (`npm install -g coros-mcp`)
- Python 3.11+
- COROS account (OAuth login required)

### Install

```bash
git clone https://github.com/aomeasy/coros-data-pipeline.git
cd coros-data-pipeline
```

### Configure

DB path defaults to `~/AppData/Local/hermes/coros_cache.db` (Windows) — edit `DB_PATH` in `coros_db.py` if needed.

### Run

```bash
# Initialize DB
python -c "import coros_db; coros_db.init_db()"

# One-time sync
python coros_daily_sync.py

# Daily cron (9 AM)
# Add via Hermes cronjob or system scheduler
```

## Schema

### `activities`
- `activity_id`, `sport_type`, `start_time`, `distance_m`, `duration_s`
- `avg_pace_s`, `avg_cadence`, `calories`, `avg_hr`, `max_hr`
- `ascent_m`, `descent_m`, `score`, `summary_json`

### `sleep_data`
- `date`, `sleep_score`, `duration_min`
- `deep_sleep_pct`, `light_sleep_pct`, `rem_sleep_pct`
- `awake_min`, `hrv`, `resting_hr`, `summary_json`

### `daily_health`
- `date`, `sleep_score`, `steps`, `stress_score`
- `avg_hr`, `max_hr`, `calories_burned`, `summary_json`

## Integration with Hermes Agent

Skills that read from cache:
- `run-coach` — running analysis (pace, cadence, progression)
- `sleep-review` — sleep quality and recovery tracking

Skills check SQLite first, call COROS-MCP only on cache miss.

## License
MIT
