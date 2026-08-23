"""Duraganlik dedektoru A/B: isci COZEMEYECEGI hatada kac tur yakiyor?

    python tests/duragan_ab.py    # Ollama gerekir

Kurulum: test_sabit.py onceden konur ve VAR OLMAYAN 'yardimci' modulunu import eder;
yazilabilir=["sabit.py"] oldugu icin isci o modulu yazamaz -> testler her turda birebir
ayni hatayla duser (cozumsuz dongu, Tetris'in test-kipindeki karsiligi).

  A: APPRENTICE_DURAGANLIK=0 -> eski davranis: max_repairs=3 tur sonuna kadar yakar
  B: dedektor acik           -> ayni imza 2 degerlendirmede -> kes, ustaya "DURAGANLIK" raporla

Olculen: tur sayisi, prompt token, sure; B raporunda duragan=true ve DURAGANLIK metni.
"""
from __future__ import annotations
import json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "duragan_ab")

TEST_DOSYASI = '''import unittest
from yardimci import katsayi          # yardimci modulu YOK ve yazilamaz

from sabit import sabit


class T(unittest.TestCase):
    def test_sabit(self):
        self.assertEqual(sabit(), 42 * katsayi)


if __name__ == "__main__":
    unittest.main()
'''

GOREV = ("sabit.py dosyasina sabit() fonksiyonu yaz: 42 dondursun. test_sabit.py zaten var, "
         "ONA DOKUNMA ve yeni dosya ekleme; yalnizca sabit.py yazilabilir.")
KRITER = ["sabit() == 42", "Yalnizca sabit.py yazilir", "Mevcut testler kosulur"]


def kol(ad: str, dedektor: bool) -> dict:
    klasor = os.path.join(KOK, ad)
    os.makedirs(klasor)
    with open(os.path.join(klasor, "test_sabit.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(TEST_DOSYASI)
    env = {"APPRENTICE_HOME": HOME}
    if not dedektor:
        env["APPRENTICE_DURAGANLIK"] = "0"
    c = Client(env)
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "duragan-ab", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "home"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)
    try:
        t0 = time.time()
        rep = c.tool("worker_run", {"gorev": GOREV, "kabul_kriterleri": KRITER, "ortam": "code",
                                    "calisma_dizini": os.path.join("duragan_ab", ad),
                                    "dogrulama": "tam", "yazilabilir": ["sabit.py"],
                                    "zaman_asimi_s": 1500}, timeout=1900)["structuredContent"]
        sure = time.time() - t0
    finally:
        c.close()
    ku = rep.get("kullanim") or {}
    kayit = {"dedektor": dedektor, "sure_s": round(sure, 1), "tur_sayisi": rep.get("tur_sayisi"),
             "prompt_tok": ku.get("prompt_tokens"), "uretim_tok": ku.get("gen_tokens"),
             "model_cagrisi": ku.get("model_cagrisi"), "duragan": rep.get("duragan", False),
             "hatalar": rep.get("hatalar", [])[:2]}
    print("  %-12s %4.0f s | tur %s | prompt %6s | cagri %s | duragan=%s" % (
        ad, sure, rep.get("tur_sayisi"), ku.get("prompt_tokens"),
        ku.get("model_cagrisi"), kayit["duragan"]), flush=True)
    return kayit


def main() -> int:
    if os.path.isdir(KOK):
        shutil.rmtree(KOK)
    os.makedirs(KOK)
    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S"),
             "A_dedektorsuz": kol("A_dedektorsuz", False),
             "B_dedektorlu": kol("B_dedektorlu", True)}
    with open(os.path.join(ROOT, "tests", "duragan_ab.son.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    A, B = rapor["A_dedektorsuz"], rapor["B_dedektorlu"]
    if A["prompt_tok"] and B["prompt_tok"]:
        print("KAZANC: prompt %d -> %d (%.0f%%), sure %.0f -> %.0f s | B duragan=%s" % (
            A["prompt_tok"], B["prompt_tok"], 100.0 * B["prompt_tok"] / A["prompt_tok"],
            A["sure_s"], B["sure_s"], B["duragan"]))
    print("-> tests/duragan_ab.son.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
