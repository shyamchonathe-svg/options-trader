# Migrating to a new VM (from this repo, no chunk pastes)

Assumes Ubuntu 22.04, a user with sudo, and the GitHub repo `git@github.com:shyamchonathe-svg/options-trader.git` (private).

1. **Access to GitHub from the VM.** `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""`, then add `~/.ssh/id_ed25519.pub` in
   GitHub repo -> Settings -> Deploy keys (tick "Allow write access" if the VM will push).
2. **Clone and venv.**
   ```
   sudo apt-get update && sudo apt-get install -y git python3-venv
   mkdir -p ~/trader && cd ~/trader
   git clone git@github.com:shyamchonathe-svg/options-trader.git repo
   python3 -m venv venv && venv/bin/pip install -r repo/requirements.txt
   ```
3. **Release.** `cd ~/trader/repo && bash tools/release.sh v1.0.0` (unpacks to `~/trader/releases/`, runs tests, points `~/trader/current`, restarts).
   First time the service does not exist yet: run step 4 before answering `y`, or restart later.
4. **Services.** `cd ~/trader/current && bash deploy/install_systemd.sh`.
5. **Secrets (never in git).** `venv/bin/python -m trader.setup_telegram`, then `venv/bin/python -m trader.setup_kite`
   (Kite API key, secret, Zerodha user id). Optionally `LOGIN_CUTOFF`, `LOGIN_PORT` in `~/trader/secrets/trader.env` (see `deploy/env.example`).
6. **Login receiver.** Point a DuckDNS name at the VM's static IP, open ports 80/443 in the cloud firewall, then
   `sudo bash ~/trader/current/deploy/install_caddy.sh <your-domain>`. Set the Kite app redirect URL to
   `https://<your-domain>/...` exactly as in the current Kite app settings.
7. **Start.** `sudo systemctl start trader.service trader-watchdog.timer`; `journalctl -u trader.service -n 30`; Telegram `/status`.
8. **Restore data (optional).** Copy `trader.db` and `exports/` from the old VM backup into `~/trader/state/`.
9. **Orders (Phase 2 only).** Register the new VM's static IP with Kite (changeable once per week).

Keep `LIVE_ENABLED=0` until the order layer is built and tested.
