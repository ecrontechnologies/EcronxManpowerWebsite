import sys
import datetime as dt

print("python", sys.version.split()[0])
samples = [
    "2026-10-15T09:00:00+05:30",
    "2026-10-15T09:00:00Z",
    "2026-10-15T09:00:00+0530",
    "2026-10-15T09:00:00.000Z",
]
for s in samples:
    try:
        print("OK  ", s, "->", dt.datetime.fromisoformat(s))
    except ValueError as exc:
        print("FAIL", s, "->", exc)
