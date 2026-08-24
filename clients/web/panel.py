"""Apprentice Web Panel - zengin canli izleme + web'den gorev gonderme.

    python clients/web/panel.py [--port 8788] [--home ~/.apprentice] [--ac]

Masaustu izleyicinin (izle.py) veri katmanini AYNEN kullanir; ayni events.jsonl'i okur.
Ek olarak POST /api/gorev ile tarayicidan is baslatilabilir: is, sunucudaki Job sinifiyla
ayni yoldan kosulur, job.json'a "kaynak": "web-panel" islenir - usta worker_status(is_id)
ile diskten gorebilir (sunucuya worker_status disk-yedegi eklendi). Bagimlilik yok (stdlib).
"""
from __future__ import annotations
import argparse, json, os, sys, threading, time, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from izle import IsDeposu, olay_satiri, kanit_coz  # noqa: E402

HOME = ""
DEPO: IsDeposu | None = None
KILIT = threading.Lock()
SAYFA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel.html")


def _sistem() -> dict:
    out = {"model": "", "yuklu_gb": 0, "vram": [0, 0], "gpu": 0}
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=3) as r:
            m = (json.load(r).get("models") or [])
        if m:
            out["model"] = m[0].get("name", "").split("/")[-1]
            out["yuklu_gb"] = round(m[0].get("size", 0) / 1e9)
    except Exception:
        out["model"] = None
    try:
        import subprocess
        s = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True,
                           timeout=3, creationflags=0x08000000 if os.name == "nt" else 0).stdout
        k, t, u = [int(x.strip()) for x in s.strip().split(",")[:3]]
        out["vram"] = [k, t]; out["gpu"] = u
    except Exception:
        pass
    return out


def _olaylar(jid: str, n: int) -> dict:
    with KILIT:
        DEPO.tazele(jid)
        s = dict(DEPO.durumlar.get(jid) or {})
        ev = DEPO.olaylar.get(jid) or []
        yeni = []
        for e in ev[n:]:
            et, metin = olay_satiri(e)
            yeni.append({"tip": e.get("type"), "asama": e.get("_asama"), "etiket": et,
                         "metin": metin, "yol": e.get("path"),
                         "kod": e.get("after") if e.get("type") == "write" else None,
                         "ham": {k: v for k, v in e.items()
                                 if k not in ("after", "before")} })
    canli = ""
    try:
        with open(os.path.join(DEPO.jobs_dir, jid, "canli.txt"), encoding="utf-8",
                  errors="replace") as f:
            canli = f.read()[-8000:]
    except OSError:
        pass
    s.pop("son_yazim", None)
    return {"ozet": s, "yeni": yeni, "toplam": n + len(yeni), "canli": canli}


def _is_listesi() -> list:
    with KILIT:
        adlar = DEPO.is_listesi()[:40]
        for jid in adlar[:10]:
            DEPO.tazele(jid)
        out = []
        for jid in adlar:
            s = DEPO.durumlar.get(jid) or {}
            out.append({"id": jid, "ortam": s.get("ortam", "?"), "durum": s.get("durum", "?"),
                        "derleme": s.get("derleme", "?"), "asama": s.get("asama", "?"),
                        "kaynak": s.get("kaynak", ""), "sure": s.get("sure")})
        return out


def _gorev_baslat(veri: dict) -> dict:
    """Web'den is: sunucudaki Job sinifinin ta kendisiyle (ayni olay semasi, ayni ev)."""
    os.environ.setdefault("APPRENTICE_HOME", HOME)
    os.environ["APPRENTICE_IZLEYICI"] = "0"            # panel zaten izliyor; pencere acma
    import importlib
    srv = importlib.import_module("server.apprentice_server")
    gorev = str(veri.get("gorev") or "").strip()
    if not gorev:
        return {"hata": "gorev bos"}
    kriterler = [k.strip() for k in (veri.get("kriterler") or []) if str(k).strip()]
    ortam = str(veri.get("ortam") or "code")
    if ortam not in srv.ENVS:
        return {"hata": "bilinmeyen ortam %r (var: %s)" % (ortam, list(srv.ENVS))}
    dogrulama = str(veri.get("dogrulama") or "derleme")
    kapali_ek = ["run_tests", "run_shell"] if dogrulama == "derleme" else []
    # calisma dizini EVE gore cozulur ve yoksa yaratilir (panelin MCP koku yok)
    dizin = str(veri.get("calisma_dizini") or "panel").strip().replace("\\", "/")
    if ".." in dizin or os.path.isabs(dizin):
        return {"hata": "calisma_dizini eve goreli olmali"}
    tam_dizin = os.path.join(HOME, dizin)
    os.makedirs(tam_dizin, exist_ok=True)
    job = srv.Job(ortam, gorev, kriterler, "", False, 3,
                  srv.config.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model"),
                  "", tam_dizin, kapali_ek, dogrulama,
                  [str(x).strip() for x in (veri.get("yazilabilir") or []) if str(x).strip()],
                  bool(veri.get("harita")), bool(veri.get("canli", True)))
    job.start()
    srv.JOBS[job.id] = job
    # kaynak isareti: usta ve izleyiciler bu isin panelden geldigini gorsun
    jp = os.path.join(job.dir, "job.json")
    try:
        with open(jp, encoding="utf-8") as f:
            j = json.load(f)
        j["kaynak"] = "web-panel"
        with open(jp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(j, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return {"is_id": job.id}


class Istek(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _gonder(self, govde, tip="application/json; charset=utf-8", kod=200):
        if isinstance(govde, (dict, list)):
            govde = json.dumps(govde, ensure_ascii=False).encode("utf-8")
        elif isinstance(govde, str):
            govde = govde.encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", tip)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(govde)

    def do_GET(self):
        yol = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(yol.query))
        try:
            if yol.path == "/":
                with open(SAYFA, encoding="utf-8") as f:
                    self._gonder(f.read(), "text/html; charset=utf-8")
            elif yol.path == "/api/isler":
                self._gonder({"isler": _is_listesi(), "sistem": _sistem()})
            elif yol.path == "/api/olaylar":
                self._gonder(_olaylar(q.get("is", ""), int(q.get("n", 0))))
            else:
                self._gonder({"hata": "yok"}, kod=404)
        except Exception as e:  # noqa: BLE001
            self._gonder({"hata": str(e)[:300]}, kod=500)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            veri = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if urllib.parse.urlparse(self.path).path == "/api/gorev":
                self._gonder(_gorev_baslat(veri))
            else:
                self._gonder({"hata": "yok"}, kod=404)
        except Exception as e:  # noqa: BLE001
            self._gonder({"hata": str(e)[:300]}, kod=500)


def main() -> int:
    global HOME, DEPO
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--home", default=os.environ.get("APPRENTICE_HOME") or
                    os.path.join(os.path.expanduser("~"), ".apprentice"))
    ap.add_argument("--ac", action="store_true", help="tarayiciyi ac")
    a = ap.parse_args()
    HOME = os.path.expanduser(a.home)
    DEPO = IsDeposu(HOME)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Istek)
    url = "http://127.0.0.1:%d" % a.port
    print("Apprentice Web Panel: %s  (ev: %s)" % (url, HOME))
    if a.ac:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
