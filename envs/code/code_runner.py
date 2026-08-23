"""Genel kod ortami: dosya oku/yaz, shell, test.

Sunucu (server/apprentice_server.py) bunu panel_runner ile AYNI komut satiri ve AYNI
olay semasiyla ayrik surecte kosturur; tek fark --workdir (calisma dizini, hapis koku).

Dogrulayici: her turdan sonra (1) yazilan .py dosyalari derlenir (py_compile, "derleyici"
karsiligi), (2) calisma dizininde test varsa pytest (yoksa stdlib unittest) kosar. Hata varsa
modele geri verilir, --repairs kadar onarim turu. Basari = derleme temiz + pytest gecti
(test yoksa derleme temiz). Modelin beyani degil.

Hapis: butun yollar --workdir altinda kalmak zorunda; disari cikan yol reddedilir.
Silme araci YOK (olculdu: silme yetkisi bir kez gercek zarar verdi). Shell komutu calisma dizininde,
zaman asimi 120 s, cikti kirpilir.

Olay semasi: butun ortam kosuculariyla ayni (system/tool/tool_result/write/
assistant/result/exit). Sohbet baglami <session-dir>/<session>.json (schema 1).
"""
from __future__ import annotations
import argparse, glob, json, os, subprocess, sys, time

_BURASI = os.path.dirname(os.path.abspath(__file__))
_KOK = os.path.dirname(os.path.dirname(_BURASI))
for _p in (_BURASI, _KOK):
    if _p not in sys.path:
        sys.path.insert(0, _p)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core.client import run_agent
from core.guard import guarded_dispatch
from core import config as CFG

DEFAULT_MODEL = CFG.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model",
                           "hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL")
NUM_CTX = CFG.env_or(["APPRENTICE_CTX", "UNITY_CODE_CTX"], "makine.num_ctx", 65536, int)
NUM_BATCH = CFG.env_or(["APPRENTICE_BATCH", "UNITY_CODE_BATCH"], "makine.num_batch", 4096, int)
MAX_READ = 60000
MAX_OUT = 8000
SHELL_TIMEOUT = 120


def _has_pytest() -> bool:
    try:
        import pytest  # noqa: F401
        return True
    except Exception:
        return False


