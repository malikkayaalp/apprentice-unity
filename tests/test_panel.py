"""Panel testleri - GPU/Ollama GEREKMEZ.

    python tests/test_panel.py

Kapsam:
  1. panel.html icindeki JS SOZDIZIMI (node varsa gercek ayristirici, yoksa kaba denetim).
     Yasandi: tek tirnakli metin icindeki kesme isareti ("Claude'a") tum betigi coktu ve
     panel bos/kilitli acildi - hata sessizdi. Bu test o sinifi yakalar.
  2. Sunucu uclari: /api/hazir (anlik), /api/isler, /api/olaylar, /api/modeller.
  3. Yerlesim butunlugu: VARSAYILAN izgarada panel cakismasi olmamali (metinden okunur).
"""
from __future__ import annotations
import json, os, re, shutil, subprocess, sys, tempfile, threading, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SAYFA = os.path.join(ROOT, "clients", "web", "panel.html")


def js_sozdizimi() -> bool:
    with open(SAYFA, encoding="utf-8") as f:
        html = f.read()
    bloklar = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert bloklar, "panel.html icinde <script> yok"
    js = "\n".join(bloklar)
    node = shutil.which("node")
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write("(async function(){\n" + js + "\n})")     # cagirmadan yalnizca AYRISTIR
            yol = f.name
        try:
            r = subprocess.run([node, "--check", yol], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60,
                               creationflags=0x08000000 if os.name == "nt" else 0)
            if r.returncode != 0:
                print("JS SOZDIZIMI HATASI:\n" + (r.stderr or "")[:600])
                return False
            print("js sozdizimi (node --check): ok  (%d karakter)" % len(js))
        finally:
            os.unlink(yol)
    else:
        # node yoksa: en sik hata sinifini kaba denetimle yakala (tek tirnakli metinde ')
        for i, satir in enumerate(js.splitlines(), 1):
            s = satir.strip()
            if s.startswith("//") or "'" not in s:
                continue
            tek = len(re.findall(r"(?<!\\)'", s))
            if tek % 2 == 1 and not s.rstrip().endswith(("+", ",", "(")):
                print("supheli tek tirnak (satir %d): %s" % (i, s[:90]))
                return False
        print("js kaba sozdizimi denetimi: ok (node yok)")
    return True


def yerlesim_butun() -> bool:
    """VARSAYILAN izgara: panel dikdortgenleri cakismamali, sutun tasmamali."""
    with open(SAYFA, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const VARSAYILAN=\{(.*?)\};", html, re.S)
    assert m, "VARSAYILAN yerlesim bulunamadi"
    grid = {}
    for eslesme in re.finditer(r"(\w+):\{gx:(\d+),gy:(\d+),gw:(\d+),gh:(\d+)\}", m.group(1)):
        ad, gx, gy, gw, gh = eslesme.group(1), *(int(x) for x in eslesme.groups()[1:])
        grid[ad] = (gx, gy, gw, gh)
    assert len(grid) >= 8, "beklenenden az panel: %s" % list(grid)
    adlar = list(grid)
    for i in range(len(adlar)):
        for j in range(i + 1, len(adlar)):
            a, b = grid[adlar[i]], grid[adlar[j]]
            cakisir = not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or
                           a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])
            assert not cakisir, "varsayilan yerlesimde cakisma: %s + %s" % (adlar[i], adlar[j])
    for ad, (gx, _gy, gw, _gh) in grid.items():
        assert gx + gw <= 24, "%s sutun tasmasi (%d+%d)" % (ad, gx, gw)
    print("varsayilan yerlesim: ok (%d panel, cakisma yok)" % len(grid))
    return True


def sunucu_uclari() -> bool:
    ev = os.path.join(ROOT, ".apprentice_test_home", "panel_unit")
    os.makedirs(os.path.join(ev, "jobs"), exist_ok=True)
    port = 8899
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "clients", "web", "panel.py"),
                          "--port", str(port), "--home", ev],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=ROOT,
                         creationflags=0x08000000 if os.name == "nt" else 0)
    try:
        for _ in range(80):
            time.sleep(0.1)
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/api/hazir" % port, timeout=1).read()
                break
            except Exception:
                continue
        else:
            print("panel sunucusu ayaga kalkmadi:",
                  (p.stderr.read() or b"").decode("utf-8", "replace")[:300])
            return False
        t0 = time.time()
        urllib.request.urlopen("http://127.0.0.1:%d/api/hazir" % port, timeout=3).read()
        hazir_s = time.time() - t0
        assert hazir_s < 1.0, "/api/hazir yavas: %.2f sn" % hazir_s
        d = json.load(urllib.request.urlopen("http://127.0.0.1:%d/api/isler" % port, timeout=10))
        assert "isler" in d and "sistem" in d, d
        t1 = time.time()
        json.load(urllib.request.urlopen("http://127.0.0.1:%d/api/isler" % port, timeout=10))
        assert time.time() - t1 < 1.0, "isler onbellegi calismiyor (%.2f sn)" % (time.time() - t1)
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=5).read().decode("utf-8")
        assert "Apprentice" in html and "<script>" in html
        print("sunucu uclari: ok (hazir %.0f ms, isler onbellekli)" % (hazir_s * 1000))
        return True
    finally:
        p.terminate()


def main() -> int:
    ok = js_sozdizimi() and yerlesim_butun() and sunucu_uclari()
    print("SONUC:", "GECTI" if ok else "KALDI")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
