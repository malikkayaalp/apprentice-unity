"""Apprentice MCP sunucusu: "yerel model isi yapar, buyuk model denetler".

Denetci (Claude Code, Cursor, VS Code... IDE'nin kendi modeli) bu sunucuya stdio MCP ile
baglanir ve TEK araci cagirir:

    worker_run(gorev, kabul_kriterleri, ortam="code")
      -> {yazilan_dosyalar, derleme_durumu, hatalar, tur_sayisi, sure, ozet, olcumler, oturum}

Isci = Ollama'daki yerel model (Qwen3-Coder-Next). Ortam = arac seti + dogrulayici; her
ortam envs/<ad>/ altinda bir klasor ve env.json ile tanimlanir, sunucu bunlari KESFEDER:
  code   envs/code/code_runner.py - genel kod: dosya oku/yaz, shell, test; workspace'e hapis.
  fake   envs/fake/fake_runner.py - isci olmadan ayni olay semasini ureten duman testi.
  (eklentiler: ornegin apprentice-unity, envs/unity olarak klonlanir; cekirdek onu bilmez.)
Kosucu AYRIK surecte calisir - tur dakikalar surer, isci cokse sunucu ayakta kalir.

Denetci kabul kriterini yazar (iscinin en zayif yeri). Sunucu kriterleri goreve metin
olarak ekler, isciyi kosturur, DOGRULANMIS sonucu (derleyici) ve HAM olcumleri dondurur;
yorumlama ve "yeter mi" karari denetcide kalir. Olculen sebep: isci kendi olcumune bakip
duzeltmeye kalkinca yakinsamadi (1.15 -> 0.01), olcum ozetlenip verilince 2 turda cozdu.

Stdout MCP kanalidir: iscinin ciktisi oraya ASLA karismaz (DEVNULL + dosya).
Bagimlilik yok (stdlib). Calistirma: python server/apprentice_server.py  (istemci baslatir)
Ev: APPRENTICE_HOME (varsayilan ~/.apprentice) -> jobs/<id>/, sessions/<ortam>/.
"""
from __future__ import annotations
import difflib, json, os, subprocess, sys, threading, time, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from core import config  # noqa: E402

PROTOCOL = "2024-11-05"
SERVER_INFO = {"name": "apprentice", "version": "0.2.0"}
HOME = os.environ.get("APPRENTICE_HOME") or os.path.join(os.path.expanduser("~"), ".apprentice")
PYTHON = os.environ.get("APPRENTICE_PYTHON") or sys.executable
# Bir tur 60-300 s; play_observe'lu isler daha uzun. Varsayilan ust sinir 30 dk.
DEFAULT_TIMEOUT_S = float(os.environ.get("APPRENTICE_TIMEOUT_S", "1800"))

ICERIK_SINIRI = int(os.environ.get("APPRENTICE_ICERIK_SINIRI", "12000"))   # dosya icerigi/karakter
# Olcum sayilan araclar: sonuclari ham olarak denetciye tasinir.
MEASURE_TOOLS = {"play_observe", "read_console", "scene_objects", "inspect_object", "run_tests"}

def _ortamlari_kesfet() -> dict:
    """envs/<ad>/env.json olan her klasor bir ortamdir. Eklentiler (ayri depolar) buraya
    klonlanir; klasor yoksa o ortam secenegi hic gorunmez."""
    out = {}
    kok = os.path.join(ROOT, "envs")
    if not os.path.isdir(kok):
        return out
    for ad in sorted(os.listdir(kok)):
        p = os.path.join(kok, ad, "env.json")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        kosucu = os.path.join(kok, ad, meta.get("kosucu", ""))
        if not os.path.isfile(kosucu):
            continue
        meta["runner"] = kosucu
        out[meta.get("ad", ad)] = meta
    return out


ENVS = _ortamlari_kesfet()
VARSAYILAN_ORTAM = "code" if "code" in ENVS else (next(iter(ENVS)) if ENVS else "code")

PROMPT_TMPL = (
    "{gorev}\n\n"
    "KABUL KRITERLERI (denetci yazdi; bitirmeden once her birini sagladigindan emin ol):\n"
    "{kriterler}\n\n"
    "Kurallar: Basariyi derleyici/dogrulayici belirler, senin beyanin degil. Olcum "
    "gerekiyorsa olc ve SONUCU HAM HALIYLE raporla; yorumlamaya ya da olcum-duzeltme "
    "dongusune girme, sinira gelince dur ve raporla. Nihai mesajinda: ne yazdin, "
    "hangi kriteri nasil sagladin, neyi saglayamadin - kisa ve somut."
)