# pytest kuruluysa o; degilse stdlib unittest (ek paket yok ilkesi). Model de bunu bilir.
HAS_PYTEST = _has_pytest()
# -B: pyc yazma. Olculdu: ayni saniyede ayni boyutta yeniden yazilan dosya icin Python
# bayat pyc'yi kullandi (mtime+boyut ayni) ve duzeltilmis test eski haliyle kostu.
TEST_CMD = ([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"] if HAS_PYTEST
            else [sys.executable, "-B", "-m", "unittest", "discover", "-v"])
TEST_ADI = "pytest" if HAS_PYTEST else "unittest"

# "tam": derleme + test kosulur (varsayilan). "derleme": yalnizca derlenir; isci test kosmaz,
# olcum uretilmez - dogrulamayi denetci yapar (kucuk donus, kucuk baglam).
DOGRULAMA = os.environ.get("APPRENTICE_DOGRULAMA", "tam")
# Yazma izni listesi (denetci verir). OLCULDU: "yalnizca X.py yaz" kriteri islevsel kalitede
# tutuluyor ama DISIPLINDE tutulmuyor - dama gorevinde 11 dosya yazildi (10'u istenmeyen .bat/.sh).
# Kriter metni yetmiyor; sinir araca konuluyor.
YAZILABILIR = [x.strip() for x in os.environ.get("APPRENTICE_YAZILABILIR", "").split(",") if x.strip()]

TEST_SATIRI_TAM = ("- Testleri run_tests ile kosarsin ({test}; test dosyalari test_*.py, "
                   "unittest.TestCase siniflari her iki kosucuda da calisir). Komutlari "
                   "run_shell ile calistirirsin (120 sn sinir).\n")
TEST_SATIRI_DERLEME = ("- BU TURDA TEST KOSUCUSU YOK. Kodu yaz; dogru ve derlenir olmasi yeterli. "
                       "Test dosyasi istenmediyse yazma, komut calistirma. Dogrulamayi DENETCI "
                       "yapacak: yazdigin kodu okuyacak. Bu yuzden okunur yaz ve nihai mesajinda "
                       "ne yaptigini kisa ve somut anlat.\n")

SYSTEM = (
    "Sen bir yazilim gelistiricisisin. Calisma dizini: {dir}\n"
    "- Dosya yollari calisma dizinine gorelidir; disina cikamazsin, silemezsin.\n"
    "- Var olan dosyayi degistirecegin zaman once read_file ile oku, sonra write_file ile "
    "TAM yeni icerigi yaz. Kismi yama yapma.\n"
    "{test_satiri}"
    "- Derleme ya da test hatasi bildirilirse ilgili dosyayi oku, sebebi bul, duzeltilmis "
    "TAM dosyayi yaz.\n"
    "- Tur basina tek arac cagir. Bittiginde kisaca Turkce ozetle: ne yazdin, testler "
    "ne dedi."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Dosyayi oku (calisma dizinine goreli yol).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Dosyayi TAM icerikle yaz (yoksa olusturur, klasorleri acar).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "contents": {"type": "string"}},
            "required": ["path", "contents"]}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "Calisma dizinindeki dosyalari listele (glob, varsayilan '**/*').",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "Calisma dizininde bir komut calistir; stdout+stderr ve cikis kodu doner.",
        "parameters": {"type": "object", "properties": {
            "cmd": {"type": "string"}}, "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "ara",
        "description": "Kod tabaninda anlamsal arama: ne aradigini duz dille yaz (orn 'kupon "
                       "indirimi nerede uygulaniyor'), en yakin kod parcalarini dosya+satir "
                       "araligiyla doner. Buyuk projede dosyalari korlemesine OKUMADAN once bunu "
                       "kullan; sonra yalnizca ilgili dosyayi read_file ile oku.",
        "parameters": {"type": "object", "properties": {
            "sorgu": {"type": "string", "description": "aranan davranis/kavram, duz dille"}},
            "required": ["sorgu"]}}},
    {"type": "function", "function": {
        "name": "run_tests",
        "description": "Testleri calistir (%s); sonucu ve cikis kodunu doner." % TEST_ADI,
        "parameters": {"type": "object", "properties": {
            "args": {"type": "string", "description": "istege bagli: test dosyasi/modulu "
                     "(orn 'test_x.py' ya da 'tests/test_x.py') veya ek %s argumani. "
                     "Bos birakirsan tum testler kosar - kabul olcumu budur." % TEST_ADI}},
            "required": []}}},
]


class Jail:
    def __init__(self, root: str):
        self.root = os.path.realpath(root)

    def path(self, p: str) -> str:
        full = os.path.realpath(os.path.join(self.root, p or ""))
        if full != self.root and not full.startswith(self.root + os.sep):
            raise ValueError("yol calisma dizini disinda: %s" % p)
        return full


def shell(cmd: list | str, cwd: str, timeout: int = SHELL_TIMEOUT) -> dict:
    t0 = time.time()
    try:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True,
                           timeout=timeout, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, env=env)
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        return {"exit": r.returncode, "out": out[-MAX_OUT:], "sure": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {"exit": -1, "out": "zaman asimi (%d s)" % timeout, "sure": timeout}


NOOP = {"n": 0}      # ust uste kac kez ayni icerik yazilmaya calisildi


def make_dispatch(jail: Jail, written: list, em):
    def d(name: str, args: dict):
        args = args if isinstance(args, dict) else {}
        detail = str(args.get("path") or args.get("cmd") or args.get("pattern") or args.get("args") or "")[:140]
        em.emit("tool", name=name, detail=detail,
                args={k: (v if len(str(v)) <= 4000 else str(v)[:4000] + " …")
                      for k, v in args.items() if not (name == "write_file" and k == "contents")})
        t0 = time.time()
        try:
            out = _run(jail, written, em, name, args)
        except Exception as e:  # noqa: BLE001
            out = {"error": "%s: %s" % (type(e).__name__, e)}
        metin = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1)
        if name == "read_file" and isinstance(out, dict) and "contents" in out:
            metin = "%d karakter okundu" % len(out["contents"])
        em.emit("tool_result", name=name, text=metin[:6000] + (" …" if len(metin) > 6000 else ""),
                sure=round(time.time() - t0, 1))
        return out
    return d


