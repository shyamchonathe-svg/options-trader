"""Minimal Telegram Bot API client (requests). The bot token is a secret: it is never logged and is stripped from
error messages (requests puts the URL, hence the token, into exception text)."""


class TelegramError(Exception):
    pass


class TelegramAPI(object):
    BASE = "https://api.telegram.org"

    def __init__(self, token, session=None):
        self._token = token
        if session is None:
            import requests
            session = requests.Session()
        self.s = session

    def _call(self, method, params=None, files=None, timeout=15):
        url = "%s/bot%s/%s" % (self.BASE, self._token, method)
        try:
            r = self.s.post(url, data=params or {}, files=files, timeout=timeout)
            j = r.json()
        except Exception as e:
            raise TelegramError("%s: %s" % (method, str(e).replace(self._token, "<token>")[:200]))
        if not j.get("ok"):
            raise TelegramError("%s: %s" % (method, str(j.get("description"))[:200]))
        return j["result"]

    def get_updates(self, offset=None, timeout=25):
        p = {"timeout": timeout, "allowed_updates": '["message","callback_query"]'}
        if offset is not None:
            p["offset"] = offset
        return self._call("getUpdates", p, timeout=timeout + 10)

    def send_message(self, chat_id, text, markup=None):
        p = {"chat_id": chat_id, "text": text[:4000]}
        if markup:
            import json
            p["reply_markup"] = json.dumps(markup)
        return self._call("sendMessage", p)

    def answer_callback(self, callback_id, text=""):
        return self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:100]})

    def set_commands(self, commands):
        import json
        return self._call("setMyCommands", {"commands": json.dumps([{"command": c, "description": d} for c, d in commands])})

    def send_document(self, chat_id, path, caption=""):
        with open(path, "rb") as f:
            return self._call("sendDocument", {"chat_id": chat_id, "caption": caption[:200]}, files={"document": f}, timeout=60)

    def delete_message(self, chat_id, message_id):
        return self._call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
