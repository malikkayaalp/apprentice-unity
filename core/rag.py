"""Kod tabani aramasi (RAG): calisma dizinini parcala, bge-m3 ile gom, kosinusle ara.

Neden: isci dosyalari tek tek okuyarak bulmaya calisiyor; gercek bir depoda bu baglami
patlatir (olculdu: 6 kucuk goreve 66k prompt tokeni, cogu dosya icerigi). `ara` araci
"neyi okuyacagini" once bulur; isci yalnizca ilgili parcayi okur.

Tasarim:
  - Indeks HOME/rag/<workdir-ozeti>.json altinda durur (kullanicinin projesi kirletilmez).
  - Dosya degisince (mtime+boyut) yalnizca o dosya yeniden gomulur.
  - Gomme Ollama /api/embed + bge-m3 (config: rag.embed_model). Ollama kapaliysa `ara`
    net bir hata dondurur; hicbir sey Ollama'yi kendiliginden BASLATMAZ.
  - Saf stdlib; kosinus benzerligi Python'da. ~2-3k parca icin yeterli (olcek buyuyunce
    numpy'a gecilebilir ama once gerek oldugu olculmeli).
  - embed islevi enjekte edilebilir: testler sahte gommeyle calisir, GPU gerektirmez.
"""
from __future__ import annotations
import hashlib, json, math, os, urllib.request

from core import config as CFG

VARSAYILAN_UZANTILAR = (".py", ".cs", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt",
                        ".html", ".css", ".yaml", ".yml", ".toml", ".ini", ".sh", ".bat",
                        ".sql", ".xml", ".shader", ".cginc")
ATLA_KLASOR = {".git", "__pycache__", "node_modules", ".venv", "venv", ".apprentice_test_home",
               "Library", "Temp", "obj", "bin", "dist", "build", "runtime", ".pytest_cache"}
PARCA_SATIR = 60          # parca boyu (satir)
BINDIRME = 10             # ardisik parcalar arasi ortak satir
DOSYA_SINIRI = 400_000    # tek dosya ust siniri (karakter); ustu indekslenmez
TOP_K = 6


def _home() -> str:
    return os.environ.get("APPRENTICE_HOME") or os.path.join(os.path.expanduser("~"), ".apprentice")


def embed_ollama(metinler: list) -> list:
    """Ollama /api/embed. Kapaliysa acik bir RuntimeError - kimse Ollama baslatmaz."""
    url = (CFG.get("ollama.url") or "http://localhost:11434").rstrip("/") + "/api/embed"
    model = CFG.env_or("APPRENTICE_EMBED_MODEL", "rag.embed_model", "bge-m3:latest")
    body = json.dumps({"model": model, "input": metinler}).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, body, {"Content-Type": "application/json"}), timeout=300) as r:
            d = json.load(r)
    except Exception as e:
        raise RuntimeError("gomme yapilamadi (%s, model %s): %s - Ollama acik mi, model cekilmis mi "
                           "(ollama pull %s)?" % (url, model, str(e)[:120], model)) from None
    e = d.get("embeddings")
    if not e:
        raise RuntimeError("gomme cevabi bos: %s" % str(d)[:200])
    return e


def _kosinus(a: list, b: list) -> float:
    pay = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-12
    nb = math.sqrt(sum(x * x for x in b)) or 1e-12
    return pay / (na * nb)


def _parcala(metin: str, yol: str) -> list:
    satirlar = metin.splitlines()
    if not satirlar:
        return []
    parcalar = []
    i = 0
    while i < len(satirlar):
        blok = satirlar[i:i + PARCA_SATIR]
        parcalar.append({"yol": yol, "bas": i + 1, "son": i + len(blok),
                         "metin": "\n".join(blok)})
        if i + PARCA_SATIR >= len(satirlar):
            break
        i += PARCA_SATIR - BINDIRME
    return parcalar


