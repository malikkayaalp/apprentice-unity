"""Code ortami olcum kampanyasi: denetci-isci deseninin sayisal karnesi.

    python tests/code_kampanya.py [--tur 2] [--gorev parantez,lru]

Her gorev icin: denetci (bu betik) gorevi + kabul kriterlerini verir, isci (worker_run,
code ortami) yazar; sonra denetci ISCIYE VERILMEYEN gizli kontrolleri calisma dizininde
kosar (isci testlerine guvenmeden). Tutmayanlar somut geri bildirime cevrilir ve ayni
'oturum' ile 2. tur istenir. Olculen: tur-1 gizli kontrol basarisi, tur-2 basarisi, sure,
onarim turu. Sonuc: tests/code_kampanya.son.json.

Neden gizli kontrol: iscinin "tum testler gecti" beyani kendi yazdigi testlere dayanir;
denetcinin degeri, iscinin dusunmedigi kose durumunu sormaktir.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")

# Her gizli kontrol: (aciklama, python ifadesi -> True beklenir). Ifade calisma dizininde,
# modul import edilmis halde degerlendirilir; istisna = basarisiz.
GOREVLER = {
    "parantez": {
        "gorev": "parantez.py dosyasina dengeli(metin) fonksiyonu yaz: (), [], {} parantezlerinin "
                 "dogru ic ice kapanip kapanmadigini bool olarak doner. Diger karakterler yok sayilir. "
                 "test_parantez.py'ye unittest testleri yaz.",
        "kriterler": ["dengeli('()[]{}') True, dengeli('([{}])') True, dengeli('(]') False, dengeli('((') False",
                      "Parantez disi karakterler yok sayilir: dengeli('a(b)c') True",
                      "run_tests hatasiz gecer; yalnizca parantez.py ve test_parantez.py yazilir"],
        "modul": "parantez",
        "gizli": [("bos metin True", "dengeli('') is True"),
                  ("yalniz kapanis False", "dengeli(')') is False"),
                  ("carpraz kapanis False", "dengeli('([)]') is False"),
                  ("uzun dengeli", "dengeli('('*500 + ')'*500) is True"),
                  ("fazla kapanis False", "dengeli('())') is False"),
                  ("bool donus tipi", "type(dengeli('()')) is bool")],
    },
    "lru": {
        "gorev": "lru.py dosyasina LRU sinifi yaz: LRU(kapasite); put(anahtar, deger); get(anahtar) "
                 "-> deger ya da None. Kapasite asilinca en uzun suredir kullanilmayan silinir; get ve put "
                 "ikisi de 'kullanim' sayilir. test_lru.py'ye unittest testleri yaz.",
        "kriterler": ["c=LRU(2); c.put(1,1); c.put(2,2); c.get(1)==1; c.put(3,3); c.get(2) is None; c.get(3)==3",
                      "Var olan anahtara put deger gunceller ve onu en yeni yapar",
                      "len(c) mevcut eleman sayisini verir",
                      "run_tests hatasiz gecer; yalnizca lru.py ve test_lru.py yazilir"],
        "modul": "lru",
        "gizli": [("get yenilemesi", "(lambda c: (c.put(1,1), c.put(2,2), c.get(1), c.put(3,3), c.get(2) is None and c.get(1)==1)[-1])(LRU(2))"),
                  ("put guncelleme yeniler", "(lambda c: (c.put(1,1), c.put(2,2), c.put(1,9), c.put(3,3), c.get(2) is None and c.get(1)==9)[-1])(LRU(2))"),
                  ("kapasite 1", "(lambda c: (c.put('a',1), c.put('b',2), c.get('a') is None and c.get('b')==2)[-1])(LRU(1))"),
                  ("len", "(lambda c: (c.put(1,1), c.put(2,2), c.put(3,3), len(c)==2)[-1])(LRU(2))"),
                  ("None deger saklanabilir mi / yok olan None", "LRU(2).get('yok') is None"),
                  ("kapasite asiminda en eski gider", "(lambda c: (c.put(1,1), c.put(2,2), c.put(3,3), c.put(4,4), c.get(1) is None and c.get(2) is None and c.get(3)==3)[-1])(LRU(2))")],
    },
    "roma": {
        "gorev": "roma.py dosyasina romaya(n) ve romadan(s) fonksiyonlari yaz: 1..3999 arasi tam sayi <-> "
                 "Roma rakami (buyuk harf, cikarma kurali: IV, IX, XL, XC, CD, CM). Aralik disi ya da gecersiz "
                 "girdide ValueError. test_roma.py'ye unittest testleri yaz.",
        "kriterler": ["romaya(1994)=='MCMXCIV', romaya(4)=='IV', romaya(3999)=='MMMCMXCIX'",
                      "romadan('MCMXCIV')==1994, romadan('LVIII')==58",
                      "romaya(0), romaya(4000), romadan(''), romadan('IIII') -> ValueError",
                      "run_tests hatasiz gecer; yalnizca roma.py ve test_roma.py yazilir"],
        "modul": "roma",
        "gizli": [("gidis-donus 1..3999", "all(romadan(romaya(i))==i for i in range(1,4000))"),
                  ("kucuk harf ValueError", "_raises(lambda: romadan('mcmxciv'))"),
                  ("VX gecersiz", "_raises(lambda: romadan('VX'))"),
                  ("IM gecersiz", "_raises(lambda: romadan('IM'))"),
                  ("negatif ValueError", "_raises(lambda: romaya(-5))"),
                  ("3888 en uzun", "romaya(3888)=='MMMDCCCLXXXVIII'")],
    },
    "satis": {
        "gorev": "satis.py dosyasina kategori_toplam(satirlar) fonksiyonu yaz: her satir "
                 "{'kategori': str, 'adet': int, 'fiyat': float} sozlugu; kategori -> toplam tutar "
                 "(adet*fiyat) sozlugu doner, kategori adi bosluklari kirpilmis ve kucuk harfe cevrilmis "
                 "olarak anahtar olur. test_satis.py'ye unittest testleri yaz.",
        "kriterler": ["[{'kategori':'Oyuncak','adet':2,'fiyat':10.0},{'kategori':'oyuncak ','adet':1,'fiyat':5.0}] -> {'oyuncak': 25.0}",
                      "Bos liste -> {}",
                      "adet 0 olan satir toplami degistirmez ama kategori anahtari olusur (0.0)",
                      "run_tests hatasiz gecer; yalnizca satis.py ve test_satis.py yazilir"],
        "modul": "satis",
        "gizli": [("bos liste", "kategori_toplam([]) == {}"),
                  ("kirpma+kucuk harf birlestirme", "kategori_toplam([{'kategori':'  A ','adet':1,'fiyat':2.0},{'kategori':'a','adet':1,'fiyat':3.0}]) == {'a': 5.0}"),
                  ("adet 0 anahtar", "kategori_toplam([{'kategori':'x','adet':0,'fiyat':9.0}]) == {'x': 0.0}"),
                  ("iki kategori", "kategori_toplam([{'kategori':'x','adet':2,'fiyat':1.5},{'kategori':'y','adet':1,'fiyat':1.0}]) == {'x': 3.0, 'y': 1.0}"),
                  ("girdi listesi degismez", "(lambda L: (kategori_toplam(L), L == [{'kategori':' Q','adet':1,'fiyat':1.0}])[-1])([{'kategori':' Q','adet':1,'fiyat':1.0}])"),
                  ("float toplam", "abs(kategori_toplam([{'kategori':'k','adet':3,'fiyat':0.1}])['k'] - 0.3) < 1e-9")],
    },
    "fib_onar": {
        "on_dosyalar": {"fib.py": "def fib(n):\n    \"\"\"n. Fibonacci sayisi: fib(0)=0, fib(1)=1.\"\"\"\n    if n < 0:\n        return None\n    a, b = 0, 1\n    for _ in range(n - 1):\n        a, b = b, a + b\n    return b\n"},
        "gorev": "fib.py'deki fib(n) hatali: fib(0) 1 donuyor (0 olmali) ve negatif n'de None donuyor "
                 "(ValueError firlatmali). read_file ile oku, hatayi duzelt, test_fib.py'ye unittest testleri yaz. "
                 "Fonksiyon imzasini ve dosya adini degistirme.",
        "kriterler": ["fib(0)==0, fib(1)==1, fib(2)==1, fib(10)==55",
                      "fib(-1) ValueError firlatir",
                      "run_tests hatasiz gecer; yalnizca fib.py ve test_fib.py yazilir"],
        "modul": "fib",
        "gizli": [("fib(0)", "fib(0) == 0"), ("fib(1)", "fib(1) == 1"), ("fib(2)", "fib(2) == 1"),
                  ("fib(30)", "fib(30) == 832040"), ("negatif", "_raises(lambda: fib(-1))"),
                  ("docstring korunmus", "'Fibonacci' in (fib.__doc__ or '')")],
    },
    "kelime": {
        "gorev": "kelime.py dosyasina en_sik(metin, n) fonksiyonu yaz: metindeki kelimeleri (harf "
                 "disi karakterler ayirici, buyuk/kucuk harf duyarsiz) sayar ve en sik n kelimeyi "
                 "[(kelime, sayi), ...] olarak, sayiya gore azalan, esitlikte alfabetik sirayla doner. "
                 "test_kelime.py'ye unittest testleri yaz.",
        "kriterler": ["en_sik('a b a c b a', 2) == [('a',3),('b',2)]",
                      "Noktalama ayirici: en_sik('Bir, bir! BIR? iki', 1) == [('bir',3)]",
                      "Esitlikte alfabetik: en_sik('z y x', 3) == [('x',1),('y',1),('z',1)]",
                      "n kelime sayisindan buyukse hepsini doner; bos metin -> []",
                      "run_tests hatasiz gecer; yalnizca kelime.py ve test_kelime.py yazilir"],
        "modul": "kelime",
        "gizli": [("bos", "en_sik('', 3) == []"),
                  ("n buyuk", "en_sik('a b', 10) == [('a',1),('b',1)]"),
                  ("n=0", "en_sik('a b', 0) == []"),
                  ("esitlik alfabetik", "en_sik('b a c', 2) == [('a',1),('b',1)]"),
                  ("rakamlar ayirici mi? (harf disi)", "en_sik('a1a', 1) == [('a',2)]"),
                  ("alt cizgi ayirici", "en_sik('x_x', 1) == [('x',2)]")],
    },
}


def gizli_kontrol(work: str, modul: str, kontroller: list) -> list:
    """Her kontrolu ayri ifade olarak calisma dizininde kosar; [(aciklama, gecti, detay)]."""
    kod = (
        "import json, sys, traceback\n"
        "def _raises(f):\n"
        "    try: f()\n"
        "    except ValueError: return True\n"
        "    except Exception as e: return 'baska istisna: ' + type(e).__name__\n"
        "    return False\n"
        "out = []\n"
        "try:\n"
        "    from %s import *\n"
        "except Exception as e:\n"
        "    print(json.dumps([[k, False, 'import: %%s' %% e] for k, _ in KONTROL])); sys.exit(0)\n"
        "for ad, ifade in KONTROL:\n"
        "    try:\n"
        "        r = eval(ifade)\n"
        "        out.append([ad, r is True, '' if r is True else 'sonuc=%%r' %% (r,)])\n"
        "    except Exception as e:\n"
        "        out.append([ad, False, '%%s: %%s' %% (type(e).__name__, str(e)[:120])])\n"
        "print(json.dumps(out, ensure_ascii=False))\n" % modul)
    kod = "KONTROL = %r\n" % (kontroller,) + kod
    r = subprocess.run([sys.executable, "-B", "-c", kod], cwd=work, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        return [tuple(x) for x in json.loads(r.stdout.strip().splitlines()[-1])]
    except Exception:
        return [(ad, False, "kontrol kosulamadi: " + (r.stderr or r.stdout)[-300:]) for ad, _ in kontroller]


def geri_bildirim(modul: str, kontroller: list, sonuc: list) -> str:
    p = []
    for (ad, ifade), (_, gecti, detay) in zip(kontroller, sonuc):
        if not gecti:
            p.append("- %s: `%s` True olmali (%s)" % (ad, ifade, detay or "False"))
    return ("DENETCI KONTROLU (%s.py): asagidaki durumlar tutmuyor. Dosyayi read_file ile oku, "
            "yalnizca gerekli yeri duzelt, TAM dosyayi write_file ile yaz, her durum icin bir test "
            "ekle, run_tests kostur.\n" % modul) + "\n".join(p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tur", type=int, default=2)
    ap.add_argument("--gorev", default="", help="virgulle gorev adlari (bos = hepsi)")
    a = ap.parse_args()
    secili = [g for g in a.gorev.split(",") if g] or list(GOREVLER)

    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "kampanya", "version": "0"}})
    c.notify("notifications/initialized")
    rapor = {"baslangic": time.strftime("%Y-%m-%d %H:%M:%S"), "gorevler": {}}
    yol = os.path.join(ROOT, "tests", "code_kampanya.son.json")
    try:
        for ad in secili:
            g = GOREVLER[ad]
            work = os.path.join(HOME, "kampanya", ad)
            if os.path.isdir(work):
                shutil.rmtree(work)       # yalnizca kampanyanin kendi gecici klasoru
            os.makedirs(work)
            for dn, icerik in (g.get("on_dosyalar") or {}).items():
                with open(os.path.join(work, dn), "w", encoding="utf-8", newline="\n") as f:
                    f.write(icerik)
            print("\n== %s" % ad)
            kayit = {"turlar": []}
            oturum, gorev = "", g["gorev"]
            for tur in range(1, a.tur + 1):
                t0 = time.time()
                rep = c.tool("worker_run", {"gorev": gorev, "kabul_kriterleri": g["kriterler"],
                                            "ortam": "code", "calisma_dizini": work, "oturum": oturum},
                             timeout=1900)["structuredContent"]
                oturum = rep.get("oturum") or oturum
                son = gizli_kontrol(work, g["modul"], g["gizli"])
                gecen = sum(1 for _, ok, _ in son if ok)
                dosyalar = sorted(f for f in os.listdir(work) if f.endswith(".py"))
                fazla = [f for f in dosyalar if f not in ("%s.py" % g["modul"], "test_%s.py" % g["modul"])]
                kayit["turlar"].append({
                    "tur": tur, "derleme_durumu": rep.get("derleme_durumu"), "onarim": rep.get("tur_sayisi"),
                    "sure": rep.get("sure"), "araclar": rep.get("araclar"), "hatalar": rep.get("hatalar"),
                    "gizli_gecen": gecen, "gizli_toplam": len(son),
                    "gizli": [{"ad": x, "gecti": ok, "detay": d} for x, ok, d in son],
                    "fazla_dosya": fazla, "is_id": rep.get("is_id")})
                print("   tur %d: %s, isci %.0fs, onarim %s, gizli %d/%d%s" % (
                    tur, rep.get("derleme_durumu"), rep.get("sure", 0), rep.get("tur_sayisi"),
                    gecen, len(son), (", FAZLA DOSYA %s" % fazla) if fazla else ""))
                for x, ok, d in son:
                    if not ok:
                        print("      x %s  %s" % (x, d))
                if gecen == len(son) and rep.get("derleme_durumu") == "derlendi":
                    break
                gorev = geri_bildirim(g["modul"], g["gizli"], son)
            kayit["oturum"] = oturum
            rapor["gorevler"][ad] = kayit
            with open(yol, "w", encoding="utf-8", newline="\n") as f:
                json.dump(rapor, f, ensure_ascii=False, indent=1)
    finally:
        c.close()

    # Ozet tablo
    print("\n%-10s %-8s %-8s %-8s %s" % ("gorev", "tur1", "son", "tur", "sure"))
    t1 = ts = n = 0
    for ad, k in rapor["gorevler"].items():
        ilk, son = k["turlar"][0], k["turlar"][-1]
        t1 += ilk["gizli_gecen"]; ts += son["gizli_gecen"]; n += ilk["gizli_toplam"]
        print("%-10s %-8s %-8s %-8d %.0fs" % (ad, "%d/%d" % (ilk["gizli_gecen"], ilk["gizli_toplam"]),
                                             "%d/%d" % (son["gizli_gecen"], son["gizli_toplam"]),
                                             len(k["turlar"]), sum(t["sure"] or 0 for t in k["turlar"])))
    print("TOPLAM tur1 %d/%d, son %d/%d" % (t1, n, ts, n))
    rapor["ozet"] = {"tur1": t1, "son": ts, "toplam": n}
    rapor["bitis"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    print("->", yol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
