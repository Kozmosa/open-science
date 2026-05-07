# Literature Tracker Design

> **Scope:** Feat 2 of RD-new — independent backend+frontend subsystem for scheduled literature tracking and analysis.

---

## Goal

Provide an automated literature tracking subsystem where users configure journals/conferences, keywords, and schedules. The system periodically crawls new papers, filters by relevance, and produces summary reports. Results are stored and browsable in a dedicated UI panel.

## Architecture

Independent of TaskHarness. Three layers:

1. **Storage Layer**: SQLite tables for tracker configs and run history
2. **Scheduler Layer**: APScheduler (or asyncio-based cron evaluator) that reads enabled configs and triggers runs
3. **Execution Layer**: Constructs a Claude Code prompt invoking ARIS literature skills, runs via the existing launcher mechanism (or direct subprocess), parses output into structured results
4. **UI Layer**: New `/literature` route with config management and result browsing

## Data Model

### `literature_tracker_configs`

| Column | Type | Notes |
|--------|------|-------|
| tracker_id | TEXT PK | UUID |
| project_id | TEXT | FK to implicit project scope |
| label | TEXT | user-defined name |
| venues | TEXT | JSON array of venue strings, e.g. `["TPAMI", "ICML 2025"]` |
| keywords | TEXT | comma-separated or newline-separated keywords |
| schedule_cron | TEXT | standard 5-field cron, e.g. `0 9 1 * *` (monthly) |
| enabled | INTEGER | 0 or 1 |
| last_run_at | TEXT | ISO datetime or null |
| created_at | TEXT | ISO datetime |

### `literature_tracker_runs`

| Column | Type | Notes |
|--------|------|-------|
| run_id | TEXT PK | UUID |
| tracker_id | TEXT FK | |
| status | TEXT | `pending`, `running`, `completed`, `failed` |
| papers_found | INTEGER | count of papers discovered |
| summary_markdown | TEXT | rendered report content |
| error_summary | TEXT | nullable |
| started_at | TEXT | ISO datetime |
| completed_at | TEXT | ISO datetime |

## Scheduler

### APScheduler (recommended)

Use `apscheduler` with `AsyncIOScheduler`. On app startup:

1. Query all `enabled=1` configs from DB
2. For each, add a cron job keyed by `tracker_id`
3. Job handler:
   - Insert `literature_tracker_runs` row with `status=pending`
   - Build prompt from config
   - Execute via launcher / direct subprocess
   - Parse stdout for paper list and summary
   - Update run row to `completed` or `failed`

### Cron Evaluation

The `schedule_cron` field uses standard 5-field cron. APScheduler's `CronTrigger` handles this natively.

Example schedules:
- Monthly: `0 9 1 * *` (1st of month at 9am)
- Weekly: `0 9 * * 1` (Monday 9am)
- Daily: `0 9 * * *` (9am daily)

## Execution Flow

```
Scheduler triggers → Build prompt → Run Claude Code → Stream output → Parse results → Save to DB
```

### Prompt Construction

```
/literature-track "{{venues}}" --keywords "{{keywords}}" --since {{last_run_date or "30d"}}

Track latest papers from the specified venues matching the keywords. For each relevant paper, summarize: title, authors, key contribution, relation to existing work, and whether it represents a significant advance. Produce both a "brief summary" (2-minute read) and "deep technical review" versions.
```

### Output Parsing

The ARIS skill is expected to produce a markdown document with a predictable structure. The execution layer captures the final markdown file written to the workspace and stores it in `summary_markdown`.

If the skill writes to a known path (e.g. `workspace/literature-tracker/<tracker_id>/report.md`), the scheduler reads that file after the process exits.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/literature-trackers` | List all trackers |
| POST | `/literature-trackers` | Create tracker |
| GET | `/literature-trackers/{id}` | Get tracker + last few runs |
| PUT | `/literature-trackers/{id}` | Update tracker config |
| DELETE | `/literature-trackers/{id}` | Delete tracker + runs |
| POST | `/literature-trackers/{id}/trigger` | Manual trigger (queue a run now) |
| GET | `/literature-trackers/{id}/runs` | List runs for tracker |
| GET | `/literature-trackers/{id}/runs/{run_id}` | Get run detail |

## UI Design

### Route: `/literature`

**Tracker List**
- Card grid showing each tracker: label, venues, keywords, schedule, enabled toggle, last run status
- "New Tracker" button opens form modal

**Tracker Form Modal**
- Label input
- Venues textarea (one per line)
- Keywords textarea (comma or newline separated)
- Schedule: cron input with helper presets (daily/weekly/monthly)
- Enabled checkbox

**Run History Panel**
- Collapsible section per tracker
- Each run: timestamp, status badge, papers found count
- Expand to view `summary_markdown` rendered as HTML

**Manual Trigger**
- Play button on each tracker card to queue an immediate run

## Error Handling

- Invalid cron → rejected at create/update API (400)
- ARIS skill missing at trigger time → run status=`failed`, `error_summary` populated
- Process crash / timeout → run status=`failed`, partial output captured if available
- DB errors → logged, scheduler skips that tracker for the cycle

## Testing

- Unit: cron parsing and next-run calculation
- Unit: prompt construction from tracker config
- Integration: API CRUD for trackers
- Integration: manual trigger executes and produces a run record
- Integration: scheduler wakes up and triggers a run at the correct time (use short test cron)

## Non-Goals

- Does NOT provide real-time push notifications (user checks the panel)
- Does NOT crawl paywalled content without user credentials
- Does NOT auto-download PDFs (metadata and summaries only)
- Does NOT deduplicate across multiple trackers (each tracker is independent)