class Indeks:
    """Bir calisma dizininin gomme indeksi. Diske HOME/rag/<ozet>.json olarak yazilir."""

    def __init__(self, workdir: str, embed=None):
        self.workdir = os.path.realpath(workdir)
        self.embed = embed or embed_ollama
        oz = hashlib.sha1(self.workdir.lower().encode("utf-8")).hexdigest()[:16]
        self.yol = os.path.join(_home(), "rag", oz + ".json")
        self.veri = {"workdir": self.workdir, "dosyalar": {}, "parcalar": []}
        if os.path.isfile(self.yol):
            try:
                with open(self.yol, encoding="utf-8") as f:
                    self.veri = json.load(f)
            except Exception:
                pass

    # ---- tarama ------------------------------------------------------------
    def _dosyalari_bul(self) -> dict:
        out = {}
        for kok, klasorler, dosyalar in os.walk(self.workdir):
            klasorler[:] = [k for k in klasorler if k not in ATLA_KLASOR and not k.startswith(".")]
            for ad in dosyalar:
                if not ad.lower().endswith(VARSAYILAN_UZANTILAR):
                    continue
                tam = os.path.join(kok, ad)
                try:
                    st = os.stat(tam)
                except OSError:
                    continue
                if st.st_size > DOSYA_SINIRI:
                    continue
                rel = os.path.relpath(tam, self.workdir).replace("\\", "/")
                out[rel] = "%d:%d" % (int(st.st_mtime), st.st_size)
        return out

    def guncelle(self) -> dict:
        """Degisen/silinen dosyalari isle; yalnizca degisenler gomulur."""
        mevcut = self._dosyalari_bul()
        eski = self.veri.get("dosyalar", {})
        degisen = [r for r, imza in mevcut.items() if eski.get(r) != imza]
        silinen = [r for r in eski if r not in mevcut]
        if degisen or silinen:
            self.veri["parcalar"] = [p for p in self.veri.get("parcalar", [])
                                     if p["yol"] not in degisen and p["yol"] not in silinen]
            yeni_parcalar = []
            for rel in degisen:
                try:
                    with open(os.path.join(self.workdir, rel), encoding="utf-8", errors="replace") as f:
                        yeni_parcalar.extend(_parcala(f.read(), rel))
                except OSError:
                    continue
            # gomme toplu yapilir (tek istek cok parca)
            for i in range(0, len(yeni_parcalar), 32):
                grup = yeni_parcalar[i:i + 32]
                vekler = self.embed([p["metin"] for p in grup])
                for p, v in zip(grup, vekler):
                    p["vek"] = [round(x, 5) for x in v]
            self.veri["parcalar"].extend(yeni_parcalar)
            self.veri["dosyalar"] = mevcut
            os.makedirs(os.path.dirname(self.yol), exist_ok=True)
            with open(self.yol, "w", encoding="utf-8") as f:
                json.dump(self.veri, f)
        return {"dosya": len(mevcut), "parca": len(self.veri["parcalar"]),
                "gomulen": len(degisen), "silinen": len(silinen)}


def ara(workdir: str, sorgu: str, k: int = TOP_K, embed=None) -> dict:
    """Sorguya en yakin k parca. Ilk cagri indeksi kurar (buyuk depoda dakikalar surebilir)."""
    ix = Indeks(workdir, embed=embed)
    durum = ix.guncelle()
    if not ix.veri["parcalar"]:
        return {"durum": durum, "sonuclar": [], "not": "indekslenecek dosya yok"}
    sv = (embed or embed_ollama)([sorgu])[0]
    puanli = sorted(ix.veri["parcalar"], key=lambda p: -_kosinus(sv, p["vek"]))[:max(1, k)]
    return {"durum": durum, "sonuclar": [
        {"yol": p["yol"], "satir": "%d-%d" % (p["bas"], p["son"]),
         "benzerlik": round(_kosinus(sv, p["vek"]), 3),
         "metin": p["metin"][:1200]} for p in puanli]}
