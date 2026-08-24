"""Reranker ON-olcumu: bge-m3 tek basina hedefi kacinci sirada buluyor?

    python tests/rerank_olcum.py    # Ollama + bge-m3 gerekir (GPU, kucuk yuk)

Agir bagimlilik (torch + bge-reranker) kurmadan once soru su: `ara`nin siralamasi gercekten
sorun mu? Karistirilabilir korpus kurulur (hedef + 8 yakin-anlamli kupon/indirim fonksiyonu +
31 gurultu), 6 farkli sorgu denemesiyle hedefin sirasi olculur.

Karar kurali: top-1 isabet >= 5/6 ise reranker GEREKSIZ (kayda gecer, kurulmaz).
Altindaysa bge-reranker-v2-m3 kurulup ayni tezgahta farki olculur.
"""
from __future__ import annotations
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:      # pencereli exe/pythonw: sys.stdout None olabilir (kurulum oz-testi
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # bu satirda cokuyordu)
except Exception:
    pass
from core.rag import embed_ollama, _kosinus  # noqa: E402

HEDEF = ("def kupon_indirimi_uygula(tutar, yuzde):\n"
         '    """Sepet tutarina kupon yuzdesini uygular, yeni tutari doner."""\n'
         "    if yuzde < 0:\n        raise ValueError\n"
         "    return tutar - tutar * yuzde / 100.0")

KARISTIRICI = [
    "def kupon_kodu_dogrula(kod):\n    return len(kod) == 8 and kod.isalnum()",
    "def kupon_suresi_kontrol(kupon, bugun):\n    return kupon['bitis'] >= bugun",
    "def indirim_orani_hesapla(musteri):\n    return 5 if musteri['yeni'] else 10",
    "def kampanya_indirimi_listele(urun):\n    return [k for k in urun['kampanyalar'] if k['aktif']]",
    "def hediye_ceki_uygula(tutar, ceki):\n    return max(0, tutar - ceki['bakiye'])",
    "def sepet_toplami(kalemler):\n    return sum(k['fiyat'] * k['adet'] for k in kalemler)",
    "def fiyat_guncelle(urun, yeni):\n    urun['fiyat'] = yeni\n    return urun",
    "def kdv_ekle(tutar, oran=20):\n    return tutar * (1 + oran / 100.0)",
]

SORGULAR = [
    "kupon indirimi nerede uygulaniyor",
    "sepet tutarindan kupon yuzdesi nasil dusuluyor",
    "urunu indirimli fiyata ceviren fonksiyon",
    "yuzdelik indirim uygulanan yer",
    "kuponun tutari azalttigi kod",
    "indirim uygulama mantigi hangi fonksiyonda",
]


def main() -> int:
    gurultu = ["def islem_%02d(x):\n    return x * %d + 1" % (i, i) for i in range(31)]
    korpus = [HEDEF] + KARISTIRICI + gurultu
    t0 = time.time()
    vekler = []
    for i in range(0, len(korpus), 32):
        vekler += embed_ollama(korpus[i:i + 32])
    print("korpus gomuldu: %d parca, %.1f s" % (len(korpus), time.time() - t0), flush=True)

    sonuc = []
    for s in SORGULAR:
        sv = embed_ollama([s])[0]
        sirali = sorted(range(len(korpus)), key=lambda i: -_kosinus(sv, vekler[i]))
        sira = sirali.index(0) + 1                       # hedef korpus[0]
        rakip = sirali[0]
        sonuc.append({"sorgu": s, "hedef_sira": sira,
                      "birinci": korpus[rakip].split("(")[0].replace("def ", "")})
        print("  sira %2d | %-46s | 1.: %s" % (sira, s, sonuc[-1]["birinci"]), flush=True)

    top1 = sum(1 for r in sonuc if r["hedef_sira"] == 1)
    top3 = sum(1 for r in sonuc if r["hedef_sira"] <= 3)
    karar = ("reranker GEREKSIZ: bge-m3 tek basina yeterli"
             if top1 >= 5 else "reranker DENENMELI: top-1 isabet dusuk")
    print("top-1: %d/6, top-3: %d/6 -> %s" % (top1, top3, karar))
    with open(os.path.join(ROOT, "tests", "rerank_olcum.son.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump({"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), "sonuclar": sonuc,
                   "top1": "%d/6" % top1, "top3": "%d/6" % top3, "karar": karar},
                  f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
