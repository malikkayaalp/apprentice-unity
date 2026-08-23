"""Unity C# evaluation against a live Unity Editor over MCP.

Why this exists: published coding benchmarks (SWE-Bench, MultiPL-E) measure general C#,
not Unity C#. The failures actually observed in this project were never syntax - the
generated code compiled and ran. They were Unity semantics: not knowing that
PrimitiveType.Plane lies in the XZ plane, scaling the Y of a horizontal plane, ignoring
that the camera sits at y=1. No public benchmark measures that.

So this measures it directly, in the user's own Editor, on three tiers:

  compiled  the code got past the C# compiler
  ran       it executed without throwing
  correct   an INDEPENDENT verification query returns the expected state

The third tier matters most. Models in this project reported "exact match" for grids
that were measurably wrong, so a model's own summary is never accepted as evidence.

Tasks are deliberately small (tens of objects, not tens of thousands) so a full run
takes minutes, not hours.
"""
from __future__ import annotations
import argparse, json, os, re, sys, time

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

from core.client import run_agent
from core.guard import guarded_dispatch
from mcpbridge.http_client import MCPHttpServer
from mcpbridge.client import to_ollama_tools, content_to_text, MCPError

URL = os.environ.get("UNITY_MCP_URL", "http://127.0.0.1:8080/mcp")
EVAL_TOOLS = ["execute_code", "create_script", "validate_script", "read_console",
              "manage_asset"]

SYSTEM = (
    "You are a Unity Editor agent. You write and run C# inside the running Editor.\n"
    "- execute_code compiles your code as a METHOD BODY, not as a file. Never write "
    "using directives, a class, or a method signature. Write statements only and use "
    "fully qualified names such as UnityEditor.AssetDatabase. Use return to send data "
    "back.\n"
    "- Emit ONE tool call per turn, with strict JSON arguments and no commentary "
    "inside them.\n"
    "- Verify your own work with a follow-up query before reporting success.\n"
    "- Answer in Turkish, briefly."
)

COMPILE_ERR = re.compile(r"\berror CS\d{4}\b|CompilerError|Compilation failed", re.I)
RUNTIME_ERR = re.compile(r"Exception|NullReference|IndexOutOfRange", re.I)

# execute_code compiles its payload as a METHOD BODY, so a leading `using UnityEngine;`
# is a syntax error: "Unexpected symbol `UnityEngine', expecting `('".
# Every model tested walks into this at least once, because they are trained to emit
# complete C# files. qwen3.8 recovered by itself on the next turn; qwen3-coder repeated
# the same mistake for ten straight turns and scored zero on every task because of it.
#
# Left unhandled this eval would measure one format quirk instead of Unity knowledge, so
# the directives are stripped here. Only true directives are removed - a
# `using (var x = ...)` resource block is a statement and must survive.
_USING_DIRECTIVE = re.compile(r"^[ \t]*using[ \t]+[A-Za-z_][\w.]*[ \t]*;[ \t]*$", re.M)


def strip_using_directives(code: str) -> tuple[str, int]:
    """Remove `using X.Y;` directives, keeping `using (...) { }` statements."""
    if not code:
        return code, 0
    cleaned, n = _USING_DIRECTIVE.subn("", code)
    return (cleaned.lstrip("\n"), n) if n else (code, 0)


# --------------------------------------------------------------------- tasks
def _f(x):
    """Parse a float from Unity's culture-dependent output (it prints 1,5 not 1.5)."""
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None


def _kv(result: str) -> dict:
    """Parse 'a=1 b=2' style verification output into a dict.

    The verification string arrives embedded in the tool's JSON envelope, so a value at
    the end of the string picks up the closing quote: total=7 withRb=7" made withRb
    compare as '7"' and scored a correct C6 answer as wrong. Trailing JSON punctuation
    is stripped for that reason.
    """
    out = {}
    for m in re.finditer(r"(\w+)=([^\s]+)", result or ""):
        out[m.group(1)] = m.group(2).rstrip('",}]')
    return out


TASKS: list[dict] = []


def task(**kw):
    TASKS.append(kw)


