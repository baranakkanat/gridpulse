"""Phase 8 physics driver, run verbatim from the session scratchpad on 2026-10-18 (23:16 UTC,
nice 19, 3 workers). It calls `stress.compute`, the same function as
`python -m gridpulse robust-study --stage physics`, which afterwards found every folder
cached and recorded it. Log: outputs/robust_study/logs/physics_run.log (git-ignored)."""

import time
from datetime import UTC, datetime
from pathlib import Path

from gridpulse import dual_study as ds
from gridpulse import stress as st


def main() -> None:
    cache = Path("outputs/robust_study/fullstate_cache")
    for cond in (*st.TRUTHS, *st.METERED):
        for code in ds.HOSTING_CAPACITY:
            t0 = time.time()
            r = st.compute(code, cond, cache, workers=3)
            print(
                datetime.now(UTC).strftime("%H:%M:%S"),
                cond,
                code,
                r["computed"],
                r["from_cache"],
                "%.0fs" % (time.time() - t0),
                flush=True,
            )


if __name__ == "__main__":
    main()