def _diff_stat(before: str | None, after: str) -> tuple[int, int]:
    b = (before or "").splitlines()
    a = (after or "").splitlines()
    ek = sil = 0
    for line in difflib.unified_diff(b, a, lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            ek += 1
        elif line.startswith("-") and not line.startswith("---"):
            sil += 1
    return ek, sil


# --------------------------------------------------------------------------- is
class Job:
    def __init__(self, ortam: str, gorev: str, kriterler: list, oturum: str,
                 play: bool, onarim: int, model: str, url: str, workdir: str = "",
                 kapali: list | None = None, dogrulama: str = "tam", yazilabilir: list | None = None,
                 harita: bool = False, canli: bool = False):
        self.workdir = workdir
        self.canli = canli
        self.dogrulama = dogrulama
        self.harita = harita
        self.yazilabilir = [str(x).strip() for x in (yazilabilir or []) if str(x).strip()]
        self.kapali = [str(k) for k in (kapali or []) if str(k).strip()]
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.dir = os.path.join(HOME, "jobs", self.id)
        os.makedirs(self.dir, exist_ok=True)
        self.ortam, self.gorev, self.kriterler = ortam, gorev, kriterler
        self.oturum = oturum or self.id
        self.play, self.onarim, self.model, self.url = play, onarim, model, url
        self.t0 = time.time()
        self.proc: subprocess.Popen | None = None
        self.done = False
        self.code: int | None = None

    @property
    def events_path(self):
        return os.path.join(self.dir, "events.jsonl")

    def izleyici_ac(self):
        """Is baslarken izleyiciyi otomatik ac (acik degilse; APPRENTICE_IZLEYICI=0 kapatir).
        Konsol penceresi ACILMAZ: exe varsa o, yoksa pythonw + CREATE_NO_WINDOW."""
        if os.environ.get("APPRENTICE_IZLEYICI", "1") == "0":
            return
        try:
            sys.path.insert(0, ROOT)
            from izle import calisan_izleyici
            if calisan_izleyici(HOME):
                return
            exe = os.path.join(ROOT, "dist", "Apprentice-Izleyici.exe")
            if os.path.isfile(exe):
                cmd = [exe, "--home", HOME]
            else:
                pyw = os.path.join(os.path.dirname(PYTHON), "pythonw.exe")
                cmd = [pyw if os.path.isfile(pyw) else PYTHON,
                       os.path.join(ROOT, "izle.py"), "--home", HOME]
            bayrak = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
            subprocess.Popen(cmd, cwd=ROOT, creationflags=bayrak,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:
            pass                                                   # izleyici konfor: is engellenmez

    def start(self):
        self.izleyici_ac()
        runner = ENVS[self.ortam]["runner"]
        prompt = PROMPT_TMPL.format(
            gorev=self.gorev.strip(),
            kriterler="\n".join("- " + k.strip() for k in self.kriterler) or "- (verilmedi)")
        pf = os.path.join(self.dir, "prompt.txt")
        with open(pf, "w", encoding="utf-8", newline="\n") as f:
            f.write(prompt)
        with open(os.path.join(self.dir, "job.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"id": self.id, "ortam": self.ortam, "gorev": self.gorev,
                       "kabul_kriterleri": self.kriterler, "oturum": self.oturum,
                       "play": self.play, "model": self.model, "baslangic": self.t0,
                       "calisma_dizini": self.workdir,
                       # izleyiciler dogru gostersin (olculdu: alan yazilmayinca panel
                       # her ise "tam" diyordu - kullanici kipinden suphe etti)
                       "dogrulama": self.dogrulama, "canli": self.canli,
                       "harita": self.harita, "yazilabilir": self.yazilabilir},
                      f, ensure_ascii=False, indent=1)
        sess_dir = os.path.join(HOME, "sessions", self.ortam)
        cmd = [PYTHON, runner, "--jsonl", self.events_path, "--prompt-file", pf,
               "--session", self.oturum, "--session-dir", sess_dir,
               "--model", self.model, "--url", self.url, "--repairs", str(self.onarim)]
        if self.play:
            cmd.append("--play")
        if self.workdir:
            cmd += ["--workdir", self.workdir]
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if self.kapali:
            env["APPRENTICE_TOOLS_OFF"] = ",".join(self.kapali)
        if self.dogrulama != "tam":
            env["APPRENTICE_DOGRULAMA"] = self.dogrulama
        if self.yazilabilir:
            env["APPRENTICE_YAZILABILIR"] = ",".join(self.yazilabilir)
        if self.harita:
            env["APPRENTICE_HARITA"] = "1"
        if self.canli:
            env["APPRENTICE_CANLI"] = "1"
        self.stderr_f = open(os.path.join(self.dir, "stderr.txt"), "w", encoding="utf-8")
        # stdin/stdout=DEVNULL SART: ikisi de MCP kanali. Olculdu: stdin miras alininca
        # cocuk Windows'ta ilk satirini bile yazmadan takildi (yalniz sunucu icinde).
        self.proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL,
                                     stderr=self.stderr_f,
                                     # penceresiz: sunucu pencereli bir istemciden (Setup GUI,
                                     # izleyici exe) baslatilinca her isci konsol acmasin
                                     creationflags=0x08000000 if os.name == "nt" else 0)
        threading.Thread(target=self._wait, daemon=True).start()

    def _wait(self):
        self.code = self.proc.wait()
        try:
            self.stderr_f.close()
        except Exception:
            pass
        # Isci 'exit' yazmadan oldüyse olay dosyasini biz kapatalim (izleyiciler icin).
        try:
            ev = self.events()
            if not any(e.get("type") == "exit" for e in ev):
                with open(self.events_path, "a", encoding="utf-8") as f:
                    if not any(e.get("type") in ("result", "error") for e in ev):
                        f.write(json.dumps({"type": "error", "message":
                                            "isci sonuc yazmadan cikti (kod %s)" % self.code},
                                           ensure_ascii=False) + "\n")
                    f.write(json.dumps({"type": "exit", "code": self.code}) + "\n")
        except Exception:
            pass
        self.done = True

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def events(self) -> list:
        out = []
        try:
            with open(self.events_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except Exception:
                            pass
        except FileNotFoundError:
            pass
        return out

    def usta_rapor_isaretle(self, rep: dict):
        """Is bittiginde 'ustaya ne gitti' olayini events.jsonl'a BIR KEZ ekler - izleyici
        boru hattinin son halkasini da gorsun (isci sureci coktan bitmistir, dosya bizim)."""
        if getattr(self, "_usta_isaretli", False) or not self.done:
            return
        self._usta_isaretli = True
        try:
            with open(os.path.join(self.dir, "events.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "usta_rapor", "t": time.time(),
                                    "derleme_durumu": rep.get("derleme_durumu"),
                                    "dosya": [d["yol"] for d in rep.get("yazilan_dosyalar", [])],
                                    "hata_sayisi": len(rep.get("hatalar", [])),
                                    "uyarilar": [k for k in ("duragan", "ruff_uyarilari",
                                                             "butce_uyarisi", "hafiza_uyarisi",
                                                             "durum_uyarisi") if rep.get(k)],
                                    "kullanim": rep.get("kullanim") or {}},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass

    def report(self) -> dict:
        """Sozlesme: yazilan_dosyalar, derleme_durumu, hatalar, tur_sayisi, sure, ozet (+ek)."""
        ev = self.events()
        rep = {"yazilan_dosyalar": [], "derleme_durumu": "bilinmiyor", "hatalar": [],
               "tur_sayisi": 0, "sure": round(time.time() - self.t0, 1), "ozet": "",
               "olcumler": [], "araclar": [], "play": None,
               "oturum": self.oturum, "is_id": self.id, "ortam": self.ortam,
               "kabul_kriterleri": self.kriterler, "is_klasoru": self.dir,
               "durum": "bitti" if self.done else "calisiyor"}
        got_result = False
        for e in ev:
            t = e.get("type")
            if t == "tool":
                rep["araclar"].append("%s %s" % (e.get("name"), e.get("detail") or ""))
            elif t == "tool_result" and e.get("name") in MEASURE_TOOLS:
                rep["olcumler"].append({"arac": e.get("name"), "sonuc": e.get("text", ""),
                                        "sure_s": e.get("sure")})
            elif t == "write":
                ek, sil = _diff_stat(e.get("before"), e.get("after") or "")
                icerik = e.get("after") or ""
                rep["yazilan_dosyalar"].append({
                    "yol": e.get("path"), "yeni": e.get("before") is None,
                    "eklendi": ek, "silindi": sil,
                    "satir": len(icerik.splitlines()),
                    # Denetci (ve Cursor'daki insan) ne yazildigini arac sonucunda gorsun.
                    "icerik": icerik if len(icerik) <= ICERIK_SINIRI else icerik[:ICERIK_SINIRI] + chr(10) + "… [kirpildi]"})
            elif t == "assistant":
                rep["ozet"] = e.get("text", "")
            elif t == "result":
                got_result = True
                errs = list(e.get("errors") or [])
                rep["hatalar"].extend(errs)
                rep["derleme_durumu"] = "derlendi" if not errs else "derleme_hatasi"
                rep["tur_sayisi"] = int(e.get("rounds", 0)) + 1
                rep["play"] = e.get("play")
                if e.get("kullanim"):
                    rep["kullanim"] = e["kullanim"]     # token/sure: Ollama'nin kendi sayaci
                if e.get("ruff"):
                    # uyaridir, hata degil: derleme_durumu'na dokunmaz; karari denetci verir
                    rep["ruff_uyarilari"] = e["ruff"]
                if e.get("duragan"):
                    rep["duragan"] = True       # isci ayni hatada kilitlendi; somut teshis SENDEN
                if e.get("butce_uyarisi"):
                    rep["butce_uyarisi"] = e["butce_uyarisi"]
                if e.get("hafiza_uyarisi"):
                    rep["hafiza_uyarisi"] = e["hafiza_uyarisi"]
                if e.get("durum_uyarisi"):
                    rep["durum_uyarisi"] = e["durum_uyarisi"]
                if e.get("play") and e["play"].get("hatalar"):
                    rep["hatalar"].extend("calisma zamani: " + h for h in e["play"]["hatalar"])
            elif t == "error":
                rep["hatalar"].append(e.get("message", ""))
                rep["derleme_durumu"] = "calistirilamadi"
        if self.done and got_result and not rep["ozet"]:
            # Olculdu: adim siniri dolunca isci nihai mesaj yazmadan bitti; denetci bunu
            # "sessiz basari" sanmasin.
            rep["hatalar"].append("isci nihai ozet yazmadi (adim siniri ya da bos cevap); "
                                  "araclar listesine ve olcumlere bak")
        if self.done and not got_result and rep["derleme_durumu"] == "bilinmiyor":
            rep["derleme_durumu"] = "calistirilamadi"
            rep["hatalar"].append("isci sonuc yazmadan cikti (kod %s); bkz. %s" % (
                self.code, os.path.join(self.dir, "stderr.txt")))
        rep["sure"] = round(time.time() - self.t0, 1)
        # Yazilan dosyalar: ayni yol birden cok kez yazildiysa son hali kalsin, ilk 'yeni' korunsun.
        merged: dict[str, dict] = {}
        for d in rep["yazilan_dosyalar"]:
            if d["yol"] in merged:
                m = merged[d["yol"]]
                m["eklendi"] += d["eklendi"]
                m["silindi"] += d["silindi"]
                m["satir"] = d["satir"]
                m["icerik"] = d["icerik"]        # HATA idi: ilk surum donuyordu, denetci bayat
                m["yazma"] = m.get("yazma", 1) + 1   # kac kez yazildi (onarim isareti)
            else:
                merged[d["yol"]] = dict(d)
        rep["yazilan_dosyalar"] = list(merged.values())
        return rep


JOBS: dict[str, Job] = {}
# MCP istek id'si -> is (iptal bildirimi gelince isciyi oldurmek icin). OLCULDU (Cursor):
# istemcinin arac zaman asimi (~2.5 dk) turdan kisa; iptal dinlenmeyince isci ZOMBI
# olarak devam etti ve ikinci cagriyla ayni dosyaya paralel yazdi.
REQ_JOBS: dict = {}

# Calisma koku (dagitilabilir tasarim: sabit yol YOK). Oncelik:
#   1. MCP roots: istemci (Cursor, Claude Code, VS Code) acik workspace'ini roots/list ile
#      bildirir - kullanici hicbir yol yazmaz.
#   2. APPRENTICE_WORKDIR_ROOT ortam degiskeni (roots desteklemeyen istemciler icin).
#   3. Sunucunun calisma dizini - YALNIZCA depo kokunun ALTINDAysa.
# calisma_dizini istege bagli ve koke GORELI; kok disina cikilamaz.
#
# OLCULDU (2026-08-23, Cursor + taklit istemci, uc senaryo):
#   A) roots var, hizli yanit          -> kok dogru (Desktop\Apprentice)
#   B) roots var, 3 sn gecikmeli yanit -> kok EV DIZINI   <- yaris
#   C) roots yok                       -> kok EV DIZINI   <- sessiz yedekleme
# Iki hata da hapishane kokunu tum ev dizini yapiyordu. B icin roots yaniti artik
# KISA SURE BEKLENIR; C icin cwd yedeklemesi kaldirildi - kok bilinmiyorsa istek
# REDDEDILIR ve hata denetciye "mutlak yol ver" der (denetci workspace yolunu bilir;
# Cursor olcumde tam bunu yapti). Sessizce ev dizinini kok yapmak, bu projede bir kez
# gercek zarar veren silme kazasinin ayni sinifi.
ROOTS: list = []
CLIENT_CAPS: dict = {}
_PENDING: dict = {}          # sunucu->istemci istekleri (roots/list) icin id -> yanit isleyici
_SRV_ID = [1000]


def _uri_to_path(uri: str) -> str:
    from urllib.parse import urlparse, unquote
    u = urlparse(uri)
    if u.scheme != "file":
        return ""
    p = unquote(u.path)
    if os.name == "nt" and p.startswith("/") and len(p) > 2 and p[2] == ":":
        p = p[1:]
    return os.path.realpath(p)


ROOTS_BEKLE_S = float(os.environ.get("APPRENTICE_ROOTS_BEKLE_S", "5"))
_ROOTS_HAZIR = threading.Event()


def calisma_koku(bekle: bool = True) -> str:
    """Workspace kokunu coz. bekle=True ise istemci roots bildirdiyse yanitini kisa
    sure bekler (yaris: istek gonderilip yanit beklenmeyince kok ev dizinine dusuyordu)."""
    if bekle and not ROOTS and CLIENT_CAPS.get("roots") is not None:
        _ROOTS_HAZIR.wait(ROOTS_BEKLE_S)
    for r in ROOTS:
        if r and os.path.isdir(r):
            return r
    env = os.environ.get("APPRENTICE_WORKDIR_ROOT", "")
    if env and os.path.isdir(env):
        return os.path.realpath(env)
    # cwd YEDEKLEMESI YOK: IDE sunucuyu ev dizininden baslatiyor (olculdu), o zaman
    # hapishane kokunu tum ev dizini yapardi. Yalnizca depo icindeysek kabul edilir.
    cwd = os.path.realpath(os.getcwd())
    kok_r = os.path.realpath(ROOT)
    if cwd != kok_r and cwd.startswith(kok_r + os.sep):
        return cwd
    return ""


def roots_iste():
    """Istemci roots destekliyorsa roots/list iste; yanit serve() icinde _PENDING ile islenir."""
    if not (CLIENT_CAPS.get("roots") is not None):
        _ROOTS_HAZIR.set()          # beklenecek bir sey yok
        return
    _ROOTS_HAZIR.clear()
    _SRV_ID[0] += 1
    rid = _SRV_ID[0]

    def al(res: dict):
        ROOTS[:] = [_uri_to_path(r.get("uri", "")) for r in (res or {}).get("roots", [])]
        _log("roots: %s" % ROOTS)
        _ROOTS_HAZIR.set()
    _PENDING[rid] = al
    _send({"jsonrpc": "2.0", "id": rid, "method": "roots/list", "params": {}})
_CUR_REQ = threading.local()


# ----------------------------------------------------------------------- on kosul
def _precheck(ortam: str) -> str:
    """Isciyi baslatmadan once acik bir sebep varsa onu dondur (bos = sorun yok)."""
    import urllib.request, urllib.error
    if "ollama" not in (ENVS.get(ortam, {}).get("on_kosul") or []):
        return ""
    ollama = (config.get("ollama.url") or "http://localhost:11434").rstrip("/")
    model = config.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model")
    try:
        with urllib.request.urlopen(ollama + "/api/tags", timeout=3) as r:
            names = [m.get("name") for m in json.load(r).get("models", [])]
    except Exception as e:
        return "Ollama'ya ulasilamadi (%s): %s" % (ollama, str(e)[:120])
    if model not in names:
        return "model yuklu degil: %s (ollama pull gerekli; yuklu: %s)" % (model, names)
    # Ortamin kendi koprusu (env.json "kopru": {"ayar": "<ad>.mcp_url", "ortam_degiskeni": "..."}).
    kopru = ENVS.get(ortam, {}).get("kopru")
    if kopru:
        url = _kopru_url(ortam)
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=3)
        except urllib.error.HTTPError as he:
            if he.code not in (400, 405, 406):
                return "%s koprusu beklenmeyen cevap: HTTP %d" % (ortam, he.code)
        except Exception as e:
            return "%s koprusune ulasilamadi (%s): %s - %s" % (
                ortam, url, str(e)[:100], kopru.get("ipucu", "ortamin sunucusu acik mi?"))
    return ""


def rapor_diskten(jid: str) -> dict | None:
    """Diskteki is klasorunden rapor derler (baska surecin isi). Sozlesmenin cekirdegi."""
    d = os.path.join(HOME, "jobs", jid)
    if not os.path.isdir(d):
        return None
    try:
        with open(os.path.join(d, "job.json"), encoding="utf-8") as f:
            job = json.load(f)
    except Exception:
        job = {"id": jid}
    rep = {"is_id": jid, "ortam": job.get("ortam"), "gorev": job.get("gorev", ""),
           "kaynak": job.get("kaynak", ""), "oturum": job.get("oturum", ""),
           "yazilan_dosyalar": [], "derleme_durumu": "calisiyor", "hatalar": [],
           "tur_sayisi": 0, "ozet": "", "araclar": [], "is_klasoru": d,
           "sure": round(time.time() - job.get("baslangic", time.time()), 1),
           "durum": "calisiyor", "diskten": True}
    icerik: dict = {}
    try:
        with open(os.path.join(d, "events.jsonl"), encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                t = e.get("type")
                if t == "tool":
                    rep["araclar"].append("%s %s" % (e.get("name"), e.get("detail") or ""))
                elif t == "write":
                    icerik[e.get("path")] = e.get("after") or ""
                elif t == "assistant":
                    rep["ozet"] = e.get("text", "")
                elif t == "result":
                    rep["derleme_durumu"] = "derlendi" if e.get("ok") else "derleme_hatasi"
                    rep["hatalar"] = e.get("errors") or []
                    rep["tur_sayisi"] = int(e.get("rounds", 0)) + 1
                    if e.get("kullanim"):
                        rep["kullanim"] = e["kullanim"]
                    for alan in ("duragan", "butce_uyarisi", "hafiza_uyarisi", "durum_uyarisi"):
                        if e.get(alan):
                            rep[alan if alan != "duragan" else "duragan"] = e[alan]
                    if e.get("ruff"):
                        rep["ruff_uyarilari"] = e["ruff"]
                elif t == "error":
                    rep["hatalar"].append(e.get("message", ""))
                    rep["derleme_durumu"] = "calistirilamadi"
                elif t == "exit":
                    rep["durum"] = "bitti"
    except OSError:
        pass
    rep["yazilan_dosyalar"] = [{"yol": y, "icerik": ic[:ICERIK_SINIRI],
                                "satir": ic.count(chr(10)) + 1}
                               for y, ic in icerik.items()]
    return rep


def _kopru_url(ortam: str) -> str:
    k = ENVS.get(ortam, {}).get("kopru") or {}
    return config.env_or(k.get("ortam_degiskeni", ""), k.get("ayar", ""), k.get("varsayilan", "")) or ""


def tool_worker_run(a: dict) -> dict:
    gorev = str(a.get("gorev") or "").strip()
    if not gorev:
        return {"hata": "gorev bos"}
    kriterler = a.get("kabul_kriterleri") or []
    if isinstance(kriterler, str):
        kriterler = [k for k in kriterler.splitlines() if k.strip()]
    ortam = str(a.get("ortam") or VARSAYILAN_ORTAM)
    if ortam not in ENVS:
        return {"hata": "bilinmeyen ortam %r; secenekler: %s" % (ortam, list(ENVS))}
    if not ENVS[ortam]["runner"]:
        return {"hata": "ortam %r planli, henuz yok" % ortam}
    workdir = str(a.get("calisma_dizini") or "")
    if ENVS.get(ortam, {}).get("kosucu") == "code_runner.py" or ortam == "code":
        kok = calisma_koku()
        # Kok bilinmiyorsa GORELI yol cozulemez. Eskiden cwd'ye dusuluyordu ve hapishane
        # kokunu tum ev dizini yapiyordu; artik reddedip denetciden mutlak yol istiyoruz.
        if not kok and not os.path.isabs(workdir):
            return {"hata": "Calisma koku belirlenemedi: istemcin acik workspace'ini MCP 'roots' "
                            "ile bildirmedi. Bu cagriyi 'calisma_dizini' alanina workspace'in "
                            "MUTLAK yolunu vererek tekrarla (sen bu yolu biliyorsun). "
                            "Kalici cozum: istemcide roots destegi ya da APPRENTICE_WORKDIR_ROOT."}
        if not workdir:
            workdir = kok
        elif not os.path.isabs(workdir):
            workdir = os.path.join(kok, workdir)
        if not os.path.isdir(workdir):
            return {"hata": "calisma_dizini yok: %s" % workdir}
        workdir = os.path.realpath(workdir)
        # Olculdu: IDE'nin acik klasoru sunucuyu kendiliginden SINIRLAMAZ; sinir burada.
        if kok and workdir != kok and not workdir.startswith(kok + os.sep):
            return {"hata": "calisma_dizini workspace kokunun disinda: %s (kok: %s)" % (workdir, kok)}
    sebep = _precheck(ortam)
    if sebep:
        return {"hata": sebep, "derleme_durumu": "calistirilamadi", "yazilan_dosyalar": [],
                "hatalar": [sebep], "tur_sayisi": 0, "sure": 0.0, "ozet": ""}
    dogrulama = str(a.get("dogrulama") or "tam")
    if dogrulama not in ("tam", "derleme"):
        return {"hata": "dogrulama 'tam' ya da 'derleme' olmali"}
    kapali_ek = ["run_tests", "run_shell"] if dogrulama == "derleme" else []
    job = Job(ortam, gorev, [str(k) for k in kriterler], str(a.get("oturum") or ""),
              bool(a.get("play", False)),
              int(a.get("onarim", config.get("onarim.compile_rounds", 3))),
              config.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model"),
              _kopru_url(ortam), workdir,
              list(a.get("araclar_kapali") or []) + kapali_ek, dogrulama,
              a.get("yazilabilir") or [], bool(a.get("harita", False)),
              bool(a.get("canli", False)))
    JOBS[job.id] = job
    rid = getattr(_CUR_REQ, "id", None)
    if rid is not None:
        REQ_JOBS[rid] = job
    job.start()
    if not a.get("bekle", True):
        rep = job.report()
        rep["hatalar"].append("bekle=false: is arka planda; worker_status(is_id) ile sor")
        return rep
    limit = float(a.get("zaman_asimi_s") or DEFAULT_TIMEOUT_S)
    token = getattr(_CUR_REQ, "progress", None)
    gonderilen = 0
    while not job.done and time.time() - job.t0 < limit:
        time.sleep(0.5)
        # Canli akis: yeni olaylari notifications/progress (+ logging) ile istemciye gonder.
        ev = job.events()
        if len(ev) > gonderilen:
            for e in ev[gonderilen:]:
                msg = _olay_metni(e)
                if msg:
                    _progress(token, len(ev), msg)
            gonderilen = len(ev)
        if getattr(job, "iptal", False):
            break
    rep = job.report()
    job.usta_rapor_isaretle(rep)
    if getattr(job, "iptal", False):
        rep["derleme_durumu"] = "iptal"
        rep["hatalar"].append("istemci cagriyi iptal etti (zaman asimi?); isci durduruldu. "
                              "Uzun turlar icin bekle=false + worker_status kullan.")
        return rep
    if not job.done:
        job.kill()
        msg = "zaman asimi (%.0f s): isci durduruldu; olaylar %s" % (limit, job.events_path)
        rep["derleme_durumu"] = "zaman_asimi"
        rep["hatalar"].append(msg)
        # Olay dosyasini kapat ki izleyiciler (clients/web) isi sonsuza kadar "calisiyor" gormesin.
        try:
            with open(job.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "error", "message": msg}, ensure_ascii=False) + "\n")
                f.write(json.dumps({"type": "exit", "code": -9}) + "\n")
        except Exception:
            pass
    return rep


TOOLS = [
    {"name": "worker_run",
     "description": (
         "Yerel isci modele (Ollama, Qwen3-Coder-Next) bir gorev yaptirir ve DOGRULANMIS "
         "sonucu dondurur. Sen denetcisin: gorevi ve KABUL KRITERLERINI sen yazarsin "
         "(somut, olculebilir; isci kriter uretmekte zayif). Donus: yazilan_dosyalar "
         "(+/- satir), derleme_durumu (derlendi | derleme_hatasi | calistirilamadi | "
         "zaman_asimi), hatalar, tur_sayisi, sure, ozet (iscinin kendi anlatimi), olcumler "
         "(play_observe vb. HAM ciktilar), oturum. 'derlendi' yalnizca derleyici onayidir; "
         "kriterlerin saglanip saglanmadigina olcumlere bakarak SEN karar verirsin, "
         "olcumu ozetleyip ayni 'oturum' ile duzeltme istetirsin (baglam korunur). "
         "Bir tur 60-300 s surer, play ile daha uzun; istemci arac zaman asimini buna gore ayarla."),
     "inputSchema": {
         "type": "object",
         "properties": {
             "gorev": {"type": "string", "description": "Ne yapilacak, duz dille. Dosya/obje adlarini ver."},
             "kabul_kriterleri": {"type": "array", "items": {"type": "string"},
                                  "description": "Denetcinin yazdigi somut kriterler, her biri tek cumle."},
             "ortam": {"type": "string", "enum": [e for e in ENVS if not ENVS[e].get("gizli")] or list(ENVS),
                       "default": VARSAYILAN_ORTAM,
                       "description": "Arac seti + dogrulayici. " + "; ".join("%s: %s" % (k, v.get("aciklama", "")) for k, v in ENVS.items() if not v.get("gizli"))},
             "calisma_dizini": {"type": "string", "description": "code ortami: workspace kokune GORELI alt klasor (bos = kokun kendisi). Kok, istemcinin bildirdigi workspace'tir (MCP roots); disina cikilamaz."},
             "dogrulama": {"type": "string", "enum": ["tam", "derleme"], "default": "tam",
                           "description": "tam: isci testleri de kosar, ham test ciktisi doner (buyuk donus). "
                                          "derleme: isci YALNIZCA yazar - test/shell araclari kapali, harness test "
                                          "kosmaz, olcum donmez; kodu SEN okuyup onaylarsin ya da hatasini soylersin."},
             "harita": {"type": "boolean", "default": False,
                        "description": "true: calisma dizininin sembol haritasi (dosya -> fonksiyon/sinif) "
                                       "iscinin sistem istemine eklenir. Hedef dosyanin YERINI bilmedigin "
                                       "iste ise yarar; kucuk/adresli iste harita baglami bosuna sisirir."},
             "canli": {"type": "boolean", "default": False,
                       "description": "true: isci arac cagrilarini XML-icerik protokoluyle yapar, "
                                      "uretim token token canli.txt'ye akar (izle.py daktilo gosterir). "
                                      "Native tool yolu yerine gecer; kalite A/B'si tests/canli_ab.py."},
             "yazilabilir": {"type": "array", "items": {"type": "string"},
                             "description": "Yazma izni verilen dosyalarin TAM listesi (calisma dizinine goreli). "
                                            "Verilirse baska dosyaya yazma REDDEDILIR. Olculdu: 'yalnizca X yaz' "
                                            "kriteri metin olarak yeterli degil - dama gorevinde isci 11 dosya yazdi."},
             "araclar_kapali": {"type": "array", "items": {"type": "string"},
                                "description": "Bu turda isciden saklanacak arac adlari (orn. [\"play_observe\"]: olcumu denetci yapar, isci olcum-duzeltme dongusune giremez)."},
             "oturum": {"type": "string", "description": "Onceki worker_run'in 'oturum' degeri: isci ayni baglamla devam eder. Bos = yeni oturum."},
             "play": {"type": "boolean", "default": False,
                      "description": "Ortama ozgu ek calisma-zamani dogrulamasi (ortam destekliyorsa; ornegin bir motor eklentisinde play modu)."},
             "onarim": {"type": "integer", "default": 3, "description": "Azami derleme onarim turu."},
             "zaman_asimi_s": {"type": "number", "default": DEFAULT_TIMEOUT_S},
         },
         "required": ["gorev", "kabul_kriterleri"],
     }},
]
def _olay_metni(e: dict) -> str:
    t = e.get("type")
    if t == "tool":
        return "arac: %s %s" % (e.get("name"), (e.get("detail") or "")[:80])
    if t == "write":
        icerik = e.get("after") or ""
        return "yazdi: %s (%d satir)%s" % (e.get("path"), len(icerik.splitlines()),
                                          "" if e.get("before") is None else " [degisti]")
    if t == "tool_result" and e.get("name") in ("run_tests", "validate_script", "play_observe", "read_console"):
        return "%s -> %s" % (e.get("name"), (e.get("text") or "")[:200].replace(chr(10), " "))
    if t == "assistant":
        return "isci ozeti: " + (e.get("text") or "")[:300].replace(chr(10), " ")
    if t == "result":
        return "sonuc: %s, onarim turu %s, %s s" % ("derlendi" if e.get("ok") else "hata", e.get("rounds"), e.get("wall"))
    if t == "error":
        return "hata: " + (e.get("message") or "")[:200]
    return ""


def _progress(token, n: int, msg: str):
    """MCP ilerleme + log bildirimi. Cursor/Claude Code arac kutusunda canli gosterir."""
    if token is not None:
        _send({"jsonrpc": "2.0", "method": "notifications/progress",
               "params": {"progressToken": token, "progress": n, "message": msg}})
    _send({"jsonrpc": "2.0", "method": "notifications/message",
           "params": {"level": "info", "logger": "apprentice", "data": msg}})


def tool_worker_status(a: dict) -> dict:
    jid = str(a.get("is_id") or "")
    job = JOBS.get(jid)
    if job is None:
        # DISK YEDEGI (2026-08-24): baska surecten (web paneli, olcum betigi) baslatilan
        # isler bu surecin JOBS sozlugunde yoktur ama diskte durur - usta yine gorebilsin.
        r = rapor_diskten(jid)
        if r is not None:
            return r
        return {"hata": "bilinmeyen is_id %r (bu surecte: %s)" % (jid, list(JOBS)[-5:])}
    if a.get("durdur"):
        job.kill()
    rep = job.report()
    job.usta_rapor_isaretle(rep)
    return rep


TOOLS.append(
    {"name": "worker_status",
     "description": ("bekle=false ile baslatilan ya da istemci zaman asimina ugrayan bir worker_run "
                     "isinin raporu (calisiyor/bitti). durdur=true isciyi oldurur. Olculdu: Cursor'in "
                     "arac zaman asimi bir turdan kisa; orada worker_run(bekle=false) + bu aracla yokla."),
     "inputSchema": {"type": "object",
                     "properties": {"is_id": {"type": "string"}, "durdur": {"type": "boolean", "default": False}},
                     "required": ["is_id"]}})
TOOLS[0]["inputSchema"]["properties"]["bekle"] = {
    "type": "boolean", "default": True,
    "description": "false: hemen is_id ile don, worker_status ile sor (istemci zaman asimi kisaysa)."}

def _panel_bildirimleri_al() -> list:
    """HOME/panel_bekleyen.json: panelin biraktigi is kimlikleri; oku ve bosalt."""
    p = os.path.join(HOME, "panel_bekleyen.json")
    try:
        with open(p, encoding="utf-8") as f:
            b = json.load(f)
        os.remove(p)
        return [str(x) for x in b][:10]
    except Exception:
        return []


HANDLERS = {"worker_run": tool_worker_run, "worker_status": tool_worker_status}


# ------------------------------------------------------------------ JSON-RPC/stdio
_lock = threading.Lock()


def _send(obj: dict):
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    with _lock:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def _log(msg: str):
    sys.stderr.write("[apprentice] %s\n" % msg)
    sys.stderr.flush()


def handle(req: dict) -> dict | None:
    m, rid, p = req.get("method"), req.get("id"), req.get("params") or {}
    if m == "initialize":
        CLIENT_CAPS.clear()
        CLIENT_CAPS.update(p.get("capabilities") or {})
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": p.get("protocolVersion") or PROTOCOL,
            "capabilities": {"tools": {}, "logging": {}}, "serverInfo": SERVER_INFO}}
    if m == "notifications/cancelled":
        job = REQ_JOBS.pop(p.get("requestId"), None)
        if job is not None and not job.done:
            job.iptal = True
            job.kill()
            _log("iptal: is %s olduruldu (istek %s)" % (job.id, p.get("requestId")))
            try:
                with open(job.events_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"type": "error", "message": "istemci iptal etti"}) + "\n")
            except Exception:
                pass
        return None
    if m == "notifications/initialized":
        roots_iste()
        return None
    if m == "notifications/roots/list_changed":
        roots_iste()
        return None
    if m in ("ping", "logging/setLevel"):
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if m == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if m == "tools/call":
        name = p.get("name")
        fn = HANDLERS.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32602, "message": "bilinmeyen arac %r" % name}}
        try:
            out = fn(p.get("arguments") or {})
        except Exception as e:  # noqa: BLE001
            out = {"hata": "%s: %s" % (type(e).__name__, e)}
        # PANEL BILDIRIMI: web panelinden gonderilen isler kutuya yazilir; usta bir sonraki
        # HER arac cagrisinda gorur (MCP'de sunucu ustayi kendiliginden uyandiramaz - bu
        # durust kanal). Okununca kutu bosaltilir.
        if isinstance(out, dict):
            b = _panel_bildirimleri_al()
            if b:
                out["panel_bildirimi"] = ("Web panelinden %d is gonderildi - worker_status(is_id) "
                                          "ile incele: %s" % (len(b), ", ".join(b)))
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}],
            "structuredContent": out,
            "isError": bool(isinstance(out, dict) and out.get("hata"))}}
    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "yok: %s" % m}}


def serve():
    os.makedirs(HOME, exist_ok=True)
    _log("hazir; ev=%s ayar=%s" % (HOME, config.source()))
    stdin = sys.stdin.buffer
    while True:
        line = stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line.decode("utf-8"))
        except Exception:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue

        # Sunucunun kendi istegine (roots/list) gelen YANIT: method yok, id bizde kayitli.
        if "method" not in req and req.get("id") in _PENDING:
            try:
                _PENDING.pop(req["id"])(req.get("result") or {})
            except Exception as e:
                _log("roots yaniti islenemedi: %s" % e)
            continue

        def run(r=req):
            _CUR_REQ.id = r.get("id")
            _CUR_REQ.progress = ((r.get("params") or {}).get("_meta") or {}).get("progressToken")
            resp = handle(r)
            REQ_JOBS.pop(r.get("id"), None)
            if resp is not None:
                _send(resp)
        # Uzun suren tools/call, ping gibi istekleri bloklamasin.
        if req.get("method") == "tools/call":
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
    for j in JOBS.values():
        j.kill()


if __name__ == "__main__":
    serve()
