"""Oturum surekliligi olcumu: ikinci turda 'oturum' vermek ise yariyor mu?

    python tests/oturum_ab.py       # Ollama gerekir

Kurulum: TUR 1 bir kez kosar (stok.py yazilir), klasor iki kopyaya ayrilir.
TUR 2 ayni degisiklik istegi iki kez:
  A: oturum VERILIR  -> isci onceki konusmayi hatirlar, dosyayi yeniden okumasi gerekmez
  B: oturum VERILMEZ -> temiz baglam, dosyayi read_file ile okumak zorunda

Olculen: prompt tokeni, sure, arac sayisi, gizli kontrol (kalite). Iddia: A daha az token
harcar. Cikmazsa "denetci her turda oturum gecirmeli" kurali gereksiz demektir.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "oturum")

TUR1_GOREV = ("stok.py dosyasina iki fonksiyon yaz: stok_ekle(depo, urun, adet) -> depo sozlugune "
              "urunun adedini ekler (yoksa olusturur), yeni depo sozlugunu doner; stok_dus(depo, urun, adet) "
              "-> adedi duser, stok yetmezse ValueError, adet sifira inerse urunu sozlukten cikarir. "
              "Negatif adet ValueError. Girdi sozlugunu DEGISTIRME, kopyasini dondur.")
TUR1_KRITER = ["stok_ekle({}, 'elma', 3) -> {'elma': 3}",
               "stok_dus({'elma': 5}, 'elma', 2) -> {'elma': 3}; 5 dusunce urun sozlukten cikar",
               "Yetersiz stok ve negatif adet -> ValueError; girdi sozlugu degismez",
               "Yalnizca stok.py yazilir"]

TUR2_GOREV = ("Ayni stok.py dosyasina UCUNCU bir fonksiyon ekle: stok_tasi(depo, kaynak, hedef, adet) -> "
              "kaynak urunden adet kadar dusup hedef urune ekler ve yeni depoyu doner. Mevcut iki "
              "fonksiyonu KULLAN (kendi mantigini tekrar yazma) ve davranislarini bozma. "
              "Kaynakta yeterli stok yoksa ValueError.")
TUR2_KRITER = ["stok_tasi({'a': 5}, 'a', 'b', 2) -> {'a': 3, 'b': 2}",
               "Kaynak bitince kaynak urun sozlukten cikar",
               "Yetersiz stok -> ValueError; girdi sozlugu degismez",
               "Mevcut stok_ekle/stok_dus davranisi aynen korunur; yalnizca stok.py degisir"]

GIZLI = r'''
import sys
sys.path.insert(0, ".")
from stok import stok_ekle, stok_dus
try:
    from stok import stok_tasi
except ImportError:
    stok_tasi = None
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
kontrol("ekle yeni urun", lambda: stok_ekle({}, "elma", 3) == {"elma": 3})
kontrol("ekle mevcut urun", lambda: stok_ekle({"elma": 2}, "elma", 3) == {"elma": 5})
kontrol("dus normal", lambda: stok_dus({"elma": 5}, "elma", 2) == {"elma": 3})
kontrol("dus sifirlaninca cikar", lambda: stok_dus({"elma": 5, "armut": 1}, "elma", 5) == {"armut": 1})
kontrol("yetersiz stok", lambda: _hata(lambda: stok_dus({"elma": 1}, "elma", 2)))
kontrol("negatif adet", lambda: _hata(lambda: stok_ekle({}, "elma", -1)))
kontrol("girdi degismez", lambda: (lambda d: (stok_ekle(d, "x", 1), d == {"a": 1})[-1])({"a": 1}))
kontrol("tasi var", lambda: stok_tasi is not None)
if stok_tasi:
    kontrol("tasi temel", lambda: stok_tasi({"a": 5}, "a", "b", 2) == {"a": 3, "b": 2})
    kontrol("tasi kaynak biter", lambda: stok_tasi({"a": 2}, "a", "b", 2) == {"b": 2})
    kontrol("tasi yetersiz", lambda: _hata(lambda: stok_tasi({"a": 1}, "a", "b", 5)))
    kontrol("tasi girdi degismez", lambda: (lambda d: (stok_tasi(d, "a", "b", 1), d == {"a": 2})[-1])({"a": 2}))
for ad, ok, d in out:
    print(("OK   " if ok else "HATA ") + ad + ("  " + d if d else ""))
print("PUAN %d/%d" % (sum(1 for _, o, _ in out if o), len(out)))
'''


def gizli(klasor: str) -> tuple:
    r = subprocess.run([sys.executable, "-B", "-c", GIZLI], cwd=klasor, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"))
    cikti = (r.stdout or "") + (("\n" + r.stderr[-300:]) if r.returncode and r.stderr else "")
    puan = (0, 0)
    for satir in cikti.splitlines():
        if satir.startswith("PUAN"):
            a, b = satir.split()[1].split("/")
            puan = int(a), int(b)
    return puan, cikti


def cagir(c: Client, klasor_adi: str, gorev: str, kriter: list, oturum: str) -> dict:
    t0 = time.time()
    rep = c.tool("worker_run", {"gorev": gorev, "kabul_kriterleri": kriter, "ortam": "code",
                                "calisma_dizini": os.path.join("oturum", klasor_adi),
                                "dogrulama": "derleme", "yazilabilir": ["stok.py"],
                                "oturum": oturum}, timeout=1900)["structuredContent"]
    rep["_sure"] = time.time() - t0
    return rep


def main() -> int:
    if os.path.isdir(KOK):
        shutil.rmtree(KOK)
    os.makedirs(os.path.join(KOK, "tur1"))
    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "oturum-ab", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "home"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)

    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        print("TUR 1 (bir kez, ortak)", flush=True)
        r1 = cagir(c, "tur1", TUR1_GOREV, TUR1_KRITER, "")
        oturum1 = r1.get("oturum") or ""
        ku1 = r1.get("kullanim") or {}
        (g1, t1), _ = gizli(os.path.join(KOK, "tur1"))
        print("  %s | %.0f s | prompt %s | gizli %d/%d" % (r1.get("derleme_durumu"), r1["_sure"],
                                                           ku1.get("prompt_tokens"), g1, t1), flush=True)
        rapor["tur1"] = {"sure_s": round(r1["_sure"], 1), "kullanim": ku1, "gizli": "%d/%d" % (g1, t1)}

        for ad in ("A_oturumlu", "B_oturumsuz"):
            shutil.copytree(os.path.join(KOK, "tur1"), os.path.join(KOK, ad))

        print("\nTUR 2 - ayni istek, iki kip", flush=True)
        for ad, otr in (("A_oturumlu", oturum1), ("B_oturumsuz", "")):
            r = cagir(c, ad, TUR2_GOREV, TUR2_KRITER, otr)
            ku = r.get("kullanim") or {}
            (g, t), cikti = gizli(os.path.join(KOK, ad))
            rapor[ad] = {"oturum_verildi": bool(otr), "sure_s": round(r["_sure"], 1),
                         "prompt_tok": ku.get("prompt_tokens"), "uretim_tok": ku.get("gen_tokens"),
                         "arac": len(r.get("araclar", [])), "araclar": r.get("araclar", []),
                         "gizli": "%d/%d" % (g, t), "derleme_durumu": r.get("derleme_durumu")}
            print("  %-14s %-12s %4.0f s | prompt %6s | uretim %5s | arac %d | gizli %d/%d | %s" % (
                ad, r.get("derleme_durumu"), r["_sure"], ku.get("prompt_tokens"), ku.get("gen_tokens"),
                len(r.get("araclar", [])), g, t, ",".join(r.get("araclar", []))[:60]), flush=True)
    finally:
        c.close()
        yol = os.path.join(ROOT, "tests", "oturum_ab.son.json")
        with open(yol, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rapor, f, ensure_ascii=False, indent=1)
        print("\n->", yol)
    A, B = rapor.get("A_oturumlu"), rapor.get("B_oturumsuz")
    if A and B and A["prompt_tok"] and B["prompt_tok"]:
        print("KAZANC: prompt %d (oturumlu) vs %d (oturumsuz) = %.2fx | sure %.0f vs %.0f s" % (
            A["prompt_tok"], B["prompt_tok"], B["prompt_tok"] / A["prompt_tok"], A["sure_s"], B["sure_s"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