# ---- C1: the exact trap both models fell into
task(id="C1", title="Kameraya bakan 4x4 karo izgarasi",
     why="Plane XZ duzleminde yatar; kameraya bakan karo Quad ister ya da X'te 90 derece",
     prompt="Kameranin gordugu alanin ortasinda, 'EvalGrid' adinda bir kok nesnenin "
            "altinda 4x4 = 16 adet kare karo olustur. Karolar kameraya BAKMALI, yani "
            "Game view'da gorunmeliler. Bitisik olsunlar. Toplam izgara kameranin gorus "
            "genisliginin yarisi kadar genis olsun.",
     cleanup='var g = GameObject.Find("EvalGrid"); if (g != null) UnityEngine.Object.DestroyImmediate(g); '
             'return "cleaned";',
     verify='var g = GameObject.Find("EvalGrid"); if (g == null) return "missing=1"; '
            'var rs = g.GetComponentsInChildren<Renderer>(); '
            'if (rs.Length == 0) return "children=0"; '
            'var b = rs[0].bounds; for (int i=1;i<rs.Length;i++) b.Encapsulate(rs[i].bounds); '
            'var cam = Camera.main; '
            'var one = rs[0].bounds; '
            'return string.Format("n={0} sx={1:F3} sy={2:F3} sz={3:F3} cx={4:F3} cy={5:F3} camfwd={6:F2}", '
            'rs.Length, b.size.x, b.size.y, b.size.z, one.size.x, one.size.y, cam.transform.forward.z);',
     check=lambda r: _c1(r))


def _c1(r: str):
    d = _kv(r)
    if d.get("missing") == "1":
        return False, "EvalGrid olusturulmamis"
    n = d.get("n")
    if n != "16":
        return False, "karo sayisi=" + str(n) + " (16 bekleniyor)"
    sx, sy, sz = _f(d.get("sx")), _f(d.get("sy")), _f(d.get("sz"))
    if None in (sx, sy, sz):
        return False, "olculemedi: " + r[:120]
    # A camera-facing tile has extent in X and Y and (near) none in Z.
    if sy is not None and sy < 0.01:
        return False, "karolar YATAY duruyor (Y boyutu %.4f) - kameraya bakmiyor" % sy
    if sz > max(sx, sy) * 0.1:
        return False, "karolar Z'ye yayilmis (sz=%.3f) - dikey duzlemde degil" % sz
    cw, ch = _f(d.get("cx")), _f(d.get("cy"))
    square = cw and ch and abs(cw - ch) / max(cw, ch) < 0.05
    return True, "16 karo, dikey duzlem, hucre %.2fx%.2f%s" % (
        cw or 0, ch or 0, "" if square else " (kare degil)")


# ---- C2: editor scripting with undo
task(id="C2", title="Editor betigi: toplu yeniden adlandirma + Undo",
     why="UnityEditor API ve Undo kaydi bilgisi",
     setup='var root = new GameObject("RenameMe"); '
           'for (int i=0;i<5;i++){ var c = new GameObject("wrong_" + i); '
           'c.transform.SetParent(root.transform); } return "setup";',
     prompt="Sahnedeki 'RenameMe' nesnesinin 5 cocugunu sirayla 'Tile_00', 'Tile_01', "
            "'Tile_02', 'Tile_03', 'Tile_04' olarak yeniden adlandir. Islemi Unity'nin "
            "geri alma (Undo) yiginina kaydet ki kullanici Ctrl+Z ile geri alabilsin.",
     cleanup='var g = GameObject.Find("RenameMe"); if (g != null) UnityEngine.Object.DestroyImmediate(g); '
             'return "cleaned";',
     verify='var g = GameObject.Find("RenameMe"); if (g == null) return "missing=1"; '
            'var names = new System.Collections.Generic.List<string>(); '
            'foreach (Transform t in g.transform) names.Add(t.name); '
            'names.Sort(); return "names=" + string.Join(",", names.ToArray());',
     check=lambda r: (_kv(r).get("names") == "Tile_00,Tile_01,Tile_02,Tile_03,Tile_04",
                      _kv(r).get("names", "yok")))


