"""Lider takibi gorevi icin denetci olcumu (tests/suru_kabul.py ile ayni yontem).

    python tests/lider_olc.py [--saniye 15]
Her ornekte: n, min_cift (kureler arasi XZ), min_lider, max_lider (kure-lider XZ), max_abs_xz,
lider_x, lider_z. Kriter: 1.5<=d_lider<=4, cift>=1.5, |xz|<=7, lider hareketli.
Sonuc: tests/lider_olc.son.json
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
from mcpbridge.http_client import MCPHttpServer  # noqa: E402
import unity_code as UC  # noqa: E402

CS = r'''
var g = UnityEngine.GameObject.Find("Suru"); var l = UnityEngine.GameObject.Find("Lider");
if (g == null) return "SURU_YOK"; if (l == null) return "LIDER_YOK";
var ps = new System.Collections.Generic.List<UnityEngine.Vector3>();
foreach (UnityEngine.Transform t in g.transform) ps.Add(t.position);
var lp = l.transform.position; lp.y = 0;
float minc = float.MaxValue, minl = float.MaxValue, maxl = 0f, mabs = 0f;
for (int i = 0; i < ps.Count; i++) {
  var a = ps[i]; a.y = 0;
  mabs = UnityEngine.Mathf.Max(mabs, UnityEngine.Mathf.Abs(a.x), UnityEngine.Mathf.Abs(a.z));
  float dl = UnityEngine.Vector3.Distance(a, lp); minl = UnityEngine.Mathf.Min(minl, dl); maxl = UnityEngine.Mathf.Max(maxl, dl);
  for (int j = i + 1; j < ps.Count; j++) { var b = ps[j]; b.y = 0; minc = UnityEngine.Mathf.Min(minc, UnityEngine.Vector3.Distance(a, b)); }
}
var ic = System.Globalization.CultureInfo.InvariantCulture;
return "n=" + ps.Count + ";min_cift=" + minc.ToString("0.000", ic) + ";min_lider=" + minl.ToString("0.000", ic) + ";max_lider=" + maxl.ToString("0.000", ic) + ";max_abs=" + mabs.ToString("0.000", ic) + ";lx=" + l.transform.position.x.ToString("0.00", ic) + ";lz=" + l.transform.position.z.ToString("0.00", ic);
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saniye", type=int, default=15)
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
            d = dict(kv.split("=") for kv in s.split(";"))
            rows.append({k: (int(v) if k == "n" else float(v)) for k, v in d.items()})
        except Exception:
            rows.append({"ham": s})
    ok_rows = [x for x in rows if "ham" not in x]
    say = {
        "ornek": len(rows), "hata": r.get("error") or r.get("hatalar"),
        "lider_ihlal": sum(1 for x in ok_rows if x["min_lider"] < 1.5 or x["max_lider"] > 4.0),
        "cift_ihlal": sum(1 for x in ok_rows if x["min_cift"] < 1.5),
        "sinir_ihlal": sum(1 for x in ok_rows if x["max_abs"] > 7.0),
        "min_lider": min((x["min_lider"] for x in ok_rows), default=None),
        "max_lider": max((x["max_lider"] for x in ok_rows), default=None),
        "min_cift": min((x["min_cift"] for x in ok_rows), default=None),
        "max_abs": max((x["max_abs"] for x in ok_rows), default=None),
        "lider_hareketli": len({(x["lx"], x["lz"]) for x in ok_rows}) > 1,
    }
    for s in r.get("ornekler") or []:
        print("  ", s)
    print(json.dumps(say, ensure_ascii=False))
    gecti = bool(ok_rows) and say["lider_ihlal"] == 0 and say["cift_ihlal"] == 0 and say["sinir_ihlal"] == 0 and say["lider_hareketli"]
    print("SONUC:", "GECTI" if gecti else "KALDI")
    with open(os.path.join(BURASI, "lider_olc.son.json"), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), "ozet": say, "ornekler": rows,
                            "gecti": gecti}, ensure_ascii=False) + "\n")
    return 0 if gecti else 1


if __name__ == "__main__":
    sys.exit(main())
