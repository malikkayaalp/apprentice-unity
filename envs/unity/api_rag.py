"""Unity API aramasi: Editor'un kendi XML belgelerinden, gomme YOK, baglam sismeden.

Neden: bu projenin en cok tekrarlanan hatasi modelin VAR OLMAYAN Unity API'si uydurmasi
(sistem isteminde "yalnizca gercekten var olan API'leri kullan" satiri bu yuzden var).
`api_ara` bunu tahmine degil Unity'nin kendi belgesine baglar.

Kaynak: <Editor>/Data/Managed/UnityEngine/UnityEngine.*.xml - her uye
`<member name="M:UnityEngine.Physics.Raycast(...)"><summary>...</summary>` bicimindedir.
Bu surumde 74 dosya / 22 401 uye olculdu.

Neden gomme (bge-m3) DEGIL, sozcuk aramasi:
  - 22k uyeyi gommek tek seferlik dakikalar surer ve indeks yuzlerce MB olur (1024 boyut x 22k).
  - API sorgusu isim-agirlikli ("raycast", "animator parameter", "camera shake"); BM25 bunu
    milisaniyede bulur, GPU istemez, indeks ~10 MB.
  - Turkce sorgu icin sistem istemi isciye "sorguyu Ingilizce yaz" der.
Olcum aksini soylerse gommeye gecilir; karar burada yaziyor ki sonradan tartisilmasin.

Donus KISA tutulur (baglam sismesin): uye adi + tek satir ozet, varsayilan 8 sonuc.
Indeks: APPRENTICE_HOME/unity_api/<surum-ozeti>.json (proje klasoru kirletilmez).
"""
from __future__ import annotations
import glob, hashlib, json, math, os, re, sys, xml.etree.ElementTree as ET

TIP_ADI = {"T": "tip", "M": "metot", "P": "ozellik", "F": "alan", "E": "olay"}
VARSAYILAN_K = 8
OZET_SINIRI = 180          # tek sonucta ozet karakter siniri
BOLUCU = re.compile(r"[^A-Za-z0-9]+")
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _home() -> str:
    return os.environ.get("APPRENTICE_HOME") or os.path.join(os.path.expanduser("~"), ".apprentice")


def editor_xml_klasoru() -> str:
    """Unity Editor'un XML belge klasoru: ayar/ortam degiskeni, yoksa yaygin yollardan ilki."""
    ev = os.environ.get("UNITY_API_XML")
    if ev and os.path.isdir(ev):
        return ev
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from core import config as CFG
        yol = CFG.get("unity.api_xml") or ""
        if yol and os.path.isdir(yol):
            return yol
    except Exception:
        pass
    for kalip in (r"C:\Program Files\Unity\Hub\Editor\*\Editor\Data\Managed\UnityEngine",
                  r"E:\UnityEditor\*\Editor\Data\Managed\UnityEngine",
                  "/Applications/Unity/Hub/Editor/*/Unity.app/Contents/Managed/UnityEngine"):
        bulunan = sorted(glob.glob(kalip))
        if bulunan:
            return bulunan[-1]
    return ""


def _parcala(metin: str) -> list:
    """Kelimelere ayir: nokta/parantez ayirir, CamelCase'i boler, kucuk harfe cevirir."""
    ham = BOLUCU.split(metin)
    out = []
    for p in ham:
        if not p:
            continue
        for parca in CAMEL.split(p):
            if len(parca) > 1:
                out.append(parca.lower())
    return out


def uyeleri_topla(xml_dir: str, editor_dahil: bool = False) -> list:
    """XML'lerden [{ad, tip, ozet}] uret. Varsayilan: yalniz UnityEngine.* (UnityEditor haric)."""
    kayitlar = []
    for p in sorted(glob.glob(os.path.join(xml_dir, "*.xml"))):
        ad = os.path.basename(p)
        if not editor_dahil and not ad.startswith("UnityEngine."):
            continue
        try:
            kok = ET.parse(p).getroot()
        except Exception:
            continue
        for m in kok.iter("member"):
            tam = m.get("name") or ""
            if len(tam) < 3 or tam[1] != ":":
                continue
            tip, isim = tam[0], tam[2:]
            if tip not in TIP_ADI:
                continue
            s = m.find("summary")
            ozet = " ".join("".join(s.itertext()).split()) if s is not None else ""
            if not ozet:
                continue
            kayitlar.append({"ad": isim, "tip": tip, "ozet": ozet[:400]})
    return kayitlar


