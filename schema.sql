CREATE TABLE IF NOT EXISTS draws (game INTEGER NOT NULL, round TEXT NOT NULL, main TEXT NOT NULL, bonus TEXT NOT NULL, PRIMARY KEY(game,round));
CREATE TABLE IF NOT EXISTS jobs (game INTEGER NOT NULL, round TEXT NOT NULL, seed_start INTEGER NOT NULL DEFAULT 0, scanned INTEGER NOT NULL DEFAULT 0, seed_limit INTEGER NOT NULL DEFAULT 10000, best TEXT NOT NULL DEFAULT '[]', exact_count INTEGER NOT NULL DEFAULT 0, updated_at TEXT, PRIMARY KEY(game,round));
CREATE INDEX IF NOT EXISTS jobs_remaining ON jobs(game,scanned);
CREATE TABLE IF NOT EXISTS seed_analysis (game INTEGER NOT NULL PRIMARY KEY, summary TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exact_matches (game INTEGER NOT NULL, round TEXT NOT NULL, seed INTEGER NOT NULL, detected_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(game,round,seed));
CREATE TABLE IF NOT EXISTS search_runs (run_id TEXT PRIMARY KEY, scanned INTEGER NOT NULL, found INTEGER NOT NULL, duration_seconds REAL NOT NULL, completed_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS global_progress (id INTEGER PRIMARY KEY CHECK(id=1), cursor INTEGER NOT NULL DEFAULT 0, target_hash TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS global_exact_matches (game INTEGER NOT NULL, round TEXT NOT NULL, seed INTEGER NOT NULL, detected_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(game,round,seed));
