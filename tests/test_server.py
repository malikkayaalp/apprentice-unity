"""Apprentice MCP sunucusunun sozlesme testi.

    python tests/test_server.py            # Ollama GEREKMEZ: stdio el sikisma, tools/list,
                                           # hata yollari, fake ortamla tam boru hatti (4 senaryo)
    python tests/test_server.py --live     # + gercek worker_run (code ortami, Ollama acik)

Sunucuyu ayrik surec olarak baslatir ve gercek bir MCP istemcisi gibi konusur; stdout'a
karisan tek bir yabanci satir bile burada yakalanir. Fake ortam (envs/fake) isciyi taklit
eder ve mcpbridge/fake_server.py'ye gercekten baglanir.
"""
from __future__ import annotations
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server", "apprentice_server.py")
try:      # pencereli exe/pythonw: sys.stdout None olabilir (kurulum oz-testi
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # bu satirda cokuyordu)
except Exception:
    pass

SOZLESME = {"yazilan_dosyalar": list, "derleme_durumu": str, "hatalar": list,
            "tur_sayisi": int, "sure": (int, float), "ozet": str}


class Client:
    def __init__(self, env=None):
        env = dict(env or {})
        env.setdefault("APPRENTICE_IZLEYICI", "0")   # olcumler pencere acmasin
        e = dict(os.environ)
        e.update(env or {})
        # CREATE_NO_WINDOW: pencereli exe'den (Setup GUI oz-testi) calisinca her sunucu
        # sureci konsol penceresi aciyordu (yasandi: kurulum sirasinda MS-DOS pencereleri).
        self.p = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, env=e,
                                  creationflags=0x08000000 if os.name == "nt" else 0)
        self._id = 0

    def call(self, method, params=None, timeout=60):
        self._id += 1
        rid = self._id
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                                        "params": params or {}}) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        t0 = time.time()
        while time.time() - t0 < timeout:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("sunucu kapandi: " + self.p.stderr.read().decode("utf-8", "replace")[-800:])
            msg = json.loads(line.decode("utf-8"))
            assert msg.get("jsonrpc") == "2.0", "bozuk satir: %r" % line[:200]
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]
        raise TimeoutError(method)

    def tool(self, name, args, timeout=60):
        return self.call("tools/call", {"name": name, "arguments": args}, timeout)

    def notify(self, method, params=None):
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method,
                                        "params": params or {}}) + "\n").encode("utf-8"))
        self.p.stdin.flush()

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(5)
        except Exception:
            self.p.kill()


def sema_kontrol(rep: dict):
    for k, t in SOZLESME.items():
        assert k in rep, "eksik alan: %s" % k
        assert isinstance(rep[k], t), "%s tipi %s, beklenen %s" % (k, type(rep[k]).__name__, t)
    for d in rep["yazilan_dosyalar"]:
        for k in ("yol", "yeni", "eklendi", "silindi", "satir"):
            assert k in d, "yazilan_dosyalar eksik alan: %s" % k


