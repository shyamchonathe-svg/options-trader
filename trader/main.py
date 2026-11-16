"""Service entry point:  python -m trader.main     (systemd unit: trader.service)
One thread: every loop = daemon.step(now) + a 1-second Telegram long-poll. Ticks from a feed thread arrive via a queue.
/restart simply exits; systemd (Restart=always) starts the newest ~/trader/current."""
import os
import sys
import time

from trader import __version__
from trader.broker import PaperBroker
from trader.bot import Bot
from trader.clock import ist_now
from trader.config import Config
from trader.control import Controller
from trader.daemon import Daemon
from trader.notify import Notifier
from trader.pin import PinFile
from trader.state import RuntimeState
from trader.store import Store
from trader.tg_api import TelegramAPI


def version_string():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        for line in open(os.path.join(here, "VERSION")):
            if line.startswith("version="):
                return line.strip().split("=", 1)[1]
    except IOError:
        pass
    return __version__


def build(cfg, transport, provider=None, broker=None, clock=ist_now):
    cfg.ensure_dirs()
    store = Store(cfg.db)
    state = RuntimeState(store, live_enabled=cfg.live_enabled, version=version_string())
    notifier = Notifier(transport, cfg.env.get("TG_CHAT_ID"), store)

    def beat():
        with open(cfg.heartbeat, "a"):
            os.utime(cfg.heartbeat, None)

    daemon = Daemon(store, state, notifier, provider, broker or PaperBroker(), cfg=cfg, sender=notifier, heartbeat=beat)
    hooks = {"flat": daemon.flat, "restart": daemon.request_restart, "export": daemon.export_now}
    ctl = Controller(store, state, cfg.env.get("TG_CHAT_ID"), PinFile(cfg.pin), hooks=hooks, clock=clock)
    bot = Bot(transport, ctl, store)
    return store, state, notifier, daemon, bot


def run(cfg, transport, provider=None, max_loops=None, sleep=time.sleep, clock=ist_now):
    store, state, notifier, daemon, bot = build(cfg, transport, provider, clock=clock)
    notifier.send("Trader %s started. mode=%s%s, risk %s. /help" % (
        state.version, state.mode, " (live ENABLED in config)" if state.live_enabled else "", state.risk))
    backoff_until = 0.0
    loops = 0
    while not daemon.restart_requested:
        try:
            daemon.step(clock())
        except Exception as e:
            try:
                store.event("ERROR", "step", "%s: %s" % (type(e).__name__, str(e)[:200]))
            except Exception:
                pass
        if time.time() >= backoff_until:
            try:
                bot.poll_once(timeout=1)
            except Exception as e:
                store.event("ERROR", "bot", type(e).__name__)
                backoff_until = time.time() + 30
                sleep(1)
        else:
            sleep(1)
        loops += 1
        if max_loops is not None and loops >= max_loops:
            return "loops"
    return "restart"


def main():
    cfg = Config()
    tok, chat = cfg.env.get("TG_TOKEN"), cfg.env.get("TG_CHAT_ID")
    if not tok or not chat:
        print("No Telegram settings. Run: python -m trader.setup_telegram")
        return 2
    run(cfg, TelegramAPI(tok))
    return 0     # exit code 0 + Restart=always -> systemd restarts us


if __name__ == "__main__":
    sys.exit(main())
