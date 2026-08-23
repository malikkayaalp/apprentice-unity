"""Duman testi ortami: isci ve Ollama OLMADAN gercek kosucularla ayni olay semasini uretir.

Ne dogrular: sunucunun isciyi ayrik surecte baslatmasi, prompt-file'i okumasi, JSONL
olaylarini rapora cevirmesi (write -> yazilan_dosyalar, result -> derleme_durumu...).
Gercek bir arac sunucusu yerine mcpbridge/fake_server.py'ye stdio ile baglanir ve
read_console cagirir: boylece kopru katmani da ayni testte kosar.

Ne DOGRULAMAZ: modelin kodu, derleyici. Bunlar icin tests/test_server.py --live.
Prompt'ta 'HATA_URET' gecerse derleme hatasi, 'COK' gecerse surec cokmesi, 'YAVAS' gecerse 5 sn gecikme taklit edilir.
"""
from __future__ import annotations
import argparse, json, os, sys, time

_KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _KOK not in sys.path:
    sys.path.insert(0, _KOK)
from mcpbridge.client import MCPServer  # noqa: E402

FAKE = os.path.join(_KOK, "mcpbridge", "fake_server.py")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--jsonl", required=True)
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--session-dir", default="")
    p.add_argument("--model", default="fake")
    p.add_argument("--url", default="")
    p.add_argument("--repairs", type=int, default=3)
    p.add_argument("--play", action="store_true")
    p.add_argument("--play-repairs", type=int, default=2)
    a = p.parse_args()

    def emit(kind, **kw):
        rec = {"type": kind}
        rec.update(kw)
        with open(a.jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    open(a.jsonl, "w").close()
    code = 1
    t0 = time.time()
    try:
        with open(a.prompt_file, encoding="utf-8") as f:
            prompt = f.read()
        if "COK" in prompt:
            raise SystemExit(3)          # isci sonuc yazmadan oluyor
        if "YAVAS" in prompt:
            time.sleep(5)                # zaman asimi senaryosu
        emit("system", subtype="init", model=a.model, session_id=a.session)

        srv = MCPServer(sys.executable, [FAKE], name="fake")
        srv.start()
        try:
            names = [t["name"] for t in srv.list_tools()]
            emit("tool", name="read_console", detail="", args={"count": 5})
            t1 = time.time()
            out = srv.call_tool("read_console", {"count": 5})
            text = "\n".join(c.get("text", "") for c in out.get("content", []))
            emit("tool_result", name="read_console", text=text[:6000], sure=round(time.time() - t1, 2))
        finally:
            srv.stop()

        path = "Assets/Scripts/FakeSmoke.cs"
        after = "using UnityEngine;\npublic class FakeSmoke : MonoBehaviour { void Start() { Debug.Log(\"fake\"); } }\n"
        emit("tool", name="write_script", detail=path, args={"path": path})
        emit("write", path=path, before=None, after=after)
        emit("tool_result", name="write_script", text="{\"ok\": true}", sure=0.01)
        if a.session_dir:
            os.makedirs(a.session_dir, exist_ok=True)
            with open(os.path.join(a.session_dir, a.session + ".json"), "w", encoding="utf-8") as f:
                json.dump({"schema": 1, "model": a.model, "messages": [{"role": "user", "content": prompt}]}, f)

        errs = ["Assets/Scripts/FakeSmoke.cs(2,1): error CS0000: taklit hata"] if "HATA_URET" in prompt else []
        emit("assistant", text="FakeSmoke.cs yazildi (taklit). Araclar: %s" % ", ".join(names[:3]))
        play = {"dogrulandi": True, "hatalar": []} if a.play else None
        emit("result", ok=not errs, errors=errs, rounds=1 if errs else 0,
             wall=round(time.time() - t0, 2), written=[path], play=play)
        code = 0 if not errs else 2
    except SystemExit as e:
        code = int(e.code or 1)
        raise
    except Exception as e:  # noqa: BLE001
        emit("error", message="%s: %s" % (type(e).__name__, e))
        code = 1
    finally:
        if code != 3:
            emit("exit", code=code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
