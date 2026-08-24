"""Ortam tanisi: kurulum ONCESI ve SONRASI her sey yerinde mi, degilse KULLANICI NE YAPMALI.

    python -m core.tani            # okunur rapor
    python -m core.tani --json     # makine okur (panel/GUI)

Amac: depoyu GitHub'dan indiren, bizim gelistirme ortamimizla hicbir ilgisi olmayan bir
kullanicinin makinesinde kurulumun neden calismadigini TAHMIN ETTIRMEMEK. Her kontrol
uc sey doner: durum (ok/uyari/hata), ne oldugu, ve NE YAPMALI.

Kapsanan gercek senaryolar (hepsi sahada gorulen turden):
  - Ollama hic kurulu degil / kurulu ama PATH'te degil (Windows'ta sik) / eski surum
  - Ollama calismiyor / 11434 portunu BASKA bir program tutuyor
  - Model indirilmemis / yarim inmis / kullanici model klasorunu baska diske tasimis
    (OLLAMA_MODELS) ve orada yer yok
  - Makine 80B modeli kaldiramiyor (RAM/VRAM yetersiz) -> donaniminA GORE model onerisi
  - Disk dolu (model 20-47 GB), kurulum klasorune yazma izni yok
  - Internet/proxy yok (model cekilemez), Python surumu eski
  - Panel portu (8788) baskasinda
Bagimlilik yok (stdlib).
"""
from __future__ import annotations
import json, os, platform, shutil, socket, subprocess, sys, urllib.error, urllib.request

PENCERESIZ = 0x08000000 if os.name == "nt" else 0
GB = 1024 ** 3

# Donanima gore model onerisi. Boyutlar indirme boyutudur; calisirken RAM ihtiyaci ~ayni
# buyukluktedir (agirliklar bellege acilir), VRAM'e sigmayan katmanlar RAM'de kalir.
# OLCULDU (bu depoda): 80B/Q4_K_XL -> ~39 GB RAM + 14.6 GB VRAM ile 26 tok/s.
MODELLER = [
    {"ad": "hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL", "kisa": "Qwen3-Coder-Next 80B Q4",
     "gb": 47, "ram_gb": 48, "not": "sampiyon (bu depoda olculdu: 93/100)"},
    {"ad": "qwen2.5-coder:32b", "kisa": "Qwen2.5-Coder 32B", "gb": 20, "ram_gb": 24,
     "not": "guclu orta secenek"},
    {"ad": "qwen2.5-coder:14b", "kisa": "Qwen2.5-Coder 14B", "gb": 9, "ram_gb": 12,
     "not": "dizustu/16 GB makineler"},
    {"ad": "qwen2.5-coder:7b", "kisa": "Qwen2.5-Coder 7B", "gb": 5, "ram_gb": 8,
     "not": "en hafif; basit gorevler"},
]


def _kos(cmd, zaman=15):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=zaman, creationflags=PENCERESIZ)


def sonuc(ad, durum, mesaj, cozum="", veri=None) -> dict:
    return {"ad": ad, "durum": durum, "mesaj": mesaj, "cozum": cozum, "veri": veri or {}}


# --------------------------------------------------------------------- donanim
def ram_gb() -> float:
    """Toplam fiziksel RAM (GB). Bulunamazsa 0."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS(); m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / GB, 1)
        if sys.platform == "darwin":
            return round(int(_kos(["sysctl", "-n", "hw.memsize"]).stdout.strip()) / GB, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / GB, 1)
    except Exception:
        return 0.0


def vram_gb() -> float:
    """NVIDIA VRAM (GB); nvidia-smi yoksa 0 (CPU/AMD/Apple - is yine calisir, yavas)."""
    try:
        r = _kos(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], 10)
        return round(int(r.stdout.strip().splitlines()[0]) / 1024, 1)
    except Exception:
        return 0.0


def onerilen_model(ram: float, vram: float) -> dict:
    """Makinenin kaldirabilecegi EN IYI model. Buyuk modelin agirligi RAM'e acilir;
    VRAM'e sigmayan katmanlar RAM'de kalir - bu yuzden olcut RAM'dir, VRAM hiz katar."""
    for m in MODELLER:
        if ram >= m["ram_gb"]:
            return m
    return MODELLER[-1]


# --------------------------------------------------------------------- kontroller
def kontrol_python() -> dict:
    s = sys.version_info
    if s >= (3, 10):
        return sonuc("python", "ok", "Python %d.%d.%d" % s[:3], veri={"surum": "%d.%d" % s[:2]})
    return sonuc("python", "hata", "Python %d.%d cok eski (3.10+ gerekiyor)" % s[:2],
                 "python.org/downloads adresinden 3.10 veya ustunu kur; Windows'ta Setup "
                 "exe zaten gomulu Python indirebilir.")


