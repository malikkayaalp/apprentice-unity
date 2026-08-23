"""Suru kabul testi: denetci-isci deseninin sunucu uzerinden ucta uca kosusu.

    python tests/suru_kabul.py [--tur 5] [--saniye 15]

Rol dagilimi:
  isci     worker_run (yerel model): SuruYoneticisi.cs yazar, Suru'ya ekler, derler.
  denetci  BU BETIK (sabit kurallarla): isin bitiminde play_observe ile 15 sn BAGIMSIZ
           olcer, kriterleri sayiyla degerlendirir, tutmuyorsa olcumu OZETLEYIP ayni
           oturumla yeni worker_run ister. En fazla --tur tur.

Kriterler (denetci yazdi):
  K1  hicbir anda hicbir kure cifti 2 birimden yakin olmasin
  K2  her kurenin |x| ve |z| degeri 5'i asmasin
  K3  15 sn boyunca (her 0.5 sn ornek) K1 ve K2 tutsun

Rapor: tests/suru_kabul.son.json (her turun olcumu) - RAPOR.md bunu okur.
Unity (MagicSort_Case, sahnede Suru + 8 kure) ve Ollama acik olmali. Test sonunda
play modundan cikilir (play_observe bunu kendisi yapar).
"""
from __future__ import annotations
import argparse, json, os, sys, time

