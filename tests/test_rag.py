"""RAG ve proje hafizasi testi - GPU/Ollama GEREKMEZ (sahte gomme ile).

    python tests/test_rag.py           # cevrimdisi: parcalama, indeks, arama, artimli guncelleme, hafiza
    python tests/test_rag.py --live    # + gercek bge-m3 ile tek sorgu (Ollama acik olmali)
"""
from __future__ import annotations
import os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "envs", "code"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["APPRENTICE_HOME"] = os.path.join(ROOT, ".apprentice_test_home")
from core import rag  # noqa: E402


def sahte_embed(metinler):
    """Deterministik sahte gomme: kaba kelime-cantasi. Benzer metin -> benzer vektor."""
    boyut = 64
    out = []
    for m in metinler:
        v = [0.0] * boyut
        for kelime in m.lower().split():
            v[hash(kelime) % boyut] += 1.0
        out.append(v)
    return out


def offline() -> bool:
    work = os.path.join(ROOT, ".apprentice_test_home", "rag_unit")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(os.path.join(work, "alt"))
    with open(os.path.join(work, "odeme.py"), "w", encoding="utf-8") as f:
        f.write("def kupon_indirimi_uygula(tutar, kod):\n    # kupon indirimi burada uygulanir\n    return tutar\n")
    with open(os.path.join(work, "alt", "kargo.py"), "w", encoding="utf-8") as f:
        f.write("def kargo_ucreti_hesapla(agirlik):\n    # kargo ucreti hesabi\n    return agirlik * 2\n")
    with open(os.path.join(work, "uzun.py"), "w", encoding="utf-8") as f:
        f.write("\n".join("satir_%d = %d" % (i, i) for i in range(200)))     # cok parcali dosya

    # eski indeks kalmasin
    ix0 = rag.Indeks(work, embed=sahte_embed)
    if os.path.isfile(ix0.yol):
        os.remove(ix0.yol)

    # 1) ilk arama indeksi kurar ve dogru dosyayi bulur
    r = rag.ara(work, "kupon indirimi nerede uygulanir", embed=sahte_embed)
    assert r["durum"]["dosya"] == 3 and r["durum"]["gomulen"] == 3, r["durum"]
    assert r["sonuclar"][0]["yol"] == "odeme.py", r["sonuclar"][0]
    assert "-" in r["sonuclar"][0]["satir"]
    print("ilk indeks + arama: ok  (%d parca)" % r["durum"]["parca"])
    assert r["durum"]["parca"] >= 5, "uzun.py birden cok parcaya bolunmeli"

    # 2) degisiklik yokken yeniden gomme olmaz
    r2 = rag.ara(work, "kargo ucreti", embed=sahte_embed)
    assert r2["durum"]["gomulen"] == 0, r2["durum"]
    assert r2["sonuclar"][0]["yol"] == "alt/kargo.py", r2["sonuclar"][0]
    print("artimli (degisiklik yok): ok")

    # 3) dosya degisince yalnizca o dosya gomulur
    time.sleep(1.1)   # mtime cozunurlugu
    with open(os.path.join(work, "odeme.py"), "w", encoding="utf-8") as f:
        f.write("def kupon_indirimi_uygula(tutar, kod):\n    return tutar * 0.9\n")
    r3 = rag.ara(work, "kupon", embed=sahte_embed)
    assert r3["durum"]["gomulen"] == 1, r3["durum"]
    print("artimli (tek dosya): ok")

    # 4) dosya silinince parcalari duser
    os.remove(os.path.join(work, "uzun.py"))
    r4 = rag.ara(work, "kupon", embed=sahte_embed)
    assert r4["durum"]["silinen"] == 1 and all(x["yol"] != "uzun.py" for x in r4["sonuclar"])
    print("silme: ok")

    # 5) BM25 yedegi: gomme hic yapilamiyorsa arac yine calisir ve dogru dosyayi bulur
    def bozuk_embed(metinler):
        raise RuntimeError("gomme yapilamadi (test)")
    work2 = os.path.join(ROOT, ".apprentice_test_home", "rag_bm25")
    if os.path.isdir(work2):
        shutil.rmtree(work2)
    os.makedirs(work2)
    with open(os.path.join(work2, "odeme.py"), "w", encoding="utf-8") as f:
        f.write("def kupon_indirimi_uygula(tutar, kod):\n    # kupon indirimi burada\n    return tutar\n")
    with open(os.path.join(work2, "kargo.py"), "w", encoding="utf-8") as f:
        f.write("def kargo_ucreti_hesapla(agirlik):\n    return agirlik * 2\n")
    ixb = rag.Indeks(work2, embed=bozuk_embed)
    if os.path.isfile(ixb.yol):
        os.remove(ixb.yol)
    rb = rag.ara(work2, "kupon indirimi", embed=bozuk_embed)
    assert rb["kip"].startswith("bm25"), rb.get("kip")
    assert rb["sonuclar"] and rb["sonuclar"][0]["yol"] == "odeme.py", rb["sonuclar"]
    assert rb["durum"]["gomme_hatasi"], rb["durum"]
    print("bm25 yedegi (gomme yok): ok")

    # 6) gomme geri gelince eksik parcalar kendiliginden gomulur, anlamsala donulur
    rc = rag.ara(work2, "kupon indirimi", embed=sahte_embed)
    assert rc["kip"] == "anlamsal", rc.get("kip")
    assert rc["durum"]["gomulen"] >= 2, rc["durum"]     # vek'siz parcalar yeniden islendi
    assert rc["sonuclar"][0]["yol"] == "odeme.py"
    print("bm25 -> anlamsal kendiliginden donus: ok")

    # 7) sorgu aninda gomme coken indeks de bm25'e duser (indeks gomulu olsa bile)
    rd = rag.ara(work2, "kargo ucreti", embed=bozuk_embed)
    assert rd["kip"].startswith("bm25") and rd["sonuclar"][0]["yol"] == "kargo.py", rd
    print("bm25 yedegi (sorgu aninda coken gomme): ok")

    # 8) kesit hedefe ortalanir: cevap parcanin ortasindaysa 1200'luk kesitte GORUNUR
    work3 = os.path.join(ROOT, ".apprentice_test_home", "rag_kesit")
    if os.path.isdir(work3):
        shutil.rmtree(work3)
    os.makedirs(work3)
    satirlar = ['<div class="urun uzun-gurultu-satiri-%02d">Urun %d - 100 TL</div>' % (i, i)
                for i in range(40)]
    satirlar.insert(30, "<p>Iade suresi 14 gun, urunler faturasiyla birlikte kabul edilir.</p>")
    with open(os.path.join(work3, "magaza.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(satirlar))
    ixk = rag.Indeks(work3, embed=sahte_embed)
    if os.path.isfile(ixk.yol):
        os.remove(ixk.yol)
    rk = rag.ara(work3, "iade suresi kac gun", embed=sahte_embed)
    m = rk["sonuclar"][0]["metin"]
    assert "Iade suresi 14 gun" in m, m[:200]         # eski davranista bas-kesiti bunu keserdi
    assert m.startswith("...") and len(m) <= 1215, (len(m), m[:60])
    print("kesit hedefe ortalanir: ok")

    # 8b) ekli sorgu da tutar: gunum~gundur, urunu~urunler (ortak onek eslesmesi)
    rk2 = rag.ara(work3, "urunu geri gondermek istersem kac gunum var", embed=sahte_embed)
    m2 = rk2["sonuclar"][0]["metin"]
    assert "Iade suresi 14 gun" in m2, m2[:200]
    print("kesit ekli (morfolojik) sorguyla: ok")

    # 9) sozcuksel eslesme yoksa kesit bastan (eski davranis, kirilmadi)
    r_bos = rag._kesit("hicbiryerde gecmeyenkelime", "\n".join(satirlar))
    assert r_bos == "\n".join(satirlar)[:1200]
    print("kesit gerileme (eslesme yok): ok")

    # 10) HAFIZA.md sistem istemine girer (code_runner uzerinden)
    import importlib
    CR = importlib.import_module("code_runner")
    with open(os.path.join(work, "HAFIZA.md"), "w", encoding="utf-8") as f:
        f.write("- Bu projede para birimi daima kurus (int) tutulur.")
    # code_runner main'ini calistirmadan ayni okuma mantigini dogrula
    hp = os.path.join(work, "HAFIZA.md")
    icerik = open(hp, encoding="utf-8").read()
    assert "kurus" in icerik
    src = open(os.path.join(ROOT, "envs", "code", "code_runner.py"), encoding="utf-8").read()
    assert 'HAFIZA.md' in src and "PROJE HAFIZASI" in src and '"ara"' in src
    assert 'STATE.md' in src and "GUNCEL DURUM" in src and "STATE_ARSIV" in src   # devir kancasi
    kural = open(os.path.join(ROOT, "kur.py"), encoding="utf-8").read()
    assert "AGENTS.md" in kural and "STATE.md" in kural                           # kural standardi
    print("hafiza + durum (STATE) + ara kancalari: ok")
    return True


def live() -> bool:
    work = os.path.join(ROOT, ".apprentice_test_home", "rag_unit")
    r = rag.ara(work, "kupon indirimi nerede uygulanir")     # gercek bge-m3
    print("live:", r["sonuclar"][0]["yol"], r["sonuclar"][0]["benzerlik"])
    return r["sonuclar"][0]["yol"] == "odeme.py"


def main() -> int:
    ok = offline()
    if "--live" in sys.argv:
        ok = live() and ok
    print("SONUC:", "GECTI" if ok else "KALDI")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
