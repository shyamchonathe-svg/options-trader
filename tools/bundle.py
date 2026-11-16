#!/usr/bin/env python3
"""Build a paste-bundle for the VM from a COMMITTED git ref (so the VM only ever runs versioned code).
Usage: python3 tools/bundle.py [ref]          default ref = HEAD
Output: deploy/out/<version>/00_prepare.txt, chunk_NN.txt ..., 99_install.txt   (paste in that order into the VM shell)
Python 3.6+ stdlib only."""
import sys, os, io, subprocess, tarfile, gzip, base64, hashlib, time, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNK = int(os.environ.get("BUNDLE_CHUNK", "6000"))   # base64 characters per paste

def sh(*a):
    return subprocess.check_output(a, cwd=ROOT).decode().strip()

def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    sha = sh("git", "rev-parse", "--short", ref)
    branch = sh("git", "rev-parse", "--abbrev-ref", ref).replace("/", "-")
    try: tag = sh("git", "describe", "--tags", "--exact-match", ref)
    except Exception: tag = ""
    dirty = bool(sh("git", "status", "--porcelain"))
    version = tag or ("%s-%s" % (branch, sha))
    ignore = [l.strip() for l in open(os.path.join(ROOT, ".bundleignore")) if l.strip() and not l.startswith("#")]
    raw = subprocess.check_output(["git", "archive", "--format=tar", ref], cwd=ROOT)
    src = tarfile.open(fileobj=io.BytesIO(raw))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as dst:
        for m in src.getmembers():
            if any((m.name + "/").startswith(p) or m.name.startswith(p) for p in ignore): continue
            dst.addfile(m, src.extractfile(m) if m.isfile() else None)
        info = ("version=%s\ncommit=%s\nbranch=%s\nbuilt=%s\nworking_tree_dirty=%s\n" %
                (version, sh("git", "rev-parse", ref), branch, time.strftime("%Y-%m-%d %H:%M:%S"), dirty)).encode()
        ti = tarfile.TarInfo("VERSION"); ti.size = len(info); ti.mtime = 0
        dst.addfile(ti, io.BytesIO(info))
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g: g.write(buf.getvalue())
    b64 = base64.b64encode(gz.getvalue()).decode()
    lines = [b64[i:i + 76] for i in range(0, len(b64), 76)]
    b64_text = "\n".join(lines) + "\n"
    digest = hashlib.sha256(b64_text.encode()).hexdigest()

    out = os.path.join(ROOT, "deploy", "out", version)
    if os.path.isdir(out): shutil.rmtree(out)
    os.makedirs(out)
    def w(name, text): open(os.path.join(out, name), "w").write(text)
    w("00_prepare.txt", "mkdir -p ~/trader/incoming ~/trader/releases && : > ~/trader/incoming/bundle.b64 && echo prepared\n")
    per = CHUNK // 77
    n = 0
    for i in range(0, len(lines), per):
        n += 1
        w("chunk_%02d.txt" % n, "cat >> ~/trader/incoming/bundle.b64 <<'EOF_CHUNK'\n%s\nEOF_CHUNK\necho chunk %d ok\n" % ("\n".join(lines[i:i + per]), n))
    w("99_install.txt", """cd ~/trader/incoming
GOT=$(sha256sum bundle.b64 | cut -d' ' -f1)
if [ "$GOT" = "%(d)s" ]; then
  base64 -d bundle.b64 > bundle.tar.gz && mkdir -p ~/trader/releases/%(v)s && tar -xzf bundle.tar.gz -C ~/trader/releases/%(v)s \\
  && ln -sfn ~/trader/releases/%(v)s ~/trader/current && cd ~/trader/current && cat VERSION \\
  && ~/trader/venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -4
else
  echo "CHECKSUM MISMATCH (got $GOT) - a chunk was truncated; run 00_prepare and paste ALL chunks again"
fi
""" % {"d": digest, "v": version})
    print("version  :", version, "(working tree dirty)" if dirty else "")
    print("bundle   : %d bytes gz, %d chunks, sha256 %s" % (len(gz.getvalue()), n, digest[:12]))
    print("folder   :", out)
    print("paste in : 00_prepare.txt, chunk_01..%02d.txt, 99_install.txt" % n)

if __name__ == "__main__":
    main()