def ollama_yolu() -> str:
    """PATH'te yoksa bilinen kurulum yerlerine bak: Windows'ta Ollama PATH'e gec eklenir,
    kullanici 'kurdum ama bulunamiyor' der."""
    y = shutil.which("ollama")
    if y:
        return y
    adaylar = []
    if os.name == "nt":
        yerel = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        adaylar = [os.path.join(yerel, "Programs", "Ollama", "ollama.exe"),
                   os.path.join(pf, "Ollama", "ollama.exe")]
    elif sys.platform == "darwin":
        adaylar = ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama",
                   "/Applications/Ollama.app/Contents/Resources/ollama"]
    else:
        adaylar = ["/usr/local/bin/ollama", "/usr/bin/ollama",
                   os.path.expanduser("~/.local/bin/ollama")]
    for a in adaylar:
        if a and os.path.isfile(a):
            return a
    return ""


def kontrol_ollama_kurulu() -> dict:
    y = ollama_yolu()
    if not y:
        return sonuc("ollama_kurulu", "hata", "Ollama bulunamadi",
                     "https://ollama.com/download adresinden indir ve kur, sonra bu kurulumu "
                     "tekrar calistir. (Ollama yerel modeli calistiran motordur; Apprentice "
                     "onsuz cirak calistiramaz.)")
    surum = ""
    try:
        surum = (_kos([y, "--version"], 20).stdout or "").strip().splitlines()[0][:40]
    except Exception:
        pass
    if not shutil.which("ollama"):
        return sonuc("ollama_kurulu", "uyari",
                     "Ollama kurulu ama PATH'te degil: %s" % y,
                     "Calisir; yine de terminalden 'ollama' yazabilmek istersen bilgisayari "
                     "yeniden baslat ya da klasoru PATH'e ekle.", {"yol": y, "surum": surum})
    return sonuc("ollama_kurulu", "ok", "Ollama kurulu: %s" % (surum or y),
                 veri={"yol": y, "surum": surum})


def _port_dolu(port: int, host="127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def kontrol_ollama_calisiyor(url="http://localhost:11434") -> dict:
    try:
        with urllib.request.urlopen(url + "/api/tags", timeout=4):
            return sonuc("ollama_calisiyor", "ok", "Ollama calisiyor (%s)" % url)
    except Exception:
        pass
    port = 11434
    try:
        port = int(url.rsplit(":", 1)[1].split("/")[0])
    except Exception:
        pass
    if _port_dolu(port):
        # Port dolu ama Ollama API'si cevap vermiyor -> baska bir program o portu tutuyor.
        return sonuc("ollama_calisiyor", "hata",
                     "%d portu dolu ama Ollama cevap vermiyor - baska bir program tutuyor" % port,
                     "O programi kapat, ya da Ollama'yi baska portta calistirip "
                     "apprentice.config.json icinde ollama.url degerini ona ayarla "
                     "(orn. OLLAMA_HOST=127.0.0.1:11500 ollama serve).")
    return sonuc("ollama_calisiyor", "uyari", "Ollama calismiyor",
                 "Kurulum baslatmayi deneyecek. Elle: terminalde 'ollama serve' "
                 "(tepside simge cikmaz, bu normaldir).")


def model_deposu() -> str:
    """Modellerin durdugu klasor. Kullanici OLLAMA_MODELS ile baska diske tasimis olabilir."""
    ozel = os.environ.get("OLLAMA_MODELS")
    if ozel:
        return ozel
    if os.name == "nt":
        return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), ".ollama", "models")
    if sys.platform == "darwin":
        return os.path.expanduser("~/.ollama/models")
    return "/usr/share/ollama/.ollama/models" if os.path.isdir("/usr/share/ollama") \
        else os.path.expanduser("~/.ollama/models")


