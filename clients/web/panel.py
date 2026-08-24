"""Apprentice Web Panel - zengin canli izleme + web'den gorev gonderme.

    python clients/web/panel.py [--port 8788] [--home ~/.apprentice] [--ac]

Masaustu izleyicinin (izle.py) veri katmanini AYNEN kullanir; ayni events.jsonl'i okur.
Ek olarak POST /api/gorev ile tarayicidan is baslatilabilir: is, sunucudaki Job sinifiyla
ayni yoldan kosulur, job.json'a "kaynak": "web-panel" islenir - usta worker_status(is_id)
ile diskten gorebilir (sunucuya worker_status disk-yedegi eklendi). Bagimlilik yok (stdlib).
"""
from __future__ import annotations
import argparse, json, os, sys, threading, time, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from izle import IsDeposu, olay_satiri, kanit_coz  # noqa: E402

HOME = ""
DEPO: IsDeposu | None = None
KILIT = threading.Lock()
SAYFA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel.html")
AYAR: dict = {}
METIN_UZANTILAR = (".py", ".md", ".txt", ".json", ".csv", ".html", ".js", ".ts", ".cs",
                   ".yaml", ".yml", ".xml", ".toml", ".ini", ".sql", ".sh", ".bat", ".css")


def _ayar_yolu() -> str:
    return os.path.join(HOME, "panel_ayar.json")


def _ayar_yukle():
    global AYAR
    try:
        with open(_ayar_yolu(), encoding="utf-8") as f:
            AYAR = json.load(f)
    except Exception:
        AYAR = {}
    AYAR.setdefault("kok", HOME)          # calisma alani: kullanicinin proje klasoru


def _ayar_kaydet():
    try:
        with open(_ayar_yolu(), "w", encoding="utf-8", newline="\n") as f:
            json.dump(AYAR, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _kok_sec() -> dict:
    """Yerel klasor secme diyalogu (panel yerelde kosar - gercek Windows penceresi).
    tkinter ana surecte sorun cikarmasin diye ayri Python surecinde acilir."""
    import subprocess
    kod = ("import tkinter, tkinter.filedialog as f\n"
           "r = tkinter.Tk(); r.withdraw(); r.attributes('-topmost', 1)\n"
           "print(f.askdirectory(title='Apprentice calisma alani sec'))")
    try:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        r = subprocess.run([pyw if os.path.isfile(pyw) else sys.executable, "-c", kod],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        yol = (r.stdout or "").strip()
        if yol and os.path.isdir(yol):
            AYAR["kok"] = os.path.abspath(yol)
            _ayar_kaydet()
            return {"kok": AYAR["kok"]}
        return {"kok": AYAR.get("kok", HOME), "iptal": True}
    except Exception as e:  # noqa: BLE001
        return {"hata": str(e)[:200]}


def _ekleri_kaydet(ekler: list, hedef_dir: str, yalniz_metin: bool) -> tuple:
    """Panelden gelen ekleri diske yazar. Doner: (yollar, reddedilenler)."""
    import base64
    os.makedirs(hedef_dir, exist_ok=True)
    yollar, red = [], []
    for e in (ekler or [])[:6]:
        ad = os.path.basename(str(e.get("ad") or "ek"))
        if yalniz_metin and not ad.lower().endswith(METIN_UZANTILAR):
            red.append(ad + " (cirak yalniz metin alir)")
            continue
        yol = os.path.join(hedef_dir, ad)
        try:
            if e.get("b64") is not None:
                veri = base64.b64decode(str(e["b64"]).split(",")[-1])
                if len(veri) > 8_000_000:
                    red.append(ad + " (8 MB siniri)")
                    continue
                with open(yol, "wb") as f:
                    f.write(veri)
            else:
                with open(yol, "w", encoding="utf-8", newline="\n") as f:
                    f.write(str(e.get("icerik") or "")[:2_000_000])
            yollar.append(yol)
        except OSError as hata:
            red.append("%s (%s)" % (ad, str(hata)[:60]))
    return yollar, red


def _sistem() -> dict:
    out = {"model": "", "yuklu_gb": 0, "vram": [0, 0], "gpu": 0}
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=3) as r:
            m = (json.load(r).get("models") or [])
        if m:
            out["model"] = m[0].get("name", "").split("/")[-1]
            out["yuklu_gb"] = round(m[0].get("size", 0) / 1e9)
    except Exception:
        out["model"] = None
    try:
        import subprocess
        s = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True,
                           timeout=3, creationflags=0x08000000 if os.name == "nt" else 0).stdout
        k, t, u = [int(x.strip()) for x in s.strip().split(",")[:3]]
        out["vram"] = [k, t]; out["gpu"] = u
    except Exception:
        pass
    return out


