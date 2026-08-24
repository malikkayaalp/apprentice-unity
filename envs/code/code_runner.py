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


def test_ozetle(ham: str, cikis) -> dict:
    """Ham test dokumunu hata-izi kivamina sikistirir (2026-08-24, olculen ilke: isciye
    giden sinyal 'satiri ve nedeni yazili' olmali; 800 satirlik dokum baglam katilidir).

    Doner: {"sayim": "2 failed, 5 passed", "hatalar": [(test_id, sebep)], "imzalar": frozenset}
    Imza = test_id + hata tipi; onarim turlari arasinda ayni-hata takibi bununla yapilir.
    """
    hatalar = []
    for s in ham.splitlines():
        s = s.strip()
        if s.startswith(("FAILED ", "ERROR ")) and ("::" in s or ".py" in s):
            parca = s.split(" ", 1)[1]                     # pytest -q: id - sebep
            tid, _, sebep = parca.partition(" - ")
            hatalar.append((tid.strip(), sebep.strip()[:160]))
        elif s.startswith(("FAIL: ", "ERROR: ")):          # unittest basligi
            hatalar.append((s.split(": ", 1)[1].strip()[:120], ""))
    sayim = ""
    for s in reversed(ham.splitlines()):
        t = s.strip().strip("= ")
        if t and ("passed" in t or "failed" in t or "error" in t.lower()
                  or t.startswith("Ran ") or t.startswith("FAILED (")):
            sayim = t[:120]
            break
    if not hatalar:                                        # cozulmeyen bicim: son anlamli satir
        son = [x for x in ham.strip().splitlines() if x.strip()]
        hatalar = [("cikti_cozulemedi", (son[-1].strip()[:160] if son else "cikis %s" % cikis))]
    imzalar = frozenset("%s|%s" % (t, (s.split(":")[0] if s else "")) for t, s in hatalar)
    return {"sayim": sayim or ("cikis %s" % cikis), "hatalar": hatalar, "imzalar": imzalar}


SON_TEST_HAM = {"out": ""}      # sikistirici ham dokumu YUTMASIN: usta eskalasyonda isteyebilir


def test_raporu(jail: Jail) -> dict:
    """Testleri kosar; basarisizsa sikistirilmis rapor doner. Ham dokum SON_TEST_HAM'da
    kalir ve is bitiminde events.jsonl'a yazilir - isci ozeti gorur, usta gerekirse hami."""
    if not has_tests(jail.root):
        return {"ok": True}
    r = shell(TEST_CMD, jail.root)
    SON_TEST_HAM["out"] = r["out"] or ""
    if r["exit"] == 0:
        return {"ok": True}
    return dict(test_ozetle(r["out"], r["exit"]), ok=False)


def test_metni(rap: dict, onceki: frozenset | None) -> str:
    """Isciye giden ozet; onceki tur imzalari verilirse her hata YENI/AYNI diye etiketlenir."""
    satirlar = ["%s testleri: %s" % (TEST_ADI, rap["sayim"])]
    for tid, sebep in rap["hatalar"][:8]:
        imza = "%s|%s" % (tid, (sebep.split(":")[0] if sebep else ""))
        etiket = ""
        if onceki is not None:
            etiket = " [AYNI - onceki duzeltme bunu COZMEDI]" if imza in onceki else " [YENI]"
        satirlar.append("DUSTU %s%s%s" % (tid, (" - " + sebep) if sebep else "", etiket))
    if len(rap["hatalar"]) > 8:
        satirlar.append("... ve %d hata daha" % (len(rap["hatalar"]) - 8))
    return "\n".join(satirlar)


def test_errors(jail: Jail) -> list:
    rap = test_raporu(jail)
    return [] if rap["ok"] else [test_metni(rap, None)]