def kontrol_disk(model_gb: float, kurulum_dizini: str = "") -> dict:
    """Model deposunda ve kurulum klasorunde yeterli yer var mi? (model 5-47 GB)"""
    depo = model_deposu()
    bak = depo
    while bak and not os.path.isdir(bak):                  # klasor henuz yoksa ust klasore bak
        ust = os.path.dirname(bak)
        if ust == bak:
            break
        bak = ust
    try:
        bos = shutil.disk_usage(bak or os.path.expanduser("~")).free / GB
    except Exception:
        return sonuc("disk", "uyari", "Disk alani okunamadi (%s)" % depo, veri={"depo": depo})
    gerek = model_gb * 1.15 + 2                            # indirme + acma payi
    ozel = " (OLLAMA_MODELS ile tasinmis)" if os.environ.get("OLLAMA_MODELS") else ""
    if bos < gerek:
        return sonuc("disk", "hata",
                     "Model deposunda yer yetersiz: %.0f GB bos, ~%.0f GB gerekli%s"
                     % (bos, gerek, ozel),
                     "Yer ac; ya da modelleri baska diske tasi: OLLAMA_MODELS ortam degiskenini "
                     "bos diskteki bir klasore ayarlayip Ollama'yi yeniden baslat. "
                     "Alternatif: daha kucuk bir model sec (kurulum onerecek).",
                     {"depo": depo, "bos_gb": round(bos, 1), "gerek_gb": round(gerek)})
    return sonuc("disk", "ok", "Model deposu: %s - %.0f GB bos%s" % (depo, bos, ozel),
                 veri={"depo": depo, "bos_gb": round(bos, 1)})


def kontrol_bellek(model: dict) -> dict:
    ram, vram = ram_gb(), vram_gb()
    onerilen = onerilen_model(ram, vram)
    v = {"ram_gb": ram, "vram_gb": vram, "onerilen": onerilen["ad"], "onerilen_kisa": onerilen["kisa"]}
    if not ram:
        return sonuc("bellek", "uyari", "RAM okunamadi", veri=v)
    if ram + 0.5 < model.get("ram_gb", 0):
        return sonuc("bellek", "uyari",
                     "%.0f GB RAM, secili model (%s) ~%d GB istiyor"
                     % (ram, model.get("kisa", model.get("ad", "?")), model.get("ram_gb", 0)),
                     "Bu makine icin onerilen: %s (~%d GB indirme). Kurulum bunu secebilir; "
                     "yine de buyuk modeli denemek istersen calisir ama cok yavas olur ya da "
                     "bellek hatasi verir." % (onerilen["kisa"], onerilen["gb"]), v)
    hiz = "GPU: %.0f GB VRAM" % vram if vram else "GPU yok/algilanmadi - CPU'da calisir (yavas)"
    return sonuc("bellek", "ok", "%.0f GB RAM, %s" % (ram, hiz), veri=v)


def kontrol_model(model_ad: str, url="http://localhost:11434") -> dict:
    try:
        with urllib.request.urlopen(url + "/api/tags", timeout=5) as r:
            veri = json.load(r)
    except Exception:
        return sonuc("model", "uyari", "Ollama calismadigi icin model kontrol edilemedi",
                     "Once Ollama'yi baslat.")
    adlar = [m.get("name", "") for m in veri.get("models", [])]
    if model_ad in adlar:
        boy = next((m.get("size", 0) for m in veri.get("models", []) if m.get("name") == model_ad), 0)
        return sonuc("model", "ok", "Model yuklu: %s (%.0f GB)" % (model_ad.split("/")[-1], boy / 1e9),
                     veri={"model": model_ad, "gb": round(boy / 1e9, 1)})
    benzer = [a for a in adlar if a.split(":")[0].split("/")[-1].lower()
              in model_ad.split(":")[0].split("/")[-1].lower()]
    return sonuc("model", "uyari", "Model yuklu degil: %s" % model_ad.split("/")[-1],
                 "Kurulum indirebilir (baglanti hizina gore 10-60 dk). Elle: "
                 "ollama pull %s%s" % (model_ad,
                                       "  |  makinede benzer model var: " + ", ".join(benzer[:3])
                                       if benzer else ""),
                 {"yuklu_modeller": adlar[:12]})


def kontrol_ag(url="http://localhost:11434") -> dict:
    """Model cekilebilir mi? Kurumsal proxy/guvenlik duvari cok yaygin bir tokezleme noktasi."""
    hedef = "https://ollama.com"
    try:
        istek = urllib.request.Request(hedef, method="HEAD")
        urllib.request.urlopen(istek, timeout=8)
        return sonuc("ag", "ok", "Internet erisimi var (model indirilebilir)")
    except urllib.error.HTTPError:
        return sonuc("ag", "ok", "Internet erisimi var")
    except Exception as e:
        vekil = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        return sonuc("ag", "uyari", "ollama.com'a ulasilamadi (%s)" % str(e)[:60],
                     "Zaten indirilmis modelle CALISIR; yeni model indiremezsin. Kurumsal ag "
                     "kullaniyorsan HTTPS_PROXY ortam degiskenini ayarla%s."
                     % (" (su an: %s)" % vekil if vekil else ""))