_USTA_TAMAM: set = set()


def _usta_rapor_tamamla(jid: str):
    """Panelden baslatilan islerde usta_rapor olayini MCP yolu yazmaz (o yol worker_status'ta);
    is bitince panel kendisi isler - kullanici geri bildirimi: 'usta raporunu hic gormedim'."""
    if jid in _USTA_TAMAM:
        return
    yol = os.path.join(DEPO.jobs_dir, jid, "events.jsonl")
    try:
        metin = open(yol, encoding="utf-8", errors="replace").read()
    except OSError:
        return
    if '"usta_rapor"' in metin or '"exit"' not in metin:
        if '"usta_rapor"' in metin:
            _USTA_TAMAM.add(jid)
        return
    try:
        os.environ.setdefault("APPRENTICE_HOME", HOME)
        import importlib
        srv = importlib.import_module("server.apprentice_server")
        rep = srv.rapor_diskten(jid) or {}
        with open(yol, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "usta_rapor", "t": time.time(),
                                "derleme_durumu": rep.get("derleme_durumu"),
                                "dosya": [d["yol"] for d in rep.get("yazilan_dosyalar", [])],
                                "hata_sayisi": len(rep.get("hatalar", [])),
                                "uyarilar": [k for k in ("duragan", "ruff_uyarilari",
                                                         "butce_uyarisi", "hafiza_uyarisi",
                                                         "durum_uyarisi") if rep.get(k)],
                                "kullanim": rep.get("kullanim") or {}},
                               ensure_ascii=False) + "\n")
        _USTA_TAMAM.add(jid)
    except Exception:
        pass


def _olaylar(jid: str, n: int) -> dict:
    with KILIT:
        _usta_rapor_tamamla(jid)
        DEPO.tazele(jid)
        s = dict(DEPO.durumlar.get(jid) or {})
        ev = DEPO.olaylar.get(jid) or []
        yeni = []
        for e in ev[n:]:
            et, metin = olay_satiri(e)
            yeni.append({"tip": e.get("type"), "asama": e.get("_asama"), "etiket": et,
                         "metin": metin, "yol": e.get("path"),
                         "kod": e.get("after") if e.get("type") == "write" else None,
                         "ham": {k: v for k, v in e.items()
                                 if k not in ("after", "before")} })
    canli = ""
    try:
        with open(os.path.join(DEPO.jobs_dir, jid, "canli.txt"), encoding="utf-8",
                  errors="replace") as f:
            canli = f.read()[:20000]
    except OSError:
        pass
    if n == 0:                                        # ilk cekilise iscinin tam promptu da girer
        try:
            with open(os.path.join(DEPO.jobs_dir, jid, "prompt.txt"), encoding="utf-8",
                      errors="replace") as f:
                s["prompt"] = f.read()[:5000]
        except OSError:
            pass
    s.pop("son_yazim", None)
    return {"ozet": s, "yeni": yeni, "toplam": n + len(yeni), "canli": canli}


def _is_listesi() -> list:
    with KILIT:
        adlar = DEPO.is_listesi()[:40]
        for jid in adlar[:10]:
            DEPO.tazele(jid)
        out = []
        for jid in adlar:
            s = DEPO.durumlar.get(jid) or {}
            out.append({"id": jid, "ortam": s.get("ortam", "?"), "durum": s.get("durum", "?"),
                        "derleme": s.get("derleme", "?"), "asama": s.get("asama", "?"),
                        "kaynak": s.get("kaynak", ""), "sure": s.get("sure"),
                        "baslik": s.get("baslik") or
                        " ".join((s.get("gorev") or "").split()[:6])[:48]})
        return out


