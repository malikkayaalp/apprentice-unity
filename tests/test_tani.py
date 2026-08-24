"""Ortam tanisi testleri - Ollama/GPU GEREKMEZ (hepsi taklit edilir).

    python tests/test_tani.py

Amac: depoyu indiren kullanicinin makinesinde ne ters giderse gitsin, tani DOGRU sebebi ve
NE YAPMALI'yi soylemeli. Burada o senaryolar tek tek taklit edilir:
  1. Ollama hic kurulu degil
  2. Ollama kurulu ama PATH'te degil (Windows'ta sik)
  3. Ollama calismiyor
  4. 11434 portunu BASKA program tutuyor (Ollama degil)
  5. Model indirilmemis
  6. Kullanici model klasorunu baska diske tasimis (OLLAMA_MODELS) ve orada yer yok
  7. Makine buyuk modeli kaldiramiyor -> donanima gore oneri
  8. Kurulum klasorune yazma izni yok
  9. Internet/proxy yok
 10. Python surumu eski
"""
from __future__ import annotations
import json, os, socket, sys, threading, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from core import tani as T  # noqa: E402


class Yama:
    """Basit monkeypatch: with Yama(T, "ram_gb", lambda: 8): ..."""

    def __init__(self, nesne, ad, yeni):
        self.n, self.a, self.y = nesne, ad, yeni

    def __enter__(self):
        self.eski = getattr(self.n, self.a)
        setattr(self.n, self.a, self.y)
        return self

    def __exit__(self, *a):
        setattr(self.n, self.a, self.eski)


def _dinleyici(port: int):
    """11434'u tutan 'baska bir program' taklidi: baglanti kabul eder, HTTP konusmaz."""
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port)); s.listen(5)
    dur = threading.Event()

    def kos():
        s.settimeout(0.3)
        while not dur.is_set():
            try:
                c, _ = s.accept(); c.close()
            except Exception:
                continue
    t = threading.Thread(target=kos, daemon=True); t.start()
    return s, dur