# ---- C3: asset pipeline
task(id="C3", needs_compile=True, title="ScriptableObject asset olustur",
     why="AssetDatabase, CreateAssetMenu ve asset yolu kurallari",
     prompt="'Assets/Eval' klasoru altinda 'EvalConfig.asset' adinda bir ScriptableObject "
            "asset'i olustur. Icinde 'gridWidth' adinda int bir alan olsun ve degeri 108 "
            "olarak ayarlansin. Gerekiyorsa once ScriptableObject sinifini yaz.",
     cleanup='UnityEditor.AssetDatabase.DeleteAsset("Assets/Eval"); '
             'UnityEditor.AssetDatabase.Refresh(); return "cleaned";',
     verify='var o = UnityEditor.AssetDatabase.LoadAssetAtPath<ScriptableObject>('
            '"Assets/Eval/EvalConfig.asset"); if (o == null) return "missing=1"; '
            'var so = new UnityEditor.SerializedObject(o); '
            'var p = so.FindProperty("gridWidth"); '
            'return string.Format("type={0} width={1}", o.GetType().Name, '
            'p == null ? -1 : p.intValue);',
     check=lambda r: (_kv(r).get("width") == "108",
                      "type=%s width=%s" % (_kv(r).get("type"), _kv(r).get("width"))))


# ---- C4: camera maths on an orthographic camera
task(id="C4", title="Ekran kosesinden dunya konumu",
     why="Ortografik kamera matematigi ve ScreenToWorldPoint",
     prompt="Kameranin gordugu alanin SOL-ALT ve SAG-UST koselerine tam olarak birer "
            "kucuk kup yerlestir. Adlari 'Corner_BL' ve 'Corner_TR' olsun. Kupler "
            "kosenin tam uzerinde olmali.",
     cleanup='foreach (var n in new string[]{"Corner_BL","Corner_TR"}) '
             '{ var g = GameObject.Find(n); if (g != null) UnityEngine.Object.DestroyImmediate(g); } '
             'return "cleaned";',
     verify='var bl = GameObject.Find("Corner_BL"); var tr = GameObject.Find("Corner_TR"); '
            'if (bl == null || tr == null) return "missing=1"; '
            'var cam = Camera.main; '
            'float hh = cam.orthographic ? cam.orthographicSize : '
            '  (0f - cam.transform.position.z) * Mathf.Tan(cam.fieldOfView*0.5f*Mathf.Deg2Rad); '
            'float hw = hh * cam.aspect; '
            'float ex = cam.transform.position.x - hw, ey = cam.transform.position.y - hh; '
            'float fx = cam.transform.position.x + hw, fy = cam.transform.position.y + hh; '
            'var p = bl.transform.position; var q = tr.transform.position; '
            'return string.Format("dbl={0:F3} dtr={1:F3} span={2:F3}", '
            'Vector2.Distance(new Vector2(p.x,p.y), new Vector2(ex,ey)), '
            'Vector2.Distance(new Vector2(q.x,q.y), new Vector2(fx,fy)), hw*2);',
     check=lambda r: _c4(r))


def _c4(r: str):
    d = _kv(r)
    if d.get("missing") == "1":
        return False, "kupler olusturulmamis"
    dbl, dtr, span = _f(d.get("dbl")), _f(d.get("dtr")), _f(d.get("span"))
    if None in (dbl, dtr, span):
        return False, "olculemedi: " + r[:120]
    tol = max(span * 0.01, 0.05)         # 1% of the view width
    ok = dbl <= tol and dtr <= tol
    return ok, "sapma sol-alt=%.3f sag-ust=%.3f (tolerans %.3f)" % (dbl, dtr, tol)


# ---- C5: a real script file that must compile
task(id="C5", needs_compile=True, title="Derlenen MonoBehaviour + coroutine",
     why="Script dosyasi yazma, yasam dongusu, IEnumerator, derleme",
     prompt="'Assets/Eval/FadeSprite.cs' yolunda bir MonoBehaviour betigi olustur. "
            "Sinif adi FadeSprite olsun. Start icinde baslayan bir coroutine ile "
            "uzerindeki SpriteRenderer'in alpha degerini 1'den 0'a 2 saniyede dusursun. "
            "SpriteRenderer yoksa hata vermeden cikmali. Yazdiktan sonra derlenip "
            "derlenmedigini kontrol et.",
     cleanup='UnityEditor.AssetDatabase.DeleteAsset("Assets/Eval"); '
             'UnityEditor.AssetDatabase.Refresh(); return "cleaned";',
     verify='var t = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEditor.MonoScript>('
            '"Assets/Eval/FadeSprite.cs"); if (t == null) return "missing=1"; '
            'var cls = t.GetClass(); '
            'if (cls == null) return "compiled=0"; '
            'var m = cls.GetMethod("Start", System.Reflection.BindingFlags.Instance '
            '| System.Reflection.BindingFlags.NonPublic '
            '| System.Reflection.BindingFlags.Public); '
            'bool mono = typeof(MonoBehaviour).IsAssignableFrom(cls); '
            'return string.Format("compiled=1 mono={0} start={1}", mono, m != null);',
     check=lambda r: _c5(r))


