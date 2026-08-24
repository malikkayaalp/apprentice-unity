"""Ilk calistirma olcumu: bu makinede num_batch icin en iyi degeri bul, ayar dosyasina yaz.

    python core/olcum.py [--model M] [--batches 512,1024,2048,4096] [--tokens 12000] [--yaz]

Neden: num_batch prefill hizini belirler (olculen: 512=189 t/s, 4096=730 t/s, +%285) ama
VRAM harcar; kucuk kartta sigmayabilir. Deger donanima ozel, kopyalanmamali - sablondaki
"makine" bolumu bu yuzden "ilk calistirmada olc" der. Bu betik her num_batch icin UZUN bir
promptla (kisa promptla olcum yaniltir: tek batch'e sigar) /api/generate cagirir,
prompt_eval_count / prompt_eval_duration'dan t/s hesaplar, en hizli ve hatasiz olani secer.

Onbellek tuzagi: Ollama ayni prefix'i yeniden islemez. Her kosuda prompt'un BASINA
benzersiz bir damga konur ki tam prefill olculsun.

--yaz: apprentice.config.json'daki "makine" bolumunu gunceller (dosya yoksa sablondan
olusturur). Yazmazsa yalnizca raporlar.
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.request, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import config  # noqa: E402


def _post(url: str, body: dict, timeout: float = 600) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def uzun_prompt(hedef_token: int) -> str:
    # ~4 karakter/token varsayimi; kod benzeri metin (gercek is yuku: arac blogu + dosyalar)
    satir = ("class Ornek%d:\n    def guncelle(self, dt):\n        self.konum = "
             "(self.konum[0] + %d * dt, self.konum[1] + %d * dt)\n\n")
    parcalar, n, i = [], 0, 0
    while n < hedef_token * 4:
        s = satir % (i, i % 7, i % 5)
        parcalar.append(s)
        n += len(s)
        i += 1
    return "".join(parcalar) + "\nYukaridaki siniflardan kacinin guncelle metodu var? Tek sayi yaz."


def olc(base: str, model: str, num_batch: int, num_ctx: int, prompt: str) -> dict:
    damga = "// olcum %s\n" % uuid.uuid4().hex
    t0 = time.time()
    try:
        r = _post(base + "/api/generate", {
            "model": model, "prompt": damga + prompt, "stream": False,
            "options": {"num_batch": num_batch, "num_ctx": num_ctx, "num_predict": 8,
                        "temperature": 0}, "keep_alive": "10m"})
    except Exception as e:
        return {"num_batch": num_batch, "hata": str(e)[:200]}
    pe, pd = r.get("prompt_eval_count", 0), r.get("prompt_eval_duration", 0)
    return {"num_batch": num_batch, "prompt_token": pe,
            "prefill_tps": round(pe / (pd / 1e9), 1) if pd else None,
            "prefill_s": round(pd / 1e9, 1) if pd else None,
            "toplam_s": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=config.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model"))
    ap.add_argument("--url", default=(config.get("ollama.url") or "http://localhost:11434").rstrip("/"))
    ap.add_argument("--batches", default="512,1024,2048,4096")
    ap.add_argument("--tokens", type=int, default=12000)
    ap.add_argument("--ctx", type=int, default=config.get("makine.num_ctx", 65536))
    ap.add_argument("--yaz", action="store_true")
    a = ap.parse_args()

    prompt = uzun_prompt(a.tokens)
    sonuc = []
    print("model %s, ~%d token prompt, ctx %d" % (a.model, a.tokens, a.ctx), flush=True)
    for b in [int(x) for x in a.batches.split(",") if x.strip()]:
        r = olc(a.url, a.model, b, a.ctx, prompt)
        sonuc.append(r)
        print("  num_batch %5d: %s" % (b, "HATA %s" % r["hata"] if "hata" in r else
                                      "%s t/s prefill (%s s, %s token)" % (r["prefill_tps"], r["prefill_s"], r["prompt_token"])),
              flush=True)
    iyi = [r for r in sonuc if r.get("prefill_tps")]
    if not iyi:
        print("olcum alinamadi")
        return 1
    en = max(iyi, key=lambda r: r["prefill_tps"])
    print("secim: num_batch=%d (%s t/s)" % (en["num_batch"], en["prefill_tps"]))

    if a.yaz:
        up = config.user_path()
        cfg = {}
        if os.path.exists(up):
            with open(up, encoding="utf-8") as f:
                cfg = json.load(f)
        else:
            with open(config.TEMPLATE, encoding="utf-8") as f:
                cfg = json.load(f)
        mk = cfg.setdefault("makine", {})
        mk["num_batch"] = en["num_batch"]
        mk["num_ctx"] = a.ctx
        mk["ilk_calistirmada_olc"] = False
        mk["olcum"] = {"tarih": time.strftime("%Y-%m-%d %H:%M"), "model": a.model,
                       "prompt_token": a.tokens, "sonuclar": sonuc}
        try:
            import subprocess
            gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 creationflags=0x08000000 if os.name == "nt" else 0,
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            mk["olculdugu_gpu"] = gpu
        except Exception:
            pass
        with open(up, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print("yazildi:", up)
    return 0


if __name__ == "__main__":
    sys.exit(main())
