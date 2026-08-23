"""Q3CNFU panel kosucusu: Unity panelinden gelen tek istegi calistirir.

Panel bu betigi AYRIK surec olarak baslatir ve cikti dosyasini (JSONL) takip eder.
CursorBridge'in node bootstrap'ina gerek yok: olaylari dosyaya kendimiz yazariz,
cikis olayi dahil. Boylece Unity domain reload yapsa da akis kopmaz.

Prompt hicbir komut satirindan gecmez (heredoc/kacis dersi): --prompt-file ile
ayri bir dosyadan okunur. Sohbet gecmisi de surec olumsuz oldugu icin dosyada
yasar: Library/Q3CNFU/sessions/<id>.json (calisma dizini Unity proje koku).

Olay semasi (satir basina bir JSON):
  {"type":"system","subtype":"init","model":M,"session_id":S}
  {"type":"tool","name":N,"detail":D,"args":{...}}        arac cagrisi basladi
  {"type":"tool_result","name":N,"text":T,"sure":S}       arac sonucu (kirpilmis)
  {"type":"write","path":P,"before":X|null,"after":Y}     dosya yazildi (diff icin)
  {"type":"assistant","text":T}                           modelin nihai metni
  {"type":"result","ok":B,"errors":[...],"rounds":R,"wall":W,
   "written":[...],"play":{"dogrulandi":B,"hatalar":[...]}|null}
  {"type":"exit","code":C}                                daima yazilir (finally)
"""
from __future__ import annotations
import argparse, json, os, sys, time

_BURASI = os.path.dirname(os.path.abspath(__file__))
_KOK = os.path.dirname(os.path.dirname(_BURASI))   # depo koku (core/, mcpbridge/)
for _p in (_BURASI, _KOK):
    if _p not in sys.path:
        sys.path.insert(0, _p)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import unity_code as UC
import unity_csharp_eval as U
from core.guard import guarded_dispatch
from mcpbridge.http_client import MCPHttpServer

SESSION_DIR = os.environ.get("Q3_SESSION_DIR") or os.path.join("Library", "Q3CNFU", "sessions")


class Emitter:
    """JSONL olay yazicisi. Her olay tek satir, aninda flush - panel canli okur."""

    def __init__(self, path: str):
        self.path = path
        # Dosyayi bastan olustur: panel offset 0'dan okumaya baslar.
        with open(path, "w", encoding="utf-8"):
            pass

    def emit(self, kind: str, **kw):
        rec = {"type": kind}
        rec.update(kw)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass  # olay yazilamasa da is durmasin; panel liveness'i PID'den anlar


def load_session(session_id: str) -> list:
    p = os.path.join(SESSION_DIR, "%s.json" % session_id)
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("schema") != 1:
            return []
        return d.get("messages", [])
    except Exception:
        return []


def save_session(session_id: str, msgs: list, model: str):
    os.makedirs(SESSION_DIR, exist_ok=True)
    p = os.path.join(SESSION_DIR, "%s.json" % session_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "model": model, "updated": time.time(),
                   "messages": msgs}, f, ensure_ascii=False)