def canli_run(msgs: list, tools: list, dispatch, model: str, canli_yol: str,
              max_steps: int = 12):
    """CANLI KIP (2026-08-24): arac cagrilari XML-icerik protokoluyle - Ollama duz metni
    token token akitir (olculdu: native tool argumanlari TEK parca gelir, akmaz). Akan metin
    canli.txt'ye anlik yazilir; izleyici daktilo gibi gosterir. parse_xml_tool_calls zaten
    Qwen3-Coder'in kendi soz dizimini cozer - protokol modele yabanci degil.
    run_agent'in dar bir es-degeri: ayni alanlari doldurur, olcum yolu (chat) degismez."""
    from core.client import chat_stream, parse_xml_tool_calls, LoopResult

    talimat = ("\n\nARAC CAGIRMA BICIMI (bu iste araclari SU bicimle, duz metin olarak cagir):\n"
               "<function=arac_adi>\n<parameter=param_adi>\ndeger\n</parameter>\n</function>\n"
               "Araclar: " + "; ".join(
                   "%s(%s)" % (t["function"]["name"],
                               ",".join((t["function"].get("parameters") or {})
                                        .get("properties", {}).keys()))
                   for t in tools) +
               "\nHer cevapta ya arac cagir ya da bitti isen kisa Turkce ozet yaz.")
    if msgs and msgs[0]["role"] == "system" and "ARAC CAGIRMA BICIMI" not in msgs[0]["content"]:
        msgs[0] = {"role": "system", "content": msgs[0]["content"] + talimat}

    son_yazim = [0.0]

    def akit(_parca, toplam):
        if time.time() - son_yazim[0] > 0.15:
            son_yazim[0] = time.time()
            try:
                with open(canli_yol, "w", encoding="utf-8", newline="\n") as f:
                    f.write(toplam[-6000:])
            except OSError:
                pass

    res = LoopResult(messages=msgs)
    for _adim in range(max_steps):
        turn = chat_stream(res.messages, tools=None, model=model, think=False,
                           num_ctx=NUM_CTX, temperature=0.0, num_predict=6000,
                           extra_options={"num_batch": NUM_BATCH}, on_token=akit)
        res.turns.append(turn)
        res.metrics.merge(turn.metrics)
        if turn.error:
            res.stopped, res.error = "error", turn.error
            break
        # chat_stream XML cagrilari ZATEN ayristirir ve icerikten temizler:
        # turn.tool_calls dolu, turn.content kalan duz metindir. (Ilk surum icerigi
        # ikinci kez ayristirmaya kalkip "cagri yok" saniyordu - olculdu, duzeltildi.)
        from core.client import tc_name, tc_args
        calls = turn.tool_calls or []
        icerik = (turn.content or "").strip()
        if not calls:
            res.final_text = icerik
            res.stopped = "done"
            res.messages.append({"role": "assistant", "content": icerik})
            break
        # konusma gecmisine cagrilar XML olarak geri yazilir - model ne yaptigini gorur
        xml = "".join("\n<function=%s>%s\n</function>" % (
            tc_name(c), "".join("\n<parameter=%s>\n%s\n</parameter>" % (k, v)
                                for k, v in tc_args(c).items()))
            for c in calls)
        res.messages.append({"role": "assistant", "content": (icerik + xml).strip()})
        sonuclar = []
        for c in calls:
            out = dispatch(tc_name(c), tc_args(c))
            sonuclar.append({"arac": tc_name(c), "sonuc": out})
        res.messages.append({"role": "user", "content":
                             "ARAC SONUCLARI:\n" + json.dumps(sonuclar, ensure_ascii=False)[:8000]})
    else:
        res.stopped = "max_steps"
    try:                                                       # tur bitti: canli ekran temiz
        open(canli_yol, "w", encoding="utf-8").write("")
    except OSError:
        pass
    return res