def _run(jail: Jail, written: list, em, name: str, a: dict):
    if name == "read_file":
        p = jail.path(a.get("path", ""))
        if not os.path.isfile(p):
            return {"error": "dosya yok: %s" % a.get("path")}
        with open(p, encoding="utf-8", errors="replace") as f:
            s = f.read()
        return {"path": a.get("path"), "contents": s[:MAX_READ],
                "kirpildi": len(s) > MAX_READ}
    if name == "write_file":
        p = jail.path(a.get("path", ""))
        rel = os.path.relpath(p, jail.root).replace("\\", "/")   # olaylarda daima goreli yol
        if YAZILABILIR and rel not in YAZILABILIR:
            return {"error": "yazma izni yok: %s. Bu iste yalnizca su dosyalar yazilabilir: %s"
                             % (rel, ", ".join(YAZILABILIR))}
        before = None
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                before = f.read()
        # BOS YAZMA KORUMASI (olculdu 2026-08-23): dogrulama="derleme" kipinde test/shell araci
        # olmadigi icin model "kontrol etmek" ister gibi AYNI icerigi 10 kez yazdi; 880 s ve
        # 150k token yandi, adim siniri doldu, ozet yazilamadi. Ayni icerik artik yazma sayilmaz
        # ve modele acikca "degismedi, bittiyse ozetle" denir.
        if before is not None and before == str(a.get("contents") or ""):
            NOOP["n"] += 1
            uyari = ("AYNI ICERIK: %s zaten birebir bu haldeydi, hicbir sey degismedi. "
                     "Tekrar yazma. Yapacak baska bir sey kaldiysa onu yap; kalmadiysa ARAC CAGIRMA "
                     "ve tek mesajla ozetle." % rel)
            if NOOP["n"] >= 2:
                uyari += (" [%d kez ust uste bos yazma yaptin - dosya hazir. SIMDI OZETLE.]" % NOOP["n"])
            return {"ok": True, "path": rel, "degisiklik": False, "uyari": uyari}
        NOOP["n"] = 0
        os.makedirs(os.path.dirname(p) or jail.root, exist_ok=True)
        contents = str(a.get("contents") or "")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(contents)
        written.append(rel)
        em.emit("write", path=rel, before=before, after=contents)
        sonuc = {"ok": True, "path": rel, "bytes": len(contents.encode("utf-8"))}
        # ANINDA DERLEME KANITI (2026-08-23): "derlendi" bilgisi modelin duracagi anda elinde
        # olsun diye yazim cevabina konur. Turdan sonraki onarim dongusu yine kosar; bu, modele
        # "bittin mi?" kararini kanitla verdirmek icin. (Tetris olayi: kanitsiz model ayni
        # dosyayi 10 kez yazdi - dur sinyali iddiayla degil derleyiciyle gelir.)
        if rel.endswith(".py"):
            try:
                compile(contents, rel, "exec")
                sonuc["derleme"] = "temiz - bu dosyada yapacak is kalmadiysa tekrar yazma"
            except SyntaxError as e:
                sonuc["derleme"] = "HATA %s satir %s: %s" % (rel, e.lineno, e.msg)
            # RUFF KANITI (2026-08-24): compile() yalniz sozdizimi gorur; F-sinifi hatalar
            # (tanimsiz isim, kullanilmayan/eksik import) derlenir ama calisirken patlar.
            # ruff bunlari milisaniyede "dosya:satir: kod mesaj" formatinda verir - isciye
            # giden sinyal hata-izi kivaminda kalir. Yoksa/patlarsa sessizce atlanir.
            uyarilar = ruff_uyarilari(jail, rel)
            if uyarilar:
                sonuc["ruff"] = uyarilar
        return sonuc
    if name == "list_files":
        pat = a.get("pattern") or "**/*"
        out = []
        for p in glob.glob(os.path.join(jail.root, pat), recursive=True):
            if os.path.isfile(p) and not any(x in p for x in ("__pycache__", os.sep + ".git" + os.sep, ".pytest_cache")):
                out.append(os.path.relpath(p, jail.root).replace("\\", "/"))
        return {"files": sorted(out)[:500], "sayi": len(out)}
    if name == "ara":
        from core import rag
        try:
            return rag.ara(jail.root, str(a.get("sorgu") or ""))
        except RuntimeError as e:
            return {"error": str(e)}
    if name == "run_shell":
        cmd = str(a.get("cmd") or "")
        # Silme yasagi shell uzerinden delinmesin; push disariya cikistir.
        yasak = ("git push", "rm -rf", "rm -r ", "rmdir", "del ", "erase ", "Remove-Item",
                 "shutil.rmtree", "os.remove", "git reset --hard", "git clean")
        vur = [y for y in yasak if y.lower() in cmd.lower()]
        if vur:
            return {"error": "komut reddedildi (%s): silme ve push bu ortamda yok" % ", ".join(vur)}
        return shell(cmd, jail.root)
    if name == "run_tests":
        return shell(_test_cmd(str(a.get("args") or "")), jail.root)
    return {"error": "bilinmeyen arac %r" % name}


