"""One-time setup, run ON THE VM:  ~/trader/venv/bin/python -m trader.setup_kite
Asks for the Kite Connect API key and secret (hidden input) and saves them to secrets/trader.env (mode 0600).
Nothing is printed or logged. Afterwards restart the service:  sudo systemctl restart trader.service"""
import getpass
import sys

from trader.config import Config, write_env


def main(argv=None):
    cfg = Config()
    key = getpass.getpass("Kite API key (hidden): ").strip()
    secret = getpass.getpass("Kite API secret (hidden): ").strip()
    if not key or not secret:
        print("Both are required.")
        return 1
    write_env(cfg.env_path, {"KITE_API_KEY": key, "KITE_API_SECRET": secret})
    print("Saved to %s (mode 0600). Now: sudo systemctl restart trader.service, then /config in Telegram for the login link." % cfg.env_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
