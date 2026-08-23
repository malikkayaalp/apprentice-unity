"""Apprentice kurulum: tek betik, adim adim, bagimliliksiz.

    python kur.py                 # kontrol et, eksikleri tamamla (model indirme dahil), IDE'leri ayarla
    python kur.py --kontrol       # yalnizca durumu goster, hicbir sey degistirme
    python kur.py --ide cursor,vscode   # yalnizca bu IDE'leri ayarla (cursor, vscode, windsurf, claude-desktop)
    python kur.py --olc           # + ilk calistirma num_batch olcumu (2-3 dk, GPU'ya ozel)
    python kur.py --kural <proje_klasoru>   # denetci kuralini yaz: AGENTS.md (ortak) + Cursor .mdc + Copilot yonlendirme

Windows'ta ayni betik Apprentice-Setup.exe olarak paketlenir (PyInstaller); Python yoksa resmi
gomulu Python'u (embeddable, ~11 MB) depoya indirir ve sunucu onunla calisir.

Adimlar:
  1  Python 3.10+ (yoksa gomulu Python indirilir - yalniz Windows)
  2  Ollama kurulu mu, calisiyor mu (degilse baslatmayi dener)
  3  Model var mi, yoksa indir (ilerleme yuzdesiyle)
  4  IDE'ler: kurulu olan her IDE'nin MCP ayarina "apprentice" girdisi (diger girdilere dokunmaz)
     Claude Code: depodaki .mcp.json zaten yeterli
  5  Ruff (istege bagli): yazim-ani F-sinifi kanit icin; kurulamazsa is surer
  6  Oz-test: sunucuyla el sikisma + fake ortamda bir tur (model gerekmez)
  7  (istege bagli) num_batch olcumu -> apprentice.config.json
"""
from __future__ import annotations
import argparse, json, os, platform, shutil, subprocess, sys, time, urllib.request, urllib.error

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OK, HATA, UYARI, BILGI = "[ok]  ", "[X]   ", "[!]   ", "      "
DEGISTIR = True
ROOT = ""                 # kurulu Apprentice klasoru; set_root ile verilir
GOMULU_DIR = ""
log = print               # GUI bunu kendi kaydedicisiyle degistirir
ilerleme = None           # GUI: ilerleme(yuzde 0-100 | None, metin)


def set_root(path: str):
    """Kurulum klasorunu sec; core/ buradan import edilir (exe icinde core yoktur)."""
    global ROOT, GOMULU_DIR
    ROOT = os.path.abspath(path)
    GOMULU_DIR = os.path.join(ROOT, "runtime", "python")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    for m in [k for k in sys.modules if k == "core" or k.startswith("core.")]:
        del sys.modules[m]


def _cfg():
    from core import config
    return config


def depo_mu(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "server", "apprentice_server.py"))


def adim(n, baslik):
    log("\n%d) %s" % (n, baslik))


def ollama_url() -> str:
    try:
        return (_cfg().get("ollama.url") or "http://localhost:11434").rstrip("/")
    except Exception:
        return "http://localhost:11434"


def ollama_tags():
    with urllib.request.urlopen(ollama_url() + "/api/tags", timeout=3) as r:
        return [m.get("name") for m in json.load(r).get("models", [])]


# ------------------------------------------------------------------ 1 python
DONMUS = getattr(sys, "frozen", False)          # PyInstaller exe icinden mi calisiyoruz
GOMULU_SURUM = "3.12.8"


