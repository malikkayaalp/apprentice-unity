"""MAP (proje haritasi) olcumu: sakli hedefte harita, `ara`ya karsi.

    python tests/map_ab.py      # Ollama gerekir (+B kolu icin bge-m3)

Ayni sakli-hedef senaryosu (rag_ab_sakli): 120 tekduze dosya, kupon fonksiyonu modul_61 icinde.
  A: ara ACIK, harita yok      (mevcut kazanan: 11.2k tok)
  B: harita ACIK, ara kapali   (adres sistem isteminde; embedding yok)
  C: ikisi de acik
Olculen: prompt tok, arac sayisi, sure, gizli 6 kontrol. Karar kurala yazilir.
"""
from __future__ import annotations
import importlib.util, json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from test_server import Client  # noqa: E402

spec = importlib.util.spec_from_file_location("rs", os.path.join(ROOT, "tests", "rag_ab_sakli.py"))
RS = importlib.util.module_from_spec(spec); spec.loader.exec_module(RS)

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "map_ab")


def kosu(c: Client, etiket: str, klasor: str, gorev: str, harita: bool, ara_kapali: bool) -> dict:
    args = {"gorev": gorev, "kabul_kriterleri": RS.KRITERLER, "ortam": "code",
            "calisma_dizini": os.path.join("map_ab", klasor), "dogrulama": "derleme",
            "harita": harita}
    if ara_kapali:
        args["araclar_kapali"] = ["ara"]
    t0 = time.time()
    rep = c.tool("worker_run", args, timeout=1900)["structuredContent"]
    sure = time.time() - t0
    (g, t), cikti = RS.gizli_kontrol(os.path.join(KOK, klasor))
    ku = rep.get("kullanim") or {}
    kayit = {"etiket": etiket, "sure_s": round(sure, 1), "derleme_durumu": rep.get("derleme_durumu"),
             "prompt_tok": ku.get("prompt_tokens"), "uretim_tok": ku.get("gen_tokens"),
             "arac": len(rep.get("araclar", [])), "araclar": rep.get("araclar", []),
             "gizli": "%d/%d" % (g, t), "dosya": [d["yol"] for d in rep.get("yazilan_dosyalar", [])]}
    print("  %-9s %-10s %4.0f s | prompt %6s | arac %d | gizli %d/%d | %s" % (
        etiket, rep.get("derleme_durumu"), sure, ku.get("prompt_tokens"),
        kayit["arac"], g, t, ",".join(a.split()[0] for a in rep.get("araclar", []))[:50]), flush=True)
    return kayit


def main() -> int:
    if os.path.isdir(KOK):
        shutil.rmtree(KOK)
    os.makedirs(KOK)
    for ad in ("A_ara", "B_harita", "C_ikisi"):
        RS.depo_kur(os.path.join(KOK, ad), 120)
    print("depo kuruldu: 3 kol x 120 dosya (hedef modul_61 icinde)", flush=True)

    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "map-ab", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "home"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)

    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        rapor["A_ara"] = kosu(c, "A_ara", "A_ara", RS.GOREV_B, harita=False, ara_kapali=False)
        rapor["B_harita"] = kosu(c, "B_harita", "B_harita", RS.GOREV_A, harita=True, ara_kapali=True)
        rapor["C_ikisi"] = kosu(c, "C_ikisi", "C_ikisi", RS.GOREV_B, harita=True, ara_kapali=False)
    finally:
        c.close()
        yol = os.path.join(ROOT, "tests", "map_ab.son.json")
        with open(yol, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rapor, f, ensure_ascii=False, indent=1)
        print("->", yol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