BURASI = os.path.dirname(os.path.abspath(__file__))
UNITY = os.path.dirname(BURASI)                      # apprentice-unity koku (= apprentice/envs/unity)
KOK = os.path.dirname(os.path.dirname(UNITY))        # apprentice koku (core/, mcpbridge/, server/)
for _p in (KOK, UNITY, os.path.join(KOK, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from test_server import Client  # noqa: E402
from mcpbridge.http_client import MCPHttpServer  # noqa: E402
import unity_code as UC  # noqa: E402

GOREV = "Suru altındaki 8 küre XZ düzleminde rastgele hareket etsin."
KRITERLER = [
    "Hiçbir anda hiçbir küre çifti birbirine 2 birimden yakın olmasın (merkezler arası mesafe ≥ 2).",
    "Her kürenin |x| ve |z| değeri 5'i aşmasın.",
    "Bunu play_observe ile 15 saniye boyunca doğrula; ölçümü ham raporla.",
    "Script Assets/Scripts/SuruYoneticisi.cs olsun, Suru objesine add_component ile ekle "
    "(küreleri silme, yeniden yaratma).",
]

# Denetcinin olcum kodu: her ornekte min cift mesafesi, max|x|, max|z|, kure sayisi.
OLCUM_CS = r'''
var g = UnityEngine.GameObject.Find("Suru");
if (g == null) return "SURU_YOK";
var ps = new System.Collections.Generic.List<UnityEngine.Vector3>();
foreach (UnityEngine.Transform t in g.transform) ps.Add(t.position);
float min = float.MaxValue, mx = 0f, mz = 0f;
for (int i = 0; i < ps.Count; i++) {
  mx = UnityEngine.Mathf.Max(mx, UnityEngine.Mathf.Abs(ps[i].x));
  mz = UnityEngine.Mathf.Max(mz, UnityEngine.Mathf.Abs(ps[i].z));
  for (int j = i + 1; j < ps.Count; j++) {
    var a = ps[i]; var b = ps[j]; a.y = 0; b.y = 0;
    min = UnityEngine.Mathf.Min(min, UnityEngine.Vector3.Distance(a, b));
  }
}
var ic = System.Globalization.CultureInfo.InvariantCulture;
return "n=" + ps.Count + ";min=" + min.ToString("0.000", ic) + ";maxx=" + mx.ToString("0.000", ic) + ";maxz=" + mz.ToString("0.000", ic);
'''


def olc(saniye: int) -> dict:
    srv = MCPHttpServer(UC.U.URL)
    srv.start()
    try:
        r = UC.play_observe(srv, OLCUM_CS, saniye=saniye, zaman_asimi=60)
    finally:
        srv.stop()
    return r


def degerlendir(r: dict) -> dict:
    ornek = r.get("ornekler") or []
    satir = []
    for s in ornek:
        try:
            d = dict(kv.split("=") for kv in s.split(";"))
            satir.append({"n": int(d["n"]), "min": float(d["min"]),
                          "maxx": float(d["maxx"]), "maxz": float(d["maxz"])})
        except Exception:
            pass
    k1_ihlal = sum(1 for s in satir if s["min"] < 2.0)
    k2_ihlal = sum(1 for s in satir if s["maxx"] > 5.0 or s["maxz"] > 5.0)
    hareket = len({round(s["min"], 3) for s in satir}) > 1 if satir else False
    return {
        "ornek_sayisi": len(satir), "hata": r.get("error") or r.get("hatalar") or [],
        "en_kucuk_mesafe": min((s["min"] for s in satir), default=None),
        "max_abs_x": max((s["maxx"] for s in satir), default=None),
        "max_abs_z": max((s["maxz"] for s in satir), default=None),
        "K1_ihlal_ornek": k1_ihlal, "K2_ihlal_ornek": k2_ihlal,
        "hareket_var": hareket,
        "K1": bool(satir) and k1_ihlal == 0,
        "K2": bool(satir) and k2_ihlal == 0,
        "K3": bool(satir) and len(satir) >= 10 and k1_ihlal == 0 and k2_ihlal == 0 and hareket,
        "ornekler": ornek,
    }


def ozet_geri_bildirim(d: dict) -> str:
    """Denetcinin isciye verdigi OZET (ham veri degil) - olculen calisan desen."""
    p = []
    if not d["ornek_sayisi"]:
        p.append("Ölçüm alınamadı: %s" % d["hata"])
    if d["ornek_sayisi"] and not d["hareket_var"]:
        p.append("Küreler HAREKET ETMİYOR (15 sn boyunca konumlar sabit). Script Suru'ya "
                 "eklenmemiş ya da Update'te hareket yok. add_component ile Suru'ya ekle.")
    if d["K1_ihlal_ornek"]:
        p.append("K1 İHLAL: %d/%d örnekte bir çift 2 birimden yakın; en küçük mesafe %.2f. "
                 "Yumuşak itme yetmez, SERT kısıt gerek: her adımda yeni konumu önce "
                 "dene, 2 birimden yakın düşüyorsa o adımı ATLA ya da yön değiştir."
                 % (d["K1_ihlal_ornek"], d["ornek_sayisi"], d["en_kucuk_mesafe"]))
    if d["K2_ihlal_ornek"]:
        p.append("K2 İHLAL: %d/%d örnekte |x| ya da |z| > 5 (max |x|=%.2f, |z|=%.2f). "
                 "Konumu Mathf.Clamp ile [-5,5] içinde tut ve sınırda yönü tersine çevir."
                 % (d["K2_ihlal_ornek"], d["ornek_sayisi"], d["max_abs_x"], d["max_abs_z"]))
    return "DENETÇİ ÖLÇÜMÜ (15 sn, her 0.5 sn):\n- " + "\n- ".join(p) + \
        "\n\nSuruYoneticisi.cs'yi read_script ile oku, yalnızca gerekli yeri düzelt, " \
        "write_script ile TAM dosyayı yaz. Başlangıç konumlarını da 2 birim aralıklı ver."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tur", type=int, default=5)
    ap.add_argument("--saniye", type=int, default=15)
    a = ap.parse_args()

    rapor = {"baslangic": time.strftime("%Y-%m-%d %H:%M:%S"), "gorev": GOREV,
             "kriterler": KRITERLER, "turlar": []}
    yol = os.path.join(BURASI, "suru_kabul.son.json")

    print("0) baslangic olcumu (script yokken)")
    d0 = degerlendir(olc(min(5, a.saniye)))
    print("   ornek=%d min=%s hareket=%s" % (d0["ornek_sayisi"], d0["en_kucuk_mesafe"], d0["hareket_var"]))
    rapor["baslangic_olcumu"] = {k: v for k, v in d0.items() if k != "ornekler"}

    c = Client()
    gecti = False
    try:
        c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "suru_kabul", "version": "0"}})
        c.notify("notifications/initialized")
        oturum = ""
        gorev = GOREV
        for tur in range(1, a.tur + 1):
            print("\n%d) worker_run (oturum=%s)" % (tur, oturum or "yeni"))
            t0 = time.time()
            rep = c.tool("worker_run", {"gorev": gorev, "kabul_kriterleri": KRITERLER,
                                        "ortam": "unity", "play": False, "oturum": oturum},
                         timeout=1900)["structuredContent"]
            oturum = rep.get("oturum") or oturum
            print("   derleme=%s tur=%s sure=%.0fs dosyalar=%s araclar=%d olcum=%d" % (
                rep.get("derleme_durumu"), rep.get("tur_sayisi"), rep.get("sure", 0),
                [d["yol"] for d in rep.get("yazilan_dosyalar", [])],
                len(rep.get("araclar", [])), len(rep.get("olcumler", []))))
            if rep.get("hatalar"):
                print("   hatalar:", rep["hatalar"][:3])
            print("   ozet:", (rep.get("ozet") or "")[:300].replace("\n", " "))

            kayit = {"tur": tur, "isci": {k: rep.get(k) for k in (
                "derleme_durumu", "hatalar", "tur_sayisi", "sure", "yazilan_dosyalar",
                "araclar", "is_id", "oturum")}, "isci_ozet": rep.get("ozet"),
                "isci_olcum_sayisi": len(rep.get("olcumler", []))}

            if rep.get("derleme_durumu") != "derlendi":
                print("   derlenmedi -> olcum atlanir, onarim istenir")
                kayit["denetci"] = None
                gorev = ("Önceki tur derlenmedi: %s. Hatayı düzelt." %
                         "; ".join(rep.get("hatalar", [])[:3]))
                rapor["turlar"].append(kayit)
                continue

            print("   denetci olcumu (%d sn)..." % a.saniye)
            d = degerlendir(olc(a.saniye))
            kayit["denetci"] = {k: v for k, v in d.items() if k != "ornekler"}
            kayit["denetci_ornekler"] = d["ornekler"]
            print("   ornek=%d min=%s maxx=%s maxz=%s K1=%s(%d ihlal) K2=%s(%d ihlal) K3=%s hareket=%s" % (
                d["ornek_sayisi"], d["en_kucuk_mesafe"], d["max_abs_x"], d["max_abs_z"],
                d["K1"], d["K1_ihlal_ornek"], d["K2"], d["K2_ihlal_ornek"], d["K3"], d["hareket_var"]))
            rapor["turlar"].append(kayit)
            if d["K1"] and d["K2"] and d["K3"]:
                gecti = True
                print("   KABUL: butun kriterler tuttu")
                break
            gorev = ozet_geri_bildirim(d)
            print("   geri bildirim:", gorev[:200].replace("\n", " "))
    finally:
        c.close()
        rapor["gecti"] = gecti
        rapor["bitis"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(yol, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rapor, f, ensure_ascii=False, indent=1)
        # Play modunda birakma: play_observe zaten cikar; yine de garanti
        try:
            srv = MCPHttpServer(UC.U.URL)
            srv.start()
            UC._oyna(srv, "UnityEditor.EditorApplication.isPlaying = false; return \"ok\";")
            srv.stop()
        except Exception:
            pass
    print("\nSONUC:", "GECTI" if gecti else "KALDI", "->", yol)
    return 0 if gecti else 1


if __name__ == "__main__":
    sys.exit(main())