def _c5(r: str):
    d = _kv(r)
    if d.get("missing") == "1":
        return False, "dosya olusturulmamis"
    if d.get("compiled") == "0":
        return False, "dosya var ama DERLENMEDI (GetClass null)"
    return (d.get("mono") == "True" and d.get("start") == "True"),\
        "derlendi, MonoBehaviour=%s Start=%s" % (d.get("mono"), d.get("start"))


# ---- C6: querying the scene correctly
task(id="C6", title="Belirli bilesene sahip nesneleri say",
     why="GetComponentsInChildren, FindObjectsOfType ve dogru filtreleme",
     setup='var root = new GameObject("CountMe"); '
           'for (int i=0;i<7;i++){ var c = GameObject.CreatePrimitive(PrimitiveType.Cube); '
           'c.name = "Box_" + i; c.transform.SetParent(root.transform); '
           'if (i % 2 == 0) c.AddComponent<Rigidbody>(); } return "setup";',
     prompt="'CountMe' nesnesinin altindaki cocuklardan kacinda Rigidbody bileseni var? "
            "Sayiyi bul ve Rigidbody'si OLMAYAN cocuklarin hepsine Rigidbody ekle. "
            "Islem sonunda kac tane eklendigini soyle.",
     cleanup='var g = GameObject.Find("CountMe"); if (g != null) UnityEngine.Object.DestroyImmediate(g); '
             'return "cleaned";',
     verify='var g = GameObject.Find("CountMe"); if (g == null) return "missing=1"; '
            'int total = 0, withRb = 0; '
            'foreach (Transform t in g.transform) { total++; '
            'if (t.GetComponent<Rigidbody>() != null) withRb++; } '
            'return string.Format("total={0} withRb={1}", total, withRb);',
     check=lambda r: (_kv(r).get("total") == "7" and _kv(r).get("withRb") == "7",
                      "toplam=%s rigidbody=%s (7/7 bekleniyor)"
                      % (_kv(r).get("total"), _kv(r).get("withRb"))))


# --------------------------------------------------------------------- runner
def raw_exec(srv, code: str, timeout: int = 180, safety: bool = True) -> str:
    """Run harness-authored C# directly, bypassing the model.

    safety=False is used only for the eval's own fixed setup/cleanup strings. The
    server blocks AssetDatabase.DeleteAsset by default, which is the right default for
    MODEL-generated code but stops the harness from removing the Assets/Eval folder it
    created itself. The distinction is trust in the author of the string, not in the
    operation: everything passed with safety=False is a literal in this file.
    """
    try:
        return content_to_text(srv.call_tool(
            "execute_code", {"action": "execute", "code": code,
                             "safety_checks": safety}, timeout=timeout))
    except MCPError as e:
        return "MCPError: " + str(e)[:300]


_LIST_ASSETS = ('var sb = new System.Text.StringBuilder(); '
                'foreach (var f in System.IO.Directory.GetFiles("Assets", "*.*", '
                'System.IO.SearchOption.AllDirectories)) '
                '{ if (f.EndsWith(".cs") || f.EndsWith(".asset")) '
                'sb.Append(f.Replace((char)92, (char)47)); sb.Append((char)10); } '
                'return sb.ToString();')


def asset_snapshot(srv) -> set:
    """Every .cs and .asset path under Assets right now."""
    raw = raw_exec(srv, _LIST_ASSETS, safety=False)
    try:
        body = json.loads(raw).get("data", {}).get("result", "")
    except Exception:
        body = raw
    return {ln.strip() for ln in str(body).splitlines()
            if ln.strip().startswith("Assets/")}


# Everything the eval is allowed to create lives here. Deletion is restricted to this
# prefix, permanently.
SANDBOX = "Assets/Eval/"


