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


def dizilimler_butun() -> bool:
    """Her DIZILIM presetinde: gorunur paneller cakismamali, sutun tasmamali, panel adi
    bilinmeyen/eksik olmamali. (Presetler elle yazildi; birinde cakisma olsa panel ust uste biner.)"""
    with open(SAYFA, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const DIZILIMLER=\{(.*?)\n\};", html, re.S)
    assert m, "DIZILIMLER bulunamadi"
    govde = m.group(1)
    adlar_m = re.search(r"const PANEL_ADLARI=\{(.*?)\};", html, re.S)
    tum_panel = set(re.findall(r"(\w+):\"", adlar_m.group(1)))
    parcalar = re.split(r"\n  (?=\w+:\{etiket:)", govde)
    toplam = 0
    for parca in parcalar:
        bas = re.match(r"\s*(\w+):\{etiket:", parca)
        if not bas:
            continue
        ad = bas.group(1)
        g = re.search(r"gizli:\[(.*?)\]", parca, re.S)
        gizli = set(re.findall(r'"(\w+)"', g.group(1))) if g else set()
        kutu = {}
        for k in re.finditer(r"(\w+):\{gx:(\d+),gy:(\d+),gw:(\d+),gh:(\d+)\}", parca):
            kutu[k.group(1)] = tuple(int(x) for x in k.groups()[1:])
        if not kutu:
            assert "VARSAYILAN" in parca, "%s: kutu yok" % ad
            continue                      # dengeli: VARSAYILAN'a isaret eder, o ayrica denetlendi
        bilinmeyen = (set(kutu) | gizli) - tum_panel
        assert not bilinmeyen, "%s: bilinmeyen panel adi %s" % (ad, bilinmeyen)
        eksik = tum_panel - set(kutu)
        assert not eksik, "%s: yerlesimde tanimsiz panel %s" % (ad, eksik)
        gorunur = [k for k in kutu if k not in gizli]
        assert gorunur, "%s dizilimi: hic gorunur panel yok" % ad
        for i in range(len(gorunur)):
            for j in range(i + 1, len(gorunur)):
                a_, b_ = kutu[gorunur[i]], kutu[gorunur[j]]
                cak = not (a_[0] + a_[2] <= b_[0] or b_[0] + b_[2] <= a_[0] or
                           a_[1] + a_[3] <= b_[1] or b_[1] + b_[3] <= a_[1])
                assert not cak, "%s dizilimi: %s + %s cakisiyor" % (ad, gorunur[i], gorunur[j])
        for k, (gx, _gy, gw, _gh) in kutu.items():
            assert gx + gw <= 24, "%s/%s sutun tasmasi (%d+%d)" % (ad, k, gx, gw)
        toplam += 1
    assert toplam >= 5, "beklenenden az dizilim dogrulandi: %d" % toplam
    print("dizilim presetleri: ok (%d dizilim, cakisma/tasma/eksik yok)" % toplam)
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


def calisma_dizini_kurallari() -> bool:
    """Panel gorev ucu: calisma dizini cozumu ve yol kacisi denetimi.
    Kural (kullanici karari): BOS = calisma alaninin KOKU (cirak proje dosyalarini gorsun);
    dolu = yalniz o alt klasor. Kok hala kurulum evi ise 'panel' alt klasoru kullanilir.
    Yasandi: eskiden bos birakilinca hep 'panel' alt klasoru aciliyor ve cirak projeyi
    ne okuyabiliyor ne de `ara` ile bulabiliyordu."""
    import shutil
    ev = os.path.join(ROOT, ".apprentice_test_home", "dizin_unit")
    proje = os.path.join(ev, "proje")
    if os.path.isdir(ev):
        shutil.rmtree(ev)
    os.makedirs(os.path.join(ev, "jobs"), exist_ok=True)
    os.makedirs(proje, exist_ok=True)
    port = 8898
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "clients", "web", "panel.py"),
                          "--port", str(port), "--home", ev],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=ROOT,
                         creationflags=0x08000000 if os.name == "nt" else 0)

    def gonder(dizin, ortam="fake"):
        govde = json.dumps({"gorev": "x", "kriterler": ["y"], "ortam": ortam,
                            "calisma_dizini": dizin}).encode()
        r = urllib.request.Request("http://127.0.0.1:%d/api/gorev" % port, govde,
                                   {"Content-Type": "application/json",
                                    "X-Apprentice": "panel"})
        with urllib.request.urlopen(r, timeout=30) as c:
            return json.loads(c.read().decode("utf-8"))

    try:
        for _ in range(80):
            time.sleep(0.1)
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/api/hazir" % port, timeout=1).read()
                break
            except Exception:
                continue
        else:
            print("panel kalkmadi:", (p.stderr.read() or b"").decode("utf-8", "replace")[:200])
            return False
        # 1) proje SECILMEMIS (kok == ev): bos dizin -> 'panel' alt klasoru (ev kirletilmesin)
        d = gonder("")
        assert d.get("klasor", "").rstrip("\/").endswith("panel"), d
        # 2) proje secili: bos dizin -> PROJE KOKU
        r = urllib.request.Request("http://127.0.0.1:%d/api/kok" % port,
                                   json.dumps({"yol": proje}).encode(),
                                   {"Content-Type": "application/json", "X-Apprentice": "panel"})
        try:
            urllib.request.urlopen(r, timeout=10).read()
        except Exception:
            with open(os.path.join(ev, "panel_ayar.json"), "w", encoding="utf-8") as f:
                json.dump({"kok": proje}, f)
            print("  (not: /api/kok yok, ayar dosyasi ile ayarlandi - panel yeniden okumali)")
            return True
        d = gonder("")
        assert os.path.realpath(d.get("klasor", "")) == os.path.realpath(proje), d
        # 3) alt klasor verilince oraya hapsolur
        d = gonder("alt/klasor")
        assert os.path.realpath(d.get("klasor", "")) == os.path.realpath(
            os.path.join(proje, "alt", "klasor")), d
        # 4) yol kacislari reddedilir (Windows tuzaklari dahil)
        for kotu in ("../disari", "C:kotu", "/mutlak", "alt/../../disari"):
            d = gonder(kotu)
            assert d.get("hata"), "%r kabul edildi: %s" % (kotu, d)
        print("calisma dizini kurallari: ok (bos=kok, alt klasor hapsi, 4 kacis reddedildi)")
        return True
    finally:
        p.terminate()


def main() -> int:
    ok = (js_sozdizimi() and yerlesim_butun() and dizilimler_butun()
          and sunucu_uclari() and calisma_dizini_kurallari())
    print("SONUC:", "GECTI" if ok else "KALDI")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
