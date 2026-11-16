"""One-time setup, run ON THE VM:  ~/trader/venv/bin/python -m trader.setup_telegram
Asks for the bot token (hidden input), finds your chat id from the message you sent to the bot, saves both to
secrets/trader.env (mode 0600) and sends a test message. The token is never printed or logged."""
import getpass
import sys

from trader.config import Config, write_env
from trader.tg_api import TelegramAPI, TelegramError


def main(argv=None):
    cfg = Config()
    token = getpass.getpass("Bot token (hidden): ").strip()
    if ":" not in token:
        print("That does not look like a bot token.")
        return 1
    api = TelegramAPI(token)
    try:
        ups = api.get_updates(None, 0)
    except TelegramError as e:
        print("Telegram said: %s" % e)
        return 1
    chats = {}
    for u in ups:
        m = u.get("message") or {}
        c = m.get("chat") or {}
        if c.get("type") == "private":
            chats[c["id"]] = "%s %s (@%s)" % (c.get("first_name", ""), c.get("last_name", ""), c.get("username", ""))
    if not chats:
        print("No message found. Open your bot in Telegram, press Start, send 'hi', then run this again.")
        return 1
    if len(chats) > 1:
        print("More than one chat wrote to this bot:")
        for k, v in chats.items():
            print("  %s  %s" % (k, v))
        print("Someone else messaged your bot. Revoke the token with BotFather (/revoke) and start again.")
        return 1
    chat_id, who = list(chats.items())[0]
    print("Found chat: %s -> %s" % (chat_id, who.strip()))
    if input("Is this you? [y/N] ").strip().lower() != "y":
        return 1
    write_env(cfg.env_path, {"TG_TOKEN": token, "TG_CHAT_ID": str(chat_id)})
    api.send_message(chat_id, "Setup done. The trader will message you from this bot.")
    print("Saved to %s (mode 0600). Test message sent." % cfg.env_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