def remove_new_assets(srv, before: set) -> list:
    """Delete eval-created files - ONLY inside the sandbox prefix.

    An earlier version deleted "any path that appeared since the snapshot". The snapshot
    call failed once and returned an empty set, so the diff became "every file in the
    project" and it deleted the user's entire Assets/Scripts tree. The bug was not the
    diff logic; it was granting a cleanup routine the authority to delete arbitrary
    paths at all.

    Two independent limits now apply, and both must hold:
      - the path must start with SANDBOX
      - the batch must be small; a large batch means the snapshot lied, so refuse
    Files the model writes outside the sandbox are reported, never deleted.
    """
    try:
        after = asset_snapshot(srv)
    except Exception:
        return []
    if not before or not after:
        return []                      # a failed snapshot must never authorise deletion
    new_paths = sorted(after - before)
    if not new_paths:
        return []
    inside = [p for p in new_paths if p.startswith(SANDBOX)]
    outside = [p for p in new_paths if not p.startswith(SANDBOX)]
    if outside:
        # Never delete outside the sandbox (that policy once cost the user their whole
        # Assets/Scripts tree). But leaving a model-written .cs in place is not neutral
        # either: C1's leftover carried a genuine compile error (CS0542) and one broken
        # file stops Unity compiling ANY new script, so it silently poisoned every later
        # task - twice. Quarantine instead: rename *.cs -> *.cs.quarantine.txt, which
        # removes it from compilation, loses nothing, and is trivially reversible.
        for path in outside:
            if path.endswith(".cs"):
                raw_exec(srv, 'if (System.IO.File.Exists("%s")) '
                              '{ System.IO.File.Move("%s", "%s.quarantine.txt"); '
                              'if (System.IO.File.Exists("%s.meta")) '
                              'System.IO.File.Delete("%s.meta"); } '
                              'UnityEditor.AssetDatabase.Refresh(); return "q";'
                         % (path, path, path, path, path), safety=False)
                print("           (karantinaya alindi: %s -> .quarantine.txt)" % path)
            else:
                print("           (sandbox disinda birakildi, SILINMEDI: %s)" % path)
    if len(inside) > 12:
        print("           (%d dosya sandbox icinde gorundu - anormal, silme iptal)"
              % len(inside))
        return []
    if not inside:
        return []
    body = "".join('UnityEditor.AssetDatabase.DeleteAsset("%s"); ' % p for p in inside)
    raw_exec(srv, body + 'UnityEditor.AssetDatabase.Refresh('
             'UnityEditor.ImportAssetOptions.ForceUpdate); return "removed";',
             safety=False)
    return inside