def _test_cmd(args: str) -> list:
    """run_tests komutunu kur.

    OLCULDU (2026-08-23, Cursor turu): isci makul bicimde run_tests(args="test_x.py")
    cagirdi; TEST_CMD pytest yoksa "unittest discover" oldugu icin ilk konumsal arguman
    BASLANGIC DIZINI sayildi -> "Start directory is not importable: 'test_x.py'". Isci
    ayni testi run_shell ile kosup gecti gordu ve "testler gecti" dedi; resmi olcum
    kirmizi kaldi. Yani sahte bir beyan-olcum celiskisi URETTIK - mimarinin dayandigi
    sinyali kirletir. unittest'te dosya/yol argumani modul adina cevrilir.
    """
    ek = [x for x in args.split() if x]
    if not ek or HAS_PYTEST:
        return TEST_CMD + ek                      # pytest dosya yolunu zaten anlar

    moduller, bayraklar = [], []
    for x in ek:
        if x.startswith("-"):
            bayraklar.append(x)
            continue
        y = x.replace("\\", "/").strip("/")
        if y.endswith(".py"):
            y = y[:-3]
        moduller.append(y.replace("/", "."))

    if not moduller:
        return TEST_CMD + bayraklar
    # discover DEGIL: modul adiyla dogrudan kosulur.
    return [x for x in TEST_CMD if x != "discover"] + bayraklar + moduller


# ----------------------------------------------------------------- dogrulayici
RUFF_KAPALI = os.environ.get("APPRENTICE_RUFF", "1") == "0"     # olcum icin kapatilabilir


