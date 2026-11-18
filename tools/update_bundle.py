#!/usr/bin/env python3
"""Build paste files that bring the VM's git clone (~/trader/repo) up to a new tag, using an incremental git bundle.
Usage: python3 tools/update_bundle.py <base-tag-on-the-VM> <new-tag> [out-dir]
Output: <out-dir>/00_prepare.txt, chunk_NN.txt, 99_merge.txt (paste in that order on the VM), then on the VM:
  cd ~/trader/repo && git push origin main --tags && bash tools/release.sh <new-tag>
Python 3.6+ stdlib only."""
import base64, hashlib, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PER = 70   # base64 lines (76 chars) per paste


def main():
    base, new = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, "..", "repo-seed", "update_" + new)
    os.makedirs(out, exist_ok=True)
    bundle = os.path.join(out, "update.bundle")
    subprocess.check_call(["git", "bundle", "create", bundle, "main", new, "^" + base], cwd=ROOT)
    subprocess.check_call(["git", "bundle", "verify", bundle], cwd=ROOT)
    b64 = base64.b64encode(open(bundle, "rb").read()).decode()
    lines = [b64[i:i + 76] for i in range(0, len(b64), 76)]
    text = "\n".join(lines) + "\n"
    digest = hashlib.sha256(text.encode()).hexdigest()
    open(os.path.join(out, "00_prepare.txt"), "w").write(
        "mkdir -p ~/trader/incoming && : > ~/trader/incoming/upd.b64 && echo prepared\n")
    n = 0
    for i in range(0, len(lines), PER):
        n += 1
        open(os.path.join(out, "chunk_%02d.txt" % n), "w").write(
            "cat >> ~/trader/incoming/upd.b64 <<'EOF_CHUNK'\n%s\nEOF_CHUNK\necho chunk %d ok\n" % ("\n".join(lines[i:i + PER]), n))
    open(os.path.join(out, "99_merge.txt"), "w").write(
        """cd ~/trader/incoming && GOT=$(sha256sum upd.b64 | cut -d' ' -f1)
if [ "$GOT" = "%s" ]; then
  base64 -d upd.b64 > update.bundle && cd ~/trader/repo && git fetch ../incoming/update.bundle main 2>&1 | tail -2 && git merge --ff-only FETCH_HEAD | tail -2 \\
  && git fetch ../incoming/update.bundle 'refs/tags/*:refs/tags/*' 2>&1 | tail -2 && git log --oneline -3 main && git tag
else echo "CHECKSUM MISMATCH ($GOT) - run 00_prepare and paste ALL chunks again"; fi
""" % digest)
    print("bundle %d bytes, %d chunks, sha256 %s -> %s" % (os.path.getsize(bundle), n, digest[:12], out))


if __name__ == "__main__":
    main()
