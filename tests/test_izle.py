"""Izleyici testleri - GPU GEREKMEZ. Veri katmani cevrimdisi, GUI duman testi surec olarak.

    python tests/test_izle.py
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import izle  # noqa: E402

HOME = os.path.join(ROOT, ".apprentice_test_home", "izle_unit")


def sahte_is(jid: str, olaylar: list, gorev="deneme gorevi"):
    d = os.path.join(HOME, "jobs", jid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "job.json"), "w", encoding="utf-8") as f:
        json.dump({"id": jid, "ortam": "code", "gorev": gorev, "dogrulama": "derleme",
                   "baslangic": time.time() - 5}, f)
    with open(os.path.join(d, "events.jsonl"), "w", encoding="utf-8") as f:
        for e in olaylar:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def main() -> int:
    if os.path.isdir(HOME):
        shutil.rmtree(HOME)
    sahte_is("20260824-100000-aaaaaa", [
        {"type": "baglam", "sistem": 1450, "hafiza": 231, "durum": 574, "harita": 0,
         "araclar": ["read_file", "write_file", "list_files", "ara"]},
        {"type": "tool", "name": "read_file", "detail": "stok.py"},
        {"type": "tool_result", "text": "def stok_ekle..."},
        {"type": "write", "path": "stok.py", "after": "x = 1\ny = 2\n"},
        {"type": "tool_result", "name": "write_file", "text": json.dumps(
            {"ok": True, "path": "stok.py", "bytes": 12,
             "derleme": "temiz - bu dosyada yapacak is kalmadiysa tekrar yazma"})},
        {"type": "tool_result", "name": "write_file", "text": json.dumps(
            {"ok": True, "path": "stok.py", "degisiklik": False, "uyari": "AYNI ICERIK..."})},
        {"type": "onarim", "tur": 1, "mesaj": "unittest testleri: 1 failed"},
        {"type": "assistant", "text": "stok_tasi eklendi"},
        {"type": "result", "ok": True, "rounds": 0, "wall": 38.2, "errors": [],
         "kullanim": {"prompt_tokens": 5178, "gen_tokens": 700, "model_cagrisi": 3},
         "ruff": None, "duragan": False},
        {"type": "usta_rapor", "derleme_durumu": "derlendi", "dosya": ["stok.py"],
         "uyarilar": [], "kullanim": {"prompt_tokens": 5178}},
        {"type": "exit", "code": 0}])
    sahte_is("20260824-110000-bbbbbb", [
        {"type": "tool", "name": "write_file", "args": {"path": "a.py"}},
        {"type": "result", "ok": False, "rounds": 2, "wall": 600.0,
         "errors": ["DURAGANLIK: ayni test hatalari"], "duragan": True,
         "kullanim": {"prompt_tokens": 45684}},
        {"type": "exit", "code": 2}])

    depo = izle.IsDeposu(HOME)
    adlar = depo.is_listesi()
    assert adlar[0].startswith("20260824-11"), adlar          # en yeni ustte
    for jid in adlar:
        assert depo.tazele(jid) is True
    s1 = depo.durumlar["20260824-100000-aaaaaa"]
    assert s1["durum"] == "bitti" and s1["derleme"] == "derlendi" and s1["tur"] == 1
    assert s1["kullanim"]["prompt_tokens"] == 5178
    assert s1["asama"] == "usta", s1["asama"]                       # boru hattinin sonu
    assert s1["baglam"]["hafiza"] == 231 and s1["baglam"]["durum"] == 574
    assert s1["sayac"]["noop"] == 1 and s1["sayac"]["onarim"] == 1, s1["sayac"]
    assert s1["son_yazim"]["path"] == "stok.py" and "y = 2" in s1["son_yazim"]["icerik"]
    assert s1["ozet"] == "stok_tasi eklendi"
    s2 = depo.durumlar["20260824-110000-bbbbbb"]
    assert s2["derleme"] == "hata" and any("DURAGANLIK" in str(u) for u in s2["uyarilar"]), s2
    print("veri katmani: ok")

    # artimli okuma: ayni dosyada yeni satir -> yalnizca o islenir
    with open(os.path.join(HOME, "jobs", "20260824-110000-bbbbbb", "events.jsonl"),
              "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "tool", "name": "run_tests"}) + "\n")
    n_once = len(depo.olaylar["20260824-110000-bbbbbb"])
    assert depo.tazele("20260824-110000-bbbbbb") is True
    assert len(depo.olaylar["20260824-110000-bbbbbb"]) == n_once + 1
    assert depo.tazele("20260824-110000-bbbbbb") is False      # degisiklik yok
    print("artimli okuma: ok")

    # olay satirlari renk siniflari
    et, m = izle.olay_satiri({"type": "write", "path": "a.py", "after": "x\n"})
    assert et == "yazim" and "YAZDI a.py" in m
    et, _ = izle.olay_satiri({"type": "error", "message": "patladi"})
    assert et == "hata"
    et, m = izle.olay_satiri({"type": "result", "ok": True, "rounds": 0, "wall": 10})
    assert et == "sonuc" and "derlendi" in m
    et, m = izle.olay_satiri({"type": "baglam", "sistem": 1450, "hafiza": 231, "durum": 574,
                              "harita": 0, "araclar": ["read_file"]})
    assert "BAGLAM" in m and "231" in m
    et, m = izle.olay_satiri({"type": "duraganlik", "imza_sayisi": 1, "tur": 1})
    assert et == "hata" and "USTAYA devir" in m
    et, m = izle.olay_satiri({"type": "usta_rapor", "derleme_durumu": "derlendi",
                              "dosya": ["a.py"], "uyarilar": ["duragan"], "kullanim": {}})
    assert et == "sonuc" and "USTAYA RAPOR" in m and "duragan" in m
    # kanit ayristirici
    k = izle.kanit_coz(json.dumps({"ok": True, "path": "a.py",
                                   "derleme": "temiz - ...", "ruff": ["a.py:2:1: F821 Undefined name `x`"]}))
    assert k and k["etiket"] == "hata" and "F821" in k["metin"], k
    k = izle.kanit_coz(json.dumps({"error": "yazma izni yok: b.py"}))
    assert k and k["sayac"] == "izin_red"
    print("olay satirlari + kanit ayristirici: ok")

    # GUI duman testi: surec 4 sn ayakta kalmali (aninda cokme = kurulum hatasi)
    p = subprocess.Popen([sys.executable, "-B", os.path.join(ROOT, "izle.py"), "--home", HOME],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(4)
    if p.poll() is not None:
        print("GUI COKTU:", (p.stderr.read() or b"").decode("utf-8", "replace")[:400])
        return 1
    p.terminate()
    print("GUI duman testi: ok (4 sn ayakta)")
    print("SONUC: GECTI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