def ruff_uyarilari(jail: Jail, rel: str, sinir: int = 8) -> list:
    """Yazilan dosyada F-sinifi (pyflakes) + E9 bulgulari. ruff yoksa bos doner.

    Yalniz F ve E9 secilir: uslup kurallari (E/W geri kalani) bilerek DISARIDA -
    olculdu: uslup geri bildirimi modele islemiyor, gurultu olarak baglami sisirir.
    """
    if RUFF_KAPALI:
        return []
    try:
        r = subprocess.run([sys.executable, "-m", "ruff", "check", "--select", "F,E9",
                            "--output-format", "concise", "--no-cache", rel],
                           cwd=jail.root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
    except Exception:                                            # noqa: BLE001 - ruff yok/patladi
        return []
    if r.returncode not in (0, 1):                               # 2 = kullanim hatasi
        return []
    out = [s.strip() for s in (r.stdout or "").splitlines()
           if s.strip() and not s.startswith(("Found ", "All checks passed"))]
    if len(out) > sinir:
        out = out[:sinir] + ["... ve %d uyari daha" % (len(out) - sinir)]
    return out


def compile_errors(jail: Jail, written: list) -> list:
    errs = []
    for rel in dict.fromkeys(written):
        if not rel.endswith(".py"):
            continue
        try:
            with open(jail.path(rel), encoding="utf-8", errors="replace") as f:
                compile(f.read(), rel, "exec")      # pyc yazmaz (py_compile yazar)
        except SyntaxError as e:
            errs.append("%s(%s): %s: %s" % (rel, e.lineno, type(e).__name__, e.msg)[:300])
        except Exception as e:  # noqa: BLE001
            errs.append("%s: %s" % (rel, e))
    return errs


def has_tests(root: str) -> bool:
    return bool(glob.glob(os.path.join(root, "**", "test_*.py"), recursive=True) or
                glob.glob(os.path.join(root, "**", "*_test.py"), recursive=True))


def test_errors(jail: Jail) -> list:
    if not has_tests(jail.root):
        return []
    r = shell(TEST_CMD, jail.root)
    if r["exit"] == 0:
        return []
    return ["%s cikis %s:\n%s" % (TEST_ADI, r["exit"], r["out"][-2500:])]


def one_request(jail: Jail, dispatch, written: list, msgs: list, request: str,
                model: str, max_repairs: int, tools: list | None = None) -> dict:
    tools = tools if tools is not None else TOOLS
    msgs.append({"role": "user", "content": request})
    t0 = time.time()
    rounds = 0
    errs: list = []
    from core.client import Metrics
    kullanim = Metrics()            # olcum: toplam prompt/uretim tokeni ve sureleri (Ollama sayar)
    adim_sayisi = 0
    while True:
        res = run_agent(msgs, tools, dispatch, max_steps=12, model=model, think=False,
                        num_ctx=NUM_CTX, temperature=0.0, num_predict=6000, retries=2,
                        extra_options={"num_batch": NUM_BATCH})
        kullanim.merge(res.metrics); adim_sayisi += len(res.turns)
        msgs[:] = res.messages
        errs = compile_errors(jail, written)
        if not errs and DOGRULAMA == "tam":
            errs = test_errors(jail)
        if not errs or rounds >= max_repairs:
            break
        rounds += 1
        msgs.append({"role": "user", "content":
                     "DOGRULAMA HATASI:\n" + "\n".join(errs[:6]) +
                     "\nIlgili dosyayi read_file ile oku, sebebi bul ve write_file ile "
                     "duzeltilmis TAM dosyayi yaz."})
    k = kullanim.as_dict(); k["model_cagrisi"] = adim_sayisi
    return {"errors": errs, "rounds": rounds, "wall": time.time() - t0,
            "text": res.final_text or "", "stopped": res.stopped, "error": res.error,
            "kullanim": k}


# ---------------------------------------------------------------------- CLI
class Emitter:
    def __init__(self, path: str):
        self.path = path
        with open(path, "w", encoding="utf-8"):
            pass

    def emit(self, kind: str, **kw):
        rec = {"type": kind}
        rec.update(kw)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass


def load_session(d: str, sid: str) -> list:
    p = os.path.join(d, "%s.json" % sid)
    try:
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        return j.get("messages", []) if j.get("schema") == 1 else []
    except Exception:
        return []


def save_session(d: str, sid: str, msgs: list, model: str):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "%s.json" % sid), "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "model": model, "updated": time.time(), "messages": msgs}, f,
                  ensure_ascii=False)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--jsonl", required=True)
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--session-dir", default=os.path.join(_KOK, ".apprentice", "sessions", "code"))
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--url", default="", help="kullanilmaz (panel_runner ile uyum)")
    p.add_argument("--repairs", type=int, default=3)
    p.add_argument("--play", action="store_true", help="kullanilmaz")
    p.add_argument("--play-repairs", type=int, default=2, help="kullanilmaz")
    p.add_argument("--workdir", default=os.getcwd(), help="calisma dizini (hapis koku)")
    a = p.parse_args()

    em = Emitter(a.jsonl)
    code = 1
    try:
        with open(a.prompt_file, encoding="utf-8") as f:
            request = f.read().strip()
        if not request:
            em.emit("error", message="bos istek")
            return 1
        if not os.path.isdir(a.workdir):
            em.emit("error", message="calisma dizini yok: %s" % a.workdir)
            return 1
        jail = Jail(a.workdir)
        em.emit("system", subtype="init", model=a.model, session_id=a.session, workdir=jail.root)

        # Proje hafizasi: calisma dizinindeki HAFIZA.md (usta yazar: proje kurallari, gecmis
        # dersler). Varsa sistem istemine eklenir, 3000 karakterle kirpilir.
        hafiza = ""
        hp = os.path.join(jail.root, "HAFIZA.md")
        if os.path.isfile(hp):
            try:
                with open(hp, encoding="utf-8", errors="replace") as f:
                    hafiza = f.read().strip()[:3000]
            except OSError:
                pass
        written: list = []
        kapali = [k.strip() for k in os.environ.get("APPRENTICE_TOOLS_OFF", "").split(",") if k.strip()]
        tools = [t for t in TOOLS if t["function"]["name"] not in kapali]
        if kapali:
            em.emit("system", subtype="tools_off", tools=kapali)
        dispatch = guarded_dispatch(tools, make_dispatch(jail, written, em))
        msgs = load_session(a.session_dir, a.session)
        if not msgs:
            sistem = SYSTEM.format(dir=jail.root, test=TEST_ADI,
                test_satiri=(TEST_SATIRI_TAM.format(test=TEST_ADI) if DOGRULAMA == "tam" else TEST_SATIRI_DERLEME))
            if hafiza:
                sistem += "\n\nPROJE HAFIZASI (bu projenin kurallari ve gecmis dersleri; UY):\n" + hafiza
            # PROJE HARITASI (2026-08-24, OpenMemory'nin MAP fikri): hedefin YERI bilinmeyen
            # iste isci adressiz kaliyordu (olculdu: 120 dosyayi sirayla okuyup coktu).
            # Harita "dosya -> semboller" adresini sifir sorguyla verir; denetci acar (harita=true).
            if os.environ.get("APPRENTICE_HARITA") == "1":
                try:
                    from core import harita as HARITA
                    sistem += "\n\n" + HARITA.uret(jail.root)[:16000] + \
                              "\nHaritadaki adresi kullan: once ilgili dosyayi read_file ile oku."
                except Exception as e:                           # noqa: BLE001 - harita cokse is surer
                    em.emit("system", subtype="harita_hatasi", error=str(e)[:200])
            msgs = [{"role": "system", "content": sistem}]
        r = one_request(jail, dispatch, written, msgs, request, a.model, a.repairs, tools)
        save_session(a.session_dir, a.session, msgs, a.model)
        if r["text"]:
            em.emit("assistant", text=r["text"])
        errs = list(r["errors"])
        if r.get("error"):
            errs.append("model dongusu: %s" % r["error"])
        # Ruff bulgulari USTAYA da gider: olculdu (2026-08-24, ruff_ab) - isci uyariyla yeni
        # kodu temiz yaziyor ama MEVCUT tohum hataya "davranisi koru" diye dokunmuyor; o karar
        # ustanin. Hata degil uyari olarak ayri alanda doner, derleme_durumu'nu etkilemez.
        ruff_rapor = []
        for rel in dict.fromkeys(written):
            if rel.endswith(".py"):
                ruff_rapor += ruff_uyarilari(jail, rel)
        em.emit("result", ok=not errs, errors=[e[:600] for e in errs[:5]], rounds=r["rounds"],
                wall=round(r["wall"], 1), written=list(dict.fromkeys(written)), play=None,
                kullanim=r.get("kullanim"), ruff=ruff_rapor[:12] or None)
        code = 0 if not errs else 2
    except Exception as e:  # noqa: BLE001
        em.emit("error", message=("%s: %s" % (type(e).__name__, e))[:300])
        code = 1
    finally:
        em.emit("exit", code=code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
