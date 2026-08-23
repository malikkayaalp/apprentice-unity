"""RAG A/B olcumu: `ara` araci isciye ne kazandiriyor?

    python tests/rag_ab.py [--dosya 30]      # Ollama + bge-m3 gerekir (GPU)

Kurulum: 30 dosyalik sentetik depo iki kez kurulur (A ve B klasoru, birebir ayni).
Gorev ikisinde de ayni ve dosya adi VERILMEZ: "kupon indiriminin uygulandigi yeri bul ve
indirimi %50 ile sinirla". Hedef tek bir dosyada; gerisi gurultu.

  A: `ara` araci KAPALI  -> isci dosyalari korlemesine okumak zorunda
  B: `ara` araci ACIK    -> gorevde "once ara ile bul" denir

Olculen: prompt tokeni, uretim tokeni, tur/arac sayisi, sure + gizli kontrol (isciye verilmez):
hedef fonksiyon dogru davraniyor mu, baska dosya bozuldu mu.
Sonuc: tests/rag_ab.son.json  |  Iddia: B'de okunan token belirgin dusmeli. Cikmazsa RAG'in
`ara` araci varsayilan olarak KAPATILMALI - araci bulundurmanin da bedeli var (~150 token/tur).
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "rag_ab")

HEDEF = '''"""Sepet fiyatlandirma: kupon ve indirim kurallari."""


def kupon_indirimi_uygula(tutar, yuzde):
    """Kupon indirimini uygular ve yeni tutari doner."""
    if yuzde < 0:
        raise ValueError("yuzde negatif olamaz")
    return tutar - tutar * yuzde / 100.0
'''

GURULTU = '''"""%(ad)s modulu: %(konu)s."""


class %(sinif)s:
    def __init__(self, deger=0):
        self.deger = deger

    def artir(self, n=1):
        self.deger += n
        return self.deger

    def azalt(self, n=1):
        self.deger -= n
        return self.deger


def %(fn)s_hesapla(x, y=2):
    """%(konu)s icin basit hesap."""
    return x * y + %(sabit)d


def %(fn)s_dogrula(x):
    if x is None:
        raise ValueError("%(fn)s bos olamaz")
    return True
'''

KONULAR = ["kargo takibi", "stok sayimi", "fatura numaralandirma", "musteri puani", "iade sureci",
           "depo rafi", "tedarikci notu", "vergi dilimi", "kur cevrimi", "teslimat penceresi",
           "urun etiketi", "kampanya takvimi", "abonelik yenileme", "hediye paketi", "adres dogrulama",
           "telefon bicimi", "e-posta sablonu", "bildirim kuyrugu", "oturum anahtari", "gunluk kaydi",
           "yedekleme plani", "erisim rolu", "rapor ozeti", "sayfalama", "onbellek anahtari",
           "sira numarasi", "birim cevrimi", "agirlik siniri", "renk kodu"]


def depo_kur(hedef_klasor: str, n_dosya: int):
    if os.path.isdir(hedef_klasor):
        shutil.rmtree(hedef_klasor)
    os.makedirs(os.path.join(hedef_klasor, "modul"))
    with open(os.path.join(hedef_klasor, "modul", "fiyatlandirma.py"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(HEDEF)
    for i in range(n_dosya):
        konu = KONULAR[i % len(KONULAR)]
        ad = "modul_%02d" % i
        with open(os.path.join(hedef_klasor, "modul", ad + ".py"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(GURULTU % {"ad": ad, "konu": konu, "sinif": "Sinif%02d" % i,
                               "fn": "islem%02d" % i, "sabit": i})


GIZLI = r'''
import sys
sys.path.insert(0, ".")
from modul.fiyatlandirma import kupon_indirimi_uygula as k
out = []
def kontrol(ad, fn):
    try:
        r = fn(); out.append((ad, r is True, "" if r is True else "sonuc=%r" % (r,)))
    except Exception as e:
        out.append((ad, False, "%s: %s" % (type(e).__name__, str(e)[:80])))
kontrol("normal indirim (%20)", lambda: abs(k(100, 20) - 80.0) < 1e-9)
kontrol("sinirda (%50)", lambda: abs(k(100, 50) - 50.0) < 1e-9)
kontrol("ustu sinirlanir (%80 -> %50)", lambda: abs(k(100, 80) - 50.0) < 1e-9)
def _neg():
    try:
        k(100, -1); return False
    except ValueError:
        return True
    except Exception as e:
        return "baska istisna: " + type(e).__name__
kontrol("negatif ValueError", _neg)
kontrol("sifir indirim", lambda: abs(k(100, 0) - 100.0) < 1e-9)
import glob
bozuk = []
for p in glob.glob("modul/modul_*.py"):
    src = open(p, encoding="utf-8").read()
    if "def islem" not in src or "class Sinif" not in src:
        bozuk.append(p)
out.append(("gurultu dosyalari bozulmadi", not bozuk, ",".join(bozuk[:3])))
for ad, ok, d in out:
    print(("OK   " if ok else "HATA ") + ad + ("  " + d if d else ""))
print("PUAN %d/%d" % (sum(1 for _, ok, _ in out if ok), len(out)))
'''


def gizli_kontrol(klasor: str) -> tuple:
    r = subprocess.run([sys.executable, "-B", "-c", GIZLI], cwd=klasor, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"))
    cikti = r.stdout or r.stderr[-500:]
    puan = 0, 0
    for satir in cikti.splitlines():
        if satir.startswith("PUAN"):
            a, b = satir.split()[1].split("/")
            puan = int(a), int(b)
    return puan, cikti


GOREV_A = ("Bu depoda kupon indiriminin uygulandigi yeri BUL ve indirimi en fazla %50 ile "
           "sinirla: yuzde 50'den buyuk verilirse 50 kabul edilsin (hata firlatma). Negatif "
           "yuzdede mevcut ValueError davranisi korunsun. Dosya adini sana vermiyorum; kendin bul. "
           "Yalnizca ilgili dosyayi degistir, baska dosyalara dokunma, yeni dosya ekleme.")
GOREV_B = GOREV_A + " Once ara(...) araciyla ilgili yeri bul, sonra yalnizca o dosyayi read_file ile oku."

KRITERLER = ["Yuzde 50'nin ustundeki her deger 50 gibi uygulanir (100 tutar, %80 -> 50.0)",
             "Yuzde 50 ve altinda davranis degismez (100 tutar, %20 -> 80.0)",
             "Negatif yuzde ValueError firlatmaya devam eder",
             "Yalnizca ilgili dosya degisir; diger moduller ve imzalar ayni kalir"]


def kosu(c: Client, etiket: str, klasor_adi: str, gorev: str, ara_kapali: bool) -> dict:
    args = {"gorev": gorev, "kabul_kriterleri": KRITERLER, "ortam": "code",
            "calisma_dizini": os.path.join("rag_ab", klasor_adi), "dogrulama": "derleme"}
    if ara_kapali:
        args["araclar_kapali"] = ["ara"]
    t0 = time.time()
    rep = c.tool("worker_run", args, timeout=1900)["structuredContent"]
    sure = time.time() - t0
    (gecen, toplam), cikti = gizli_kontrol(os.path.join(KOK, klasor_adi))
    ku = rep.get("kullanim") or {}
    kayit = {"etiket": etiket, "sure_s": round(sure, 1), "derleme_durumu": rep.get("derleme_durumu"),
             "prompt_tok": ku.get("prompt_tokens"), "uretim_tok": ku.get("gen_tokens"),
             "model_cagrisi": ku.get("model_cagrisi"), "arac_sayisi": len(rep.get("araclar", [])),
             "araclar": rep.get("araclar", []), "gizli": "%d/%d" % (gecen, toplam),
             "dosya": [d["yol"] for d in rep.get("yazilan_dosyalar", [])], "is_id": rep.get("is_id")}
    print("  %s: %s | %.0f s | prompt %s | uretim %s | arac %d | gizli %s | dosya %s" % (
        etiket, kayit["derleme_durumu"], sure, kayit["prompt_tok"], kayit["uretim_tok"],
        kayit["arac_sayisi"], kayit["gizli"], kayit["dosya"]))
    return kayit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dosya", type=int, default=30, help="gurultu dosyasi sayisi")
    a = ap.parse_args()

    os.makedirs(KOK, exist_ok=True)
    for ad in ("A_arasiz", "B_arali"):
        depo_kur(os.path.join(KOK, ad), a.dosya)
    print("depo kuruldu: %d + 1 hedef dosya x2" % a.dosya)

    # RAG indeksini onceden kur ki olcum indeksleme suresini icermesin (ilk kurulum tek seferlik)
    try:
        from core import rag
        d = rag.Indeks(os.path.join(KOK, "B_arali")).guncelle()
        print("B icin indeks hazir:", d)
    except Exception as e:
        print("UYARI: indeks kurulamadi (%s). Ollama/bge-m3 acik mi?" % str(e)[:120])
        return 1

    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "rag-ab", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "home"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)

    try:
        A = kosu(c, "A (ara KAPALI)", "A_arasiz", GOREV_A, ara_kapali=True)
        B = kosu(c, "B (ara ACIK)", "B_arali", GOREV_B, ara_kapali=False)
    finally:
        c.close()

    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), "gurultu_dosyasi": a.dosya, "A": A, "B": B}
    if A.get("prompt_tok") and B.get("prompt_tok"):
        rapor["kazanc"] = {"prompt_tok_fark": A["prompt_tok"] - B["prompt_tok"],
                           "prompt_tok_oran": round(B["prompt_tok"] / A["prompt_tok"], 3),
                           "sure_oran": round(B["sure_s"] / A["sure_s"], 3) if A["sure_s"] else None}
        print("\nKAZANC: prompt %d -> %d (%.0f%%), sure %.0f -> %.0f s, gizli %s -> %s" % (
            A["prompt_tok"], B["prompt_tok"], 100 * rapor["kazanc"]["prompt_tok_oran"],
            A["sure_s"], B["sure_s"], A["gizli"], B["gizli"]))
    yol = os.path.join(ROOT, "tests", "rag_ab.son.json")
    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    print("->", yol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
