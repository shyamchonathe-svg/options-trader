# Weekly-options trader (Nifty + Sensex) - paper first, live later
Design: docs/DESIGN.md.  Strategy: trader/rules_v3.py (frozen, v3.0).

## Layout
- trader/          package (rules_v3, candles, store, feed; later instruments, engine, broker, notify, runner)
- trader/adapters/ everything that talks to Kite lives here ONLY (untestable from the lab)
- tests/           unit tests (stdlib unittest). tests/lab_* need the research data on the lab machine only.
- tools/           gc.sh (commit helper), bundle.py (build the VM paste-bundle from git)
- deploy/          systemd units, .env.example (no secrets ever in git)

## Branches / versions
- main: only tested, tagged releases (vX.Y.Z). The VM runs only tagged releases.
- feature/<name>: all work; merge to main by fast-forward after tests pass; then tag.
- Commit with tools/gc.sh "msg" (no AI attribution trailers).

## Tests
python3 -m unittest discover -s tests -t .
python3 tests/lab_replay_check.py     # lab only: must print PASS - identical (the 11 known trades)
