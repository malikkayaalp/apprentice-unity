"""Canli kip A/B: XML-icerik protokolu (canli=true) native tool yoluna gore kalite/maliyet?

    python tests/canli_ab.py    # Ollama gerekir

Ayni gorev iki kolda: A native (varsayilan), B canli (XML-icerik + token akisi).
Olculen: gizli 6 kontrol, prompt/uretim token, sure. Canli kipin bedeli kabul edilebilirse
"izlerken calistir" kipi olarak kurala girer; kalite dusuyorsa yalniz gosteri amacli kalir.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
try:      # pencereli exe/pythonw: sys.stdout None olabilir (kurulum oz-testi
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # bu satirda cokuyordu)
except Exception:
    pass
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "canli_ab")

GOREV = ("siparis.py dosyasina iki fonksiyon yaz: siparis_toplami(kalemler) -> her kalem "
         "{'fiyat_kurus': int, 'adet': int}; toplami kurus cinsinden int doner, bos listede 0. "
         "indirim_uygula(toplam_kurus, yuzde) -> yeni toplami int doner, yuzde 0-100 disinda "
         "ValueError. Girdileri DEGISTIRME.")
KRITER = ["siparis_toplami([{'fiyat_kurus':1000,'adet':3}]) == 3000",
          "indirim_uygula(10000, 25) == 7500; yuzde 101 -> ValueError",
          "Yalnizca siparis.py yazilir"]

GIZLI = r'''
import sys
sys.path.insert(0, ".")
from siparis import siparis_toplami, indirim_uygula
out = []
def kontrol(ad, fn):
    try:
        r = fn(); out.append((ad, r is True, "" if r is True else "sonuc=%r" % (r,)))
    except Exception as e:
        out.append((ad, False, "%s: %s" % (type(e).__name__, str(e)[:70])))
def _hata(f):
    try:
        f(); return False
    except ValueError:
        return True
    except Exception as e:
        return "baska istisna: " + type(e).__name__
kontrol("toplam", lambda: siparis_toplami([{"fiyat_kurus": 1000, "adet": 3},
                                           {"fiyat_kurus": 250, "adet": 2}]) == 3500)
kontrol("bos liste 0", lambda: siparis_toplami([]) == 0)
kontrol("indirim", lambda: indirim_uygula(10000, 25) == 7500)
kontrol("int doner", lambda: isinstance(indirim_uygula(999, 10), int))
kontrol("yuzde 101 ValueError", lambda: _hata(lambda: indirim_uygula(100, 101)))
kontrol("negatif yuzde ValueError", lambda: _hata(lambda: indirim_uygula(100, -1)))
for ad, ok, d in out:
    print(("OK   " if ok else "HATA ") + ad + ("  " + d if d else ""))
print("PUAN %d/%d" % (sum(1 for _, o, _ in out if o), len(out)))
'''


def gizli(klasor: str) -> tuple:
    r = subprocess.run([sys.executable, "-B", "-c", GIZLI], cwd=klasor, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"))
    cikti = (r.stdout or "") + (("\n" + r.stderr[-300:]) if r.returncode and r.stderr else "")
    puan = (0, 0)
    for s in cikti.splitlines():
        if s.startswith("PUAN"):
            a, b = s.split()[1].split("/")
            puan = int(a), int(b)
    return puan, cikti


def kol(c: Client, ad: str, canli: bool) -> dict:
    os.makedirs(os.path.join(KOK, ad))
    t0 = time.time()
    rep = c.tool("worker_run", {"gorev": GOREV, "kabul_kriterleri": KRITER, "ortam": "code",
                                "calisma_dizini": os.path.join("canli_ab", ad),
                                "dogrulama": "derleme", "yazilabilir": ["siparis.py"],
                                "canli": canli}, timeout=1900)["structuredContent"]
    sure = time.time() - t0
    (g, t), cikti = gizli(os.path.join(KOK, ad))
    ku = rep.get("kullanim") or {}
    print("  %-9s %-9s %4.0f s | prompt %6s | uretim %5s | gizli %d/%d" % (
        ad, rep.get("derleme_durumu"), sure, ku.get("prompt_tokens"),
        ku.get("gen_tokens"), g, t), flush=True)
    return {"canli": canli, "sure_s": round(sure, 1), "prompt_tok": ku.get("prompt_tokens"),
            "uretim_tok": ku.get("gen_tokens"), "gizli": "%d/%d" % (g, t),
            "derleme_durumu": rep.get("derleme_durumu"), "cikti": cikti}


def main() -> int:
    if os.path.isdir(KOK):
        shutil.rmtree(KOK)
    os.makedirs(KOK)
    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "canli-ab", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "h"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)
    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        rapor["A_native"] = kol(c, "A_native", False)
        rapor["B_canli"] = kol(c, "B_canli", True)
    finally:
        c.close()
        with open(os.path.join(ROOT, "tests", "canli_ab.son.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(rapor, f, ensure_ascii=False, indent=1)
        print("-> tests/canli_ab.son.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
