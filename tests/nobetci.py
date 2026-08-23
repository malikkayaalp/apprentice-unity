"""Nobetci: ~/.apprentice/jobs'u izler, her yeni is ve her bitis icin tek satir yazar.

    python tests/nobetci.py [--home ~/.apprentice] [--aralik 5]
Satirlar (stdout, satir basina bir olay):
  YENI  <id> <ortam> <gorev ilk 80 karakter>
  BITTI <id> <ortam> derleme=<ok|hata|calistirilamadi> sure=<s> araclar=<n> dosyalar=<...>
"""
from __future__ import annotations
import argparse, json, os, sys, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def events(p):
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=os.environ.get("APPRENTICE_HOME") or os.path.join(os.path.expanduser("~"), ".apprentice"))
    ap.add_argument("--aralik", type=float, default=5)
    a = ap.parse_args()
    jobs = os.path.join(a.home, "jobs")
    gorulen, biten = set(os.listdir(jobs)) if os.path.isdir(jobs) else set(), set()
    print("NOBET basladi: %s (%d eski is atlandi)" % (jobs, len(gorulen)))
    while True:
        time.sleep(a.aralik)
        if not os.path.isdir(jobs):
            continue
        for jid in sorted(os.listdir(jobs)):
            d = os.path.join(jobs, jid)
            if jid not in gorulen:
                gorulen.add(jid)
                try:
                    with open(os.path.join(d, "job.json"), encoding="utf-8") as f:
                        j = json.load(f)
                except Exception:
                    j = {}
                print("YENI  %s %s %s" % (jid, j.get("ortam", "?"), (j.get("gorev") or "")[:80].replace("\n", " ")))
            if jid in biten:
                continue
            ev = events(os.path.join(d, "events.jsonl"))
            if any(e.get("type") == "exit" for e in ev):
                biten.add(jid)
                res = next((e for e in ev if e.get("type") == "result"), None)
                err = [e.get("message", "") for e in ev if e.get("type") == "error"]
                durum = "calistirilamadi" if (res is None) else ("ok" if res.get("ok") else "hata")
                dosyalar = sorted({e.get("path", "") for e in ev if e.get("type") == "write"})
                try:
                    with open(os.path.join(d, "job.json"), encoding="utf-8") as f:
                        ortam = json.load(f).get("ortam", "?")
                except Exception:
                    ortam = "?"
                print("BITTI %s %s derleme=%s sure=%s araclar=%d dosyalar=%s %s" % (
                    jid, ortam, durum, (res or {}).get("wall", "?"),
                    sum(1 for e in ev if e.get("type") == "tool"), ",".join(dosyalar)[:160],
                    ("hata=" + err[0][:120]) if err else ""))


if __name__ == "__main__":
    main()
