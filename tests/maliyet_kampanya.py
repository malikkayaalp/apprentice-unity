"""Maliyet kampanyasi: yerel isci (A) icin token, sure, GPU enerjisi (Wh) ve gizli kontrol puani.

    python tests/maliyet_kampanya.py [--kwh-tl 2.5] [--gorev parantez,lru]

Olcum yontemi:
  - token/sure: Ollama'nin kendi sayaclari (prompt_eval_count, eval_count, sureler) -> worker_run
    donusundeki 'kullanim'
  - enerji: nvidia-smi power.draw 0.5 sn'de bir orneklenir; is oncesi 10 sn bosta taban olculur,
    taban dusulerek Wh = sum((P - P_bos) * dt) / 3600. Yalnizca GPU (CPU/RAM haric -> alt sinir).
  - kalite: code_kampanya.GOREVLER'deki gizli kontroller (isciye verilmez)
Sonuc: tests/maliyet_kampanya.son.json. B (usta dogrudan yazar) icin karsilastirma ayni dosyaya
elle/ayri betikle eklenir; bu betik yalnizca A'yi olcer.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
try:      # pencereli exe/pythonw: sys.stdout None olabilir (kurulum oz-testi
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # bu satirda cokuyordu)
except Exception:
    pass
from test_server import Client  # noqa: E402
import code_kampanya as K  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")


class GucOrnekleyici:
    def __init__(self, aralik=0.5):
        self.aralik, self.ornekler, self._dur = aralik, [], False

    def _oku(self):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
            return sum(float(x) for x in out if x.strip())
        except Exception:
            return None

    def _dongu(self):
        while not self._dur:
            t = time.time(); p = self._oku()
            if p is not None:
                self.ornekler.append((t, p))
            time.sleep(self.aralik)

    def baslat(self):
        self._dur = False; self.ornekler = []
        threading.Thread(target=self._dongu, daemon=True).start()

    def durdur(self):
        self._dur = True; time.sleep(self.aralik + 0.1)

    def wh(self, taban_w: float) -> dict:
        if len(self.ornekler) < 2:
            return {"wh": None, "ort_w": None, "tepe_w": None, "ornek": len(self.ornekler)}
        top = 0.0
        for (t0, p0), (t1, p1) in zip(self.ornekler, self.ornekler[1:]):
            top += max(0.0, (p0 + p1) / 2 - taban_w) * (t1 - t0)
        ws = [p for _, p in self.ornekler]
        return {"wh": round(top / 3600, 4), "ort_w": round(sum(ws) / len(ws), 1), "tepe_w": round(max(ws), 1),
                "taban_w": round(taban_w, 1), "ornek": len(ws)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kwh-tl", type=float, default=2.5, help="elektrik fiyati TL/kWh")
    ap.add_argument("--gorev", default="")
    a = ap.parse_args()
    secili = [g for g in a.gorev.split(",") if g] or list(K.GOREVLER)

    g = GucOrnekleyici()
    print("bosta GPU gucu olculuyor (10 sn)...")
    g.baslat(); time.sleep(10); g.durdur()
    taban = sum(p for _, p in g.ornekler) / max(1, len(g.ornekler))
    print("taban: %.1f W" % taban)

    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "maliyet", "version": "0"}})
    c.notify("notifications/initialized")
    rapor = {"baslangic": time.strftime("%Y-%m-%d %H:%M:%S"), "taban_w": round(taban, 1), "kwh_tl": a.kwh_tl, "A": {}}
    yol = os.path.join(ROOT, "tests", "maliyet_kampanya.son.json")
    try:
        for ad in secili:
            gg = K.GOREVLER[ad]
            work = os.path.join(HOME, "maliyet", ad)
            if os.path.isdir(work):
                shutil.rmtree(work)
            os.makedirs(work)
            for dn, icerik in (gg.get("on_dosyalar") or {}).items():
                with open(os.path.join(work, dn), "w", encoding="utf-8", newline="\n") as f:
                    f.write(icerik)
            print("\n== %s" % ad)
            g.baslat(); t0 = time.time()
            rep = c.tool("worker_run", {"gorev": gg["gorev"], "kabul_kriterleri": gg["kriterler"],
                                        "ortam": "code", "calisma_dizini": work}, timeout=1900)["structuredContent"]
            sure = time.time() - t0; g.durdur()
            en = g.wh(taban)
            son = K.gizli_kontrol(work, gg["modul"], gg["gizli"])
            gecen = sum(1 for _, ok, _ in son if ok)
            ku = rep.get("kullanim") or {}
            kayit = {"sure_s": round(sure, 1), "derleme_durumu": rep.get("derleme_durumu"), "onarim": rep.get("tur_sayisi"),
                     "kullanim": ku, "enerji": en, "gizli": "%d/%d" % (gecen, len(son)),
                     "maliyet_tl": round((en["wh"] or 0) / 1000 * a.kwh_tl, 4)}
            rapor["A"][ad] = kayit
            print("   %s | %.0fs | prompt %s tok, uretim %s tok | %s Wh (ort %s W) | gizli %s | %.4f TL" % (
                rep.get("derleme_durumu"), sure, ku.get("prompt_tokens"), ku.get("gen_tokens"), en["wh"], en["ort_w"],
                kayit["gizli"], kayit["maliyet_tl"]))
            with open(yol, "w", encoding="utf-8", newline="\n") as f:
                json.dump(rapor, f, ensure_ascii=False, indent=1)
    finally:
        c.close()
    A = rapor["A"]
    print("\nTOPLAM A: %.0f s, %d prompt tok, %d uretim tok, %.3f Wh, %.4f TL, gizli %s" % (
        sum(k["sure_s"] for k in A.values()), sum(k["kullanim"].get("prompt_tokens", 0) for k in A.values()),
        sum(k["kullanim"].get("gen_tokens", 0) for k in A.values()), sum(k["enerji"]["wh"] or 0 for k in A.values()),
        sum(k["maliyet_tl"] for k in A.values()),
        "%d/%d" % (sum(int(k["gizli"].split("/")[0]) for k in A.values()), sum(int(k["gizli"].split("/")[1]) for k in A.values()))))
    print("->", yol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
