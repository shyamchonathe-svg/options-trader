"""Polling loop: Telegram updates -> Controller -> replies. At-most-once: the update offset is saved BEFORE a command runs,
so a crash can never replay an old command (dangerous commands also need a fresh in-memory code)."""
import time


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
            m = u.get("message") or {}
            text, chat = m.get("text"), (m.get("chat") or {}).get("id")
            if text is None or chat is None:
                continue
            sensitive = self.c.is_sensitive(text)
            for reply in self.c.handle(chat, text):
                for part in chunks(reply):
                    self.t.send_message(chat, part)
            if sensitive and m.get("message_id") is not None:
                try:
                    self.t.delete_message(chat, m["message_id"])
                except Exception:
                    pass
            n += 1
        return n

    def run(self, should_stop=lambda: False):
        while not should_stop():
            try:
                self.poll_once()
                self.errors = 0
            except Exception as e:
                self.errors += 1
                self.store.event("ERROR", "bot", type(e).__name__)
                self.sleep(min(60, 2 ** min(self.errors, 6)))
