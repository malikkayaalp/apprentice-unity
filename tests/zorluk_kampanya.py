"""Zorluk kampanyasi: model neyi yazabiliyor, yazamadigini SOYLEYINCE duzeltiyor mu?

    python tests/zorluk_kampanya.py [--gorev rle,heap,dijkstra,ifade,dama] [--tur 2]

Her gorev icin dongu (usta-cirak deseninin ta kendisi):
  1. cirak yazar (dogrulama="derleme": yalniz yazar, test kosmaz)
  2. USTA (bu betik) isciye HIC verilmemis gizli kontrolleri kosar
  3. tutmayan varsa SOMUT teshis uretilir (hangi girdi -> ne bekleniyor -> ne geldi) ve ayni
     'oturum' ile ikinci tur istenir
  4. tekrar olculur

Boylece iki soru ayni anda cevaplanir: (a) model bu zorlukta kod yazabiliyor mu,
(b) hata SOMUT soylenince duzeltebiliyor mu. Kademeler: kolay -> orta -> zor -> oyun mantigi.
Sonuc: tests/zorluk_kampanya.son.json
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "zorluk")

# Gizli kontrol iskeleti: her kontrol "AD | BEKLENEN | GELEN" bicimimde rapor eder ki
# usta somut teshis yazabilsin (olculdu: genel geri bildirim cozmuyor, somut cozuyor).
ISKELET = '''
import sys
sys.path.insert(0, ".")
out = []


def esit(ad, ifade, beklenen):
    try:
        g = eval(ifade, ORTAM)
        out.append((ad, g == beklenen, ifade, repr(beklenen), repr(g)))
    except Exception as e:
        out.append((ad, False, ifade, repr(beklenen), "%s: %s" % (type(e).__name__, str(e)[:70])))


def dogru(ad, ifade):
    try:
        g = eval(ifade, ORTAM)
        out.append((ad, g is True, ifade, "True", repr(g)))
    except Exception as e:
        out.append((ad, False, ifade, "True", "%s: %s" % (type(e).__name__, str(e)[:70])))


def hata_verir(ad, ifade, tip="ValueError"):
    try:
        eval(ifade, ORTAM)
        out.append((ad, False, ifade, tip + " firlatmali", "hata firlatmadi"))
    except Exception as e:
        out.append((ad, type(e).__name__ == tip, ifade, tip, type(e).__name__))


ORTAM = {"__builtins__": __builtins__}
try:
    exec(IMPORT, ORTAM)
except Exception as e:
    print("IMPORT HATASI | %s: %s" % (type(e).__name__, str(e)[:200]))
    print("PUAN 0/1")
    sys.exit(0)
ORTAM.update({"esit": esit, "dogru": dogru, "hata_verir": hata_verir})
try:
    exec(EK, ORTAM, ORTAM)
except Exception as e:
    out.append(("kontrol betigi calisti", False, "-", "-", "%s: %s" % (type(e).__name__, str(e)[:120])))
for ad, ok, ifade, bek, gel in out:
    if ok:
        print("OK   | %s" % ad)
    else:
        print("HATA | %s | ifade: %s | beklenen: %s | gelen: %s" % (ad, ifade, bek, gel))
print("PUAN %d/%d" % (sum(1 for x in out if x[1]), len(out)))
'''

GOREVLER = {
"rle": {
    "zorluk": "1-kolay",
    "gorev": ("rle.py dosyasina iki fonksiyon yaz: sikistir(metin) -> ardisik tekrarlari "
              "'karakter+sayi' olarak kodlar (orn 'aaabbc' -> 'a3b2c1'); ac(kod) -> geri cozer. "
              "Bos metin bos doner. ac() bicimi bozuk girdide (orn 'a' ya da '3a') ValueError."),
    "kriter": ["sikistir('aaabbc') == 'a3b2c1' ve ac('a3b2c1') == 'aaabbc'",
               "sikistir('') == '' ve ac('') == ''",
               "Her metin icin ac(sikistir(m)) == m (gidis-donus)",
               "ac() bozuk girdide ValueError; yalnizca rle.py yazilir"],
    "import": "from rle import sikistir, ac",
    "kontroller": '''
esit("temel sikistirma", "sikistir('aaabbc')", "a3b2c1")
esit("temel acma", "ac('a3b2c1')", "aaabbc")
esit("bos sikistir", "sikistir('')", "")
esit("bos ac", "ac('')", "")
esit("tek karakter", "sikistir('a')", "a1")
esit("cok haneli sayi", "sikistir('a'*12)", "a12")
dogru("cok haneli gidis-donus", "ac(sikistir('a'*12)) == 'a'*12")
dogru("karisik gidis-donus", "ac(sikistir('aabbbaaaacc')) == 'aabbbaaaacc'")
hata_verir("bozuk girdi 'a'", "ac('a')")
'''},

"heap": {
    "zorluk": "2-orta",
    "gorev": ("minheap.py dosyasina MinHeap sinifi yaz (hazir heapq KULLANMA, kendi sift-up/"
              "sift-down'ini yaz): ekle(deger), cikar() -> en kucuk degeri cikarip doner, "
              "bak() -> en kucugu cikarmadan doner, __len__. Bos yigindan cikar()/bak() "
              "IndexError firlatir."),
    "kriter": ["ekle/cikar sirasi kucukten buyuge dogru olmali",
               "bak() en kucugu cikarmadan doner; len() dogru sayar",
               "Bos yiginda cikar() ve bak() IndexError",
               "heapq modulu KULLANILMAZ; yalnizca minheap.py yazilir"],
    "import": "from minheap import MinHeap",
    "kontroller": '''
dogru("siralama dogru", "(lambda h=[MinHeap()][0]: ([h.ekle(x) for x in [5,3,8,1,9,2]], [h.cikar() for _ in range(6)])[1])() == [1,2,3,5,8,9]")
dogru("bak cikarmaz", "(lambda h=[MinHeap()][0]: ([h.ekle(x) for x in [4,2]], h.bak(), len(h))[1:])() == (2, 2)")
esit("bos len", "len(MinHeap())", 0)
hata_verir("bos cikar", "MinHeap().cikar()", "IndexError")
hata_verir("bos bak", "MinHeap().bak()", "IndexError")
dogru("tekrarli degerler", "(lambda h=[MinHeap()][0]: ([h.ekle(x) for x in [3,1,3,1]], [h.cikar() for _ in range(4)])[1])() == [1,1,3,3]")
dogru("negatif degerler", "(lambda h=[MinHeap()][0]: ([h.ekle(x) for x in [0,-5,7,-2]], [h.cikar() for _ in range(4)])[1])() == [-5,-2,0,7]")
dogru("heapq kullanilmamis", "'heapq' not in open('minheap.py', encoding='utf-8').read()")
dogru("buyuk veri sirali", "(lambda h=[MinHeap()][0]: ([h.ekle(x) for x in [(i*37)%101 for i in range(101)]], [h.cikar() for _ in range(101)])[1])() == sorted([(i*37)%101 for i in range(101)])")
'''},

"dijkstra": {
    "zorluk": "3-orta-zor",
    "gorev": ("yol.py dosyasina en_kisa_yol(graf, bas, son) yaz: graf {'A': {'B': 5, 'C': 2}, ...} "
              "bicimi (yonlu, agirlikli). Doner: (toplam_maliyet, [dugum listesi]). Ulasilamiyorsa "
              "(float('inf'), []). Negatif agirlik ValueError. Baslangic dugum grafta yoksa KeyError."),
    "kriter": ["Bilinen grafta en kisa yolun maliyeti ve dugum sirasi dogru",
               "Ulasilamayan hedef -> (inf, [])",
               "Negatif agirlik -> ValueError; olmayan dugum -> KeyError",
               "bas == son ise (0, [bas]); yalnizca yol.py yazilir"],
    "import": ("from yol import en_kisa_yol" + chr(10) +
               "G = {'A': {'B': 1, 'C': 4}, 'B': {'C': 2, 'D': 5}, 'C': {'D': 1}, 'D': {}, 'E': {'A': 3}}"),
    "kontroller": '''
esit("A->D maliyet", "en_kisa_yol(G, 'A', 'D')[0]", 4)
esit("A->D yol", "list(en_kisa_yol(G, 'A', 'D')[1])", ["A", "B", "C", "D"])
esit("A->C maliyet (dolayli daha ucuz)", "en_kisa_yol(G, 'A', 'C')[0]", 3)
esit("kendine yol", "en_kisa_yol(G, 'A', 'A')", (0, ["A"]))
dogru("ulasilamaz -> inf", "en_kisa_yol(G, 'D', 'A')[0] == float('inf')")
esit("ulasilamaz -> bos liste", "list(en_kisa_yol(G, 'D', 'A')[1])", [])
esit("tek kenar", "en_kisa_yol(G, 'E', 'A')", (3, ["E", "A"]))
hata_verir("negatif agirlik", "en_kisa_yol({'A': {'B': -1}, 'B': {}}, 'A', 'B')")
hata_verir("olmayan dugum", "en_kisa_yol(G, 'Z', 'A')", "KeyError")
'''},

"ifade": {
    "zorluk": "4-zor",
    "gorev": ("hesap.py dosyasina hesapla(metin) yaz: dort islem + parantez iceren bir ifadeyi "
              "cozer, sonucu float doner. Operator onceligi (* / once, + - sonra) ve parantez "
              "dogru islenmeli, tekli eksi desteklenmeli (orn '-3 + 5'). eval/exec/compile "
              "KULLANMA - kendi ayrıştırıcını yaz. Gecersiz ifade ya da sifira bolme ValueError."),
    "kriter": ["Oncelik ve parantez dogru: '2+3*4' -> 14, '(2+3)*4' -> 20",
               "Tekli eksi: '-3+5' -> 2, '2*-3' -> -6",
               "Sifira bolme ve gecersiz ifade -> ValueError",
               "eval/exec/compile kullanilmaz; yalnizca hesap.py yazilir"],
    "import": "from hesap import hesapla",
    "kontroller": '''
esit("oncelik", "hesapla('2+3*4')", 14.0)
esit("parantez", "hesapla('(2+3)*4')", 20.0)
esit("ic ice parantez", "hesapla('((1+2)*(3+4))')", 21.0)
esit("bolme", "hesapla('7/2')", 3.5)
esit("tekli eksi bas", "hesapla('-3+5')", 2.0)
esit("tekli eksi carpim", "hesapla('2*-3')", -6.0)
esit("bosluklu", "hesapla('  10 - 2 * 3 ')", 4.0)
esit("soldan birlesim", "hesapla('10-2-3')", 5.0)
hata_verir("sifira bolme", "hesapla('1/0')")
hata_verir("gecersiz ifade", "hesapla('2+')")
hata_verir("kapanmamis parantez", "hesapla('(2+3')")
dogru("eval kullanilmamis", "all(k not in open('hesap.py', encoding='utf-8').read() for k in ['eval(', 'exec(', 'compile('])")
'''},

"dama": {
    "zorluk": "5-oyun mantigi",
    "gorev": ("dama.py dosyasina 8x8 Turk usulu OLMAYAN, klasik (Ingiliz/checkers) dama motoru yaz - "
              "ARAYUZ YOK, saf mantik:\\n"
              "- Dama sinifi: tahta 8x8 liste; baslangicta siyah ustte 3 sira (satir 0,1,2), beyaz "
              "altta 3 sira (satir 5,6,7), yalnizca KOYU karelerde ((satir+sutun) tek olan kareler). "
              "Bos kare None, tas ('b'|'s') ve dama ('B'|'S') harfle tutulur.\\n"
              "- gecerli_hamleler(oyuncu) -> [(bas, son), ...] koordinat ciftleri ((satir, sutun)).\\n"
              "- Yeme ZORUNLU: yeme hamlesi varsa gecerli_hamleler yalnizca yeme hamlelerini dondurur.\\n"
              "- oyna(bas, son) hamleyi uygular, yenen tasi kaldirir, son sirada terfi eder (b->B, s->S), "
              "sira degistirir; gecersiz hamlede ValueError.\\n"
              "- Normal tas ileri capraz gider (beyaz yukari/satir azalir, siyah asagi), dama iki yone.\\n"
              "- kazanan() -> 'beyaz'|'siyah'|None: rakibin tasi kalmadiysa ya da hamlesi yoksa."),
    "kriter": ["Baslangic dizilisi: 12 beyaz, 12 siyah, yalnizca koyu karelerde",
               "gecerli_hamleler beyazla 7 hamle verir (klasik baslangic)",
               "Yeme zorunlu: yeme varken normal hamle listelenmez",
               "Yeme sonrasi yenen tas tahtadan kalkar; son sirada terfi olur",
               "Gecersiz hamle ValueError; kazanan() rakip tas/hamle kalmayinca dogru sonucu verir",
               "Yalnizca dama.py yazilir, arayuz/pygame yok"],
    "import": "from dama import Dama",
    "kontroller": '''
def _yeni():
    return Dama()
dogru("12 beyaz tas", "sum(1 for r in _yeni().tahta for c in r if c in ('b','B')) == 12")
dogru("12 siyah tas", "sum(1 for r in _yeni().tahta for c in r if c in ('s','S')) == 12")
dogru("orta iki sira bos", "all(_yeni().tahta[i][j] is None for i in (3,4) for j in range(8))")
dogru("yalniz koyu karelerde", "all(_yeni().tahta[i][j] is None for i in range(8) for j in range(8) if (i+j)%2==0)")
dogru("baslangicta beyaz 7 hamle", "len(_yeni().gecerli_hamleler('beyaz')) == 7")
dogru("hamleler cift koordinat", "all(len(h)==2 and len(h[0])==2 and len(h[1])==2 for h in _yeni().gecerli_hamleler('beyaz'))")
dogru("gecersiz hamle ValueError", "(lambda d=_yeni(): _hata(d))()")
dogru("hamle sonrasi sira degisir", "(lambda d=_yeni(): (d.oyna(*d.gecerli_hamleler('beyaz')[0]), len(d.gecerli_hamleler('siyah')) > 0)[1])()")
dogru("yeme zorunlu", "_yeme_zorunlu()")
dogru("yeme tasi kaldirir", "_yeme_kaldirir()")
dogru("terfi olur", "_terfi()")
dogru("kazanan bos tahtada", "_kazanan()")
'''},
}

# dama icin yardimci kontrol fonksiyonlari (gizli kontrol icinde tanimlanir)
DAMA_YARDIMCI = '''
def _hata(d):
    try:
        d.oyna((0, 0), (7, 7)); return False
    except ValueError:
        return True
    except Exception:
        return False
def _kur(yerlesim, sira="beyaz"):
    d = Dama()
    for i in range(8):
        for j in range(8):
            d.tahta[i][j] = None
    for (i, j), t in yerlesim.items():
        d.tahta[i][j] = t
    for ad in ("sira", "siradaki", "aktif", "oyuncu", "sira_kimde"):
        if hasattr(d, ad):
            try:
                setattr(d, ad, sira)
            except Exception:
                pass
    return d
def _yeme_zorunlu():
    d = _kur({(5, 2): "b", (4, 3): "s", (5, 6): "b"})
    h = d.gecerli_hamleler("beyaz")
    return bool(h) and all(abs(a[0] - b[0]) == 2 for a, b in h)
def _yeme_kaldirir():
    d = _kur({(5, 2): "b", (4, 3): "s"})
    h = d.gecerli_hamleler("beyaz")
    if not h:
        return "yeme hamlesi uretilmedi"
    d.oyna(*h[0])
    return d.tahta[4][3] is None and d.tahta[3][4] in ("b", "B")
def _terfi():
    d = _kur({(1, 2): "b"})
    h = [x for x in d.gecerli_hamleler("beyaz") if x[1][0] == 0]
    if not h:
        return "terfi hamlesi uretilmedi"
    d.oyna(*h[0])
    return d.tahta[h[0][1][0]][h[0][1][1]] == "B"
def _kazanan():
    d = _kur({(5, 2): "b"})
    return d.kazanan() == "beyaz"
'''


def gizli_kod(g: dict) -> str:
    """IMPORT + EK (kontroller) degiskenlerini iskelete gomer; kontroller ORTAM icinde kosar."""
    yardimci = DAMA_YARDIMCI if "Dama" in g["import"] else ""
    return "IMPORT = %r\nEK = %r\n" % (g["import"], yardimci + g["kontroller"]) + ISKELET


def kontrol_et(klasor: str, g: dict) -> tuple:
    kod = gizli_kod(g)
    r = subprocess.run([sys.executable, "-B", "-c", kod], cwd=klasor, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"))
    cikti = (r.stdout or "") + (("\n" + r.stderr[-300:]) if r.returncode and r.stderr else "")
    puan = (0, 0)
    for satir in cikti.splitlines():
        if satir.startswith("PUAN"):
            a, b = satir.split()[1].split("/")
            puan = int(a), int(b)
    hatalar = [s for s in cikti.splitlines() if s.startswith("HATA") or s.startswith("IMPORT HATASI")]
    return puan, hatalar, cikti


def teshis(hatalar: list, g: dict) -> str:
    """Usta geri bildirimi: genel degil SOMUT (olculdu: genel geri bildirim cozmuyor)."""
    satirlar = []
    for h in hatalar[:8]:
        satirlar.append("- " + h.replace("HATA | ", "").replace(" | ", "  |  "))
    return ("DENETCI KONTROLU - asagidaki durumlar TUTMUYOR. Her satir: kontrol | calistirilan ifade | "
            "beklenen | gelen.\n" + "\n".join(satirlar) +
            "\n\nDosyayi read_file ile oku, SEBEBI bul, write_file ile TAM duzeltilmis dosyayi yaz. "
            "Calisan davranislari bozma. Yeni dosya ekleme.")


def kosu(c: Client, ad: str, g: dict, tur_siniri: int) -> dict:
    klasor = os.path.join(KOK, ad)
    if os.path.isdir(klasor):
        shutil.rmtree(klasor)
    os.makedirs(klasor)
    oturum, gorev = "", g["gorev"]
    turlar = []
    for tur in range(1, tur_siniri + 1):
        t0 = time.time()
        rep = c.tool("worker_run", {"gorev": gorev, "kabul_kriterleri": g["kriter"], "ortam": "code",
                                    "calisma_dizini": os.path.join("zorluk", ad), "oturum": oturum,
                                    "dogrulama": "derleme"}, timeout=1900)["structuredContent"]
        oturum = rep.get("oturum") or oturum
        sure = time.time() - t0
        (gecen, toplam), hatalar, cikti = kontrol_et(klasor, g)
        ku = rep.get("kullanim") or {}
        turlar.append({"tur": tur, "sure_s": round(sure, 1), "derleme_durumu": rep.get("derleme_durumu"),
                       "prompt_tok": ku.get("prompt_tokens"), "uretim_tok": ku.get("gen_tokens"),
                       "arac": len(rep.get("araclar", [])), "gizli": "%d/%d" % (gecen, toplam),
                       "hatalar": hatalar[:8],
                       "dosya": [d["yol"] for d in rep.get("yazilan_dosyalar", [])]})
        print("    tur %d: %-16s %4.0f s | prompt %6s | uretim %5s | gizli %s%s" % (
            tur, rep.get("derleme_durumu"), sure, ku.get("prompt_tokens"), ku.get("gen_tokens"),
            "%d/%d" % (gecen, toplam), ("  dosya " + str(turlar[-1]["dosya"])) if tur == 1 else ""), flush=True)
        for h in hatalar[:3]:
            print("        " + h[:150], flush=True)
        if toplam and gecen == toplam:
            break
        if tur < tur_siniri:
            gorev = teshis(hatalar, g)
    return {"zorluk": g["zorluk"], "turlar": turlar, "oturum": oturum}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gorev", default="rle,heap,dijkstra,ifade,dama")
    ap.add_argument("--tur", type=int, default=2)
    a = ap.parse_args()
    secili = [x.strip() for x in a.gorev.split(",") if x.strip() in GOREVLER]
    os.makedirs(KOK, exist_ok=True)

    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "zorluk", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "home"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)

    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), "gorevler": {}}
    yol = os.path.join(ROOT, "tests", "zorluk_kampanya.son.json")
    try:
        for ad in secili:
            print("\n== %s (%s)" % (ad, GOREVLER[ad]["zorluk"]), flush=True)
            rapor["gorevler"][ad] = kosu(c, ad, GOREVLER[ad], a.tur)
            with open(yol, "w", encoding="utf-8", newline="\n") as f:
                json.dump(rapor, f, ensure_ascii=False, indent=1)
    finally:
        c.close()

    print("\n%-10s %-14s %-8s %-8s %-6s %s" % ("gorev", "zorluk", "tur1", "son", "tur", "sure"))
    for ad, k in rapor["gorevler"].items():
        ilk, son = k["turlar"][0], k["turlar"][-1]
        print("%-10s %-14s %-8s %-8s %-6d %.0f s" % (ad, k["zorluk"], ilk["gizli"], son["gizli"],
                                                     len(k["turlar"]), sum(t["sure_s"] for t in k["turlar"])))
    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    print("->", yol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