def one_request(jail: Jail, dispatch, written: list, msgs: list, request: str,
                model: str, max_repairs: int, tools: list | None = None, em=None,
                canli_yol: str = "") -> dict:
    tools = tools if tools is not None else TOOLS
    msgs.append({"role": "user", "content": request})
    t0 = time.time()
    rounds = 0
    errs: list = []
    from core.client import Metrics
    kullanim = Metrics()            # olcum: toplam prompt/uretim tokeni ve sureleri (Ollama sayar)
    adim_sayisi = 0
    onceki_imzalar: frozenset | None = None
    duragan = False
    while True:
        if canli_yol and os.environ.get("APPRENTICE_CANLI") == "1":
            res = canli_run(msgs, tools, dispatch, model, canli_yol)
        else:
            res = run_agent(msgs, tools, dispatch, max_steps=12, model=model, think=False,
                            num_ctx=NUM_CTX, temperature=0.0, num_predict=6000, retries=2,
                            extra_options={"num_batch": NUM_BATCH})
        kullanim.merge(res.metrics); adim_sayisi += len(res.turns)
        msgs[:] = res.messages
        errs = compile_errors(jail, written)
        imzalar: frozenset | None = None
        if not errs and DOGRULAMA == "tam":
            rap = test_raporu(jail)
            if not rap["ok"]:
                errs = [test_metni(rap, onceki_imzalar)]
                imzalar = rap["imzalar"]
        if not errs or rounds >= max_repairs:
            break
        # DURAGANLIK DEDEKTORU (2026-08-24): ayni hata imzalari iki degerlendirmede ust uste
        # degismediyse isci ilerleyemiyor demektir - kalan onarim turlarini yakmak yerine
        # ustaya birak (olculdu: dongudeki model dongude oldugunu degerlendiremiyor;
        # bos-yazma korumasinin test kipindeki karsiligi). APPRENTICE_DURAGANLIK=0 kapatir.
        if (imzalar is not None and imzalar == onceki_imzalar
                and os.environ.get("APPRENTICE_DURAGANLIK", "1") != "0"):
            duragan = True
            errs = ["DURAGANLIK: ayni test hatalari 2 tur ust uste degismedi - isci "
                    "ilerleyemiyor, usta mudahalesi gerekli.\n" + errs[0]]
            if em:
                em.emit("duraganlik", imza_sayisi=len(imzalar), tur=rounds)
            break
        onceki_imzalar = imzalar if imzalar is not None else onceki_imzalar
        rounds += 1
        if em:
            em.emit("onarim", tur=rounds, mesaj="\n".join(errs[:6])[:500])
        msgs.append({"role": "user", "content":
                     "DOGRULAMA HATASI:\n" + "\n".join(errs[:6]) +
                     "\nIlgili dosyayi read_file ile oku, sebebi bul ve write_file ile "
                     "duzeltilmis TAM dosyayi yaz."})
    k = kullanim.as_dict(); k["model_cagrisi"] = adim_sayisi
    # Butce bekcisi: cagri basina ortalama prompt 17k'yi asiyorsa filtreleme birakilmis demektir
    # (rapor uyarisi; sert sinir degil - karari usta verir).
    ort = (k.get("prompt_tokens") or 0) / max(1, adim_sayisi)
    butce = ("cagri basina ortalama prompt %d token (>17k) - baglam filtrelemesi zayifladi; "
             "yazilabilir/ara/harita ayarlarini gozden gecir" % ort) if ort > 17000 else ""
    return {"errors": errs, "rounds": rounds, "wall": time.time() - t0,
            "text": res.final_text or "", "stopped": res.stopped, "error": res.error,
            "kullanim": k, "duragan": duragan, "butce_uyarisi": butce}


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
        hafiza_uyarisi = ""
        hp = os.path.join(jail.root, "HAFIZA.md")
        if os.path.isfile(hp):
            try:
                with open(hp, encoding="utf-8", errors="replace") as f:
                    tam_hafiza = f.read().strip()
                hafiza = tam_hafiza[:3000]
                if len(tam_hafiza) > 3000:
                    # SISME KUSURU (2026-08-24): usta dersleri SONA ekler, kirpma BASTAN alir
                    # -> dosya tasinca en yeni dersler isciye sessizce gitmiyordu. Sessiz kalmasin:
                    hafiza_uyarisi = ("HAFIZA.md %d karakter (sinir 3000) - SON %d karakter isciye "
                                      "GITMIYOR; dosyayi ozetleyip kisalt (eski dersleri birlestir/sil)"
                                      % (len(tam_hafiza), len(tam_hafiza) - 3000))
            except OSError:
                pass
        durum = ""
        durum_uyarisi = ""
        dp = os.path.join(jail.root, "STATE.md")
        if os.path.isfile(dp):
            try:
                with open(dp, encoding="utf-8", errors="replace") as f:
                    tam_durum = f.read().strip()
                durum = tam_durum[:2000]
                if tam_durum.count("\n") > 200:
                    durum_uyarisi = ("STATE.md %d satir (sinir 200) - eski devirleri "
                                     "STATE_ARSIV.md'ye tasi" % (tam_durum.count("\n") + 1))
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
            # GUNCEL DURUM (2026-08-24, OpenMemory STATE fikri): onceki islerden damitilmis devir.
            # Olculdu: ham oturum tasimak +%59 pahali; devir dosyasi "dosyada olmayan baglami"
            # (elenen yollar, koddan gorunmeyen kararlar) ucuza tasir. Teamul: EN YENI USTTE -
            # bastan kirpma bu sayede en yeniyi korur (HAFIZA'daki sessiz-kayip kusuru burada yok).
            if durum:
                sistem += ("\n\nGUNCEL DURUM (STATE.md - onceki islerin devri, en yeni ustte; "
                           "koddan gorunmeyen kararlara UY):\n" + durum)
            # PROJE HARITASI (2026-08-24, OpenMemory'nin MAP fikri): hedefin YERI bilinmeyen
            # iste isci adressiz kaliyordu (olculdu: 120 dosyayi sirayla okuyup coktu).
            # Harita "dosya -> semboller" adresini sifir sorguyla verir; denetci acar (harita=true).
            harita_n = 0
            if os.environ.get("APPRENTICE_HARITA") == "1":
                try:
                    from core import harita as HARITA
                    h = HARITA.uret(jail.root)[:16000]
                    harita_n = len(h)
                    sistem += "\n\n" + h + \
                              "\nHaritadaki adresi kullan: once ilgili dosyayi read_file ile oku."
                except Exception as e:                           # noqa: BLE001 - harita cokse is surer
                    em.emit("system", subtype="harita_hatasi", error=str(e)[:200])
            # Izlenebilirlik: sistem istemine NE girdigini izleyici gorsun (boyutlar karakter)
            em.emit("baglam", sistem=len(sistem), hafiza=len(hafiza), durum=len(durum),
                    harita=harita_n, araclar=[t["function"]["name"] for t in tools])
            msgs = [{"role": "system", "content": sistem}]
        canli_yol = os.path.join(os.path.dirname(os.path.abspath(a.jsonl)), "canli.txt") \
            if a.jsonl else ""
        r = one_request(jail, dispatch, written, msgs, request, a.model, a.repairs, tools,
                        em=em, canli_yol=canli_yol)
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
        if SON_TEST_HAM["out"] and (errs or r.get("duragan")):
            # ham dokum is klasorunde (events.jsonl) dursun; rapora GIRMEZ (baglami sisirmesin)
            em.emit("test_ham", boyut=len(SON_TEST_HAM["out"]), out=SON_TEST_HAM["out"][-20000:])
        em.emit("result", ok=not errs, errors=[e[:600] for e in errs[:5]], rounds=r["rounds"],
                wall=round(r["wall"], 1), written=list(dict.fromkeys(written)), play=None,
                kullanim=r.get("kullanim"), ruff=ruff_rapor[:12] or None,
                duragan=r.get("duragan", False), butce_uyarisi=r.get("butce_uyarisi") or None,
                hafiza_uyarisi=hafiza_uyarisi or None, durum_uyarisi=durum_uyarisi or None)
        code = 0 if not errs else 2
    except Exception as e:  # noqa: BLE001
        em.emit("error", message=("%s: %s" % (type(e).__name__, e))[:300])
        code = 1
    finally:
        em.emit("exit", code=code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
