"""envs/code testi.

    python tests/test_code_env.py          # modelsiz: hapis, araclar, dogrulayici (py_compile + pytest)
    python tests/test_code_env.py --live   # + sunucu uzerinden gercek gorev (Ollama acik olmali)

Canli gorev .apprentice_test_home/code_task/ altinda kosar (gitignore): "toplam.py'de
toplam(a, b) yaz, test_toplam.py ile test et, pytest gecsin". Dogrulayici pytest'tir;
rapor derleme_durumu=derlendi ancak pytest gecince doner.
"""
from __future__ import annotations
import json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "envs", "code"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import code_runner as CR  # noqa: E402


class Em:
    def __init__(self):
        self.ev = []

    def emit(self, kind, **kw):
        self.ev.append(dict(type=kind, **kw))


def offline() -> bool:
    home = os.path.join(ROOT, ".apprentice_test_home", "code_unit")
    if os.path.isdir(home):
        shutil.rmtree(home)      # yalnizca testin kendi gecici klasoru
    os.makedirs(home)
    jail = CR.Jail(home)
    em = Em()
    written: list = []
    d = CR.make_dispatch(jail, written, em)

    # hapis
    r = d("read_file", {"path": "../../README.md"})
    assert "disinda" in r.get("error", ""), r
    r = d("write_file", {"path": "../kacak.txt", "contents": "x"})
    assert "disinda" in r.get("error", ""), r
    assert not os.path.exists(os.path.join(ROOT, ".apprentice_test_home", "kacak.txt"))
    print("hapis: ok")

    # yaz / oku / listele / write olayi
    r = d("write_file", {"path": "pkg/toplam.py", "contents": "def toplam(a, b):\n    return a + b\n"})
    assert r.get("ok") and written == ["pkg/toplam.py"]
    assert any(e["type"] == "write" and e["before"] is None for e in em.ev)
    r = d("read_file", {"path": "pkg/toplam.py"})
    assert "def toplam" in r["contents"]
    r = d("list_files", {})
    assert r["files"] == ["pkg/toplam.py"], r
    print("dosya araclari: ok")

    # dogrulayici: derleme temiz, test yok
    assert CR.compile_errors(jail, written) == []
    assert CR.test_errors(jail) == []
    # bozuk py -> derleme hatasi
    d("write_file", {"path": "bozuk.py", "contents": "def (:\n"})
    errs = CR.compile_errors(jail, written)
    assert errs and "bozuk.py" in errs[0], errs
    os.remove(os.path.join(home, "bozuk.py"))
    written.remove("bozuk.py")
    print("derleme dogrulayici: ok")

    # pytest: basarisiz test -> hata; duzeltince temiz
    # pytest varsa pytest, yoksa unittest: her ikisinde de calisan test govdesi
    T = ("import unittest\nfrom pkg.toplam import toplam\n\nclass T(unittest.TestCase):\n"
         "    def test_t(self):\n        self.assertEqual(toplam(2, 2), %d)\n")
    d("write_file", {"path": "pkg/__init__.py", "contents": ""})
    d("write_file", {"path": "test_toplam.py", "contents": T % 5})
    errs = CR.test_errors(jail)
    assert errs and CR.TEST_ADI in errs[0], errs
    d("write_file", {"path": "test_toplam.py", "contents": T % 4})
    assert CR.test_errors(jail) == []
    r = d("run_tests", {})
    assert r["exit"] == 0, r
    print("%s dogrulayici: ok" % CR.TEST_ADI)

    # shell
    r = d("run_shell", {"cmd": "git push origin main"})
    assert "reddedildi" in r.get("error", ""), r
    r = d("run_shell", {"cmd": "rm -rf ."})
    assert "reddedildi" in r.get("error", ""), r
    r = d("run_shell", {"cmd": "echo merhaba"})
    assert r["exit"] == 0 and "merhaba" in r["out"]
    r = d("run_shell", {"cmd": sys.executable + " -c \"import time; time.sleep(3)\""})
    assert r["exit"] == 0
    print("shell: ok")
    return True


def live() -> bool:
    from test_server import Client
    work = os.path.join(ROOT, ".apprentice_test_home", "code_task")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    c = Client({"APPRENTICE_HOME": os.path.join(ROOT, ".apprentice_test_home")})
    try:
        c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "t", "version": "0"}})
        c.notify("notifications/initialized")
        t0 = time.time()
        rep = c.tool("worker_run", {
            "gorev": "toplam.py dosyasinda toplam(a, b) fonksiyonu yaz (iki sayiyi toplar) ve "
                     "test_toplam.py dosyasinda %s ile en az 3 test yaz (pozitif, negatif, sifir)." % CR.TEST_ADI,
            "kabul_kriterleri": ["toplam.py ve test_toplam.py calisma dizininde olsun.",
                                 "run_tests hatasiz gecsin, en az 3 test kossun.",
                                 "Baska dosya yazma."],
            "ortam": "code", "calisma_dizini": work}, timeout=900)["structuredContent"]
        print(json.dumps({k: rep.get(k) for k in ("derleme_durumu", "hatalar", "yazilan_dosyalar",
                                                  "tur_sayisi", "sure", "ozet", "araclar")},
                         ensure_ascii=False, indent=1))
        # Denetci kontrolu: pytest'i BIZ kosalim
        # Denetci kontrolu: testleri BIZ kosalim, sayiyi BIZ okuyalim
        import re
        r = CR.shell(CR.TEST_CMD, work)
        print("denetci %s: exit=%s\n%s" % (CR.TEST_ADI, r["exit"], r["out"][-600:]))
        m = re.search(r"Ran (\d+) test", r["out"]) or re.search(r"(\d+) passed", r["out"])
        n = int(m.group(1)) if m else 0
        ok = rep["derleme_durumu"] == "derlendi" and r["exit"] == 0 and n >= 3 and \
            os.path.exists(os.path.join(work, "toplam.py")) and \
            os.path.exists(os.path.join(work, "test_toplam.py"))
        print("denetci: test sayisi=%d (>=3 gerekli)" % n)
        print("live: %s (%.0fs)" % ("ok" if ok else "KALDI", time.time() - t0))
        return bool(ok)
    finally:
        c.close()


def main() -> int:
    ok = offline()
    if "--live" in sys.argv:
        ok = live() and ok
    print("SONUC:", "GECTI" if ok else "KALDI")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