class ApiIndeks:
    """BM25 tersyuz indeks. Kurulum ~10 sn, sorgu milisaniye; GPU yok."""

    def __init__(self, xml_dir: str = "", editor_dahil: bool = False):
        self.xml_dir = xml_dir or editor_xml_klasoru()
        self.editor_dahil = editor_dahil
        oz = hashlib.sha1(("%s|%s" % (self.xml_dir.lower(), editor_dahil)).encode()).hexdigest()[:12]
        self.yol = os.path.join(_home(), "unity_api", oz + ".json")
        self.veri = None

    def yukle(self, yenile: bool = False) -> dict:
        if self.veri is not None and not yenile:
            return self.veri
        if not yenile and os.path.isfile(self.yol):
            try:
                with open(self.yol, encoding="utf-8") as f:
                    self.veri = json.load(f)
                return self.veri
            except Exception:
                pass
        if not self.xml_dir or not os.path.isdir(self.xml_dir):
            raise RuntimeError("Unity API XML klasoru bulunamadi. UNITY_API_XML ortam degiskeni "
                               "ya da apprentice.config.json > unity.api_xml ile ver "
                               "(<Editor>/Data/Managed/UnityEngine).")
        kayitlar = uyeleri_topla(self.xml_dir, self.editor_dahil)
        # tersyuz indeks: kelime -> [(belge no, frekans)]
        ters: dict = {}
        boylar = []
        for i, k in enumerate(kayitlar):
            # ad iki kez sayilir: API aramasinda isim ozetten agirdir
            kelimeler = _parcala(k["ad"]) * 2 + _parcala(k["ozet"])
            boylar.append(len(kelimeler) or 1)
            sayim: dict = {}
            for w in kelimeler:
                sayim[w] = sayim.get(w, 0) + 1
            for w, f in sayim.items():
                ters.setdefault(w, []).append((i, f))
        self.veri = {"xml_dir": self.xml_dir, "kayitlar": kayitlar, "ters": ters, "boylar": boylar,
                     "ort_boy": sum(boylar) / max(1, len(boylar))}
        os.makedirs(os.path.dirname(self.yol), exist_ok=True)
        with open(self.yol, "w", encoding="utf-8") as f:
            json.dump(self.veri, f)
        return self.veri

    def ara(self, sorgu: str, k: int = VARSAYILAN_K, tip: str = "") -> list:
        v = self.yukle()
        kayitlar, ters, boylar, ort = v["kayitlar"], v["ters"], v["boylar"], v["ort_boy"]
        N = len(kayitlar)
        k1, b = 1.5, 0.75
        puan: dict = {}
        for w in set(_parcala(sorgu)):
            gonderi = ters.get(w)
            if not gonderi:
                continue
            idf = math.log(1 + (N - len(gonderi) + 0.5) / (len(gonderi) + 0.5))
            for i, f in gonderi:
                dl = boylar[i]
                puan[i] = puan.get(i, 0.0) + idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / ort))
        sirali = sorted(puan.items(), key=lambda x: -x[1])
        out = []
        for i, p in sirali:
            kay = kayitlar[i]
            if tip and kay["tip"] != tip[0].upper():
                continue
            out.append({"uye": kay["ad"], "tur": TIP_ADI[kay["tip"]],
                        "ozet": kay["ozet"][:OZET_SINIRI], "puan": round(p, 2)})
            if len(out) >= max(1, k):
                break
        return out


_INDEKS = None


def api_ara(sorgu: str, k: int = VARSAYILAN_K, tip: str = "") -> dict:
    global _INDEKS
    if _INDEKS is None:
        _INDEKS = ApiIndeks()
    try:
        sonuc = _INDEKS.ara(sorgu, k, tip)
    except RuntimeError as e:
        return {"error": str(e)}
    return {"sorgu": sorgu, "sonuc_sayisi": len(sonuc), "sonuclar": sonuc,
            "not": "Bunlar Unity'nin kendi belgesinden geldi; listede olmayan bir API'yi UYDURMA."}


if __name__ == "__main__":
    ix = ApiIndeks()
    print("xml:", ix.xml_dir)
    v = ix.yukle(yenile="--yenile" in sys.argv)
    print("uye:", len(v["kayitlar"]), "| kelime:", len(v["ters"]), "| indeks:", ix.yol,
          "%.1f MB" % (os.path.getsize(ix.yol) / 1e6))
    for s in sys.argv[1:]:
        if s.startswith("--"):
            continue
        print("\n>>", s)
        for r in ix.ara(s, 5):
            print("  %-58s %-8s %s" % (r["uye"][:58], r["tur"], r["ozet"][:80]))
