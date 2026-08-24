"""Maliyet kampanyasi B: usta (Claude) ayni 6 gorevi DOGRUDAN yazar, cirak yok.

Dosyalar bu betigin icinde (Claude'un yazdigi cozumler); calistirinca .apprentice_test_home/maliyet_B/<ad>/
altina acilir, gizli kontroller kosulur, token kestirimi (4 karakter/token) ve liste fiyatiyla
maliyet yazilir. Gercek fatura DEGIL: Claude Code'un sistem istemi/baglami dahil edilmez.

    python tests/maliyet_B_usta.py [--usd-try 41] [--giris-usd 3 --cikis-usd 15]   (Sonnet liste fiyati)
"""
from __future__ import annotations
import argparse, json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
try:      # pencereli exe/pythonw: sys.stdout None olabilir (kurulum oz-testi
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # bu satirda cokuyordu)
except Exception:
    pass
import code_kampanya as K  # noqa: E402

COZUMLER = {
"parantez": {"parantez.py": '''ESLER = {")": "(", "]": "[", "}": "{"}


def dengeli(metin):
    yigin = []
    for ch in metin:
        if ch in "([{":
            yigin.append(ch)
        elif ch in ESLER:
            if not yigin or yigin[-1] != ESLER[ch]:
                return False
            yigin.pop()
    return not yigin
''', "test_parantez.py": '''import unittest
from parantez import dengeli


class T(unittest.TestCase):
    def test_dengeli(self):
        self.assertTrue(dengeli("()[]{}")); self.assertTrue(dengeli("([{}])")); self.assertTrue(dengeli(""))

    def test_dengesiz(self):
        self.assertFalse(dengeli("(]")); self.assertFalse(dengeli("((")); self.assertFalse(dengeli("([)]"))
        self.assertFalse(dengeli(")")); self.assertFalse(dengeli("())"))

    def test_diger_karakterler(self):
        self.assertTrue(dengeli("a(b)c"))
'''},
"lru": {"lru.py": '''from collections import OrderedDict


class LRU:
    def __init__(self, kapasite):
        if kapasite < 1:
            raise ValueError("kapasite >= 1 olmali")
        self.kapasite = kapasite
        self._d = OrderedDict()

    def get(self, anahtar):
        if anahtar not in self._d:
            return None
        self._d.move_to_end(anahtar)
        return self._d[anahtar]

    def put(self, anahtar, deger):
        if anahtar in self._d:
            self._d.move_to_end(anahtar)
        self._d[anahtar] = deger
        if len(self._d) > self.kapasite:
            self._d.popitem(last=False)

    def __len__(self):
        return len(self._d)
''', "test_lru.py": '''import unittest
from lru import LRU


class T(unittest.TestCase):
    def test_temel(self):
        c = LRU(2); c.put(1, 1); c.put(2, 2)
        self.assertEqual(c.get(1), 1); c.put(3, 3)
        self.assertIsNone(c.get(2)); self.assertEqual(c.get(3), 3)

    def test_guncelleme_yeniler(self):
        c = LRU(2); c.put(1, 1); c.put(2, 2); c.put(1, 9); c.put(3, 3)
        self.assertIsNone(c.get(2)); self.assertEqual(c.get(1), 9)

    def test_len(self):
        c = LRU(2); c.put(1, 1); c.put(2, 2); c.put(3, 3)
        self.assertEqual(len(c), 2)
'''},
"roma": {"roma.py": '''_DEGERLER = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
             (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
_HARF = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def romaya(n):
    if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > 3999:
        raise ValueError("1..3999 arasi tam sayi gerekli")
    out = []
    for deger, harf in _DEGERLER:
        while n >= deger:
            out.append(harf); n -= deger
    return "".join(out)


def romadan(s):
    if not isinstance(s, str) or not s or any(ch not in _HARF for ch in s):
        raise ValueError("gecersiz Roma rakami")
    toplam, i = 0, 0
    while i < len(s):
        v = _HARF[s[i]]
        if i + 1 < len(s) and _HARF[s[i + 1]] > v:
            toplam += _HARF[s[i + 1]] - v; i += 2
        else:
            toplam += v; i += 1
    if toplam < 1 or toplam > 3999 or romaya(toplam) != s:   # gidis-donus: IIII, VX, IM gibi formlari eler
        raise ValueError("gecersiz Roma rakami")
    return toplam
''', "test_roma.py": '''import unittest
from roma import romaya, romadan


class T(unittest.TestCase):
    def test_romaya(self):
        self.assertEqual(romaya(1994), "MCMXCIV"); self.assertEqual(romaya(4), "IV"); self.assertEqual(romaya(3999), "MMMCMXCIX")

    def test_romadan(self):
        self.assertEqual(romadan("MCMXCIV"), 1994); self.assertEqual(romadan("LVIII"), 58)

    def test_gecersiz(self):
        for f in (lambda: romaya(0), lambda: romaya(4000), lambda: romadan(""), lambda: romadan("IIII"),
                  lambda: romadan("VX"), lambda: romadan("mcmxciv")):
            self.assertRaises(ValueError, f)

    def test_gidis_donus(self):
        self.assertTrue(all(romadan(romaya(i)) == i for i in range(1, 4000)))
'''},
"satis": {"satis.py": '''def kategori_toplam(satirlar):
    toplam = {}
    for s in satirlar:
        k = str(s["kategori"]).strip().lower()
        toplam[k] = toplam.get(k, 0.0) + float(s["adet"]) * float(s["fiyat"])
    return toplam
''', "test_satis.py": '''import unittest
from satis import kategori_toplam


class T(unittest.TestCase):
    def test_birlestir(self):
        self.assertEqual(kategori_toplam([{"kategori": "Oyuncak", "adet": 2, "fiyat": 10.0},
                                          {"kategori": "oyuncak ", "adet": 1, "fiyat": 5.0}]), {"oyuncak": 25.0})

    def test_bos(self):
        self.assertEqual(kategori_toplam([]), {})

    def test_adet_sifir(self):
        self.assertEqual(kategori_toplam([{"kategori": "x", "adet": 0, "fiyat": 9.0}]), {"x": 0.0})
'''},
"fib_onar": {"fib.py": '''def fib(n):
    """n. Fibonacci sayisi: fib(0)=0, fib(1)=1."""
    if n < 0:
        raise ValueError("n >= 0 olmali")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
''', "test_fib.py": '''import unittest
from fib import fib


class T(unittest.TestCase):
    def test_degerler(self):
        self.assertEqual([fib(i) for i in range(6)], [0, 1, 1, 2, 3, 5]); self.assertEqual(fib(10), 55)

    def test_negatif(self):
        self.assertRaises(ValueError, fib, -1)
'''},
"kelime": {"kelime.py": '''import re
from collections import Counter


def en_sik(metin, n):
    if n <= 0:
        return []
    kelimeler = re.findall(r"[^\\W\\d_]+", metin.lower())
    sayim = Counter(kelimeler)
    return sorted(sayim.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
''', "test_kelime.py": '''import unittest
from kelime import en_sik


class T(unittest.TestCase):
    def test_temel(self):
        self.assertEqual(en_sik("a b a c b a", 2), [("a", 3), ("b", 2)])

    def test_noktalama_ve_harf(self):
        self.assertEqual(en_sik("Bir, bir! BIR? iki", 1), [("bir", 3)])

    def test_esitlik_alfabetik(self):
        self.assertEqual(en_sik("z y x", 3), [("x", 1), ("y", 1), ("z", 1)])

    def test_sinirlar(self):
        self.assertEqual(en_sik("", 3), []); self.assertEqual(en_sik("a b", 10), [("a", 1), ("b", 1)])
'''},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--usd-try", type=float, default=41.0)
    ap.add_argument("--giris-usd", type=float, default=3.0, help="USD / 1M girdi tokeni (Sonnet liste)")
    ap.add_argument("--cikis-usd", type=float, default=15.0, help="USD / 1M cikti tokeni (Sonnet liste)")
    a = ap.parse_args()
    kok = os.path.join(ROOT, ".apprentice_test_home", "maliyet_B")
    rapor = {}
    t_ok = t_n = 0
    for ad, dosyalar in COZUMLER.items():
        g = K.GOREVLER[ad]
        work = os.path.join(kok, ad)
        if os.path.isdir(work):
            shutil.rmtree(work)
        os.makedirs(work)
        for dn, icerik in (g.get("on_dosyalar") or {}).items():
            with open(os.path.join(work, dn), "w", encoding="utf-8", newline="\n") as f:
                f.write(icerik)
        for dn, icerik in dosyalar.items():
            with open(os.path.join(work, dn), "w", encoding="utf-8", newline="\n") as f:
                f.write(icerik)
        son = K.gizli_kontrol(work, g["modul"], g["gizli"])
        gecen = sum(1 for _, ok, _ in son if ok)
        girdi = g["gorev"] + "\n".join(g["kriterler"]) + "".join((g.get("on_dosyalar") or {}).values())
        cikti = "".join(dosyalar.values())
        gt, ct = len(girdi) // 4, len(cikti) // 4
        usd = gt / 1e6 * a.giris_usd + ct / 1e6 * a.cikis_usd
        rapor[ad] = {"gizli": "%d/%d" % (gecen, len(son)), "girdi_tok~": gt, "cikti_tok~": ct,
                     "maliyet_usd~": round(usd, 5), "maliyet_tl~": round(usd * a.usd_try, 4),
                     "ihlal": [x for x, ok, _ in son if not ok]}
        t_ok += gecen; t_n += len(son)
        print("%-9s gizli %s  girdi~%d tok  cikti~%d tok  %.4f TL %s" % (ad, rapor[ad]["gizli"], gt, ct, rapor[ad]["maliyet_tl~"],
                                                                          rapor[ad]["ihlal"] or ""))
    yol = os.path.join(ROOT, "tests", "maliyet_kampanya.son.json")
    try:
        with open(yol, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d["B"] = {"fiyat": {"giris_usd_M": a.giris_usd, "cikis_usd_M": a.cikis_usd, "usd_try": a.usd_try,
                        "not": "liste fiyati x kestirim token (4 kar/token); Claude Code sistem istemi/baglam dahil DEGIL"},
              "gorevler": rapor, "toplam_gizli": "%d/%d" % (t_ok, t_n),
              "toplam_tl~": round(sum(r["maliyet_tl~"] for r in rapor.values()), 4)}
    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("TOPLAM B: gizli %d/%d, ~%.4f TL (liste fiyati)" % (t_ok, t_n, d["B"]["toplam_tl~"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
