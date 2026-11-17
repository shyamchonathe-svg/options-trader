class FakeTransport(object):
    def __init__(self):
        self.sent, self.deleted, self.updates, self.fail = [], [], [], False

    def send_message(self, chat_id, text, markup=None):
        if self.fail:
            raise RuntimeError("net down")
        self.sent.append((chat_id, text))
        self.markups = getattr(self, "markups", [])
        self.markups.append(markup)

    def answer_callback(self, cid, text=""):
        self.answered = getattr(self, "answered", []) + [cid]

    def set_commands(self, commands):
        self.commands = commands

    def delete_message(self, chat_id, mid):
        self.deleted.append((chat_id, mid))

    def get_updates(self, offset=None, timeout=0):
        ups = [u for u in self.updates if offset is None or u["update_id"] >= offset]
        return ups


class FixedRng(object):
    def randrange(self, n):
        return 123456


def _send_document(self, chat_id, path, caption=""):
    if self.fail:
        raise RuntimeError("net down")
    self.docs.append((chat_id, path, caption))


FakeTransport.send_document = _send_document
_orig_init = FakeTransport.__init__


def _init(self):
    _orig_init(self)
    self.docs = []


FakeTransport.__init__ = _init
