"""Devriye gorevi (Cursor A/B) icin denetci olcumu.

    python tests/devriye_olc.py [--saniye 15] [--etiket A]
Kriterler: her kure merkezden 4.0+-0.1; komsu acilari 45+-3 derece; saat yonunde; tur 12+-1 sn; y=0.5.
Sonuc: tests/devriye_olc.son.json (satir basina bir kosu, etiketli).
"""
from __future__ import annotations
import argparse, json, math, os, sys, time

BURASI = os.path.dirname(os.path.abspath(__file__))
UNITY = os.path.dirname(BURASI)                      # apprentice-unity koku (= apprentice/envs/unity)
KOK = os.path.dirname(os.path.dirname(UNITY))        # apprentice koku (core/, mcpbridge/, server/)
for _p in (KOK, UNITY, os.path.join(KOK, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from mcpbridge.http_client import MCPHttpServer  # noqa: E402
import unity_code as UC  # noqa: E402

CS = r'''
var g = UnityEngine.GameObject.Find("Suru"); if (g == null) return "SURU_YOK";
var ic = System.Globalization.CultureInfo.InvariantCulture;
var sb = new System.Text.StringBuilder();
sb.Append("t=").Append(UnityEngine.Time.time.ToString("0.000", ic));
foreach (UnityEngine.Transform tr in g.transform) {
  var p = tr.position;
  sb.Append(";").Append(p.x.ToString("0.000", ic)).Append(",").Append(p.y.ToString("0.000", ic)).Append(",").Append(p.z.ToString("0.000", ic));
}
return sb.ToString();
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saniye", type=int, default=15)
    ap.add_argument("--etiket", default="")
    a = ap.parse_args()
    srv = MCPHttpServer(UC.U.URL)
    srv.start()
    try:
        r = UC.play_observe(srv, CS, saniye=a.saniye, zaman_asimi=60)
    finally:
        try:
            UC._oyna(srv, "UnityEditor.EditorApplication.isPlaying = false; return \"ok\";")
        except Exception:
            pass
        srv.stop()
    rows = []
    for s in r.get("ornekler") or []:
        try:
            parts = s.split(";")
            t = float(parts[0].split("=")[1])
            pts = [tuple(float(v) for v in p.split(",")) for p in parts[1:]]
            rows.append((t, pts))
        except Exception:
            pass
    yar_ihlal = aci_ihlal = y_ihlal = 0
    yarlar, acilar = [], []
    for t, pts in rows:
        angs = sorted(math.degrees(math.atan2(z, x)) % 360 for x, y, z in pts)
        for x, y, z in pts:
            rr = math.hypot(x, z); yarlar.append(rr)
            if abs(rr - 4.0) > 0.1: yar_ihlal += 1
            if abs(y - 0.5) > 0.05: y_ihlal += 1
        for i in range(len(angs)):
            d = (angs[(i + 1) % len(angs)] - angs[i]) % 360
            acilar.append(d)
            if abs(d - 45) > 3: aci_ihlal += 1
    # tur suresi ve yon: ilk kurenin acisinin zamana gore degisimi
    tur = yon = None
    if len(rows) >= 2:
        # Ardisik orneklerle sarmasiz birikim (ilk/son farki 180 dereceyi asinca sarar -
        # olculdu: 450 derecelik donus 38 sn/tur ve ters yon diye okundu).
        toplam = 0.0
        for (ta, pa), (tb, pb) in zip(rows, rows[1:]):
            a0 = math.degrees(math.atan2(pa[0][2], pa[0][0]))
            a1 = math.degrees(math.atan2(pb[0][2], pb[0][0]))
            toplam += (a1 - a0 + 180) % 360 - 180
        dt = rows[-1][0] - rows[0][0]
        hiz = toplam / dt if dt > 0 else 0  # derece/sn
        # Unity sol-elli, Y yukari: ustten bakinca +X sag, +Z yukari -> atan2(z,x) ARTISI saat
        # yonunun tersi, AZALISI saat yonu (Rotate(0,+90,0) +Z'yi +X'e cevirir = saat yonu).
        # Ilk surum tersini varsaydi; Cursor'daki denetci de ayni hatayi yapip 2 tur harcadi.
        if abs(hiz) > 1e-3:
            tur = 360 / abs(hiz)
            yon = "saat_yonu" if hiz < 0 else "saat_yonu_tersi"
    n = len(rows) * 8 if rows else 0
    say = {"etiket": a.etiket, "ornek": len(rows), "hata": r.get("error") or r.get("hatalar"),
           "yaricap_min": round(min(yarlar), 3) if yarlar else None, "yaricap_max": round(max(yarlar), 3) if yarlar else None,
           "yaricap_ihlal": yar_ihlal, "aci_min": round(min(acilar), 1) if acilar else None,
           "aci_max": round(max(acilar), 1) if acilar else None, "aci_ihlal": aci_ihlal,
           "y_ihlal": y_ihlal, "tur_suresi_s": round(tur, 2) if tur else None, "yon": yon, "nokta": n}
    gecti = bool(rows) and yar_ihlal == 0 and aci_ihlal == 0 and y_ihlal == 0 and tur is not None \
        and abs(tur - 12) <= 1 and yon == "saat_yonu"
    print(json.dumps(say, ensure_ascii=False))
    print("SONUC:", "GECTI" if gecti else "KALDI")
    with open(os.path.join(BURASI, "devriye_olc.son.json"), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), "ozet": say, "gecti": gecti,
                            "ham": r.get("ornekler")}, ensure_ascii=False) + "\n")
    return 0 if gecti else 1


if __name__ == "__main__":
    sys.exit(main())
