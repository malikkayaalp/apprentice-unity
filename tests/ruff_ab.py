"""Ruff kaniti A/B olcumu: derlenen-ama-bozuk hatayi isci ruff uyarisiyla duzeltiyor mu?

    python tests/ruff_ab.py     # Ollama gerekir

Kurulum: envanter.py'de TOHUMLANMIS hata var - stok_ekle icinde tanimsiz kaydet_log(...)
cagrisi (F821: derlenir, cagrilinca NameError). Gorev iki kolda da ayni: "stok_dus ekle,
mevcut fonksiyonu bozma". Hata gorevde SOYLENMEZ.

  A: APPRENTICE_RUFF=0 -> yazim kaniti yalniz compile() (temiz gorunur)
  B: ruff acik         -> yazim cevabinda "F821 Undefined name kaydet_log" uyarisi

Gizli kontrol: stok_ekle gercekten CAGRILIR (A'da NameError beklenir), stok_dus dogrulugu.
Iddia: B'de isci uyariyi gorup tohumlanmis hatayi da duzeltir; A'da kopyalayip birakir.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "ruff_ab")

TOHUMLU = '''"""Basit envanter islemleri."""


def stok_ekle(depo, urun, adet):
    if adet < 0:
        raise ValueError("adet negatif olamaz")
    yeni = dict(depo)
    yeni[urun] = yeni.get(urun, 0) + adet
    kaydet_log(urun, adet)
    return yeni
'''

GOREV = ("envanter.py dosyasina stok_dus(depo, urun, adet) fonksiyonu ekle: adedi duser, "
         "stok yetmezse ValueError, sifira inen urun sozlukten cikar, girdi sozlugu degismez "
         "(kopya doner). Mevcut stok_ekle fonksiyonunun davranisini KORU.")
KRITER = ["stok_dus({'a': 5}, 'a', 2) -> {'a': 3}; sifira inince urun cikar",
          "Yetersiz stok -> ValueError; girdi degismez",
          "stok_ekle calismaya devam eder", "Yalnizca envanter.py degisir"]

GIZLI = r'''
import sys
sys.path.insert(0, ".")
from envanter import stok_ekle, stok_dus
out = []
def kontrol(ad, fn):
    try:
        r = fn(); out.append((ad, r is True, "" if r is True else "sonuc=%r" % (r,)))
    except Exception as e:
        out.append((ad, False, "%s: %s" % (type(e).__name__, str(e)[:70])))
kontrol("stok_ekle CALISIR (tohum hata)", lambda: stok_ekle({}, "elma", 3) == {"elma": 3})
kontrol("stok_dus temel", lambda: stok_dus({"a": 5}, "a", 2) == {"a": 3})
kontrol("stok_dus sifirda cikar", lambda: stok_dus({"a": 2, "b": 1}, "a", 2) == {"b": 1})
def _hata(f):
    try:
        f(); return False
    except ValueError:
        return True
    except Exception as e:
        return "baska istisna: " + type(e).__name__
kontrol("yetersiz stok ValueError", lambda: _hata(lambda: stok_dus({"a": 1}, "a", 3)))
kontrol("girdi degismez", lambda: (lambda d: (stok_dus(d, "a", 1), d == {"a": 2})[-1])({"a": 2}))
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


def kol(ad: str, ruff_acik: bool) -> dict:
    klasor = os.path.join(KOK, ad)
    os.makedirs(klasor)
    with open(os.path.join(klasor, "envanter.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(TOHUMLU)
    env = {"APPRENTICE_HOME": HOME}
    if not ruff_acik:
        env["APPRENTICE_RUFF"] = "0"
    c = Client(env)
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "ruff-ab", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "home"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)
    try:
        t0 = time.time()
        rep = c.tool("worker_run", {"gorev": GOREV, "kabul_kriterleri": KRITER, "ortam": "code",
                                    "calisma_dizini": os.path.join("ruff_ab", ad),
                                    "dogrulama": "derleme", "yazilabilir": ["envanter.py"]},
                     timeout=1900)["structuredContent"]
        sure = time.time() - t0
    finally:
        c.close()
    (g, t), cikti = gizli(klasor)
    ku = rep.get("kullanim") or {}
    son = open(os.path.join(klasor, "envanter.py"), encoding="utf-8").read()
    kayit = {"ruff": ruff_acik, "sure_s": round(sure, 1), "derleme_durumu": rep.get("derleme_durumu"),
             "prompt_tok": ku.get("prompt_tokens"), "uretim_tok": ku.get("gen_tokens"),
             "gizli": "%d/%d" % (g, t), "tohum_duzeldi": "kaydet_log" not in son or "def kaydet_log" in son,
             "cikti": cikti}
    print("  %-10s %-10s %4.0f s | prompt %6s | gizli %d/%d | tohum %s" % (
        ad, rep.get("derleme_durumu"), sure, ku.get("prompt_tokens"), g, t,
        "DUZELDI" if kayit["tohum_duzeldi"] else "DURUYOR (NameError)"), flush=True)
    return kayit


def main() -> int:
    if os.path.isdir(KOK):
        shutil.rmtree(KOK)
    os.makedirs(KOK)
    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S"),
             "A_rufsuz": kol("A_rufsuz", False), "B_ruflu": kol("B_ruflu", True)}
    with open(os.path.join(ROOT, "tests", "ruff_ab.son.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    print("-> tests/ruff_ab.son.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