def main() -> int:
    live = "--live" in sys.argv
    home = os.path.join(ROOT, ".apprentice_test_home")
    c = Client({"APPRENTICE_HOME": home})
    ok = True
    try:
        r = c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "clientInfo": {"name": "test", "version": "0"}})
        print("initialize:", r["serverInfo"], r["protocolVersion"])
        c.notify("notifications/initialized")
        assert c.call("ping") == {}
        tools = c.call("tools/list")["tools"]
        names = [t["name"] for t in tools]
        print("tools:", names)
        assert names == ["worker_run", "worker_status"], names
        sch = tools[0]["inputSchema"]
        assert sch["type"] == "object" and set(sch["required"]) == {"gorev", "kabul_kriterleri"}

        # Hata yollari
        r = c.tool("worker_run", {"gorev": "", "kabul_kriterleri": []})
        assert r["isError"] and "bos" in r["structuredContent"]["hata"], r
        r = c.tool("worker_run", {"gorev": "x", "kabul_kriterleri": [], "ortam": "yok"})
        assert r["isError"] and "bilinmeyen ortam" in r["structuredContent"]["hata"]
        # Kok bilinmiyorken GORELI yol reddedilmeli. Olculdu: eskiden cwd'ye dusuluyordu
        # ve hapishane kokunu tum ev dizini yapiyordu (Cursor sunucuyu ev dizininden baslatir).
        r = c.tool("worker_run", {"gorev": "x", "kabul_kriterleri": [], "ortam": "code"})
        assert r["isError"] and "koku belirlenemedi" in r["structuredContent"]["hata"], r
        r = c.tool("worker_run", {"gorev": "x", "kabul_kriterleri": [], "ortam": "code",
                                  "calisma_dizini": "alt/klasor"})
        assert r["isError"] and "koku belirlenemedi" in r["structuredContent"]["hata"], r
        try:
            c.tool("yok", {})
            raise AssertionError("bilinmeyen arac hata vermedi")
        except RuntimeError as e:
            assert "bilinmeyen arac" in str(e)
        print("hata yollari: ok")

        # Fake ortam: tam boru hatti (surec, prompt-file, JSONL -> rapor)
        rep = c.tool("worker_run", {"gorev": "FakeSmoke.cs yaz", "ortam": "fake",
                                    "kabul_kriterleri": ["derlenir", "Start'ta log"]},
                     timeout=120)["structuredContent"]
        sema_kontrol(rep)
        assert rep["derleme_durumu"] == "derlendi", rep
        assert rep["tur_sayisi"] == 1 and not rep["hatalar"]
        assert [d["yol"] for d in rep["yazilan_dosyalar"]] == ["Assets/Scripts/FakeSmoke.cs"]
        assert rep["yazilan_dosyalar"][0]["yeni"] and rep["yazilan_dosyalar"][0]["eklendi"] == 2
        assert rep["olcumler"] and rep["olcumler"][0]["arac"] == "read_console"
        assert "FakeSmoke" in rep["ozet"]
        assert os.path.exists(os.path.join(home, "sessions", "fake", rep["oturum"] + ".json"))
        with open(os.path.join(home, "jobs", rep["is_id"], "prompt.txt"), encoding="utf-8") as f:
            pt = f.read()
        assert "KABUL KRITERLERI" in pt and "- derlenir" in pt and "- Start'ta log" in pt
        assert "icerik" in rep["yazilan_dosyalar"][0] and "FakeSmoke" in rep["yazilan_dosyalar"][0]["icerik"]
        print("fake/basari: ok  (%s, %.1fs)" % (rep["derleme_durumu"], rep["sure"]))

        rep = c.tool("worker_run", {"gorev": "HATA_URET", "ortam": "fake", "kabul_kriterleri": ["x"]},
                     timeout=120)["structuredContent"]
        sema_kontrol(rep)
        assert rep["derleme_durumu"] == "derleme_hatasi" and rep["tur_sayisi"] == 2
        assert rep["hatalar"] and "CS0000" in rep["hatalar"][0]
        print("fake/derleme_hatasi: ok")

        rep = c.tool("worker_run", {"gorev": "COK", "ortam": "fake", "kabul_kriterleri": ["x"]},
                     timeout=120)["structuredContent"]
        sema_kontrol(rep)
        assert rep["derleme_durumu"] == "calistirilamadi" and "sonuc yazmadan" in rep["hatalar"][0], rep
        print("fake/cokme: ok")

        rep = c.tool("worker_run", {"gorev": "YAVAS", "ortam": "fake", "kabul_kriterleri": ["x"],
                                    "zaman_asimi_s": 1}, timeout=120)["structuredContent"]
        sema_kontrol(rep)
        assert rep["derleme_durumu"] == "zaman_asimi"
        print("fake/zaman_asimi: ok")

        # bekle=false + worker_status
        rep = c.tool("worker_run", {"gorev": "YAVAS", "ortam": "fake", "kabul_kriterleri": ["x"], "bekle": False})["structuredContent"]
        assert rep["durum"] == "calisiyor"
        time.sleep(7)
        st = c.tool("worker_status", {"is_id": rep["is_id"]})["structuredContent"]
        assert st["durum"] == "bitti" and st["derleme_durumu"] == "derlendi", st
        print("bekle=false + worker_status: ok")

        # iptal: istemci notifications/cancelled gonderince isci olmeli (Cursor zaman asimi dersi)
        c._id += 1
        rid = c._id
        c.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {
            "name": "worker_run", "arguments": {"gorev": "YAVAS", "kabul_kriterleri": ["x"], "ortam": "fake"}}}) + chr(10)).encode("utf-8"))
        c.p.stdin.flush()
        time.sleep(1.5)
        c.notify("notifications/cancelled", {"requestId": rid})
        bildirim = 0
        while True:   # notifications/progress + message satirlari araya girer
            msg = json.loads(c.p.stdout.readline().decode("utf-8"))
            if msg.get("id") == rid:
                break
            assert msg.get("method", "").startswith("notifications/"), msg
            bildirim += 1
        rep = msg["result"]["structuredContent"]
        assert rep["derleme_durumu"] == "iptal", rep
        ev = [json.loads(l) for l in open(os.path.join(rep["is_klasoru"], "events.jsonl"), encoding="utf-8") if l.strip()]
        assert any(e.get("message") == "istemci iptal etti" for e in ev) and any(e["type"] == "exit" for e in ev)
        print("iptal -> isci olduruldu: ok")

        # MCP roots: istemci workspace'ini bildirir, calisma_dizini goreli olur, disari cikilamaz
        ws = os.path.join(home, "ws")
        os.makedirs(os.path.join(ws, "alt"), exist_ok=True)
        # UNITY_CODE_MODEL=yok: on kosul "model yuklu degil" ile hemen doner, gercek isci kosmaz
        c2 = Client({"APPRENTICE_HOME": home, "UNITY_CODE_MODEL": "yok:model"})
        c2.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"roots": {"listChanged": True}},
                               "clientInfo": {"name": "test", "version": "0"}})
        c2.notify("notifications/initialized")
        req = json.loads(c2.p.stdout.readline().decode("utf-8"))      # sunucunun roots/list istegi
        assert req.get("method") == "roots/list", req
        uri = "file:///" + ws.replace("\\", "/")
        c2.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"roots": [{"uri": uri, "name": "ws"}]}}) + chr(10)).encode("utf-8"))
        c2.p.stdin.flush()
        time.sleep(0.5)
        r = c2.tool("worker_run", {"gorev": "x", "kabul_kriterleri": [], "ortam": "code",
                                   "calisma_dizini": os.path.join(ROOT, "tests")})
        assert r["isError"] and "disinda" in r["structuredContent"]["hata"], r
        r = c2.tool("worker_run", {"gorev": "x", "kabul_kriterleri": [], "ortam": "code", "calisma_dizini": "yok_boyle"})
        assert r["isError"] and "calisma_dizini yok" in r["structuredContent"]["hata"], r
        # goreli alt klasor ve bos (kok): on kosul asamasina gecer (Ollama kapali olabilir; hata metni farkli olmali)
        for cd in ("alt", ""):
            r = c2.tool("worker_run", {"gorev": "x", "kabul_kriterleri": [], "ortam": "code", "calisma_dizini": cd}, timeout=60)["structuredContent"]
            h = " ".join(r.get("hatalar", [])) + (r.get("hata") or "")
            assert "model yuklu degil" in h or "Ollama" in h, r
        c2.close()
        print("roots: ok")

        if live:
            work = os.path.join(home, "live_code")
            os.makedirs(work, exist_ok=True)
            args = {"gorev": "selam.py dosyasina selam() fonksiyonu yaz: 'selam' dondursun. test_selam.py ile unittest testi yaz.",
                    "kabul_kriterleri": ["selam() == 'selam'", "run_tests hatasiz gecer", "yalnizca selam.py ve test_selam.py yazilir"],
                    "ortam": "code", "calisma_dizini": work}
            t0 = time.time()
            rep = c.tool("worker_run", args, timeout=900)["structuredContent"]
            sema_kontrol(rep)
            print(json.dumps({k: rep.get(k) for k in ("derleme_durumu", "hatalar", "tur_sayisi", "sure", "ozet")},
                             ensure_ascii=False, indent=1))
            canli = rep["derleme_durumu"] == "derlendi" and os.path.exists(os.path.join(work, "selam.py"))
            print("live: %s (%.0fs)" % ("ok" if canli else "KALDI", time.time() - t0))
            ok = ok and canli
    except Exception as e:
        ok = False
        import traceback
        traceback.print_exc()
        print("HATA:", e)
    finally:
        c.close()
        err = c.p.stderr.read().decode("utf-8", "replace")
        if err.strip():
            print("--- sunucu stderr ---\n" + err[-1500:])
    print("SONUC:", "GECTI" if ok else "KALDI")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