def main() -> int:
    hata = 0

    # 1) Ollama kurulu degil -> HATA + indirme baglantisi
    with Yama(T, "ollama_yolu", lambda: ""):
        r = T.kontrol_ollama_kurulu()
        assert r["durum"] == "hata" and "ollama.com/download" in r["cozum"], r
    print("1 ollama yok: ok")

    # 2) Kurulu ama PATH'te degil -> UYARI (calisir), yol gosterilir
    import shutil as _sh
    with Yama(T, "ollama_yolu", lambda: r"C:\Users\x\AppData\Local\Programs\Ollama\ollama.exe"), \
            Yama(_sh, "which", lambda *a, **k: None), Yama(T, "_kos", lambda *a, **k: type(
                "R", (), {"stdout": "ollama version is 0.1.0"})()):
        r = T.kontrol_ollama_kurulu()
        assert r["durum"] == "uyari" and "PATH" in r["mesaj"], r
    print("2 PATH'te degil: ok")

    # 3) Ollama calismiyor (port da bos) -> UYARI + 'ollama serve'
    r = T.kontrol_ollama_calisiyor("http://127.0.0.1:11999")
    assert r["durum"] == "uyari" and "serve" in r["cozum"], r
    print("3 calismiyor: ok")

    # 4) Portu BASKA program tutuyor -> HATA + baska port cozumu
    s, dur = _dinleyici(11998)
    try:
        r = T.kontrol_ollama_calisiyor("http://127.0.0.1:11998")
        assert r["durum"] == "hata" and "baska bir program" in r["mesaj"], r
        assert "ollama.url" in r["cozum"], r
    finally:
        dur.set(); s.close()
    print("4 port baskasinda: ok")

    # 5) Model indirilmemis -> UYARI + 'ollama pull'
    class SahteTags:
        def __init__(self, adlar): self.adlar = adlar
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"models": [{"name": a, "size": 5e9} for a in self.adlar]}).encode()
    with Yama(urllib.request, "urlopen", lambda *a, **k: SahteTags(["qwen2.5-coder:7b"])):
        r = T.kontrol_model("hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL")
        assert r["durum"] == "uyari" and "ollama pull" in r["cozum"], r
        r2 = T.kontrol_model("qwen2.5-coder:7b")
        assert r2["durum"] == "ok", r2
    print("5 model yok / var: ok")

    # 6) Model klasoru baska diskte ve YER YOK -> HATA + OLLAMA_MODELS cozumu
    import shutil
    sahte_depo = os.path.join(ROOT, ".apprentice_test_home", "sahte_model_deposu")
    os.makedirs(sahte_depo, exist_ok=True)
    os.environ["OLLAMA_MODELS"] = sahte_depo
    try:
        with Yama(shutil, "disk_usage", lambda p: type("D", (), {"free": 3 * T.GB})()):
            r = T.kontrol_disk(47)
            assert r["durum"] == "hata" and "OLLAMA_MODELS" in r["cozum"], r
            assert "tasinmis" in r["mesaj"], r          # kullanici tasidigini bilsin
        with Yama(shutil, "disk_usage", lambda p: type("D", (), {"free": 200 * T.GB})()):
            assert T.kontrol_disk(47)["durum"] == "ok"
    finally:
        os.environ.pop("OLLAMA_MODELS", None)
    print("6 model deposu tasinmis + dolu: ok")

    # 7) Zayif makine -> uygun model onerisi
    with Yama(T, "ram_gb", lambda: 16.0), Yama(T, "vram_gb", lambda: 0.0):
        r = T.kontrol_bellek(T.MODELLER[0])              # 80B secili
        assert r["durum"] == "uyari" and "onerilen" in r["cozum"].lower(), r
        assert r["veri"]["onerilen"] == "qwen2.5-coder:14b", r["veri"]
    with Yama(T, "ram_gb", lambda: 8.0), Yama(T, "vram_gb", lambda: 0.0):
        assert T.onerilen_model(8, 0)["ad"] == "qwen2.5-coder:7b"
    with Yama(T, "ram_gb", lambda: 64.0), Yama(T, "vram_gb", lambda: 24.0):
        assert T.onerilen_model(64, 24)["ad"].startswith("hf.co/unsloth/Qwen3")
    print("7 donanima gore model onerisi: ok")

    # 8) Yazma izni yok -> HATA + baska klasor onerisi
    class Patlak(Exception):
        pass
    gercek_makedirs = os.makedirs
    with Yama(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(PermissionError("erisim reddedildi"))):
        r = T.kontrol_yazma(os.path.join(ROOT, "olmayan"))
        assert r["durum"] == "hata" and "klasor" in r["cozum"].lower(), r
    os.makedirs = gercek_makedirs
    r = T.kontrol_yazma(os.path.join(ROOT, ".apprentice_test_home", "yazma_denemesi"))
    assert r["durum"] == "ok", r
    print("8 yazma izni: ok")

    # 9) Internet yok -> UYARI, ama "mevcut modelle calisir" der
    with Yama(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("ag yok"))):
        r = T.kontrol_ag()
        assert r["durum"] == "uyari" and "CALISIR" in r["cozum"], r
    print("9 internet yok: ok")

    # 10) Eski Python -> HATA
    class SahteSurum(tuple):
        pass
    with Yama(sys, "version_info", SahteSurum((3, 8, 0, "final", 0))):
        r = T.kontrol_python()
        assert r["durum"] == "hata" and "3.10" in r["cozum"], r
    print("10 eski python: ok")

    # toplu tani: sema butunlugu + 'hata' varsa toplam durum 'hata'
    r = T.tani(kurulum_dizini=os.path.join(ROOT, ".apprentice_test_home"))
    assert set(r) >= {"durum", "kontroller", "makine", "oneri"}, r
    for k in r["kontroller"]:
        assert set(k) == {"ad", "durum", "mesaj", "cozum", "veri"}, k
        assert k["durum"] in ("ok", "uyari", "hata"), k
        if k["durum"] != "ok":
            assert k["cozum"], "cozumsuz uyari/hata: %s" % k    # her sorun NE YAPMALI icermeli
    print("toplu tani semasi: ok (%d kontrol, durum=%s)" % (len(r["kontroller"]), r["durum"]))

    print("SONUC:", "GECTI" if not hata else "KALDI")
    return hata


if __name__ == "__main__":
    sys.exit(main())
