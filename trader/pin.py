"""Live-trading PIN: salted PBKDF2 hash in a file on the VM. Set it on the VM (never through Telegram):
    python -m trader.pin set [path]
Python 3.6 compatible."""
import binascii
import hashlib
import hmac
import os
import sys

ITERS = 100000


def hash_pin(pin, salt=None, iters=ITERS):
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iters)
    return "pbkdf2$%d$%s$%s" % (iters, binascii.hexlify(salt).decode(), binascii.hexlify(h).decode())


def verify_pin(pin, stored):
    try:
        kind, iters, salt, h = stored.strip().split("$")
        if kind != "pbkdf2":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), binascii.unhexlify(salt), int(iters))
        return hmac.compare_digest(binascii.hexlify(calc).decode(), h)
    except Exception:
        return False


class PinFile(object):
    def __init__(self, path):
        self.path = path

    def is_set(self):
        return os.path.exists(self.path) and os.path.getsize(self.path) > 0

    def set(self, pin):
        if len(pin) < 6 or not pin.isdigit():
            raise ValueError("PIN must be at least 6 digits")
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(hash_pin(pin) + "\n")
        os.replace(tmp, self.path)

    def verify(self, pin):
        if not self.is_set():
            return False
        with open(self.path) as f:
            return verify_pin(pin, f.read())


def main(argv):
    import getpass
    if len(argv) < 2 or argv[1] != "set":
        print("usage: python -m trader.pin set [path]")
        return 2
    path = argv[2] if len(argv) > 2 else os.path.expanduser("~/trader/state/pin.hash")
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, 0o700)
    a = getpass.getpass("New PIN (6+ digits): ")
    b = getpass.getpass("Repeat PIN: ")
    if a != b:
        print("PINs differ")
        return 1
    try:
        PinFile(path).set(a)
    except ValueError as e:
        print(str(e))
        return 1
    print("PIN saved to", path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
