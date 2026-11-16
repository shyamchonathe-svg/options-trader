"""Paths and secrets. Everything lives under TRADER_HOME (default ~/trader):
  secrets/trader.env   TG_TOKEN, TG_CHAT_ID (later KITE_API_KEY, KITE_API_SECRET), mode 0600
  state/               trader.db, pin.hash, heartbeat, exports/, instruments/
Secrets never go into the repo, the release folders or chat."""
import os


def load_env(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env(path, values):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d, 0o700)
    cur = load_env(path)
    cur.update(values)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for k in sorted(cur):
            f.write("%s=%s\n" % (k, cur[k]))
    os.replace(tmp, path)


class Config(object):
    def __init__(self, home=None):
        self.home = home or os.environ.get("TRADER_HOME") or os.path.expanduser("~/trader")
        self.env_path = os.path.join(self.home, "secrets", "trader.env")
        self.state = os.path.join(self.home, "state")
        self.db = os.path.join(self.state, "trader.db")
        self.pin = os.path.join(self.state, "pin.hash")
        self.heartbeat = os.path.join(self.state, "heartbeat")
        self.exports = os.path.join(self.state, "exports")
        self.instruments = os.path.join(self.state, "instruments")
        self.env = load_env(self.env_path)

    def ensure_dirs(self):
        for d in (self.state, self.exports, self.instruments):
            if not os.path.isdir(d):
                os.makedirs(d, 0o700)

    @property
    def live_enabled(self):
        return self.env.get("LIVE_ENABLED", "0") == "1"