def wrap_dispatch(inner, em: Emitter, srv):
    """Arac cagrilarini panele olay olarak akitir.

    write_script icin yazmadan ONCE mevcut icerik okunur ki panel diff
    gosterebilsin ve geri alma 'before'u geri yazmaktan ibaret olsun.
    (CursorBridge'de bunu CLI hazir veriyordu; burada biz uretiyoruz.)
    """
    def d(name, args):
        args = args if isinstance(args, dict) else {}
        detail = str(args.get("path") or args.get("name") or
                     args.get("class_name") or args.get("folder") or "")[:140]
        # Kullanici "ne olcuyor, nereye yaziyor, hicbir sey gormuyorum" dedi:
        # arac satiri sadece ad tasiyordu. Simdi argumanlar (kod dahil) ve donen
        # sonuc da gidiyor; panel bunlari acilir satir olarak gosterir.
        # write_script icerigi "write" olayinda zaten var, burada tekrar yollanmaz.
        arg_ozet = {k: (v if len(str(v)) <= 4000 else str(v)[:4000] + " …")
                    for k, v in args.items()
                    if not (name == "write_script" and k == "contents")}
        em.emit("tool", name=name, detail=detail, args=arg_ozet)

        before = None
        if name == "write_script":
            prev = inner("read_script", {"path": args.get("path", "")})
            if isinstance(prev, dict) and "contents" in prev:
                before = prev["contents"]

        t0 = time.time()
        out = inner(name, args)

        if name == "write_script" and isinstance(out, dict) and out.get("ok"):
            em.emit("write", path=out.get("path", ""), before=before,
                    after=str(args.get("contents") or ""))

        # Sonuc: metin ya da JSON, paneli bogmamak icin kirpilmis.
        try:
            metin = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1)
        except Exception:
            metin = str(out)
        if name == "read_script" and isinstance(out, dict) and "contents" in out:
            metin = "%d karakter okundu" % len(out["contents"])
        em.emit("tool_result", name=name, text=metin[:6000] + (" …" if len(metin) > 6000 else ""),
                sure=round(time.time() - t0, 1))
        return out
    return d


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--jsonl", required=True, help="olay cikti dosyasi")
    p.add_argument("--prompt-file", required=True, help="istek metni (UTF-8)")
    p.add_argument("--session", required=True, help="sohbet kimligi")
    p.add_argument("--model", default=UC.DEFAULT_MODEL)
    p.add_argument("--url", default=U.URL, help="Unity MCP koprusu")
    p.add_argument("--repairs", type=int, default=3)
    p.add_argument("--play", action="store_true")
    p.add_argument("--play-repairs", type=int, default=2)
    p.add_argument("--session-dir", default="", help="sohbet dosyalarinin klasoru "
                   "(varsayilan Library/Q3CNFU/sessions; MCP sunucusu kendi evini verir)")
    a = p.parse_args()
    if a.session_dir:
        global SESSION_DIR
        SESSION_DIR = a.session_dir

    em = Emitter(a.jsonl)
    code = 1
    try:
        with open(a.prompt_file, encoding="utf-8") as f:
            request = f.read().strip()
        if not request:
            em.emit("error", message="bos istek")
            return 1

        try:
            srv = MCPHttpServer(a.url)
            srv.start()
        except Exception as e:
            em.emit("error", message="Unity MCP koprusune ulasilamadi: %s" % str(e)[:200])
            return 1

        try:
            inst = "".join(c.get("text", "") for c in
                           srv.read_resource("mcpforunity://instances")
                           .get("contents", []))
            if '"instance_count": 0' in inst:
                em.emit("error", message="Unity Editor bagli degil - MCP for Unity "
                                         "penceresinde Connect'e basin.")
                return 1

            em.emit("system", subtype="init", model=a.model, session_id=a.session)

            tools = UC.build_tools(srv)
            kapali = [k.strip() for k in os.environ.get("APPRENTICE_TOOLS_OFF", "").split(",") if k.strip()]
            if kapali:
                tools = [t for t in tools if (t.get("function") or t).get("name") not in kapali]
                em.emit("system", subtype="tools_off", tools=kapali)
            written: list = []
            dispatch = wrap_dispatch(
                guarded_dispatch(tools, UC.make_dispatch(srv, written)), em, srv)

            msgs = load_session(a.session)
            if not msgs:
                msgs = [{"role": "system",
                         "content": UC.SYSTEM.format(dir=UC.SCRIPT_DIR)}]

            r = UC.one_request(srv, tools, dispatch, msgs, request, a.model,
                               a.repairs, verbose=False,
                               play_check=a.play, play_repairs=a.play_repairs)

            save_session(a.session, msgs, a.model)

            if r.get("text"):
                em.emit("assistant", text=r["text"])

            play = None
            if a.play:
                play = {"dogrulandi": bool(r.get("play_dogrulandi")),
                        "hatalar": [e[:300] for e in (r.get("runtime") or [])]}

            ok = not r["errors"]
            em.emit("result", ok=ok, errors=[e[:300] for e in r["errors"][:5]],
                    rounds=r.get("rounds", 0), wall=round(r.get("wall", 0), 1),
                    written=list(dict.fromkeys(written)), play=play)
            code = 0 if ok else 2
        finally:
            srv.stop()
    except Exception as e:  # noqa: BLE001 - panel her kosulda bir aciklama gormeli
        em.emit("error", message=("%s: %s" % (type(e).__name__, e))[:300])
        code = 1
    finally:
        em.emit("exit", code=code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
