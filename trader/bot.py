"""Polling loop: Telegram updates -> Controller -> replies. At-most-once: the update offset is saved BEFORE a command runs,
so a crash can never replay an old command (dangerous commands also need a fresh in-memory code)."""
import time


# Buttons only ever run READ-ONLY commands. Anything that changes state (stop, flat, arm, mode, set...) stays typed,
# with its one-time code and PIN, so a stray tap can never move money or change risk.
MENU = [[("Status", "status"), ("Positions", "positions"), ("Trades", "trades")],
        [("Day report", "summary"), ("Signals", "signals"), ("Health", "health")],
        [("Risk", "risk"), ("Compare exits", "compare"), ("Login", "login")]]
BUTTON_CMDS = set(c for row in MENU for _, c in row) | set(["menu"])
SHOW_MENU_AFTER = set(["status", "menu", "start", "help", "summary", "positions", "trades", "health", "risk", "compare", "signals"])
COMMAND_LIST = [("menu", "Buttons"), ("status", "Mode, feed, day state"), ("positions", "Open positions"),
                ("trades", "Today's trades"), ("summary", "Day report"), ("signals", "Pattern matches"),
                ("health", "Feed and system health"), ("risk", "Risk limits"), ("compare", "Exit-rule comparison"),
                ("login", "Kite login link"), ("help", "All commands")]


def keyboard():
    return {"inline_keyboard": [[{"text": t, "callback_data": "c:" + c} for t, c in row] for row in MENU]}


def chunks(text, n=3500):
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


class Bot(object):
    def __init__(self, transport, controller, store, sleep=time.sleep):
        self.t = transport
        self.c = controller
        self.store = store
        self.sleep = sleep
        self.errors = 0

    def poll_once(self, timeout=25):
        off = self.store.kv_get("tg_offset")
        ups = self.t.get_updates(int(off) if off else None, timeout)
        n = 0
        for u in ups:
            self.store.kv_set("tg_offset", u["update_id"] + 1)
            cb = u.get("callback_query")
            if cb:
                self._callback(cb)
                n += 1
                continue
            m = u.get("message") or {}
            text, chat = m.get("text"), (m.get("chat") or {}).get("id")
            if text is None or chat is None:
                continue
            sensitive = self.c.is_sensitive(text)
            self._reply(chat, text)
            if sensitive and m.get("message_id") is not None:
                try:
                    self.t.delete_message(chat, m["message_id"])
                except Exception:
                    pass
            n += 1
        return n

    def _reply(self, chat, text):
        cmd = text.strip().split()[0][1:].split("@")[0].lower() if text.strip().startswith("/") else ""
        parts = [p for r in self.c.handle(chat, text) for p in chunks(r)]
        for i, part in enumerate(parts):
            if i == len(parts) - 1 and cmd in SHOW_MENU_AFTER:
                self.t.send_message(chat, part, keyboard())
            else:
                self.t.send_message(chat, part)

    def _callback(self, cb):
        chat = ((cb.get("message") or {}).get("chat") or {}).get("id")
        data = cb.get("data") or ""
        try:
            self.t.answer_callback(cb.get("id"))
        except Exception:
            pass
        cmd = data[2:] if data.startswith("c:") else ""
        if chat is None or cmd not in BUTTON_CMDS:
            return
        self._reply(chat, "/" + cmd)

    def run(self, should_stop=lambda: False):
        while not should_stop():
            try:
                self.poll_once()
                self.errors = 0
            except Exception as e:
                self.errors += 1
                self.store.event("ERROR", "bot", type(e).__name__)
                self.sleep(min(60, 2 ** min(self.errors, 6)))