def kontrol_yazma(dizin: str) -> dict:
    if not dizin:
        return sonuc("yazma", "ok", "kurulum klasoru verilmedi (atlandi)")
    try:
        os.makedirs(dizin, exist_ok=True)
        p = os.path.join(dizin, ".apprentice_yazma_denemesi")
        with open(p, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(p)
        bos = shutil.disk_usage(dizin).free / GB
        if bos < 1:
            return sonuc("yazma", "uyari", "Kurulum klasorunde %.1f GB bos yer var" % bos,
                         "En az 1 GB birak (gomulu Python + gunlukler).")
        return sonuc("yazma", "ok", "Kurulum klasorune yazilabiliyor (%.0f GB bos)" % bos)
    except Exception as e:
        return sonuc("yazma", "hata", "Kurulum klasorune yazilamiyor: %s" % str(e)[:80],
                     "Baska bir klasor sec (orn. Belgeler altinda) ya da yonetici olarak "
                     "calistir. Program Files gibi korumali klasorleri secme.")


def kontrol_panel_portu(port: int = 8788) -> dict:
    if not _port_dolu(port):
        return sonuc("panel_portu", "ok", "Panel portu bos (%d)" % port)
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/hazir" % port, timeout=2) as r:
            if json.loads(r.read().decode("utf-8", "replace") or "{}").get("hazir"):
                return sonuc("panel_portu", "ok", "Panel zaten calisiyor (%d)" % port)
    except Exception:
        pass
    return sonuc("panel_portu", "uyari", "%d portunu baska bir program tutuyor" % port,
                 "Panel bir sonraki bos portu (8789...) kendiliginden kullanir; bir sey "
                 "yapmana gerek yok.")


# --------------------------------------------------------------------- toplu
def tani(model_ad: str = "", kurulum_dizini: str = "", url: str = "") -> dict:
    """Tum kontroller. Doner: {"durum": ok|uyari|hata, "kontroller": [...], "oneri": {...}}"""
    url = url or "http://localhost:11434"
    model_ad = model_ad or MODELLER[0]["ad"]
    model = next((m for m in MODELLER if m["ad"] == model_ad), {"ad": model_ad, "kisa": model_ad,
                                                                "gb": 20, "ram_gb": 16})
    k = [kontrol_python(),
         kontrol_yazma(kurulum_dizini),
         kontrol_bellek(model),
         kontrol_disk(model.get("gb", 20), kurulum_dizini),
         kontrol_ollama_kurulu()]
    if k[-1]["durum"] != "hata":
        k.append(kontrol_ollama_calisiyor(url))
        k.append(kontrol_model(model_ad, url))
    k.append(kontrol_ag(url))
    k.append(kontrol_panel_portu())
    durum = "hata" if any(x["durum"] == "hata" for x in k) else \
            ("uyari" if any(x["durum"] == "uyari" for x in k) else "ok")
    ram, vram = ram_gb(), vram_gb()
    return {"durum": durum, "kontroller": k,
            "makine": {"os": platform.platform()[:60], "ram_gb": ram, "vram_gb": vram},
            "oneri": onerilen_model(ram, vram)}


SIMGE = {"ok": "[ok]  ", "uyari": "[!]   ", "hata": "[X]   "}


def yazdir(r: dict, log=print):
    log("Makine: %s | RAM %.0f GB | VRAM %.0f GB"
        % (r["makine"]["os"], r["makine"]["ram_gb"], r["makine"]["vram_gb"]))
    for k in r["kontroller"]:
        log(SIMGE.get(k["durum"], "      ") + k["mesaj"])
        if k["cozum"] and k["durum"] != "ok":
            for satir in _sar(k["cozum"], 92):
                log("        -> " + satir)
    o = r["oneri"]
    log("      Bu makine icin onerilen model: %s (~%d GB) - %s" % (o["kisa"], o["gb"], o["not"]))


def _sar(metin: str, en: int) -> list:
    kelime, satir, out = metin.split(), "", []
    for k in kelime:
        if len(satir) + len(k) + 1 > en:
            out.append(satir); satir = k
        else:
            satir = (satir + " " + k).strip()
    if satir:
        out.append(satir)
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    r = tani(kurulum_dizini=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if "--json" in sys.argv:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        yazdir(r)
        print("\nSONUC:", {"ok": "her sey hazir", "uyari": "calisir, uyarilara bak",
                           "hata": "once yukaridaki [X] maddelerini coz"}[r["durum"]])
    sys.exit(0 if r["durum"] != "hata" else 1)
