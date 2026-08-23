"""Unity API aramasi olcumu: gercekci sorgularda dogru API ilk k sonucta cikiyor mu?

    python envs/unity/tests/test_api_rag.py            # BM25 (GPU yok)
    python envs/unity/tests/test_api_rag.py --rerank   # + bge-m3 ile yeniden siralama (Ollama gerekir)

Her satir: (sorgu, beklenen uye adinin bir parcasi). Isabet = beklenen, ilk k sonuctan birinde.
Hit@8 dusukse BM25 tek basina yetmiyor demektir; o zaman yeniden siralama (rerank) acilir.
"""
from __future__ import annotations
import os, sys, time

BURASI = os.path.dirname(os.path.abspath(__file__))
UNITY = os.path.dirname(BURASI)
KOK = os.path.dirname(os.path.dirname(UNITY))
for _p in (KOK, UNITY):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import api_rag  # noqa: E402

SORGULAR = [
    ("set animator boolean parameter", "Animator.SetBool"),
    ("cast a ray from screen point through camera", "Camera.ScreenPointToRay"),
    ("physics raycast hit information", "Physics.Raycast"),
    ("find game object by name in scene", "GameObject.Find"),
    ("instantiate a prefab clone", "Object.Instantiate"),
    ("rotate transform around axis over time", "Transform.Rotate"),
    ("smoothly interpolate between two vectors", "Vector3.Lerp"),
    ("time since last frame delta", "Time.deltaTime"),
    ("check if key was pressed this frame", "Input.GetKeyDown"),
    ("add force to rigidbody", "Rigidbody.AddForce"),
    ("play an audio clip once at position", "AudioSource.PlayClipAtPoint"),
    ("get component of type on game object", "GameObject.GetComponent"),
    ("coroutine wait for seconds", "WaitForSeconds"),
    ("clamp a float between min and max", "Mathf.Clamp"),
    ("distance between two points", "Vector3.Distance"),
]


def rerank(sorgu: str, adaylar: list, k: int) -> list:
    """BM25'in ilk N adayini bge-m3 ile yeniden sirala (yalniz adaylar gomulur, 22k degil)."""
    from core import rag
    metinler = ["%s - %s" % (a["uye"], a["ozet"]) for a in adaylar]
    vek = rag.embed_ollama([sorgu] + metinler)
    sv, dv = vek[0], vek[1:]
    puanli = sorted(zip(adaylar, dv), key=lambda x: -rag._kosinus(sv, x[1]))
    return [a for a, _ in puanli][:k]


def main() -> int:
    kullan_rerank = "--rerank" in sys.argv
    ix = api_rag.ApiIndeks()
    t0 = time.time()
    v = ix.yukle()
    print("indeks: %d uye, %d kelime, %.1f s" % (len(v["kayitlar"]), len(v["ters"]), time.time() - t0))

    isabet1 = isabet8 = 0
    sureler = []
    for sorgu, beklenen in SORGULAR:
        t = time.time()
        sonuc = ix.ara(sorgu, 40 if kullan_rerank else 8)
        if kullan_rerank:
            sonuc = rerank(sorgu, sonuc, 8)
        sureler.append(time.time() - t)
        adlar = [r["uye"] for r in sonuc]
        yer = next((i for i, a in enumerate(adlar) if beklenen.lower() in a.lower()), None)
        if yer == 0:
            isabet1 += 1
        if yer is not None:
            isabet8 += 1
        durum = "1." if yer == 0 else ("%d." % (yer + 1) if yer is not None else "YOK")
        print("  %-46s -> %-28s %s" % (sorgu[:46], beklenen, durum))
        if yer is None:
            print("      ilk 3: %s" % ", ".join(a.split("(")[0] for a in adlar[:3]))
    n = len(SORGULAR)
    print("\nhit@1 %d/%d (%.0f%%) | hit@8 %d/%d (%.0f%%) | sorgu ort %.0f ms%s" % (
        isabet1, n, 100 * isabet1 / n, isabet8, n, 100 * isabet8 / n,
        1000 * sum(sureler) / n, "  [rerank]" if kullan_rerank else ""))
    return 0 if isabet8 >= n * 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
