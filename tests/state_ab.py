"""STATE.md (devir dosyasi) A/B: koddan GORUNMEYEN karari isciye tasiyabiliyor mu?

    python tests/state_ab.py    # Ollama gerekir

Kurulum: stok.py onceden var (stok_ekle/stok_dus; hata mesajlari eski/duz bicimde).
Round-1'den sonra "usta" bir teamul kararlastirmis: YENI fonksiyonlarda yetersiz stok hatasi
"stok yetersiz: <urun>" bicimiyle firlatilacak. Bu karar KODDA YOK - yalnizca devirde.

  A: STATE.md yok       -> isci karari bilemez (kodda ipucu yok)
  B: STATE.md var       -> devir notu karari tasir

Gorev ikisinde de ayni: "stok_tasi ekle; projedeki teamullere ve onceki kararlara uy."
Gizli kontrol: 5 islevsel + 1 BICIM kontrolu (mesaj 'stok yetersiz:' ile baslar).
Iddia: B bicim kontrolunu gecer, A gecemez; bedel STATE'in ~kac yuz tokeni.
Ayrica olculmus kiyas: ayni "devam bilgisi"ni ham `oturum` ile tasimak +%59 idi.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
try:      # pencereli exe/pythonw: sys.stdout None olabilir (kurulum oz-testi
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # bu satirda cokuyordu)
except Exception:
    pass
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "state_ab")

MEVCUT = '''"""Depo stok islemleri."""


def stok_ekle(depo, urun, adet):
    if adet < 0:
        raise ValueError("adet negatif olamaz")
    yeni = dict(depo)
    yeni[urun] = yeni.get(urun, 0) + adet
    return yeni


def stok_dus(depo, urun, adet):
    if adet < 0:
        raise ValueError("adet negatif olamaz")
    if depo.get(urun, 0) < adet:
        raise ValueError("yetersiz")
    yeni = dict(depo)
    yeni[urun] -= adet
    if yeni[urun] == 0:
        del yeni[urun]
    return yeni
'''

STATE = '''# STATE.md - is devri (en yeni ustte)

## 2026-08-24 stok modulu round-1 devri
- stok.py yazildi: stok_ekle / stok_dus, kopya donduruyor, girdiyi degistirmiyor.
- KARAR (kodda henuz uygulanmadi, YENI fonksiyonlarda uygulanacak): yetersiz stok hatalari
  bundan sonra su bicimle firlatilir: ValueError("stok yetersiz: <urun_adi>")
  (musteri destegi log'larda urun adini istiyor). Eski fonksiyonlara dokunulmayacak.
- Denenip ELENEN: depo'yu yerinde degistirmek (testlerde kopya sarti var).
'''

GOREV = ("stok.py dosyasina stok_tasi(depo, kaynak, hedef, adet) fonksiyonu ekle: kaynaktan "
         "dusup hedefe ekler, yeni depoyu doner, girdiyi degistirmez. Mevcut iki fonksiyonu "
         "bozma. Projedeki teamullere ve onceki kararlara uy.")
KRITER = ["stok_tasi({'a': 5}, 'a', 'b', 2) -> {'a': 3, 'b': 2}",
          "Kaynak yetersizse ValueError; girdi degismez",
          "Mevcut fonksiyonlarin davranisi aynen korunur; yalnizca stok.py degisir"]

GIZLI = r'''
import sys
sys.path.insert(0, ".")
from stok import stok_ekle, stok_dus, stok_tasi
out = []
def kontrol(ad, fn):
    try:
        r = fn(); out.append((ad, r is True, "" if r is True else "sonuc=%r" % (r,)))
    except Exception as e:
        out.append((ad, False, "%s: %s" % (type(e).__name__, str(e)[:70])))
kontrol("tasi temel", lambda: stok_tasi({"a": 5}, "a", "b", 2) == {"a": 3, "b": 2})
kontrol("kaynak biter", lambda: stok_tasi({"a": 2}, "a", "b", 2) == {"b": 2})
kontrol("girdi degismez", lambda: (lambda d: (stok_tasi(d, "a", "b", 1), d == {"a": 2})[-1])({"a": 2}))
kontrol("mevcut ekle korunur", lambda: stok_ekle({}, "x", 1) == {"x": 1})
def _mesaj():
    try:
        stok_tasi({"a": 1}, "a", "b", 5); return "hata firlamadi"
    except ValueError as e:
        return str(e)
    except Exception as e:
        return "baska istisna: " + type(e).__name__
m = _mesaj()
out.append(("yetersizde ValueError", isinstance(m, str) and "istisna" not in m and m != "hata firlamadi", m[:60]))
out.append(("KARAR: mesaj bicimi 'stok yetersiz: <urun>'", isinstance(m, str) and m.startswith("stok yetersiz:"), m[:60]))
for ad, ok, d in out:
    print(("OK   " if ok else "HATA ") + ad + ("  " + d if d else ""))
print("PUAN %d/%d" % (sum(1 for _, o, _ in out if o), len(out)))
'''


def gizli(klasor: str) -> tuple:
    r = subprocess.run([sys.executable, "-B", "-c", GIZLI], cwd=klasor, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"))
    cikti = (r.stdout or "") + (("\n" + r.stderr[-300:]) if r.returncode and r.stderr else "")
    puan = (0, 0)
    for s in cikti.splitlines():
        if s.startswith("PUAN"):
            a, b = s.split()[1].split("/")
            puan = int(a), int(b)
    return puan, cikti


def kol(c: Client, ad: str, state_var: bool) -> dict:
    klasor = os.path.join(KOK, ad)
    os.makedirs(klasor)
    with open(os.path.join(klasor, "stok.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(MEVCUT)
    if state_var:
        with open(os.path.join(klasor, "STATE.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(STATE)
    t0 = time.time()
    rep = c.tool("worker_run", {"gorev": GOREV, "kabul_kriterleri": KRITER, "ortam": "code",
                                "calisma_dizini": os.path.join("state_ab", ad),
                                "dogrulama": "derleme", "yazilabilir": ["stok.py"]},
                 timeout=1900)["structuredContent"]
    sure = time.time() - t0
    (g, t), cikti = gizli(klasor)
    ku = rep.get("kullanim") or {}
    kayit = {"state": state_var, "sure_s": round(sure, 1), "prompt_tok": ku.get("prompt_tokens"),
             "uretim_tok": ku.get("gen_tokens"), "gizli": "%d/%d" % (g, t), "cikti": cikti,
             "derleme_durumu": rep.get("derleme_durumu")}
    karar = [s for s in cikti.splitlines() if s.startswith(("OK   KARAR", "HATA KARAR"))]
    print("  %-9s %-9s %4.0f s | prompt %6s | gizli %d/%d | %s" % (
        ad, rep.get("derleme_durumu"), sure, ku.get("prompt_tok", ku.get("prompt_tokens")),
        g, t, karar[0] if karar else "?"), flush=True)
    return kayit


def main() -> int:
    if os.path.isdir(KOK):
        shutil.rmtree(KOK)
    os.makedirs(KOK)
    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "state-ab", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "home"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)
    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        rapor["A_statesiz"] = kol(c, "A_statesiz", False)
        rapor["B_stateli"] = kol(c, "B_stateli", True)
    finally:
        c.close()
        with open(os.path.join(ROOT, "tests", "state_ab.son.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(rapor, f, ensure_ascii=False, indent=1)
        print("-> tests/state_ab.son.json")
    A, B = rapor.get("A_statesiz"), rapor.get("B_stateli")
    if A and B and A["prompt_tok"] and B["prompt_tok"]:
        print("STATE bedeli: prompt %+d tok | karar tasindi mi: A=%s B=%s" % (
            B["prompt_tok"] - A["prompt_tok"],
            "6/6" in A["gizli"], "6/6" in B["gizli"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
