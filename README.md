# LOTO DRAW LAB — free scheduled cloud seed exploration

LOTO6/7 historical seed-search experiments with GitHub Actions and Cloudflare D1. **This is not 24-hour uninterrupted computing:** a scheduled job runs approximately every hour, saves its work to D1, and resumes later. GitHub may delay or skip schedules.

**Security:** repository is PUBLIC. Do not commit Cloudflare tokens, account credentials, private CSVs, or other secrets. These must go into GitHub Actions Secrets. GitHub Actions permission is read-only.

## 1. Cloudflare setup

1. In the Cloudflare dashboard, open **Workers & Pages → D1** and create a database named `loto-draw-lab`.
2. Open that database's SQL console and run the statements in [schema.sql](schema.sql).
3. Create an API token scoped to Cloudflare D1 edit access for the required account, following Cloudflare's current permissions UI.
4. Note the Cloudflare account ID and D1 database ID (do not share the API token in chat).

## 2. GitHub secrets

In this repository choose **Settings → Secrets and variables → Actions → New repository secret**. Add:

- `CF_API_TOKEN`: the Cloudflare D1 API token
- `CF_ACCOUNT_ID`: the Cloudflare Account ID
- `CF_D1_DATABASE_ID`: the D1 Database ID

## 3. Import CSV lottery history

Use Python 3.9+. Set the three environment variables securely on your computer, then run:

```bash
python import_draws.py data/loto6.csv 6
python import_draws.py data/loto7.csv 7
```

The CSV must include a round identifier and 6 (LOTO6) or 7 (LOTO7) main numbers; bonus numbers are optional. CSV accepts UTF-8 or CP932. Each row creates a seed-search job with a default range of **0–9999**; importing again preserves existing progress. The sanitized public `data/loto6.csv` and `data/loto7.csv` files are versioned in this public repository. Never commit credentials or private datasets.

### 4. Run and observe

Open **Actions → LOTO seed search → Run workflow** to begin the first run. The scheduler is configured at minute 17 of every UTC hour. The workflow runs tests before attempting the D1 connection.

In D1 SQL console:

```sql
SELECT game, COUNT(*) AS rounds, SUM(scanned) AS scanned, SUM(seed_limit) AS planned FROM jobs GROUP BY game;
SELECT game, round, scanned, seed_limit, best FROM jobs ORDER BY game, CAST(round AS INTEGER) DESC LIMIT 20;
SELECT game, summary, updated_at FROM seed_analysis;
```

The worker checkpoints progress in small batches and stores five highest-scoring seed candidates per round. `analyze.py` computes exploratory lag-one correlation and permutation comparison over completed rounds. The virtual PRNG's seed values are **not** the real machine's internal state or evidence of predictive ability. Physics-based Rapier search is **not** included in this cloud worker.

## Cost and operational caveats

Stay within GitHub Actions and Cloudflare D1 free-tier quotas. Timed scheduling is best-effort, not guaranteed uninterrupted 24/7. The current package does **not** automatically fetch new official draw results. A read-only static dashboard is generated hourly from D1 and published using GitHub Pages after Pages is enabled in repository Settings → Pages → Source: GitHub Actions. It does not expose an API or credentials. Public GitHub Pages means search results are publicly visible. Import draws first; an empty database has no jobs.

## Dashboard

The dashboard workflow is `.github/workflows/dashboard.yml`, scheduled at minute 35 UTC each hour, separately from the seed-search worker at minute 17. Turn on GitHub Pages in repository Settings → Pages → Build and deployment → Source: **GitHub Actions**. The site URL will normally be `https://ashinagawajb-byte.github.io/loto-draw-lab/` once a Pages deployment succeeds. The dashboard is a static snapshot and may lag behind D1. It only shows completed rounds when plotting seed trends and is an exploratory research visualization, not a prediction engine.

## D1 free-tier protection (2026-11)

The GitHub Actions worker now uses the index `jobs_next_scan(scanned,game,round)` to avoid repeatedly scanning all historic jobs for each 50,000-seed checkpoint. Completed CSV imports are no longer re-inserted hourly. `worker.query` accumulates the D1 API's `meta.rows_read` and `meta.rows_written` counters, and each run conservatively stops after about 60,000 read rows or 2,000 written rows (both configurable through `D1_RUN_READ_BUDGET` and `D1_RUN_WRITE_BUDGET`). Checks occur between committed chunks, so an individual query can slightly exceed a per-run soft cap. The current default frequency is once per UTC hour, NOT continuous; other D1 databases in the same account consume the same daily free allowance.

The quota-aware `run_search.py` logs a GitHub Actions warning only for Cloudflare's recognized daily D1 free-tier row limit response; it leaves previously committed progress untouched. A later scheduled run tries again. Other errors are **not** suppressed. Cloudflare resets daily D1 limits at 00:00 UTC (09:00 Japan time); the worker cannot directly know the remaining account-wide budget from query-local metadata alone, so these guards do **not** guarantee the account never hits its limit. To check actual total usage, consult the Cloudflare D1 dashboard. To pause all search while other applications need quota, disable the GitHub Actions scheduled workflow.

## Global one-pass seed search (v2)

The scheduled workflow now uses `global_search.py` + the native `global_scan.cpp` executable. Instead of repeating an identical seed's shuffle independently for each historical round, the native scanner computes one LOTO6 and one LOTO7 virtual draw per seed and checks the two results against all known rounds using in-memory hash maps.

The one-pass cursor is tracked in `global_progress` (one 32-bit seed search space, `0..2^32-1`). Full main+bonus matches are stored in `global_exact_matches`. Legacy per-round `jobs` cursors and `exact_matches` are **retained without modification**; the dashboard displays the new unique-seed cursor separately from the legacy per-round work total, and de-duplicates matching seeds when displaying found rounds. The shared new engine only validates a deterministic *virtual PRNG* and does not reveal the lottery machine's state or imply predictive value.

If a new historical CSV changes the target snapshot, the global cursor restarts from seed 0 for correctness (new rounds must also be tested against earlier seeds), but previous matches are never cleared. Re-scans are idempotent. Each committed checkpoint follows successful verified match inserts. If the D1 quota interrupts a chunk, the cursor stays unchanged and the chunk is safely replayed. Each native hit is independently verified against the Python reference before committing. `GLOBAL_BATCH_SIZE=1000000` seeds per checkpoint by default. D1 read/write soft budgets still apply; the Cloudflare daily quota is account-wide.

To validate locally:
```bash
g++ -O3 -std=c++17 -Wall -Wextra seed_scan.cpp -o seed_scan
g++ -O3 -std=c++17 -Wall -Wextra global_scan.cpp -o global_scan
python -m unittest -q test_worker.py test_native.py test_global.py
```
