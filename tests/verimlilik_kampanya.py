"""Verimlilik kampanyasi: HAFIZA.md ve dogrulama kipi gercekten ise yariyor mu?

    python tests/verimlilik_kampanya.py [--deney hafiza,kip]     # Ollama gerekir

DENEY 1 - HAFIZA.md: ayni gorev iki kez, gorevde proje kurallari SOYLENMEZ.
  A: HAFIZA.md yok        B: HAFIZA.md'de 3 proje kurali var
  Gizli kontrol: kurallara uyuldu mu. Iddia: hafiza davranisi degistirir; degistirmezse sus payi.

DENEY 2 - dogrulama kipi: ayni gorev (kose durumlu) iki kez.
  A: dogrulama="tam" (isci test yazip kosar)   B: dogrulama="derleme" (yalniz yazar)
  Iddia: derleme kipi hizli/ucuz ama KALITE dusebilir; fark olculecek.

Sonuc: tests/verimlilik_kampanya.son.json + ekrana tablo.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "verimlilik")

HAFIZA_METNI = """# Proje hafizasi

- Para birimi DAIMA kurus (int) tutulur; float para kullanilmaz. Fonksiyon adlari `_kurus` ile biter.
- Her modul dosyasi tek satirlik bir modul docstring'i ile baslar.
- Girdi dogrulamasi ValueError ile yapilir; assert kullanilmaz.
"""

HAFIZA_GOREV = ("odeme.py dosyasina iki fonksiyon yaz: bir siparisin ara toplamini hesaplayan "
                "fonksiyon (satirlar: her biri {'adet': int, 'birim_fiyat': int} sozlugu) ve "
                "ara toplama kargo ekleyen fonksiyon (ara toplam 50000 ve uzerinde kargo bedava, "
                "altinda 2999). Negatif adet ya da negatif fiyat kabul edilmez.")
HAFIZA_KRITER = ["Ara toplam = her satirin adet x birim_fiyat toplami",
                 "Kargo: ara toplam >= 50000 ise 0, degilse 2999 eklenir",
                 "Negatif adet ya da negatif fiyat girdisi reddedilir",
                 "Yalnizca odeme.py yazilir"]

HAFIZA_GIZLI = r'''
import re, ast, importlib.util
out = []
def kontrol(ad, deger, detay=""):
    out.append((ad, bool(deger), detay))
src = open("odeme.py", encoding="utf-8").read()
fnler = re.findall(r"^def\s+([a-zA-Z_0-9]+)", src, re.M)
kontrol("K1 fonksiyon adlari _kurus ile biter", fnler and all(f.endswith("_kurus") for f in fnler), str(fnler))
try:
    kontrol("K2 modul docstring var", bool(ast.get_docstring(ast.parse(src))))
except Exception as e:
    kontrol("K2 modul docstring var", False, str(e)[:60])
ondalik = re.search(r"\d+\.\d+", src)
kontrol("K3 float para yok", not ondalik, ondalik.group(0) if ondalik else "")
kontrol("K4 assert yok, ValueError var", ("assert " not in src) and ("ValueError" in src))
spec = importlib.util.spec_from_file_location("odeme", "odeme.py"); m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
    fns = [getattr(m, f) for f in fnler]
    ara = next((f for f in fns if "kargo" not in f.__name__), None)
    kargo = next((f for f in fns if "kargo" in f.__name__), None)
    satirlar = [{"adet": 2, "birim_fiyat": 1500}, {"adet": 1, "birim_fiyat": 2000}]
    kontrol("D1 ara toplam 5000", ara and ara(satirlar) == 5000, "" if ara else "fonksiyon yok")
    if kargo:
        try:
            v = kargo(5000)
        except TypeError:
            v = kargo(satirlar)
        kontrol("D2 kargo eklenir (5000 -> 7999)", v == 7999, "sonuc=%r" % (v,))
        try:
            v2 = kargo(50000)
        except TypeError:
            v2 = kargo([{"adet": 1, "birim_fiyat": 50000}])
        kontrol("D3 50000 ustu bedava", v2 == 50000, "sonuc=%r" % (v2,))
    else:
        kontrol("D2 kargo fonksiyonu var", False)
    try:
        ara([{"adet": -1, "birim_fiyat": 100}]); kontrol("D4 negatif reddedilir", False, "hata yok")
    except ValueError:
        kontrol("D4 negatif reddedilir", True)
    except Exception as e:
        kontrol("D4 negatif reddedilir", False, type(e).__name__)
except Exception as e:
    kontrol("modul yuklendi", False, "%s: %s" % (type(e).__name__, str(e)[:80]))
for ad, ok, d in out:
    print(("OK   " if ok else "HATA ") + ad + ("  " + d if d else ""))
print("KURAL %d/4" % sum(1 for a, o, _ in out if a.startswith("K") and o))
print("PUAN %d/%d" % (sum(1 for _, o, _ in out if o), len(out)))
'''

KIP_GOREV = ("aralik.py dosyasina birlestir(araliklar) fonksiyonu yaz: [(bas, son), ...] listesini "
             "alir, ust uste binen ya da DEGEN araliklari birlestirip sirali liste doner. "
             "Ornek: [(1,3),(2,6),(8,10)] -> [(1,6),(8,10)]. Bos liste -> []. "
             "bas > son olan aralik ValueError.")
KIP_KRITER = ["birlestir([(1,3),(2,6),(8,10)]) == [(1,6),(8,10)]",
              "Bos liste -> []; tek aralik aynen doner",
              "Degen araliklar birlesir: [(1,4),(4,5)] -> [(1,5)]",
              "bas > son -> ValueError",
              "Yalnizca aralik.py (ve istenirse testi) yazilir"]

KIP_GIZLI = r'''
import sys
sys.path.insert(0, ".")
from aralik import birlestir as b
out = []
def kontrol(ad, fn):
    try:
        r = fn(); out.append((ad, r is True, "" if r is True else "sonuc=%r" % (r,)))
    except Exception as e:
        out.append((ad, False, "%s: %s" % (type(e).__name__, str(e)[:70])))
def liste(x):
    return [tuple(t) for t in x]
kontrol("temel ornek", lambda: liste(b([(1,3),(2,6),(8,10)])) == [(1,6),(8,10)])
kontrol("bos liste", lambda: liste(b([])) == [])
kontrol("tek aralik", lambda: liste(b([(2,5)])) == [(2,5)])
kontrol("degen [(1,4),(4,5)]", lambda: liste(b([(1,4),(4,5)])) == [(1,5)])
kontrol("sirasiz [(5,7),(1,3),(2,4)]", lambda: liste(b([(5,7),(1,3),(2,4)])) == [(1,4),(5,7)])
kontrol("icine alan [(1,10),(2,3)]", lambda: liste(b([(1,10),(2,3)])) == [(1,10)])
kontrol("ayni aralik iki kez", lambda: liste(b([(1,2),(1,2)])) == [(1,2)])
kontrol("bitisik degil [(1,2),(3,4)]", lambda: liste(b([(1,2),(3,4)])) == [(1,2),(3,4)])
def _hata():
    try:
        b([(5,1)]); return False
    except ValueError:
        return True
    except Exception as e:
        return "baska istisna: " + type(e).__name__
kontrol("bas>son ValueError", _hata)
kontrol("girdi listesi degismez", lambda: (lambda L: (b(L), L == [(3,4),(1,2)])[-1])([(3,4),(1,2)]))
for ad, ok, d in out:
    print(("OK   " if ok else "HATA ") + ad + ("  " + d if d else ""))
print("PUAN %d/%d" % (sum(1 for _, o, _ in out if o), len(out)))
'''


def gizli(klasor: str, kod: str) -> tuple:
    r = subprocess.run([sys.executable, "-B", "-c", kod], cwd=klasor, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"))
    cikti = (r.stdout or "") + (("\n" + r.stderr[-400:]) if r.returncode and r.stderr else "")
    puan, kural = (0, 0), None
    for satir in cikti.splitlines():
        if satir.startswith("PUAN"):
            a, b = satir.split()[1].split("/"); puan = int(a), int(b)
        if satir.startswith("KURAL"):
            kural = satir.split()[1]
    return puan, kural, cikti


def kosu(c: Client, etiket: str, klasor: str, gorev: str, kriterler: list, gizli_kod: str,
         dogrulama: str = "derleme", hafiza: str = "") -> dict:
    tam = os.path.join(KOK, klasor)
    if os.path.isdir(tam):
        shutil.rmtree(tam)
    os.makedirs(tam)
    if hafiza:
        with open(os.path.join(tam, "HAFIZA.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(hafiza)
    t0 = time.time()
    rep = c.tool("worker_run", {"gorev": gorev, "kabul_kriterleri": kriterler, "ortam": "code",
                                "calisma_dizini": os.path.join("verimlilik", klasor),
                                "dogrulama": dogrulama}, timeout=1900)["structuredContent"]
    sure = time.time() - t0
    (gecen, toplam), kural, cikti = gizli(tam, gizli_kod)
    ku = rep.get("kullanim") or {}
    donus = len(json.dumps(rep, ensure_ascii=False))
    kayit = {"etiket": etiket, "dogrulama": dogrulama, "hafiza": bool(hafiza),
             "sure_s": round(sure, 1), "derleme_durumu": rep.get("derleme_durumu"),
             "prompt_tok": ku.get("prompt_tokens"), "uretim_tok": ku.get("gen_tokens"),
             "arac": len(rep.get("araclar", [])), "donus_tok": donus // 4,
             "gizli": "%d/%d" % (gecen, toplam), "kural": kural,
             "dosya": [d["yol"] for d in rep.get("yazilan_dosyalar", [])],
             "cikti": cikti[-700:], "is_id": rep.get("is_id")}
    print("  %-22s %-16s %4.0f s | prompt %6s | uretim %5s | arac %2d | donus ~%5d tok | gizli %s%s"
          % (etiket, kayit["derleme_durumu"], sure, kayit["prompt_tok"], kayit["uretim_tok"],
             kayit["arac"], kayit["donus_tok"], kayit["gizli"],
             (" | kural " + kural) if kural else ""), flush=True)
    return kayit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deney", default="hafiza,kip")
    a = ap.parse_args()
    secili = [x.strip() for x in a.deney.split(",") if x.strip()]
    os.makedirs(KOK, exist_ok=True)

    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "verimlilik", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "home"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)

    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        if "hafiza" in secili:
            print("\nDENEY 1 - HAFIZA.md (proje kurallari gorevde SOYLENMIYOR)", flush=True)
            rapor["hafiza_A_yok"] = kosu(c, "A hafizasiz", "hafiza_A", HAFIZA_GOREV, HAFIZA_KRITER,
                                         HAFIZA_GIZLI, "derleme", hafiza="")
            rapor["hafiza_B_var"] = kosu(c, "B hafizali", "hafiza_B", HAFIZA_GOREV, HAFIZA_KRITER,
                                         HAFIZA_GIZLI, "derleme", hafiza=HAFIZA_METNI)
        if "kip" in secili:
            print("\nDENEY 2 - dogrulama kipi (ayni gorev, kose durumlu)", flush=True)
            rapor["kip_A_tam"] = kosu(c, "A tam (test kosar)", "kip_A", KIP_GOREV, KIP_KRITER,
                                      KIP_GIZLI, "tam")
            rapor["kip_B_derleme"] = kosu(c, "B derleme (yalniz yaz)", "kip_B", KIP_GOREV, KIP_KRITER,
                                          KIP_GIZLI, "derleme")
    finally:
        c.close()
        yol = os.path.join(ROOT, "tests", "verimlilik_kampanya.son.json")
        with open(yol, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rapor, f, ensure_ascii=False, indent=1)
        print("\n->", yol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