def _gorev_baslat(veri: dict) -> dict:
    """Web'den is: sunucudaki Job sinifinin ta kendisiyle (ayni olay semasi, ayni ev)."""
    os.environ.setdefault("APPRENTICE_HOME", HOME)
    os.environ["APPRENTICE_IZLEYICI"] = "0"            # panel zaten izliyor; pencere acma
    import importlib
    srv = importlib.import_module("server.apprentice_server")
    gorev = str(veri.get("gorev") or "").strip()
    if not gorev:
        return {"hata": "gorev bos"}
    kriterler = [k.strip() for k in (veri.get("kriterler") or []) if str(k).strip()]
    ortam = str(veri.get("ortam") or "code")
    if ortam not in srv.ENVS:
        return {"hata": "bilinmeyen ortam %r (var: %s)" % (ortam, list(srv.ENVS))}
    dogrulama = str(veri.get("dogrulama") or "derleme")
    kapali_ek = ["run_tests", "run_shell"] if dogrulama == "derleme" else []
    # calisma dizini SECILI CALISMA ALANINA gore cozulur (kullanicinin proje klasoru;
    # ust bardaki klasor secici belirler, varsayilan panel evi)
    dizin = str(veri.get("calisma_dizini") or "panel").strip().replace("\\", "/")
    if ".." in dizin or os.path.isabs(dizin):
        return {"hata": "calisma_dizini calisma alanina goreli olmali"}
    tam_dizin = os.path.join(AYAR.get("kok", HOME), dizin)
    os.makedirs(tam_dizin, exist_ok=True)
    # ekler: metin dosyalari dogrudan calisma dizinine - `ara` (RAG) otomatik indeksler
    ek_yollar, ek_red = _ekleri_kaydet(veri.get("ekler") or [], tam_dizin, yalniz_metin=True)
    if ek_yollar:
        gorev += ("\n\nEKLI DOSYALAR (calisma dizininde, gerekirse read_file/ara ile kullan): "
                  + ", ".join(os.path.basename(y) for y in ek_yollar))
    model = str(veri.get("model") or "").strip() or \
        srv.config.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model")
    # MODEL UYUMU: secilen modelin kartindan ctx siniri alinir - config ctx karttan buyukse
    # kisilir (olculdu: Ollama pencereyi asan istegi reddediyor; kucuk modelde 128k istemek hata).
    eski_ctx = os.environ.get("APPRENTICE_CTX")
    try:
        kart = _model_kart(model)
        cfg_ctx = int(srv.config.env_or("APPRENTICE_CTX", "ollama.num_ctx", 131072) or 131072)
        if kart.get("ctx") and int(kart["ctx"]) < cfg_ctx:
            os.environ["APPRENTICE_CTX"] = str(int(kart["ctx"]))
    except Exception:
        kart = {}
    job = srv.Job(ortam, gorev, kriterler, "", False, 3, model,
                  "", tam_dizin, kapali_ek, dogrulama,
                  [str(x).strip() for x in (veri.get("yazilabilir") or []) if str(x).strip()],
                  bool(veri.get("harita")), bool(veri.get("canli", True)))
    job.start()
    if eski_ctx is None:
        os.environ.pop("APPRENTICE_CTX", None)
    else:
        os.environ["APPRENTICE_CTX"] = eski_ctx
    srv.JOBS[job.id] = job
    # ZAMAN ASIMI BEKCISI (Kalman olayinda fark edildi): MCP'deki bekleme dongusu isciyi
    # sinirda oldurur ama panel isleri o donguden gecmez - bekci olmadan sahipsiz kalirlardi.
    sinir = min(float(veri.get("zaman_asimi_s") or 1800), 3600)
    def _bekci():
        try:
            if not job.done:
                job.kill()
        except Exception:
            pass
    threading.Timer(sinir, _bekci).start()
    # kaynak isareti: usta ve izleyiciler bu isin panelden geldigini gorsun
    jp = os.path.join(job.dir, "job.json")
    baslik = str(veri.get("baslik") or "").strip() or " ".join(gorev.split()[:6])[:48]
    try:
        with open(jp, encoding="utf-8") as f:
            j = json.load(f)
        j["kaynak"] = "web-panel"
        j["baslik"] = baslik
        with open(jp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(j, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    # usta kutusu: MCP sunucusu bir sonraki arac cagrisinda bildirir
    bp = os.path.join(HOME, "panel_bekleyen.json")
    try:
        try:
            with open(bp, encoding="utf-8") as f:
                b = json.load(f)
        except Exception:
            b = []
        b.append(job.id)
        with open(bp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(b[-10:], f)
    except OSError:
        pass
    return {"is_id": job.id, "baslik": baslik}


def _ollama_get(yol: str, govde: dict | None = None):
    import urllib.request
    url = "http://localhost:11434" + yol
    if govde is None:
        r = urllib.request.urlopen(url, timeout=6)
    else:
        r = urllib.request.urlopen(urllib.request.Request(
            url, json.dumps(govde).encode(), {"Content-Type": "application/json"}), timeout=30)
    return json.load(r)


def _modeller() -> dict:
    """Ollama'daki secilebilir isci modelleri (gomme modelleri haric)."""
    try:
        tags = _ollama_get("/api/tags").get("models", [])
    except Exception as e:  # noqa: BLE001
        return {"hata": str(e)[:200], "modeller": []}
    out = []
    for m in tags:
        ad = m.get("name", "")
        if "bge" in ad.lower() or "embed" in ad.lower():
            continue
        out.append({"ad": ad, "gb": round(m.get("size", 0) / 1e9, 1)})
    import importlib
    varsayilan = ""
    try:
        os.environ.setdefault("APPRENTICE_HOME", HOME)
        srv = importlib.import_module("server.apprentice_server")
        varsayilan = srv.config.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model") or ""
    except Exception:
        pass
    return {"modeller": out, "varsayilan": varsayilan}


def _model_kart(ad: str) -> dict:
    """Model kartindan tavsiye parametreler: /api/show -> parameters + context_length.
    Isci kosarken temperature yine 0'dir (olculdu: determinizm); kart BILGI + ctx siniri icin."""
    try:
        d = _ollama_get("/api/show", {"model": ad})
    except Exception as e:  # noqa: BLE001
        return {"hata": str(e)[:200]}
    kart = {"parametreler": {}, "ctx": None, "aile": (d.get("details") or {}).get("family", "")}
    for satir in (d.get("parameters") or "").splitlines():
        parca = satir.split(None, 1)
        if len(parca) == 2:
            kart["parametreler"][parca[0]] = parca[1].strip('"')
    for k, v in (d.get("model_info") or {}).items():
        if k.endswith("context_length"):
            kart["ctx"] = v
    kart["yetenekler"] = d.get("capabilities") or []
    return kart


def _model_yukle() -> dict:
    """On-isitma: varsayilan isci modelini simdiden RAM'e al (ilk isin ~1 dk yukleme
    bedelini pesin oder). Ollama zaten tembel yukler; bu dugme yalnizca konfor."""
    try:
        import importlib, urllib.request
        os.environ.setdefault("APPRENTICE_HOME", HOME)
        srv = importlib.import_module("server.apprentice_server")
        model = srv.config.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model")

        def isit():
            try:
                # soguk yukleme ~1-2 dk: istek arka planda, genis zaman asimiyla
                urllib.request.urlopen(urllib.request.Request(
                    "http://localhost:11434/api/generate",
                    json.dumps({"model": model, "keep_alive": "30m"}).encode(),
                    {"Content-Type": "application/json"}), timeout=600).read()
            except Exception:
                pass
        threading.Thread(target=isit, daemon=True).start()
        return {"durum": "yukleniyor", "model": model}
    except Exception as e:  # noqa: BLE001
        return {"hata": str(e)[:200]}


def _model_bosalt() -> dict:
    """Eject: yuklu modelleri RAM/VRAM'den indir (keep_alive: 0). Sonraki is yeniden yukler."""
    try:
        yuklu = [m.get("name") for m in _ollama_get("/api/ps").get("models", [])]
        for ad in yuklu:
            _ollama_get("/api/generate", {"model": ad, "keep_alive": 0})
        return {"bosaltilan": yuklu}
    except Exception as e:  # noqa: BLE001
        return {"hata": str(e)[:200]}


SOHBET = {"mesajlar": []}          # cirakla serbest sohbet (gorev kalibi yok, hafizali)


def _cirak_sohbet(veri: dict) -> dict:
    """Cirakla DUZ sohbet: worker_run kalibi (kriter/dogrulama/rapor) YOK - dogrudan Ollama.
    Kullanici geri bildirimi: 'her sorumda gorev basliyor, kriter istiyor'. Gorev kipi is
    yaptirir, sohbet kipi konusur. Hafiza: son 20 mesaj; temperature 0.7 (sohbet, is degil)."""
    import importlib, urllib.request
    prompt = str(veri.get("prompt") or "").strip()
    if veri.get("sifirla"):
        SOHBET["mesajlar"] = []
        if not prompt:
            return {"cevap": "", "sifirlandi": True}
    if not prompt:
        return {"hata": "bos"}
    os.environ.setdefault("APPRENTICE_HOME", HOME)
    srv = importlib.import_module("server.apprentice_server")
    model = str(veri.get("model") or "").strip() or \
        srv.config.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model")
    SOHBET["mesajlar"].append({"role": "user", "content": prompt})
    body = json.dumps({"model": model, "stream": False,
                       "messages": [{"role": "system", "content":
                                     "Sen Apprentice sisteminin yerel cirak modelisin (%s). "
                                     "Turkce, kisa ve net cevap ver. Kod isleri icin kullanici "
                                     "gorev kipini kullanir; burada serbest sohbettesin."
                                     % model.split("/")[-1].split(":")[0]}]
                       + SOHBET["mesajlar"][-20:],
                       "options": {"num_ctx": 16384, "temperature": 0.7, "num_predict": 1200},
                       "keep_alive": "30m"}).encode()
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(
            "http://localhost:11434/api/chat", body, {"Content-Type": "application/json"}),
            timeout=600))
        cevap = ((d.get("message") or {}).get("content") or "").strip()
        SOHBET["mesajlar"].append({"role": "assistant", "content": cevap})
        return {"cevap": cevap, "tok": d.get("eval_count")}
    except Exception as e:  # noqa: BLE001
        SOHBET["mesajlar"].pop()
        return {"hata": str(e)[:250]}


def _usta_istek(veri: dict) -> dict:
    """Panelden Claude CLI'ya BASSIZ istek (claude -p). Desktop gerekmez; kullanicinin
    girisiyle calisir. Her istek Max kotasindan harcar - o yuzden yalnizca kullanici
    tetikler, otomatik cagri YOK. Arac izni istenirse usta worker_run kullanabilir
    (tam dongu: panel -> Claude -> cirak -> Claude -> panel)."""
    import shutil as _sh, subprocess as _sp
    prompt = str(veri.get("prompt") or "").strip()
    if not prompt:
        return {"hata": "prompt bos"}
    if str(veri.get("cli") or "claude") == "claude":
        if not _sh.which("claude"):
            return {"hata": "claude CLI bulunamadi. Kur: npm i -g @anthropic-ai/claude-code "
                            "(ya da CLI seceneginden 'ozel CLI' ile baska ajan kullan)"}
        # GIRIS KONTROLU: kurulu olmak yetmez, oturum acik olmali (yoksa istek sessizce
        # anlamsiz hata dondururdu - kullanici sebebini goremezdi)
        try:
            r = _sp.run([_sh.which("claude"), "auth", "status"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=45,
                        creationflags=0x08000000 if os.name == "nt" else 0)
            d = json.loads((r.stdout or "{}").strip() or "{}")
            if not d.get("loggedIn"):
                return {"hata": "Claude oturumu YOK. Bir terminal acip 'claude auth login' "
                                "calistir (tarayicida Anthropic hesabinla giris), sonra tekrar "
                                "gonder. Cirak (yerel model) girissiz calismaya devam eder."}
        except Exception:
            pass                       # durum okunamazsa istegi engelleme, denesin
    uid = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    kdir = os.path.join(HOME, "usta_istekler")
    os.makedirs(kdir, exist_ok=True)
    kayit = {"id": uid, "prompt": prompt, "durum": "calisiyor",
             "araclar": bool(veri.get("araclar")), "baslangic": time.time(), "cevap": ""}
    yol = os.path.join(kdir, uid + ".json")
    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        json.dump(kayit, f, ensure_ascii=False)

    kayit["model"] = str(veri.get("model") or "")
    kayit["effort"] = str(veri.get("effort") or "")
    kayit["cli"] = str(veri.get("cli") or "claude")
    sablon = str(veri.get("sablon") or "")
    # ekler (resim dahil): calisma alanindaki panel_ekler/ altina; Claude yollariyla okur
    ek_yollar, ek_red = _ekleri_kaydet(veri.get("ekler") or [],
                                       os.path.join(AYAR.get("kok", HOME), "panel_ekler"),
                                       yalniz_metin=False)
    if ek_yollar:
        # talimat BASTA ve emir kipinde: sona eklenen not gorulup gecildi (yasandi -
        # Claude Read'i cagirmadan "gorsel yok" dedi). Yollar normalize edilir.
        yollar = "\n".join(os.path.normpath(y) for y in ek_yollar)
        prompt = ("ONCE su dosyalari Read araciyla TEK TEK AC ve iceriklerini gor "
                  "(kullanici panelden ekledi; resimler dahil - Read resimleri gosterir):\n"
                  + yollar + "\n\nSONRA kullanicinin istegini cevapla:\n" + prompt)
        kayit["ekler"] = [os.path.basename(y) for y in ek_yollar]
    kayit["prompt"] = prompt

    def kos():
        # KRITIK (yasandi): shell=True + cok satirli prompt arguman olarak verilince cmd.exe
        # satir sonunu KOMUT AYRACI sayiyor - Claude'a yalniz ilk satir ulasiyordu (ek yollari,
        # canli:true notu sessizce dusuyordu). Prompt artik STDIN'den gider; komutta yalniz
        # tek satirlik bayraklar durur.
        girdi = prompt
        if kayit["cli"] == "ozel" and sablon:
            if "{prompt}" in sablon:
                cmd = sablon.replace("{prompt}", '"' + prompt.replace('"', "'").replace("\n", " ") + '"')
                girdi = None
            else:
                cmd = sablon                       # sablon {prompt} icermiyorsa stdin'den
        else:
            parcalar = ["claude", "-p", "--output-format", "text"]
            if kayit["model"]:
                parcalar += ["--model", kayit["model"]]
            if kayit["effort"]:
                parcalar += ["--effort", kayit["effort"]]
            izinler = []
            if kayit["araclar"]:
                izinler += ["mcp__apprentice__worker_run", "mcp__apprentice__worker_status"]
                girdi += ("\n\n(Not: worker_run cagirirken canli:true parametresini "
                          "ekle - kullanici paneldeki canli akista izliyor. bekle:true "
                          "kullan; is bitince sonucu kisaca degerlendir.)")
            if ek_yollar:
                izinler.append("Read")             # ekleri (resim dahil) okuyabilsin
            if izinler:
                parcalar += ["--allowedTools", '"%s"' % ",".join(izinler)]
            cmd = " ".join(parcalar)
        env = dict(os.environ, APPRENTICE_HOME=HOME, APPRENTICE_IZLEYICI="0",
                   PYTHONIOENCODING="utf-8")
        try:
            r = _sp.run(cmd, input=girdi, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=600, cwd=ROOT, env=env, shell=True,
                        creationflags=0x08000000 if os.name == "nt" else 0)
            kayit["cevap"] = (r.stdout or "").strip() or ("HATA: " + (r.stderr or "")[-500:])
            kayit["durum"] = "bitti" if r.returncode == 0 else "hata"
        except Exception as e:  # noqa: BLE001
            kayit["cevap"] = "HATA: %s" % str(e)[:300]
            kayit["durum"] = "hata"
        kayit["sure"] = round(time.time() - kayit["baslangic"], 1)
        with open(yol, "w", encoding="utf-8", newline="\n") as f:
            json.dump(kayit, f, ensure_ascii=False)
    threading.Thread(target=kos, daemon=True).start()
    return {"id": uid}


def _sahipsiz_kontrol(k: dict, yol: str) -> dict:
    """Panel yeniden baslarsa kosan istegin is parcacigi olur ama kayit 'calisiyor' kalir -
    sonsuz 'dusunuyor' gorunumu (yasandi: 1016 sn). 700 sn ustu calisiyor = sahipsiz say."""
    if k.get("durum") == "calisiyor" and time.time() - k.get("baslangic", 0) > 700:
        k["durum"] = "hata"
        k["cevap"] = "istek sahipsiz kaldi (panel yeniden baslatildi ya da 700 sn zaman asimi)"
        k["sure"] = round(time.time() - k.get("baslangic", time.time()), 1)
        try:
            with open(yol, "w", encoding="utf-8", newline="\n") as f:
                json.dump(k, f, ensure_ascii=False)
        except OSError:
            pass
    return k


def _usta_liste() -> list:
    kdir = os.path.join(HOME, "usta_istekler")
    out = []
    if os.path.isdir(kdir):
        for ad in sorted(os.listdir(kdir), reverse=True)[:20]:
            try:
                with open(os.path.join(kdir, ad), encoding="utf-8") as f:
                    k = json.load(f)
                k = _sahipsiz_kontrol(k, os.path.join(kdir, ad))
                out.append({"id": k["id"], "durum": k.get("durum"),
                            "ozet": k.get("prompt", "")[:60],
                            "baslangic": k.get("baslangic"),
                            "sure": k.get("sure") if k.get("sure") is not None
                            else round(time.time() - k.get("baslangic", time.time()), 0),
                            "araclar": k.get("araclar")})
            except Exception:
                pass
    return out


def _usta_cevap(uid: str) -> dict:
    yol = os.path.join(HOME, "usta_istekler", uid + ".json")
    try:
        with open(yol, encoding="utf-8") as f:
            return _sahipsiz_kontrol(json.load(f), yol)
    except Exception:
        return {"hata": "istek yok"}


class Istek(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _gonder(self, govde, tip="application/json; charset=utf-8", kod=200):
        if isinstance(govde, (dict, list)):
            govde = json.dumps(govde, ensure_ascii=False).encode("utf-8")
        elif isinstance(govde, str):
            govde = govde.encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", tip)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(govde)

    def do_GET(self):
        yol = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(yol.query))
        try:
            if yol.path == "/":
                with open(SAYFA, encoding="utf-8") as f:
                    self._gonder(f.read(), "text/html; charset=utf-8")
            elif yol.path == "/api/isler":
                self._gonder({"isler": _is_listesi(), "sistem": _sistem()})
            elif yol.path == "/api/olaylar":
                self._gonder(_olaylar(q.get("is", ""), int(q.get("n", 0))))
            elif yol.path == "/api/usta_liste":
                self._gonder({"istekler": _usta_liste()})
            elif yol.path == "/api/usta_cevap":
                self._gonder(_usta_cevap(q.get("id", "")))
            elif yol.path == "/api/kok":
                self._gonder({"kok": AYAR.get("kok", HOME)})
            elif yol.path == "/api/modeller":
                self._gonder(_modeller())
            elif yol.path == "/api/model_kart":
                self._gonder(_model_kart(q.get("ad", "")))
            else:
                self._gonder({"hata": "yok"}, kod=404)
        except Exception as e:  # noqa: BLE001
            self._gonder({"hata": str(e)[:300]}, kod=500)

    def _sohbet_akisi(self, veri: dict):
        """Cirak sohbetini TOKEN TOKEN akit (Ollama stream -> chunked yanit).
        Kullanici geri bildirimi: 'her sey bir anda geliyor, akis yok'."""
        import importlib, urllib.request
        prompt = str(veri.get("prompt") or "").strip()
        if veri.get("sifirla"):
            SOHBET["mesajlar"] = []
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if not prompt:
            return
        os.environ.setdefault("APPRENTICE_HOME", HOME)
        srv = importlib.import_module("server.apprentice_server")
        model = str(veri.get("model") or "").strip() or \
            srv.config.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model")
        SOHBET["mesajlar"].append({"role": "user", "content": prompt})
        body = json.dumps({"model": model, "stream": True,
                           "messages": [{"role": "system", "content":
                                         "Sen Apprentice sisteminin yerel cirak modelisin (%s). "
                                         "Turkce, kisa ve net cevap ver."
                                         % model.split("/")[-1].split(":")[0]}]
                           + SOHBET["mesajlar"][-20:],
                           "options": {"num_ctx": 16384, "temperature": 0.7,
                                       "num_predict": 1200},
                           "keep_alive": "30m"}).encode()
        parcalar = []
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    "http://localhost:11434/api/chat", body,
                    {"Content-Type": "application/json"}), timeout=600) as r:
                for ham in r:
                    try:
                        d = json.loads(ham)
                    except Exception:
                        continue
                    p = (d.get("message") or {}).get("content") or ""
                    if p:
                        parcalar.append(p)
                        self.wfile.write(p.encode("utf-8"))
                        self.wfile.flush()
        except Exception as e:  # noqa: BLE001
            try:
                self.wfile.write(("\n[HATA: %s]" % str(e)[:200]).encode("utf-8"))
            except OSError:
                pass
        cevap = "".join(parcalar).strip()
        if cevap:
            SOHBET["mesajlar"].append({"role": "assistant", "content": cevap})
        else:
            SOHBET["mesajlar"].pop()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            veri = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if urllib.parse.urlparse(self.path).path == "/api/cirak_sohbet_akis":
                return self._sohbet_akisi(veri)
            yolu = urllib.parse.urlparse(self.path).path
            if yolu == "/api/gorev":
                self._gonder(_gorev_baslat(veri))
            elif yolu == "/api/usta":
                self._gonder(_usta_istek(veri))
            elif yolu == "/api/cirak_sohbet":
                self._gonder(_cirak_sohbet(veri))
            elif yolu == "/api/claude_login":
                # 'claude auth login' GORUNUR konsolda: kullanici tarayicida giris yapar.
                # Panel kimlik bilgisi ISTEMEZ/SAKLAMAZ - yalnizca resmi akisi baslatir.
                import shutil as _sh2, subprocess as _sp2
                exe = _sh2.which("claude")
                if not exe:
                    self._gonder({"hata": "claude CLI yok: npm i -g @anthropic-ai/claude-code"})
                else:
                    try:
                        if os.name == "nt":
                            _sp2.Popen(["cmd", "/c", "start", "Claude girisi", "cmd", "/k",
                                        '"%s" auth login' % exe])
                        else:
                            _sp2.Popen([exe, "auth", "login"])
                        self._gonder({"durum": "giris penceresi acildi"})
                    except Exception as e:  # noqa: BLE001
                        self._gonder({"hata": str(e)[:200]})
            elif yolu == "/api/eject":
                self._gonder(_model_bosalt())
            elif yolu == "/api/yukle":
                self._gonder(_model_yukle())
            elif yolu == "/api/kok_sec":
                self._gonder(_kok_sec())
            elif yolu == "/api/kok":
                y = str(veri.get("yol") or "").strip()
                if y and os.path.isdir(y):
                    AYAR["kok"] = os.path.abspath(y); _ayar_kaydet()
                    self._gonder({"kok": AYAR["kok"]})
                else:
                    self._gonder({"hata": "klasor bulunamadi: %s" % y})
            else:
                self._gonder({"hata": "yok"}, kod=404)
        except Exception as e:  # noqa: BLE001
            self._gonder({"hata": str(e)[:300]}, kod=500)


def main() -> int:
    global HOME, DEPO
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--home", default=os.environ.get("APPRENTICE_HOME") or
                    os.path.join(os.path.expanduser("~"), ".apprentice"))
    ap.add_argument("--ac", action="store_true", help="tarayiciyi ac")
    a = ap.parse_args()
    HOME = os.path.expanduser(a.home)
    DEPO = IsDeposu(HOME)
    _ayar_yukle()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Istek)
    url = "http://127.0.0.1:%d" % a.port
    print("Apprentice Web Panel: %s  (ev: %s)" % (url, HOME))
    if a.ac:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
