"""Run importer, exact seed search and report with explicit D1 quota handling."""
import os
import sys
from datetime import datetime, timezone
from worker import D1DailyQuotaExceeded, USAGE
import import_history
import global_search

def run():
    try:
        import_history.run()
        global_search.run()
    except D1DailyQuotaExceeded as exc:
        print('::warning title=Cloudflare D1 daily quota::D1 account-wide free-tier daily limit reached; resume after 00:00 UTC. Existing checkpoints are preserved.')
        print('D1 daily quota reached:',str(exc)[:400])
        print('D1 process usage before limit:',USAGE)
        print('UTC now:',datetime.now(timezone.utc).isoformat(timespec='seconds'))
        # Exit normally: this is a known temporary service quota, not an algorithm failure.
        # The scheduled workflow will probe again on its next scheduled UTC hour.
        return 0
    except Exception:
        # Unknown failures must stay visible as red GitHub Actions runs.
        raise
    return 0

if __name__=='__main__':
    sys.exit(run())
