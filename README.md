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
