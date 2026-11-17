# Weekly-options trader (Nifty + Sensex) - Phase 1: paper trading

Manual-login, hands-free-otherwise system. Strategy `trader/rules_v3.py` is FROZEN (v3) for out-of-sample testing;
read the first results at about 50 trades. Live orders are OFF and come in Phase 2.

Docs: `docs/DESIGN.md` (goals, decisions, status), `docs/ARCHITECTURE.md` (modules, data flow, safety),
`docs/RUNBOOK.md` (deploy, daily routine, recovery).

## Layout
- `trader/` package; `trader/adapters/` is the only place that talks to Kite
- `tests/` stdlib unittest (`python3 -m unittest discover -s tests -t .`); `tests/lab_*` need lab research data
- `tools/` `gc.sh` (commit helper), `bundle.py` (VM paste bundle)
- `deploy/` systemd units, Caddy template, `env.example` (no secrets in git)

## Workflow
`main` = tested releases, tagged `vX.Y.Z`. Work on `feature/*`, fast-forward to `main` after tests pass.
Commit with `tools/gc.sh "message"` (no AI attribution trailers).