def sistem_python() -> str:
    """Sunucuyu calistiracak Python: gomulu varsa o, yoksa PATH'teki 3.10+."""
    g = os.path.join(GOMULU_DIR, "python.exe")
    if os.path.isfile(g):
        return g
    if not DONMUS and sys.version_info >= (3, 10):
        return sys.executable
    for ad in ("python3", "python", "py"):
        exe = shutil.which(ad)
        if not exe:
            continue
        try:
            out = subprocess.run([exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            if tuple(int(x) for x in out.split(".")) >= (3, 10):
                return exe
        except Exception:
            continue
    return ""


def gomulu_python_indir() -> bool:
    """Resmi Windows embeddable Python'u runtime/python altina acar. pip yok, gerekmiyor (stdlib)."""
    if os.name != "nt":
        return False
    import zipfile, io
    url = "https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip" % (GOMULU_SURUM, GOMULU_SURUM)
    log(BILGI + "Gomulu Python indiriliyor: %s" % url)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            toplam = int(r.headers.get("Content-Length") or 0)
            parcalar, alinan = [], 0
            while True:
                b = r.read(256 * 1024)
                if not b:
                    break
                parcalar.append(b); alinan += len(b)
                if ilerleme and toplam:
                    ilerleme(100.0 * alinan / toplam, "Gomulu Python %.1f / %.1f MB" % (alinan / 1e6, toplam / 1e6))
            veri = b"".join(parcalar)
        os.makedirs(GOMULU_DIR, exist_ok=True)
        zipfile.ZipFile(io.BytesIO(veri)).extractall(GOMULU_DIR)
        # ._pth dosyasi: depo kokunu de yola ekle ki 'core', 'mcpbridge' bulunsun
        for ad in os.listdir(GOMULU_DIR):
            if ad.endswith("._pth"):
                with open(os.path.join(GOMULU_DIR, ad), "a", encoding="utf-8") as f:
                    f.write("\n..\\..\n")
        ok = subprocess.run([os.path.join(GOMULU_DIR, "python.exe"), "-c", "import json, urllib.request; print('ok')"],
                            capture_output=True, text=True, timeout=30).stdout.strip() == "ok"
        log((OK if ok else HATA) + "Gomulu Python %s: %s" % (GOMULU_SURUM, GOMULU_DIR))
        return ok
    except Exception as e:
        log(HATA + "gomulu Python indirilemedi: %s" % str(e)[:200])
        return False


def kontrol_python() -> bool:
    exe = sistem_python()
    if exe:
        try:
            v = subprocess.run([exe, "-c", "import sys;print(sys.version.split()[0])"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            v = "?"
        log(OK + "Python %s  (%s)" % (v, exe))
        return True
    log(UYARI + "Python 3.10+ bulunamadi.")
    if not DEGISTIR:
        return False
    if gomulu_python_indir():
        return True
    log(HATA + "Python kur: https://www.python.org/downloads/  (kurunca tekrar calistir)")
    return False


# ------------------------------------------------------------------ 2 ollama
def kontrol_ollama() -> bool:
    exe = shutil.which("ollama")
    if not exe:
        log(HATA + "Ollama kurulu degil. Indir: https://ollama.com/download  (kurunca bu betigi tekrar calistir)")
        return False
    log(OK + "Ollama kurulu: %s" % exe)
    try:
        ollama_tags()
        log(OK + "Ollama calisiyor (%s)" % ollama_url())
        return True
    except Exception:
        pass
    if not DEGISTIR:
        log(HATA + "Ollama calismiyor (%s)." % ollama_url())
        return False
    # Ollama sureci VARSA ikinci bir 'serve' baslatma: ikinci sunucu portu alamaz, ama bazi
    # kurulumlarda iki sunucu iki AYRI model ornegi yukler -> 80B modelde ~78 GB RAM (olculdu).
    try:
        cikti = subprocess.run(["tasklist" if os.name == "nt" else "ps", "-ax"] if os.name != "nt"
                               else ["tasklist", "/FI", "IMAGENAME eq ollama.exe"],
                               capture_output=True, text=True, timeout=10).stdout.lower()
        if "ollama" in cikti and "no tasks" not in cikti:
            log(UYARI + "Ollama sureci var ama cevap vermiyor. Ikinci sunucu BASLATILMADI "
                        "(cift model yuklemesini onlemek icin). Ollama uygulamasini yeniden baslat.")
            return False
    except Exception:
        pass
    log(BILGI + "Ollama calismiyor, baslatiliyor...")
    try:
        kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL,
              "env": dict(os.environ, OLLAMA_MAX_LOADED_MODELS=os.environ.get("OLLAMA_MAX_LOADED_MODELS", "1"))}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | NEW_PROCESS_GROUP
        subprocess.Popen([exe, "serve"], **kw)
    except Exception as e:
        log(HATA + "baslatilamadi: %s" % e)
        return False
    for _ in range(20):
        time.sleep(1)
        try:
            ollama_tags()
            log(OK + "Ollama basladi")
            return True
        except Exception:
            continue
    log(HATA + "Ollama 20 sn icinde cevap vermedi. Elle baslat: ollama serve")
    return False


# ------------------------------------------------------------------ 3 model
def kontrol_model() -> bool:
    model = _cfg().env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model")
    try:
        adlar = ollama_tags()
    except Exception:
        log(HATA + "Ollama'ya ulasilamadi, model kontrol edilemedi")
        return False
    if model in adlar:
        log(OK + "Model yuklu: %s" % model)
        return True
    log(UYARI + "Model yok: %s" % model)
    if not DEGISTIR:
        return False
    log(BILGI + "Indiriliyor (~20 GB, baglantiya gore 10-60 dk)...")
    req = urllib.request.Request(ollama_url() + "/api/pull",
                                 json.dumps({"name": model, "stream": True}).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            son = ""
            for line in r:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("error"):
                    log(HATA + d["error"])
                    return False
                durum = d.get("status", "")
                t, c = d.get("total"), d.get("completed")
                if t and c is not None:
                    birim, bol = ("GB", 1e9) if t >= 1e9 else ("MB", 1e6)
                    msg = "%s  %5.1f%%  (%.1f / %.1f %s)" % (durum, 100.0 * c / t, c / bol, t / bol, birim)
                else:
                    msg = durum
                if msg != son:
                    if ilerleme:
                        ilerleme((100.0 * c / t) if (t and c is not None) else None, msg)
                    elif log is print:
                        sys.stdout.write("\r" + BILGI + msg.ljust(70))
                        sys.stdout.flush()
                    son = msg
        if log is print:
            log()
    except Exception as e:
        log(HATA + "indirme hatasi: %s" % str(e)[:200])
        return False
    try:
        if model in ollama_tags():
            log(OK + "Model indirildi: %s" % model)
            return True
    except Exception:
        pass
    log(HATA + "indirme bitti ama model listede yok; 'ollama pull %s' ile elle dene" % model)
    return False


# ------------------------------------------------------------------ 4 IDE'ler
def _ev() -> str:
    return os.path.expanduser("~")


def _appdata() -> str:
    return os.environ.get("APPDATA") or os.path.join(_ev(), "AppData", "Roaming")


def ide_listesi() -> dict:
    """ad -> (ayar dosyasi, ust anahtar, 'kurulu mu' klasoru). Her IDE'nin MCP dosya semasi farkli:
    Cursor/Windsurf/Claude Desktop 'mcpServers', VS Code 'servers'."""
    if sys.platform == "darwin":
        vscode = os.path.join(_ev(), "Library", "Application Support", "Code", "User", "mcp.json")
        claude_d = os.path.join(_ev(), "Library", "Application Support", "Claude", "claude_desktop_config.json")
    elif os.name == "nt":
        vscode = os.path.join(_appdata(), "Code", "User", "mcp.json")
        claude_d = os.path.join(_appdata(), "Claude", "claude_desktop_config.json")
    else:
        vscode = os.path.join(_ev(), ".config", "Code", "User", "mcp.json")
        claude_d = os.path.join(_ev(), ".config", "Claude", "claude_desktop_config.json")
    return {
        "cursor":         (os.path.join(_ev(), ".cursor", "mcp.json"), "mcpServers", os.path.join(_ev(), ".cursor")),
        "vscode":         (vscode, "servers", os.path.dirname(vscode)),
        "windsurf":       (os.path.join(_ev(), ".codeium", "windsurf", "mcp_config.json"), "mcpServers",
                           os.path.join(_ev(), ".codeium", "windsurf")),
        "claude-desktop": (claude_d, "mcpServers", os.path.dirname(claude_d)),
    }


def sunucu_girdisi() -> dict:
    py = sistem_python() or "python"
    sunucu = os.path.join(ROOT, "server", "apprentice_server.py").replace("\\", "/")
    return {"command": py.replace("\\", "/"), "args": [sunucu], "env": {"PYTHONIOENCODING": "utf-8"}}


def ide_ayarla(ad: str, yol: str, anahtar: str, kurulu_dir: str) -> bool:
    istenen = sunucu_girdisi()
    if ad == "vscode":
        istenen = {"type": "stdio", **istenen}
    cfg = {}
    if os.path.exists(yol):
        try:
            with open(yol, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            log(UYARI + "%s ayar dosyasi okunamadi (%s): %s" % (ad, yol, e))
            return False
    mevcut = (cfg.get(anahtar) or {}).get("apprentice")
    if mevcut and mevcut.get("args") == istenen["args"] and mevcut.get("command") == istenen["command"]:
        log(OK + "%s: apprentice kayitli (%s)" % (ad, yol))
        return True
    if not DEGISTIR:
        log(UYARI + "%s: apprentice kayitli degil ya da yolu farkli (%s)" % (ad, yol))
        return False
    cfg.setdefault(anahtar, {})["apprentice"] = istenen
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    log(OK + "%s: yazildi -> %s  (IDE aciksa MCP listesini yenile)" % (ad, yol))
    return True


def mcp_json_guncelle():
    """Claude Code icin depodaki .mcp.json: 'python' PATH'te yoksa (gomulu Python) gercek yolu yaz."""
    p = os.path.join(ROOT, ".mcp.json")
    py = sistem_python()
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        g = cfg.setdefault("mcpServers", {}).setdefault("apprentice", {})
        if py and (shutil.which("python") is None or py.startswith(GOMULU_DIR)):
            if DEGISTIR and g.get("command") != py.replace("\\", "/"):
                g["command"] = py.replace("\\", "/")
                with open(p, "w", encoding="utf-8", newline=chr(10)) as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                log(OK + "Claude Code: .mcp.json komutu gomulu Python'a cevrildi")
                return
        log(OK + "Claude Code: depodaki .mcp.json ile otomatik (bu klasorde 'claude' ac)")
    except Exception as e:
        log(UYARI + ".mcp.json guncellenemedi: %s" % e)


def kontrol_ideler(secim: str = "") -> bool:
    ideler = ide_listesi()
    istenenler = [x.strip() for x in secim.split(",") if x.strip()] if secim else []
    bulundu, hepsi_ok = 0, True
    for ad, (yol, anahtar, kurulu_dir) in ideler.items():
        kurulu = os.path.isdir(kurulu_dir)
        if istenenler and ad not in istenenler:
            continue
        if not kurulu and not istenenler:
            continue                      # kurulu olmayan IDE'ye dokunma
        if ad == "claude-desktop" and not istenenler:
            continue                      # IDE degil; yalnizca --ide ile
        bulundu += 1
        hepsi_ok = ide_ayarla(ad, yol, anahtar, kurulu_dir) and hepsi_ok
    if not bulundu:
        log(UYARI + "Kurulu IDE bulunamadi (cursor / vscode / windsurf / claude-desktop). "
                      "--ide <ad> ile zorla ya da Claude Code kullan.")
    return hepsi_ok


# ------------------------------------------------------------------ 5 oz-test
def oz_test() -> bool:
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    try:
        from test_server import Client
    except Exception as e:
        log(HATA + "test istemcisi yuklenemedi: %s" % e)
        return False
    home = os.path.join(ROOT, ".apprentice_test_home")
    import test_server as _ts
    _ts.sys.executable = sistem_python() or sys.executable   # exe icinden: sunucuyu gercek Python'la ac
    c = Client({"APPRENTICE_HOME": home})
    try:
        c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "kur", "version": "0"}})
        c.notify("notifications/initialized")
        araclar = [t["name"] for t in c.call("tools/list")["tools"]]
        rep = c.tool("worker_run", {"gorev": "kurulum duman testi", "ortam": "fake",
                                    "kabul_kriterleri": ["x"]}, timeout=60)["structuredContent"]
        ok = rep.get("derleme_durumu") == "derlendi"
        log((OK if ok else HATA) + "Sunucu el sikisti, araclar: %s, fake tur: %s" % (araclar, rep.get("derleme_durumu")))
        return ok
    except Exception as e:
        log(HATA + "oz-test basarisiz: %s" % str(e)[:300])
        return False
    finally:
        c.close()


# ------------------------------------------------------------------ kural
KURAL = """---
description: Apprentice - yerel isci modeli denetle (worker_run)
alwaysApply: true
---
Bu projede kod yazma isi apprentice.worker_run aracina verilir; sen DENETCISIN (usta).
Dongu, olcumle secildi: cirak yazar -> usta CALISTIRARAK dogrular -> duzeltme buyuklugune gore paylasilir.

1) YAZDIR - worker_run(gorev, kabul_kriterleri, dogrulama="derleme").
   - Gorevde dosya adlarini ver; SOZLESMEYI sen yaz: cikti bicimi ("cikti tam olarak soyle: ..."),
     kenar durumlar, hangi girdide hangi hata. Olculdu: sozlesmeli tur 14/14, sozlesmesiz 12/14 -
     cirak hatayi kendisi bulur ama bicim/kenar detayini sen yazmazsan kacirir.
   - ortam "code"; calisma_dizini yazma (workspace koku), gerekirse goreli alt klasor.
   - Dosya listesi belliyse `yazilabilir: ["a.py","b.py"]` ver: baska dosyaya yazma REDDEDILIR.
     OLCULDU: kriter metni tutmuyor (dama gorevinde 11 dosya, 10'u istenmeyen .bat/.sh); izin
     listesiyle ayni gorev 1 dosya + prompt 199.9k -> 12.1k token (-%94), kalite ayni 12/12.
   - dogrulama="derleme": cirak yalnizca yazar, test/shell kapali (donus ~500 token, ~3x hizli).
     Dogrulama tek komutla BITMEYECEKSE (cok vaka/yineleme) "tam" kullan: cirak testi kendisi kosar.
   - Uzun is: bekle=false + worker_status(is_id).
2) DOGRULA - donen 'ozet' beyandir, kanit degil. 'yazilan_dosyalar[].icerik'i oku ve EN AZ BIR
   dogrulama komutunu KENDIN calistir (ornek girdilerle tek satirlik calistirma yeterli).
   Olculdu: '1.00 kalem' hatasi okumayla degil calistirmayla yakalandi.
3) DUZELT - hata varsa:
   - kucukse (<~20 satir, tek dosya): KENDIN duzelt; cirak turu bekleme, yanlis anlama riski alma.
   - buyukse/cok dosyaliysa: ciraga don. Genel konusma ("testler tutmuyor" YASAK); her hata icin:
     hangi dosya, hangi fonksiyon, hangi girdi, ne geldi, ne gelmeliydi.
   - `oturum` VARSAYILAN OLARAK VERME. Olculdu: kisa bir devam isinde oturum tasimak prompt'u
     %59 artirdi (8.1k vs 5.1k), kalite ve sure ayni - cunku isci oturumlu turda da dosyayi
     yeniden read_file ile okuyor, yani hem gecmisi hem taze okumayi odiyorsun. Oturumu yalnizca
     devam isi DOSYADA OLMAYAN bir baglama dayaniyorsa ver (onceki kararin gerekcesi, denenip
     elenen yol gibi).
4) HAFIZA - kalici bir ders cikarsa (proje kurali, tekrarlanan hata, sozlesme karari) workspace
   kokundeki HAFIZA.md dosyasina KISA bir madde ekle/guncelle; cirak her iste bunu sistem
   isteminde gorur (ilk 3000 karakter). Gecici seyleri yazma. Rapor `hafiza_uyarisi` verirse
   dosya tasmis demektir: ozetleyip kisalt, yoksa en yeni dersler ciraga gitmez.
5) DURUM (STATE.md) - onemli bir isin sonunda workspace kokundeki STATE.md'ye devir notu yaz,
   EN YENI USTTE: ne yapildi, nerede kalindi, hangi yollar denenip ELENDI, koddan gorunmeyen
   kararlar (adlandirma/bicim teamulleri gibi). Cirak her iste ilk 2000 karakteri gorur.
   200 satiri asinca eskileri STATE_ARSIV.md'ye tasi (rapor `durum_uyarisi` hatirlatir).
   Olculdu: ham `oturum` tasimak +%59 pahali - damitilmis devir onun yerine gecer.
6) BUYUK PROJE - cok dosyali depoda gorevde ciraga soyle: "once ara('...') ile ilgili yeri bul,
   sonra yalnizca o dosyalari oku". ara araci anlamsal arama yapar (bge-m3; yoksa BM25 sozcuksel yedek).
   Olculdu: dosya adini GOREVDE verebiliyorsan ara gereksiz (list_files+read_file daha ucuz);
   veremiyorsan (hedefin yerini sen de bilmiyorsan) ara SART - arasiz isci 120 dosyayi sirayla
   okumaya kalkip adim sinirinda hic yazamadan coktu (41.6k vs 11.2k token).
   Alternatif: worker_run(harita=true) sembol haritasini sistem istemine koyar - olculdu (120
   dosya): ara 11.2k tok/83s, harita 19.4k tok/51s, ikisi 30.9k (asla birlikte acma). Harita
   her model cagrisinda yeniden odenir ve depoyla buyur: varsayilan ara, bge-m3 yoksa harita.
7) RUFF - donen raporda `ruff_uyarilari` varsa (tanimsiz isim vb: derlenir ama calisirken
   patlar) degerlendir; gercekse somut teshisle duzelttir. Olculdu: isci uyariyla YENI kodu
   temiz yaziyor (bulasma 1/5 -> 4/5 onlendi) ama MEVCUT hatayi "davranisi koru" diye
   birakiyor - o karar senin.
8) En fazla 4 tur. Bitince raporla: tur sayisi, sure, her kriter NASIL dogrulandi (hangi komut/cikti).
"""


def kural_yaz(proje: str) -> bool:
    """Tek kaynak AGENTS.md (OpenMemory standardi - Codex/Copilot/Gemini dogrudan okur);
    Cursor icin .cursor/rules/apprentice.mdc ayni govdeyle (otomatik uygulanir), Copilot icin
    .github/ zaten varsa ona isaret eden kucuk bir yonlendirme yazilir."""
    govde = KURAL.split("---")[-1].strip() + "\n"
    p_agents = os.path.join(proje, "AGENTS.md")
    with open(p_agents, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Apprentice denetci kurali\n\n" + govde)
    log(OK + "AGENTS.md yazildi: %s  (tum ajanlarin ortak kural kaynagi)" % p_agents)
    d = os.path.join(proje, ".cursor", "rules")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "apprentice.mdc")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(KURAL)
    log(OK + "Cursor kurali yazildi: %s" % p)
    gh = os.path.join(proje, ".github")
    if os.path.isdir(gh):
        yol = os.path.join(gh, "copilot-instructions.md")
        if not os.path.isfile(yol):
            with open(yol, "w", encoding="utf-8", newline="\n") as f:
                f.write("Bu projede AGENTS.md'deki Apprentice denetci kuralini uygula.\n")
            log(OK + "Copilot yonlendirmesi yazildi: %s" % yol)
    # eski ad birakildiysa temizlik kullaniciya birakilir; yeni yazim APPRENTICE.md uretmez
    return True


# ------------------------------------------------------------------ main
def main() -> int:
    global DEGISTIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--kontrol", action="store_true", help="hicbir sey degistirme")
    ap.add_argument("--olc", action="store_true", help="num_batch olcumu yap ve yaz")
    ap.add_argument("--kural", metavar="PROJE", help="denetci kural dosyasini bu projeye yaz")
    ap.add_argument("--ide", default="", help="virgulle: cursor,vscode,windsurf,claude-desktop (bos = kurulu olanlar)")
    ap.add_argument("--kok", default="", help="Apprentice kurulum klasoru (varsayilan: bu betigin klasoru)")
    a = ap.parse_args()
    DEGISTIR = not a.kontrol

    set_root(a.kok or os.path.dirname(os.path.abspath(sys.executable if DONMUS else __file__)))
    if a.kural:
        return 0 if kural_yaz(a.kural) else 1
    if not depo_mu(ROOT):
        log("Apprentice dosyalari bulunamadi: %s  (--kok <kurulum_klasoru> ver ya da Apprentice-Setup.exe kullan)" % ROOT)
        return 1

    log("Apprentice kurulum  (%s, %s)" % (platform.system(), ROOT))
    sonuc = []
    adim(1, "Python");        sonuc.append(kontrol_python())
    adim(2, "Ollama");        sonuc.append(kontrol_ollama())
    adim(3, "Model");         sonuc.append(kontrol_model() if sonuc[-1] else False)
    adim(4, "IDE'ler")
    sonuc.append(kontrol_ideler(a.ide))
    mcp_json_guncelle()
    adim(5, "Ruff (istege bagli)")
    # F-sinifi yazim-ani kaniti icin; yoksa sistem yine calisir (sessiz atlanir).
    if DEGISTIR:
        py = sistem_python() or sys.executable
        r = subprocess.run([py, "-m", "ruff", "--version"], capture_output=True)
        if r.returncode != 0:
            r = subprocess.run([py, "-m", "pip", "install", "-q", "ruff"], capture_output=True)
        log("  ruff: %s" % ("hazir" if r.returncode == 0 else "kurulamadi (istege bagli, is surer)"))
    adim(6, "Oz-test");       sonuc.append(oz_test())
    if a.olc and all(sonuc[:3]):
        adim(7, "num_batch olcumu (2-3 dk)")
        r = subprocess.run([sistem_python() or sys.executable, os.path.join(ROOT, "core", "olcum.py"), "--yaz"])
        sonuc.append(r.returncode == 0)

    log()
    if all(sonuc):
        log("HAZIR. IDE'ni ac, MCP listesinde 'apprentice' yesil olsun (gerekirse yenile).")
        log("Proje icin kural dosyasi: python kur.py --kural <proje_klasoru>  (denetci rolu otomatik uygulanir)")
        return 0
    log("EKSIK ADIM VAR - yukaridaki [X] satirlarini tamamlayip tekrar calistir.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
