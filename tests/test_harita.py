"""Proje haritasi birim testleri - GPU GEREKMEZ.

    python tests/test_harita.py
"""
from __future__ import annotations
import os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from core import harita  # noqa: E402

W = os.path.join(ROOT, ".apprentice_test_home", "harita_unit")


def main() -> int:
    if os.path.isdir(W):
        shutil.rmtree(W)
    os.makedirs(os.path.join(W, "alt"))
    with open(os.path.join(W, "odeme.py"), "w", encoding="utf-8") as f:
        f.write("def kupon_uygula(t, y):\n    return t\n\n\nclass Sepet:\n"
                "    def ekle(self, u):\n        pass\n    def _gizli(self):\n        pass\n")
    with open(os.path.join(W, "alt", "Oyun.cs"), "w", encoding="utf-8") as f:
        f.write("public class SuruYoneticisi : MonoBehaviour {\n"
                "    void Update() { }\n    public static int Say(int a) { return a; }\n}\n"
                "internal struct Nokta { public int x; }\n")
    with open(os.path.join(W, "bozuk.py"), "w", encoding="utf-8") as f:
        f.write("def (:\n")
    with open(os.path.join(W, "veri.json"), "w", encoding="utf-8") as f:
        f.write("{}")                                     # haritaya girmemeli

    m = harita.uret(W)
    assert m.startswith("PROJE HARITASI"), m[:40]
    assert "odeme.py (10): kupon_uygula(), Sepet.{ekle}" in m, m         # _gizli metot yok
    assert "alt/Oyun.cs" in m and "SuruYoneticisi.{Update,Say}" in m and "Nokta" in m, m
    assert "bozuk.py" in m and "<sozdizimi hatasi>" in m, m              # cokmez, isaretler
    assert "veri.json" not in m
    print("harita: py + cs + bozuk + filtre: ok")

    # kaydet=True MAP.md yazar
    harita.uret(W, kaydet=True)
    assert os.path.isfile(os.path.join(W, "MAP.md"))
    print("MAP.md kaydi: ok")

    # bos dizin cokmez
    os.makedirs(os.path.join(W, "bos"))
    assert harita.uret(os.path.join(W, "bos")).startswith("PROJE HARITASI")
    print("bos dizin: ok")
    print("SONUC: GECTI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
