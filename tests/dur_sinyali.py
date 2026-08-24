"""Dur sinyali olcumu: dogrulanamaz gorevde isci artik durabiliyor mu?

    python tests/dur_sinyali.py     # Ollama gerekir

Tetris kazasinin (is 20260823-183654-fc8dc1) yeniden uretimi: pygame'li interaktif oyun,
dogrulama="derleme", izin listesi yok — o gun isci ayni dosyayi 10 kez yazdi (880 s, 150k token,
ozet yok). O gunden beri iki katman eklendi: yazim aninda derleme kaniti cevapta + bos yazma
korumasi. Iddia: ayni dosyaya yazim sayisi 1-2'ye iner ve isci OZET yazarak durur.
"""
from __future__ import annotations
import collections, json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
try:      # pencereli exe/pythonw: sys.stdout None olabilir (kurulum oz-testi
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # bu satirda cokuyordu)
except Exception:
    pass
from test_server import Client  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home")
KOK = os.path.join(HOME, "dur_sinyali")

GOREV = """Bu klasore pygame ile calisan basit bir Tetris oyunu yaz.

Dosyalar:
- tetris.py — ana oyun (pygame penceresi, oyun dongusu, giris)
- requirements.txt — pygame surumu

Oyun gereksinimleri:
- 800x600 pencere, koyu arka plan
- 10x20 oyun alani (grid), kenarda skor gosterimi
- 7 klasik tetromino (I,O,T,S,Z,J,L), renkli bloklar
- Klavye: sol/sag ok = yatay hareket, asagi ok = soft drop, yukari ok veya X = dondurme,
  Space = hard drop, P = pause, R = restart (game over sonrasi), Esc = cikis
- Aktif parca zemine veya baska bloga deginca kilitlenir; yeni parca spawn olur
- Dolu satir silinir, ust satirlar asagi kayar, skor artar (tek=100, cift=300, uclu=500, tetris=800)
- Ustte yeni parca sigmazsa game over; ekranda GAME OVER ve R ile restart metni
- Kod: tek dosyada self-contained tetris.py"""

KRITERLER = ["tetris.py sozdizimi hatasiz derlenir",
             "Tum tus atamalarini ve skor tablosunu icerir",
             "Yalnizca tetris.py ve requirements.txt yazilir"]


def main() -> int:
    if os.path.isdir(KOK):
        shutil.rmtree(KOK)
    os.makedirs(KOK)
    c = Client({"APPRENTICE_HOME": HOME})
    c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                          "clientInfo": {"name": "dur-sinyali", "version": "0"}})
    c.notify("notifications/initialized")
    req = json.loads(c.p.stdout.readline().decode("utf-8"))
    uri = "file:///" + HOME.replace("\\", "/")
    c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"roots": [{"uri": uri, "name": "home"}]}}) + chr(10)).encode())
    c.p.stdin.flush(); time.sleep(0.4)

    try:
        t0 = time.time()
        rep = c.tool("worker_run", {"gorev": GOREV, "kabul_kriterleri": KRITERLER, "ortam": "code",
                                    "calisma_dizini": "dur_sinyali", "dogrulama": "derleme",
                                    "zaman_asimi_s": 1200}, timeout=1500)["structuredContent"]
        sure = time.time() - t0
    finally:
        c.close()

    yazimlar = collections.Counter()
    for a in rep.get("araclar", []):
        if a.startswith("write_file"):
            yazimlar[os.path.basename(a.split(" ", 1)[1].strip())] += 1
    ku = rep.get("kullanim") or {}
    en_cok = yazimlar.most_common(1)[0] if yazimlar else ("-", 0)
    rapor = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), "sure_s": round(sure, 1),
             "derleme_durumu": rep.get("derleme_durumu"),
             "prompt_tok": ku.get("prompt_tokens"), "uretim_tok": ku.get("gen_tokens"),
             "yazim_sayilari": dict(yazimlar), "ayni_dosyaya_en_cok": en_cok[1],
             "ozet_var": bool((rep.get("ozet") or "").strip()), "hatalar": rep.get("hatalar", []),
             "araclar": rep.get("araclar", []), "is_id": rep.get("is_id"),
             "kiyas_2026_08_23_kazasi": {"ayni_dosyaya": 10, "sure_s": 880, "ozet_var": False}}
    yol = os.path.join(ROOT, "tests", "dur_sinyali.son.json")
    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    print(json.dumps(rapor, ensure_ascii=False, indent=1))
    print("\nKIYAS: kaza gunu ayni dosyaya 10 yazim / 880 s / ozet yok  ->  simdi %d yazim / %.0f s / ozet %s"
          % (en_cok[1], sure, "VAR" if rapor["ozet_var"] else "YOK"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