def wait_for_compile(srv, timeout: float = 90.0) -> str:
    """Block until Unity finishes its domain reload.

    Creating a C# asset triggers a recompile, and until it completes MonoScript.GetClass()
    returns null. Verifying immediately therefore reports "did not compile" for code that
    compiles fine a second later - a false negative that would be charged to the model.
    The server's own instructions warn about this; the eval has to honour it.
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            r = srv.read_resource("mcpforunity://editor/state")
            last = "".join(c.get("text", "") for c in r.get("contents", []))
        except MCPError:
            time.sleep(1.0)
            continue
        if '"is_compiling": false' in last.replace(" ", "").replace('"is_compiling":false',
                                                                   '"is_compiling": false'):
            return "compiled"
        if '"is_compiling":false' in last.replace(" ", ""):
            return "compiled"
        time.sleep(1.0)
    return "timeout"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="qwen3.6:35b")
    p.add_argument("--think", default="off",
                   choices=["off", "low", "medium", "high"])
    p.add_argument("--num-ctx", type=int, default=32768)
    p.add_argument("--max-steps", type=int, default=10)
    p.add_argument("--num-predict", type=int, default=3500)
    p.add_argument("--only", default="")
    p.add_argument("--url", default=URL)
    p.add_argument("--keep", action="store_true", help="skip cleanup after each task")
    a = p.parse_args()

    srv = MCPHttpServer(a.url, name="unity")
    try:
        srv.start()
    except MCPError as e:
        print("Unity MCP sunucusuna ulasilamiyor: %s" % e)
        return 1
    inst = ""
    try:
        r = srv.read_resource("mcpforunity://instances")
        inst = "".join(c.get("text", "") for c in r.get("contents", []))
    except MCPError:
        pass
    if '"instance_count": 0' in inst:
        print("Unity Editor bagli degil. MCP for Unity penceresinde Connect'e basin.")
        return 1

    raw = srv.list_tools()
    tools = to_ollama_tools([t for t in raw if t["name"] in EVAL_TOOLS])
    print("model=%s think=%s tools=%d" % (a.model, a.think, len(tools)))
    print("-" * 100, flush=True)

    think = False if a.think == "off" else a.think
    want = {x.strip().upper() for x in a.only.split(",")} if a.only else None
    rows, passed = [], 0

    for t in TASKS:
        if want and t["id"] not in want:
            continue
        raw_exec(srv, t["cleanup"], safety=False)         # start from a known state
        before_assets = asset_snapshot(srv)
        if t.get("setup"):
            raw_exec(srv, t["setup"], safety=False)

        transcript: list = []
        repairs: list = []
        stripped: list = []

        def dispatch(name: str, args: dict):
            if name == "execute_code" and isinstance(args.get("code"), str):
                fixed, n = strip_using_directives(args["code"])
                if n:
                    args = dict(args, code=fixed)
                    stripped.append(n)
            try:
                out = content_to_text(srv.call_tool(name, args, timeout=240))
            except MCPError as e:
                out = "MCPError: " + str(e)[:300]
            transcript.append({"tool": name, "result": out[:2000]})
            return out

        guarded = guarded_dispatch(tools, dispatch, log=repairs)
        t0 = time.time()
        res = run_agent([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": t["prompt"]}],
                        tools, guarded, max_steps=a.max_steps, model=a.model,
                        think=think, num_ctx=a.num_ctx, temperature=0.0,
                        num_predict=a.num_predict, retries=2, max_nudges=2)
        wall = time.time() - t0

        blob = " ".join(x["result"] for x in transcript)
        compiled = not COMPILE_ERR.search(blob)
        ran = compiled and not RUNTIME_ERR.search(blob)
        if t.get("needs_compile"):
            raw_exec(srv, 'UnityEditor.AssetDatabase.Refresh('
                          'UnityEditor.ImportAssetOptions.ForceUpdate); return "r";',
                     safety=False)
            time.sleep(3)
            wait_for_compile(srv)
        verify_out = raw_exec(srv, t["verify"])
        try:
            correct, detail = t["check"](verify_out)
        except Exception as e:
            correct, detail = False, "check hatasi: %s" % e

        tier = "correct" if correct else ("ran" if ran else
                                          ("compiled" if compiled else "failed"))
        passed += bool(correct)
        print("[%-8s] %-3s %-42s %6.1fs steps=%2d %s"
              % (tier.upper(), t["id"], t["title"][:42], wall, len(res.turns),
                 "" if not res.error else "ERR " + str(res.error)[:60]))
        print("           %s" % str(detail)[:160])
        if res.xml_recovered:
            print("           (harness %d XML tool-call kurtardi - Ollama sablonu "
                  "ayristiramiyor)" % res.xml_recovered)
        if stripped:
            print("           (harness %d kez 'using' direktifini temizledi)"
                  % sum(stripped))
        for x in transcript:
            if COMPILE_ERR.search(x["result"]):
                m = COMPILE_ERR.search(x["result"])
                s = max(0, m.start() - 60)
                print("           compiler: ..." + x["result"][s:m.end() + 80]
                      .replace("\n", " "))
                break
        rows.append({"id": t["id"], "title": t["title"], "why": t["why"],
                     "tier": tier, "correct": bool(correct), "detail": str(detail)[:300],
                     "wall_s": round(wall, 1), "steps": len(res.turns),
                     "calls": [x["tool"] for x in transcript],
                     "repairs": repairs, "error": res.error,
                     "using_directives_stripped": sum(stripped),
                     "xml_tool_calls_recovered": res.xml_recovered,
                     "verify_raw": verify_out[:400],
                     "final": (res.final_text or "")[:400]})
        if not a.keep:
            raw_exec(srv, t["cleanup"], safety=False)
            leaked = remove_new_assets(srv, before_assets)
            if leaked:
                print("           (temizlendi: %s)" % ", ".join(leaked)[:150])

    print("-" * 100)
    print("UNITY C# SONUC: %d/%d dogru" % (passed, len(rows)))
    for r in rows:
        if not r["correct"]:
            print("  %-8s %-3s %s" % (r["tier"], r["id"], r["detail"][:110]))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports",
                       "csharp_" + a.model.replace(":", "-") + "_think-" + a.think + ".json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"model": a.model, "think": a.think, "passed": passed,
                   "total": len(rows), "tasks": rows}, f, ensure_ascii=False, indent=2)
    print("rapor -> " + out)
    srv.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
