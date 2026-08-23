"""Ask for a script in plain Turkish; get a compiled script in Unity.

This is the distilled production path from the whole test campaign. It does one job:
you name what you want (optionally naming a scene object), the model writes the C#,
Unity really compiles it, and any compiler error goes straight back to the model until
it is gone. Nothing is reported as done unless the compiler agrees.

Why it is built this way, from measurements in REPORT.md:

  * write_script (full-file overwrite) is provided because MCP for Unity has no working
    way to REPLACE an existing script: create_script refuses with "Script already
    exists" and apply_text_edits' partial format broke the file for both the model and
    the harness author. Supplying this one primitive moved the plane-game benchmark
    from 4/6 to 6/6 and cut the hardest step from 200s to 54s.
  * The compile-error feedback loop is automatic because the model repairs reliably
    when it is told exactly what is wrong, but not when left to discover it.
  * Success is verified by the Unity compiler, never by the model's summary: models in
    this project repeatedly announced success for work that had not happened.
  * attach is opt-in and never deletes: the "move -> delete" and "modify -> recreate"
    reflex showed up in four separate tests, so destructive verbs are not exposed here.

Usage:
    python unity_code.py "Player objesine WASD ile hareket eden bir script yaz"
    python unity_code.py --attach Player "ates etme scripti yaz, space ile"
    python unity_code.py --interactive
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
from core import config as CFG
from core.guard import guarded_dispatch
from mcpbridge.http_client import MCPHttpServer
from mcpbridge.client import to_ollama_tools, content_to_text, MCPError
import unity_csharp_eval as U
import unity_assets as A
import unity_sandbox as SB

# Olculen: Cloner 7.00/8 (stock 5.00, p=0.016), MCP 10/11, 29.6 tok/s - test
# edilen modeller icinde kod yazmada anlamli bicimde onde olan tek model.
# Oncelik: ortam degiskeni > apprentice.config.json > sablon > burasi (core/config.py).
DEFAULT_MODEL = CFG.env_or(["APPRENTICE_MODEL", "UNITY_CODE_MODEL"], "ollama.model",
                           "hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL")
SCRIPT_DIR = CFG.env_or("UNITY_CODE_DIR", "unity.script_dir", "Assets/Scripts")
# Only what a pure write-code-and-fix-errors loop touches. manage_asset was dropped
# after measurement: 11 parameters, 433 prompt tokens on every single turn, and no run
# ever called it. Full Unity MCP surface = 20 497 tokens (~73s prefill); this set is
# 1 150 (~4s). The tool block is re-sent with every request, so an unused tool is a
# tax paid per turn, forever.
SERVER_TOOLS = ["read_console", "validate_script"]

# Olculdu (16.6k tokenlik promptla, ayni makine):
#   num_batch  512 (varsayilan)  189 t/s  -> 88 s
#   num_batch 1024               320 t/s  -> 52 s
#   num_batch 2048               520 t/s  -> 32 s
#   num_batch 4096               730 t/s  -> 23 s   (+%285)
# GPU payi %28'de sabit kaldi (VRAM'den agirlik atmadi), decode %11 dustu.
# Bu is yukunde prefill baskin (arac blogu ~3800 token + dosya okumalari + cok tur),
# bu yuzden takas acik ara karli. DIKKAT: kisa promptla olcum yaniltir - kisa prompt
# tek batch'e sigar, sure olculemeyecek kadar kisa cikar ve oran sisirilir.
NUM_BATCH = CFG.env_or(["APPRENTICE_BATCH", "UNITY_CODE_BATCH"], "makine.num_batch", 4096, int)
# 32768 -> 65536: olcumde yavaslama YOK (28.0 -> 28.9 t/s, GPU payi %28 sabit).
# Kazanci: cok dosyali islerde sinira yaklasmamak. Sinir asilirsa Ollama prompt'u
# SESSIZCE yariya kesiyor ve model kesik parcadan emin sekilde uyduruyor.
NUM_CTX = CFG.env_or(["APPRENTICE_CTX", "UNITY_CODE_CTX"], "makine.num_ctx", 65536, int)
# Kapali alan dosya araclari (sb_*) VARSAYILAN OLARAK KAPALI. Silme yetkisi iceriyorlar
# ve bu projede silme bir kez gercek zarar verdi. UNITY_CODE_SANDBOX=1 ile acilir.
SANDBOX_MODE = os.environ.get("UNITY_CODE_SANDBOX", "0") == "1"
# Ertelenmis Refresh: write_script Refresh/derleme tetiklemez; yazmalar birikir ve
# yazma-disi ilk arac (add_component, validate_script...) ya da dongu sonu tek
# Refresh+bekleme yapar. Amaç: N dosya = N domain reload yerine 1; dosyalar arasi
# gecici "tip yok" derleme hatasi hic olusmaz.
# OLCULDU (experiments/refresh_ab.py, 3 bagli dosya, 2'ser kosu): her yazmada
# Refresh 92/88 s, ertelenmis 79/77 s -> %13, dosya basina ~6 s (bir domain
# reload'un bedeli). Arac sirasi iki kipte birebir ayni, hata 0/0. Varsayilan: ertele.
DEFER_REFRESH = os.environ.get("UNITY_CODE_DEFER", "1") == "1"
# Istek basina play_observe ust siniri (bkz. make_dispatch icindeki not).
OLCUM_SINIRI = int(os.environ.get("UNITY_CODE_OLCUM_SINIRI", "3"))
REFRESH_COUNT = {"n": 0}   # olcum: kac kez Refresh+derleme beklendi

CS_ERR = re.compile(r"([\w/\\.]+\.cs)\((\d+),(\d+)\):\s*(error CS\d+:[^\n\"]+)")

# CS kodu tasimayan ama betikten kaynaklanan Unity hatalari. Bunlar derleyiciden
# degil Unity'nin kendisinden gelir ve CS_ERR'e takilmaz; yakalanmazsa model
# "derlendi" sanilir. Alakasiz hatalari (ag/paket/editor) kapsam disi birakmak icin
# desen betik-ozgu ifadelerle sinirli tutuldu.
SCRIPT_ERR = re.compile(
    r"(?:The referenced script[^\n\"]*"
    r"|[^\n\"]*MonoBehaviour[^\n\"]*(?:missing|mismatch|can't be loaded)[^\n\"]*"
    r"|[^\n\"]*class name[^\n\"]*file name[^\n\"]*"
    r"|[^\n\"]*Unable to (?:parse|load) file[^\n\"]*\.cs[^\n\"]*"
    r"|[^\n\"]*NullReferenceException[^\n\"]*Assets/Scripts[^\n\"]*)",
    re.I)

SYSTEM = (
    "Sen bir Unity C# gelistiricisisin. Kullanicinin istedigi betikleri yazarsin.\n"
    "- Betikleri {dir} altina yaz. Dosya adi sinif adiyla AYNI olmali.\n"
    "- Var olan bir dosyayi degistirecegin zaman once read_script ile oku, sonra "
    "write_script ile TAM yeni icerigi yaz. Kismi yama yapma.\n"
    "- Yalnizca gercekten var olan Unity API'lerini kullan. Unity 6 hedefle.\n"
    "- Derleme hatasi bildirilirse hatanin gectigi dosyayi oku, sebebi bul, duzeltilmis "
    "TAM dosyayi yaz.\n"
    "- SAHNEYI OKUMA: inspect_object (bir objenin scriptleri, alan degerleri, "
    "Inspector bagliliklari), hierarchy (bir kokun ALTINDAKI tum torunlar - cok "
    "cocuklu objeler icin bunu kullan), scene_objects (genel dokum), find_users_of.\n"
    "- PROJE VARLIKLARI: list_assets ile ara ('t:AnimationClip', 't:Material', "
    "'t:Texture2D', 't:AnimatorController'), inspect_asset ile detayina bak. "
    "Bir varligin var oldugunu VARSAYMA - once ara.\n"
    "- MATERYAL YAZMA: set_material ile materyal varliginin shader ozelligini yaz "
    "(_BaseMap'e texture yolu, _BaseColor'a #RRGGBB, _Metallic'e sayi). Ozellik "
    "yoksa shader'in gercek ozellik listesini dondurur. Shader'in kendisini "
    "degistirmek icin ozellik='shader', deger=shader adi; create_asset'e de "
    "shader verilebilir.\n"
    "- SAHNEYE YAZMA: add_component (bilesen ekle), set_field (Inspector alani yaz: "
    "sayi, renk '#RRGGBB', Vector3 '1,2,3', obje referansi, ve DIZI - dizi icin "
    "degerleri \\u0001 ile ayir), create_asset (Material/AnimatorController uret).\n"
    "- set_field yanlis alan adinda mevcut alanlari listeler; o listeden dogrusunu "
    "sec, ad UYDURMA. Silme araci YOK; hicbir seyi silemezsin - bir scripti 'silmek' icin "
    "dosyayi BOSALTMA (kirik bilesen kalir), gereksiz scripti denetciye bildir. Tek istisna: "
    "remove_missing_components yalnizca KIRIK (script'i kayip) bilesenleri kaldirir.\n"
    "- Tur basina tek arac cagir. Bittiginde tek cumleyle Turkce ozetle."
)



# ---- read-only scene awareness -------------------------------------------------
# The point of these three: the model must understand an EXISTING scene without being
# able to change it. inspect_object is the important one - it walks every MonoBehaviour
# with SerializedObject and reports which scene objects each field is wired to, which
# is the dependency information you cannot get from reading the .cs file alone.
# Nothing here creates, moves or deletes anything.

# Escaping note: writing "\n" inside these C# snippets does not survive the trip
# through Python string literals into the Roslyn/CodeDom compiler - it arrives as a
# real newline and breaks the C# string constant ("Newline in constant"). Every line
# break is therefore emitted as (char)10.
_INSPECT_CS = """
var go = GameObject.Find({name});
if (go == null) return "NOT_FOUND";
var sb = new System.Text.StringBuilder();
var NL = ((char)10).ToString();
sb.Append("path=" + GetPath(go) + NL);
sb.Append("active=" + go.activeInHierarchy + " tag=" + go.tag + NL);
var p = go.transform.position;
sb.Append("position=" + p.x.ToString("F2") + "," + p.y.ToString("F2") + "," + p.z.ToString("F2") + NL);
foreach (var c in go.GetComponents<Component>()) {
    if (c == null) { sb.Append("component: <MISSING SCRIPT>" + NL); continue; }
    var t = c.GetType();
    var mb = c as MonoBehaviour;
    sb.Append("component: " + t.Name);
    if (mb == null) { sb.Append(NL); continue; }
    var ms = UnityEditor.MonoScript.FromMonoBehaviour(mb);
    if (ms != null) sb.Append("  script=" + UnityEditor.AssetDatabase.GetAssetPath(ms));
    sb.Append(NL);
    var so = new UnityEditor.SerializedObject(c);
    var it = so.GetIterator();
    while (it.NextVisible(true)) {
        if (it.name == "m_Script") continue;
        if (it.propertyType == UnityEditor.SerializedPropertyType.ObjectReference) {
            var o = it.objectReferenceValue;
            if (o == null) { sb.Append("    ref " + it.name + " = <BOS>" + NL); continue; }
            var comp2 = o as Component;
            var goRef = comp2 != null ? comp2.gameObject : (o as GameObject);
            sb.Append("    ref " + it.name + " -> ");
            if (goRef != null) sb.Append("sahne:" + GetPath(goRef) + " (" + o.GetType().Name + ")");
            else sb.Append("asset:" + UnityEditor.AssetDatabase.GetAssetPath(o) + " (" + o.GetType().Name + ")");
            sb.Append(NL);
        } else if (it.depth == 0) {
            string v = null;
            if (it.propertyType == UnityEditor.SerializedPropertyType.Float) v = it.floatValue.ToString("F2");
            else if (it.propertyType == UnityEditor.SerializedPropertyType.Integer) v = it.intValue.ToString();
            else if (it.propertyType == UnityEditor.SerializedPropertyType.Boolean) v = it.boolValue.ToString();
            else if (it.propertyType == UnityEditor.SerializedPropertyType.String) v = it.stringValue;
            else if (it.propertyType == UnityEditor.SerializedPropertyType.Vector3) v = it.vector3Value.ToString("F2");
            if (v != null) sb.Append("    " + it.name + " = " + v + NL);
        }
    }
}
if (go.transform.childCount > 0) {
    sb.Append("children:");
    foreach (Transform ch in go.transform) sb.Append(" " + ch.name);
    sb.Append(NL);
}
return sb.ToString();
"""

_HELPER = """
System.Func<GameObject,string> GetPath = null;
GetPath = delegate(GameObject g) {
    var s = g.name; var tr = g.transform.parent;
    while (tr != null) { s = tr.name + "/" + s; tr = tr.parent; }
    return s;
};
"""


def _scene_tools():
    return [
        {"type": "function", "function": {
            "name": "inspect_object",
            "description": "Sahnedeki bir GameObject'i incele: bileşenleri, her "
                           "MonoBehaviour'un script dosya yolu, alan degerleri ve "
                           "Inspector'da BAGLI oldugu diger sahne objeleri/asset'leri. "
                           "Hicbir sey degistirmez.",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "Obje adi, orn: Player"}},
                "required": ["name"]}}},
        {"type": "function", "function": {
            "name": "scene_objects",
            "description": "Sahnedeki tum objeleri ve uzerlerindeki bilesenleri listele "
                           "(salt okunur, ozet).",
            "parameters": {"type": "object", "properties": {}, "required": []}}},
        {"type": "function", "function": {
            "name": "find_users_of",
            "description": "Belirli bir script sinifinin sahnede hangi objelere ekli "
                           "oldugunu ve o objelerin hangi alanlarla neye bagli oldugunu "
                           "bul. Scriptler arasi bagi anlamak icin kullan.",
            "parameters": {"type": "object", "properties": {
                "class_name": {"type": "string",
                               "description": "Sinif adi, orn: EnemyChase"}},
                "required": ["class_name"]}}},
        {"type": "function", "function": {
            "name": "play_observe",
            "description": "Play moda girer, verdigin C# ifadesini her 0.5 saniyede bir "
                           "calistirir, sonuclari sirayla dondurur, play moddan cikar. "
                           "Yazdigin kodun GERCEKTEN istenen davranisi gosterip "
                           "gostermedigini olcmek icin: mesafeler, sinirlar, sayaclar. "
                           "Kod 'return <string>' ile bitmeli; GameObject.Find ve "
                           "Transform kullanabilirsin. Sayilari InvariantCulture ile "
                           "yaz (ToString(\"0.00\", System.Globalization."
                           "CultureInfo.InvariantCulture)).",
            "parameters": {"type": "object", "properties": {
                "kod": {"type": "string", "description": "Her ornekte calisacak C# govdesi, "
                                                         "string dondurur"},
                "saniye": {"type": "integer", "description": "Kac saniye gozlenecek (1-20)"}},
                "required": ["kod"]}}},
    ]


def build_tools(srv):
    """Server tools plus the three primitives the measurements showed were missing."""
    raw = srv.list_tools()
    tools = to_ollama_tools([t for t in raw if t["name"] in SERVER_TOOLS])
    tools += [
        {"type": "function", "function": {
            "name": "write_script",
            "description": "Bir C# betigi olustur VEYA var olanin uzerine yaz. "
                           "Dosyanin TAM icerigini ver, yama verme.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string",
                         "description": "Örn: %s/PlayerMove.cs" % SCRIPT_DIR},
                "contents": {"type": "string", "description": "Dosyanin tam icerigi"}},
                "required": ["path", "contents"]}}},
        {"type": "function", "function": {
            "name": "read_script",
            "description": "Var olan bir C# betiginin tam icerigini oku.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Asset yolu"}},
                "required": ["path"]}}},
        {"type": "function", "function": {
            "name": "list_scripts",
            "description": "Proje icindeki C# betiklerini listele.",
            "parameters": {"type": "object", "properties": {
                "folder": {"type": "string",
                           "description": "Alt klasor, bos birakilirsa %s" % SCRIPT_DIR}},
                "required": []}}},
    ] + _scene_tools() + A.tanimlar() + (SB.tanimlar() if SANDBOX_MODE else [])
    return tools


def make_dispatch(srv, log):
    def w(path, contents):
        path = str(path or "").replace("\\", "/")
        if not path.endswith(".cs") or not path.startswith("Assets/"):
            return {"error": "yol Assets/ ile baslamali ve .cs ile bitmeli"}
        folder = path.rsplit("/", 1)[0]
        refresh_cs = ("" if DEFER_REFRESH else
                      'UnityEditor.AssetDatabase.Refresh('
                      'UnityEditor.ImportAssetOptions.ForceUpdate); ')
        code = ('System.IO.Directory.CreateDirectory(%s); '
                'System.IO.File.WriteAllText(%s, %s); '
                '%sreturn "written";'
                % (json.dumps(folder), json.dumps(path), json.dumps(str(contents or "")),
                   refresh_cs))
        out = U.raw_exec(srv, code, safety=False)
        ok = '"written"' in out
        durum = "ertelendi"
        if ok and DEFER_REFRESH:
            log.append(path)
            kirli["n"] += 1
            return {"ok": True, "path": path, "bytes": len(contents or ""),
                    "derleme": "ertelendi (bir sonraki arac ya da is sonunda)"}
        if ok:
            log.append(path)
            REFRESH_COUNT["n"] += 1
            # Derleme bitmeden donme. Refresh derlemeyi baslatir ama beklemez; model
            # hemen add_component deyince "TIP YOK" aliyordu (kullanici gozlemi:
            # ilk deneme hata, ikincisi tamam - arada derleme bitmisti). Bu bir
            # harness yarisi, model hatasi degil. refresh() ile ayni zamanlama:
            # is_compiling bayragi Refresh'ten hemen sonra henuz kalkmamis olabilir.
            time.sleep(2.0)
            durum = U.wait_for_compile(srv, timeout=120)
            time.sleep(1.0)
        return {"ok": ok, "path": path, "bytes": len(contents or ""),
                "derleme": "bitti" if durum == "compiled" else "zaman asimi"} if ok \
            else {"error": "yazilamadi", "raw": out[:200]}

    def r(path):
        code = ('var p = %s; if (!System.IO.File.Exists(p)) return "YOK"; '
                'return System.IO.File.ReadAllText(p);'
                % json.dumps(str(path or "").replace("\\", "/")))
        out = U.raw_exec(srv, code)
        try:
            body = json.loads(out).get("data", {}).get("result", "")
        except Exception:
            body = out
        return {"path": path, "contents": body} if body != "YOK" \
            else {"error": "dosya yok: %s" % path}

    def ls(folder=""):
        folder = str(folder or SCRIPT_DIR).replace("\\", "/")
        code = ('var d = %s; if (!System.IO.Directory.Exists(d)) return "YOK"; '
                'var sb = new System.Text.StringBuilder(); '
                'foreach (var f in System.IO.Directory.GetFiles(d, "*.cs", '
                'System.IO.SearchOption.AllDirectories)) '
                '{ sb.Append(f.Replace((char)92,(char)47)); sb.Append((char)10); } '
                'return sb.ToString();' % json.dumps(folder))
        out = U.raw_exec(srv, code)
        try:
            body = json.loads(out).get("data", {}).get("result", "")
        except Exception:
            body = out
        if body == "YOK":
            return {"folder": folder, "scripts": [], "note": "klasor yok"}
        return {"folder": folder,
                "scripts": [x.strip() for x in str(body).splitlines() if x.strip()]}

    def inspect_obj(name):
        code = _HELPER + _INSPECT_CS.replace("{name}", json.dumps(str(name or "")))
        out = U.raw_exec(srv, code, timeout=180)
        try:
            body = json.loads(out).get("data", {}).get("result", "")
        except Exception:
            body = out
        if body == "NOT_FOUND":
            return {"error": "sahnede '%s' adinda obje yok" % name}
        return {"object": name, "detail": body}

    def scene_objs():
        code = _HELPER + """
var sb = new System.Text.StringBuilder();
var sc = UnityEngine.SceneManagement.SceneManager.GetActiveScene();
var NL = ((char)10).ToString();
sb.Append("scene=" + sc.name + NL);
foreach (var root in sc.GetRootGameObjects()) {
    var all = root.GetComponentsInChildren<Transform>(true);
    foreach (var tr in all) {
        var g = tr.gameObject;
        sb.Append(GetPath(g) + "  [");
        bool first = true;
        foreach (var c in g.GetComponents<Component>()) {
            if (c == null) { sb.Append(first ? "" : ", "); sb.Append("<MISSING>"); first = false; continue; }
            var n = c.GetType().Name;
            if (n == "Transform" || n == "RectTransform") continue;
            sb.Append(first ? "" : ", "); sb.Append(n); first = false;
        }
        sb.Append("]" + NL);
    }
}
return sb.ToString();
"""
        out = U.raw_exec(srv, code, timeout=180)
        try:
            body = json.loads(out).get("data", {}).get("result", "")
        except Exception:
            body = out
        return {"scene": body}

    def users_of(class_name):
        cn = json.dumps(str(class_name or ""))
        code = _HELPER + """
var t = System.Type.GetType(""" + cn + """ + ", Assembly-CSharp");
if (t == null) foreach (var a in System.AppDomain.CurrentDomain.GetAssemblies()) {
    var c = a.GetType(""" + cn + """); if (c != null) { t = c; break; } }
if (t == null) return "NO_TYPE";
var sb = new System.Text.StringBuilder();
// Compat sarmalayici: FindObjectsByType imzasi Unity 6.5'te degisiyor; kapiyi paket tasir.
var found = MCPForUnity.Runtime.Helpers.UnityFindObjectsCompat.FindAll(t, true);
var NL = ((char)10).ToString();
sb.Append("kullanan_obje_sayisi=" + found.Length + NL);
foreach (var o in found) {
    var c = o as Component; if (c == null) continue;
    sb.Append(GetPath(c.gameObject) + NL);
    var so = new UnityEditor.SerializedObject(c);
    var it = so.GetIterator();
    while (it.NextVisible(true)) {
        if (it.name == "m_Script") continue;
        if (it.propertyType != UnityEditor.SerializedPropertyType.ObjectReference) continue;
        var r = it.objectReferenceValue;
        sb.Append("    " + it.name + " -> ");
        if (r == null) { sb.Append("<BOS>" + NL); continue; }
        var rc = r as Component; var rg = rc != null ? rc.gameObject : (r as GameObject);
        if (rg != null) sb.Append("sahne:" + GetPath(rg) + " (" + r.GetType().Name + ")" + NL);
        else sb.Append("asset:" + UnityEditor.AssetDatabase.GetAssetPath(r) + NL);
    }
}
return sb.ToString();
"""
        out = U.raw_exec(srv, code, timeout=180)
        try:
            body = json.loads(out).get("data", {}).get("result", "")
        except Exception:
            body = out
        if body == "NO_TYPE":
            return {"error": "'%s' adinda derlenmis bir sinif yok" % class_name}
        return {"class": class_name, "usage": body}

    def varlik(name, args):
        """unity_assets araclarini C#'a cevirip calistirir.

        Ham C# ciktisini oldugu gibi dondururuz: araclar zaten insan-okur metin
        uretiyor (EKLENDI/YAZILDI/ALAN YOK + mevcut alan listesi). Model bu metni
        okuyup yanlis alan adini kendi duzeltebiliyor - JSON'a sarmak bilgi kaybi
        olurdu."""
        try:
            if name == "list_assets":
                kod = A.list_assets_cs(args.get("filtre", ""), args.get("klasor"),
                                       int(args.get("limit") or 25))
            elif name == "inspect_asset":
                kod = A.inspect_asset_cs(args.get("yol", ""))
            elif name == "hierarchy":
                kod = A.hierarchy_cs(args.get("kok"), int(args.get("derinlik") or 3),
                                     int(args.get("limit") or 60))
            elif name == "add_component":
                kod = A.add_component_cs(args.get("obje", ""), args.get("tip", ""))
            elif name == "remove_missing_components":
                kod = A.remove_missing_cs(args.get("obje", ""))
            elif name == "set_field":
                kod = A.set_field_cs(args.get("obje", ""), args.get("bilesen", ""),
                                     args.get("alan", ""), str(args.get("deger", "")))
            elif name == "create_asset":
                kod = A.create_asset_cs(args.get("tur", ""), args.get("yol", ""),
                                        args.get("ozellik"), args.get("shader", ""))
            elif name == "set_material":
                kod = A.set_material_cs(args.get("yol", ""), args.get("ozellik", ""),
                                        args.get("deger", ""))
            elif name == "list_animator_states":
                kod = A.list_animator_states_cs(args.get("controller", ""))
            elif name == "add_animator_state":
                kod = A.add_animator_state_cs(
                    args.get("controller", ""), args.get("state", ""),
                    args.get("klip", ""), args.get("varsayilan", ""),
                    args.get("hiz"), args.get("ofset"))
            elif name == "create_override_controller":
                kod = A.create_override_controller_cs(
                    args.get("temel", ""), args.get("yol", ""),
                    args.get("eslemeler", ""))
            else:
                kod = A.set_animator_cs(args.get("obje", ""),
                                        args.get("controller", ""))
        except (TypeError, ValueError) as e:
            return {"error": "argüman hatasi: %s" % e}
        out = U.raw_exec(srv, kod, safety=False, timeout=240)
        try:
            d = json.loads(out)
        except Exception:
            return {"sonuc": out[:600]}
        if not d.get("success"):
            hatalar = (d.get("data") or {}).get("errors") or []
            return {"error": "; ".join(hatalar[:3])[:400] or str(d.get("message"))[:200]}
        sonuc = (d.get("data") or {}).get("result", "")
        # Ikinci emniyet: tip bulunamadiysa derleme hala suruyor olabilir (ornegin
        # baska bir yoldan yazilmis dosya). Bir kez bekle ve tekrar dene; yine yoksa
        # gercekten yok demektir ve model oyle gormeli.
        if isinstance(sonuc, str) and sonuc.startswith("TIP YOK"):
            U.wait_for_compile(srv, timeout=60)
            time.sleep(1.0)
            out2 = U.raw_exec(srv, kod, safety=False, timeout=240)
            try:
                d2 = json.loads(out2)
                if d2.get("success"):
                    sonuc = (d2.get("data") or {}).get("result", sonuc)
            except Exception:
                pass
        return {"sonuc": sonuc}

    def kapali_alan(name, args):
        """sb_* araclari. Hapishane ihlali C# hic uretilmeden yakalanir."""
        try:
            if name == "sb_list":
                kod = SB.liste_cs(args.get("klasor"))
            elif name == "sb_create":
                kod = SB.olustur_cs(args.get("yol", ""), args.get("icerik", ""))
            elif name == "sb_rename":
                kod = SB.adlandir_cs(args.get("yol", ""), args.get("yeni_ad", ""))
            elif name == "sb_move":
                kod = SB.tasi_cs(args.get("yol", ""), args.get("hedef_klasor", ""))
            elif name == "sb_copy":
                kod = SB.kopyala_cs(args.get("yol", ""), args.get("hedef_yol", ""))
            elif name == "sb_delete":
                kod = SB.sil_cs(args.get("yol", ""))
            else:
                return {"error": "bilinmeyen sandbox araci: %s" % name}
        except SB.HapisHatasi as e:
            return {"error": "REDDEDILDI (kapali alan disi): %s" % e}
        out = U.raw_exec(srv, kod, safety=False, timeout=180)
        try:
            d = json.loads(out)
        except Exception:
            return {"sonuc": out[:400]}
        if not d.get("success"):
            return {"error": "; ".join((d.get("data") or {}).get("errors", [])[:2])[:300]
                    or str(d.get("message"))[:200]}
        return {"sonuc": (d.get("data") or {}).get("result", "")}

    kirli = {"n": 0}   # ertelenmis, henuz import edilmemis yazma sayisi
    sayac = {"olcum": 0}

    def flush():
        """Biriken yazmalari tek Refresh + derleme beklemesiyle ice aktarir."""
        if kirli["n"] == 0:
            return
        kirli["n"] = 0
        REFRESH_COUNT["n"] += 1
        U.raw_exec(srv, 'UnityEditor.AssetDatabase.Refresh('
                        'UnityEditor.ImportAssetOptions.ForceUpdate); return "r";',
                   safety=False)
        time.sleep(2.0)
        U.wait_for_compile(srv, timeout=120)
        time.sleep(1.0)

    def inner(name, args):
        if name == "write_script":
            return w(args.get("path"), args.get("contents"))
        # Yazma-disi her arac derlenmis dunyayi gormeli: once biriken yazmalari isle.
        # read/list yalnizca diski okur, onlara gerek yok.
        if name not in ("read_script", "list_scripts"):
            flush()
        if name == "read_script":
            return r(args.get("path"))
        if name == "list_scripts":
            return ls(args.get("folder", ""))
        if name == "inspect_object":
            return inspect_obj(args.get("name"))
        if name == "scene_objects":
            return scene_objs()
        if name == "find_users_of":
            return users_of(args.get("class_name"))
        if name == "play_observe":
            # Istek basina olcum siniri. Gozlem: model olc->yaz->olc dongusune
            # girip 4 turda yakinsamadi, davranis kotulesti (min mesafe 1.15 ->
            # 0.01); kullanici elle durdurdu. Ayni veriyi OZETLEYIP ben verince
            # 2 turda cozmustu. Sinirda durup raporlamak, sonsuz dongunun onu.
            sayac["olcum"] += 1
            if sayac["olcum"] > OLCUM_SINIRI:
                return {"error": "OLCUM SINIRI: bu istekte %d olcum yapildi. Daha fazla "
                                 "olcme. Son olcumun sayisal OZETINI (min/ort/max, ihlal "
                                 "sayisi) ve hangi kuralin tutmadigini kullaniciya "
                                 "raporla, nasil devam edilecegini ona sor." % OLCUM_SINIRI}
            flush()
            return play_observe(srv, str(args.get("kod") or ""),
                                int(args.get("saniye") or 8))
        # --- unity_assets araclari: varlik gorme, derin hiyerarsi, Inspector yazma ---
        if name.startswith("sb_"):
            return kapali_alan(name, args)
        if name in ("list_assets", "inspect_asset", "hierarchy", "add_component",
                    "remove_missing_components", "set_field", "create_asset", "set_material",
                    "list_animator_states", "add_animator_state",
                    "create_override_controller", "set_animator"):
            return varlik(name, args)
        try:
            return content_to_text(srv.call_tool(name, args, timeout=240))
        except MCPError as e:
            return {"error": "mcp: " + str(e)[:200]}
    inner.flush = flush
    inner.reset = lambda: sayac.update(olcum=0)
    return inner


CS_WARN = re.compile(r"([\w/\\.]+\.cs)\((\d+),(\d+)\):\s*(warning CS\d+:[^\n\"]+)")


def script_warnings(srv):
    """Kendi betiklerimizle ilgili derleyici uyarilari.

    Hatalardan AYRI tutuluyor cunku uyarilar derlemeyi engellemez - ama onemli
    olanlari var: CS0618 (kullanimdan kaldirilmis API) tam olarak "bugun calisir,
    yarin kirilir" sinifi. Ilk surum yalnizca hatalara bakiyordu ve model uc yerde
    Unity 6'da deprecate edilmis FindObjectOfType kullandi; kod temiz gorunuyordu.

    Yalnizca SCRIPT_DIR altindaki dosyalar dondurulur: paket/editor uyarilari bizim
    sorumlulugumuz degil ve onarim turunu bosa harcatir."""
    try:
        raw = content_to_text(srv.call_tool(
            "read_console", {"action": "get", "types": ["warning"], "count": 60},
            timeout=120))
    except MCPError:
        return []
    kok = SCRIPT_DIR.replace("/", "").replace("\\", "").lower()
    seen, out = set(), []
    for m in CS_WARN.finditer(raw):
        yol = m.group(1).replace("/", "").replace("\\", "").lower()
        if kok not in yol:
            continue                      # bizim betigimiz degil
        line = m.group(0).strip()
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _oyna(srv, kod):
    """Play modu kontrolu icin kisa C# calistirir; kopma durumunda None doner."""
    try:
        ham = U.raw_exec(srv, kod, safety=False, timeout=180)
        d = json.loads(ham)
        return (d.get("data") or {}).get("result") if d.get("success") else None
    except Exception:
        return None


def runtime_errors(srv):
    """Konsoldaki hatalardan BIZIM betiklerimizle ilgili olanlari sec.

    Derleme hatalarindan tamamen ayri bir sinif: kod kusursuz derlenir, calisirken
    patlar. Bu oturumda iki kez yasandi - 'Animator.playbackTime' (etkisiz API) ve
    'Play(string,...)' (yanlis asiri yukleme). Ikisi de 0 derleme hatasi verdi ve
    yalnizca play modda gorundu.

    Filtre yol tabanli: yigin izinde SCRIPT_DIR gecen hatalar bizimdir. Unity'nin
    kendi/paket hatalarini almamak icin bu sinir sart."""
    # include_stacktrace SART: varsayilan cagri yalnizca MESAJ metnini donduruyor,
    # yigin izini ("at Assets/Scripts/X.cs:82") vermiyor. Ilk surum yol tabanli
    # filtreliyordu ve yol hic gelmedigi icin HER runtime hatasini eliyordu - kanca
    # kuruluydu ama hicbir sey yakalamiyordu.
    try:
        ham = content_to_text(srv.call_tool(
            "read_console", {"action": "get", "types": ["error"], "count": 40,
                             "include_stacktrace": True, "format": "detailed"},
            timeout=120))
    except MCPError:
        return []
    kok = SCRIPT_DIR.replace("/", "").replace("\\", "").lower()
    out, seen = [], set()
    for parca in re.split(r"\},\s*\{|\n\n+", ham):
        duz = re.sub(r"\s+", " ", parca).strip()
        if not duz or '"success"' in duz and len(duz) < 60:
            continue
        yolsuz = duz.replace("/", "").replace("\\", "").lower()
        # Yigin izi geldiyse yol esleşmesi, gelmediyse Unity'nin bilinen runtime
        # hata kaliplari. Ikisi de tutmuyorsa bizim degildir.
        bizim = (kok in yolsuz
                 or re.search(r"NullReferenceException|MissingReference|"
                              r"IndexOutOfRange|Animator\.|GotoState|"
                              r"could not be found|bulunamadi", duz, re.I))
        if not bizim:
            continue
        kisa = duz[:260]
        if kisa not in seen:
            seen.add(kisa)
            out.append(kisa)
    return out


_BATCH_CS = r"""
UnityEditor.SessionState.SetString("apprentice.obs", "");
UnityEditor.SessionState.SetInt("apprentice.obs.n", 0);
string NL = ((char)10).ToString();
double sonraki = UnityEditor.EditorApplication.timeSinceStartup;
double bitis = UnityEditor.EditorApplication.timeSinceStartup + __SANIYE__;
UnityEditor.EditorApplication.CallbackFunction tick = null;
System.Func<string> olc = () => { __KOD__ };
tick = () => {
    double t = UnityEditor.EditorApplication.timeSinceStartup;
    if (t >= bitis || !UnityEditor.EditorApplication.isPlaying) {
        UnityEditor.EditorApplication.update -= tick;
        UnityEditor.SessionState.SetInt("apprentice.obs.n", -1); return; }
    if (t < sonraki) return;
    sonraki = t + 0.5;
    string v; try { v = olc(); } catch (System.Exception e) { v = "HATA:" + e.GetType().Name + ": " + e.Message; }
    UnityEditor.SessionState.SetString("apprentice.obs",
        UnityEditor.SessionState.GetString("apprentice.obs", "") + v.Replace(NL, " ") + NL);
    UnityEditor.SessionState.SetInt("apprentice.obs.n", UnityEditor.SessionState.GetInt("apprentice.obs.n", 0) + 1);
};
UnityEditor.EditorApplication.update += tick;
return "kuruldu";
"""


def _observe_batched(srv, kod, saniye):
    """Ornekleri Unity icinde biriktir (EditorApplication.update, 0.5 sn), tek okumayla al.

    Neden: her ornek icin ayri execute_code = ayri codedom derlemesi; editorun ana
    dongusunu takar ve 15 sn'de ancak ~10 ornek alinir. Burada 15 sn ~30 ornek.
    Kurulum derlenmezse None doner, eski tek tek yol kullanilir.
    """
    cs = _BATCH_CS.replace("__SANIYE__", "%.1f" % saniye).replace("__KOD__", kod)
    ham = U.raw_exec(srv, cs, safety=False, timeout=60)
    try:
        d = json.loads(ham)
    except Exception:
        return None
    if not d.get("success"):
        return None
    bitis = time.time() + saniye + 10
    while time.time() < bitis:
        time.sleep(1.0)
        n = _oyna(srv, "return UnityEditor.SessionState.GetInt(\"apprentice.obs.n\", 0).ToString();")
        if n == "-1":
            break
    metin = _oyna(srv, "return UnityEditor.SessionState.GetString(\"apprentice.obs\", \"\");") or ""
    ornekler = [x for x in metin.split(chr(10)) if x.strip()]
    hatalar = [x for x in ornekler if x.startswith("HATA:")][:2]
    return {"saniye": saniye, "ornek_sayisi": len(ornekler), "ornekler": ornekler,
            "hatalar": hatalar, "toplu": True}


def play_observe(srv, kod, saniye=8, zaman_asimi=40):
    """Modelin kendi olcum kodunu play modda ornekler.

    Neden var: "2 birimden fazla yaklasmasin" gorevinde model yumusak itme yazdi,
    "yaklasmaz" diye raporladi; derleyici de play modu da gecti cunku HATA yoktu,
    YANLIS DAVRANIS vardi. Bu sinifi ancak olcum yakalar. Arac modele olcme
    imkani verir; olcup olcmedigi ve olcunce anlayip anlamadigi ayri bir sorudur.
    """
    kod = (kod or "").strip()
    if not kod:
        return {"error": "kod bos"}
    if "return" not in kod:
        return {"error": "kod 'return <string>' ile bitmeli"}
    saniye = max(1, min(20, int(saniye or 8)))
    girdi = False
    ornekler, hatalar = [], []
    try:
        _oyna(srv, "UnityEditor.EditorApplication.isPlaying = true; return \"g\";")
        bitis = time.time() + zaman_asimi
        while time.time() < bitis:
            time.sleep(2)
            if _oyna(srv, "return UnityEditor.EditorApplication.isPlaying "
                          "? \"P\" : \"E\";") == "P":
                girdi = True
                break
        if not girdi:
            return {"error": "play moda girilemedi (%d sn)" % zaman_asimi}
        # OLCULDU (2026-08-23): editor odakta degilken Unity play dongusunu DURAKLATIR;
        # ornekler 4-6 sn boyunca birebir ayni geldi, "kod donuyor" sanildi. runInBackground
        # acilmazsa olcum editorun odagina bagli olur.
        _oyna(srv, "UnityEngine.Application.runInBackground = true; return \"r\";")
        time.sleep(2.0)                          # Start()/ilk kareler
        toplu = _observe_batched(srv, kod, saniye)
        if toplu is not None:
            return toplu
        t0 = time.time()
        while time.time() - t0 < saniye:
            ham = U.raw_exec(srv, kod, safety=False, timeout=60)
            try:
                d = json.loads(ham)
                if d.get("success"):
                    ornekler.append(str((d.get("data") or {}).get("result", "")))
                else:
                    err = "; ".join(((d.get("data") or {}).get("errors") or [])[:2]) \
                          or str(d.get("message"))
                    hatalar.append(err[:300])
                    if len(hatalar) >= 2:
                        break               # derlenmeyen kodu 20 kez denemeyelim
            except Exception:
                hatalar.append(ham[:200])
            time.sleep(0.5)
        return {"saniye": saniye, "ornek_sayisi": len(ornekler), "ornekler": ornekler,
                "hatalar": hatalar[:2]}
    finally:
        if girdi:
            _oyna(srv, "UnityEditor.EditorApplication.isPlaying = false; return \"ok\";")
            bitis = time.time() + zaman_asimi
            while time.time() < bitis:
                time.sleep(2)
                if _oyna(srv, "return UnityEditor.EditorApplication.isPlaying "
                              "? \"P\" : \"E\";") == "E":
                    break


def play_probe(srv, isinma=3.0, zaman_asimi=40, verbose=True):
    """Play moda girer, Start() calissin diye bekler, runtime hatalarini toplar, cikar.

    Konsol GIRISTEN ONCE temizlenir: amac calisma zamani hatalarini derleme
    gurultusunden ayirmak. Cikis her durumda denenir (finally) - Editor'u play modda
    birakmak kullaniciyi bloke ederdi.

    Olculdu: giris ~2-3 sn, MCP koprusu play moda gecişte ve cikista SAG KALIYOR
    (uc kez denendi). Toplam maliyet ~15-20 sn."""
    try:
        srv.call_tool("read_console", {"action": "clear"}, timeout=60)
    except MCPError:
        pass
    time.sleep(1)
    girdi = False
    try:
        _oyna(srv, "UnityEditor.EditorApplication.isPlaying = true; return \"g\";")
        bitis = time.time() + zaman_asimi
        while time.time() < bitis:
            time.sleep(2)
            if _oyna(srv, "return UnityEditor.EditorApplication.isPlaying "
                          "? \"P\" : \"E\";") == "P":
                girdi = True
                break
        if not girdi:
            if verbose:
                print("   ! play moda girilemedi (%d sn) - atlaniyor" % zaman_asimi,
                      flush=True)
            return None
        time.sleep(isinma)                      # Start()/ilk kareler
        return runtime_errors(srv)
    finally:
        if girdi:
            _oyna(srv, "UnityEditor.EditorApplication.isPlaying = false; return \"ok\";")
            bitis = time.time() + zaman_asimi
            while time.time() < bitis:
                time.sleep(2)
                if _oyna(srv, "return UnityEditor.EditorApplication.isPlaying "
                              "? \"P\" : \"E\";") == "E":
                    break


def compile_errors(srv):
    """Konsoldaki hatalari topla: derleme (CS) + betikle ilgili CS-DISI hatalar.

    Ilk surum yalnizca 'error CS####' ariyordu. Unity'nin betikten kaynaklanan ama CS
    kodu tasimayan hatalari (eksik referans, MonoBehaviour'un dosya adiyla eslesmemesi,
    seri hale getirme hatalari) bu ada takilmadigi icin sessizce kaciyordu - model
    "derlendi" saniliyordu. Simdi ikinci bir desen bunlari da yakaliyor.

    Alakasiz Unity hatalari (ag, paket, editor eklentisi) onarim dongusunu bosuna
    calistirmasin diye yalnizca betik/derleme ile ILGILI olanlar dondurulur."""
    try:
        raw = content_to_text(srv.call_tool(
            "read_console", {"action": "get", "types": ["error"], "count": 40},
            timeout=120))
    except MCPError:
        return []
    seen, out = set(), []
    for m in CS_ERR.finditer(raw):
        line = m.group(0).strip()
        if line not in seen:
            seen.add(line)
            out.append(line)
    for m in SCRIPT_ERR.finditer(raw):
        line = re.sub(r"\s+", " ", m.group(0)).strip()[:220]
        if "referenced script" in line.lower():
            # Dosya yazarak duzelmez; isci 16 kez denedi (Cursor deneyi). Eylemi soyle.
            line += (" [COZUM: sinif adi dosya adiyla ayni mi ve derleniyor mu kontrol et; "
                     "script gercekten yoksa remove_missing_components(obje) ile kirik bileseni kaldir]")
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def refresh(srv):
    U.raw_exec(srv, 'UnityEditor.AssetDatabase.Refresh('
                    'UnityEditor.ImportAssetOptions.ForceUpdate); return "r";',
               safety=False)
    time.sleep(3)
    U.wait_for_compile(srv)
    time.sleep(2)


def attach(srv, obj, cls):
    """Attach a compiled component to a scene object. Never deletes anything."""
    code = ('var go = GameObject.Find(%s); if (go == null) return "NO_OBJECT"; '
            'var t = System.Type.GetType(%s + ", Assembly-CSharp"); '
            'if (t == null) { foreach (var a in System.AppDomain.CurrentDomain'
            '.GetAssemblies()) { var c = a.GetType(%s); if (c != null) { t = c; break; } } } '
            'if (t == null) return "NO_TYPE"; '
            'if (go.GetComponent(t) != null) return "ALREADY"; '
            'UnityEditor.Undo.AddComponent(go, t); return "ATTACHED";'
            % (json.dumps(obj), json.dumps(cls), json.dumps(cls)))
    out = U.raw_exec(srv, code, safety=False)
    for tag in ("ATTACHED", "ALREADY", "NO_OBJECT", "NO_TYPE"):
        if tag in out:
            return tag
    return "ERROR"


def _flush(dispatch):
    """Ertelenmis yazmalari isle. guarded_dispatch sarmalayicisi flush'i tasimaz;
    ic fonksiyona ulasmak icin __wrapped__ ya da dogrudan nitelik denenir."""
    for cand in (dispatch, getattr(dispatch, "__wrapped__", None),
                 getattr(dispatch, "inner", None)):
        f = getattr(cand, "flush", None) if cand is not None else None
        if callable(f):
            f()
            return


def one_request(srv, tools, dispatch, msgs, request, model, max_repairs,
                verbose=True, fix_warnings=True, play_check=False,
                play_repairs=2):
    written: list = []
    dispatch_log = written
    msgs.append({"role": "user", "content": request})
    for cand in (dispatch, getattr(dispatch, "inner", None)):
        f = getattr(cand, "reset", None) if cand is not None else None
        if callable(f):
            f()
            break
    t0 = time.time()
    rounds = 0
    while True:
        res = run_agent(msgs, tools, dispatch, max_steps=12, model=model, think=False,
                        num_ctx=NUM_CTX, temperature=0.0, num_predict=6000,
                        retries=2, extra_options={"num_batch": NUM_BATCH})
        msgs[:] = res.messages
        _flush(dispatch)
        refresh(srv)
        errs = compile_errors(srv)
        if verbose:
            for n, a in res.calls:
                detail = a.get("path", "") if isinstance(a, dict) else ""
                print("   %-16s %s" % (n, detail), flush=True)
        if not errs:
            break
        if rounds >= max_repairs:
            break
        rounds += 1
        if verbose:
            print("   ! derleme hatasi (%d) - onarim turu %d" % (len(errs), rounds),
                  flush=True)
            print("     %s" % errs[0][:130], flush=True)
        msgs.append({"role": "user", "content":
                     "DERLEME HATASI (Unity konsolu):\n" + "\n".join(errs[:8])
                     + "\nHatanin gectigi dosyayi read_script ile oku, sebebi bul ve "
                       "write_script ile duzeltilmis TAM dosyayi yaz."})

    # Hatalar bittikten SONRA tek bir uyari temizleme turu. Neden dongu degil tek tur:
    # uyari derlemeyi engellemez, bazilari da kacinilmazdir; sinirsiz tur harcamak
    # yerine bir sans verilir. Yeni hata dogarsa yukaridaki dongu zaten yakalayamaz,
    # bu yuzden temizlik sonrasi hatalar tekrar okunur ve raporlanir.
    warns = script_warnings(srv) if not errs and fix_warnings else []
    if warns:
        if verbose:
            print("   ! derleyici uyarisi (%d) - temizleme turu" % len(warns),
                  flush=True)
            print("     %s" % warns[0][:130], flush=True)
        msgs.append({"role": "user", "content":
                     "DERLEYICI UYARISI (Unity konsolu):\n" + "\n".join(warns[:8])
                     + "\nBunlar derlemeyi engellemez ama kod kalitesi sorunudur "
                       "(ozellikle kullanimdan kaldirilmis API). Ilgili dosyayi "
                       "read_script ile oku ve write_script ile duzeltilmis TAM "
                       "dosyayi yaz. Davranisi DEGISTIRME, sadece uyariyi gider."})
        res = run_agent(msgs, tools, dispatch, max_steps=12, model=model, think=False,
                        num_ctx=NUM_CTX, temperature=0.0, num_predict=6000,
                        retries=2, extra_options={"num_batch": NUM_BATCH})
        msgs[:] = res.messages
        _flush(dispatch)
        refresh(srv)
        errs = compile_errors(srv)
        warns = script_warnings(srv)
        if verbose:
            for n, a in res.calls:
                print("   %-16s %s" % (n, a.get("path", "")
                                       if isinstance(a, dict) else ""), flush=True)
    # ---- play modda davranis dogrulamasi (opsiyonel) -------------------------------
    # Derleyici "calisir mi" sorusunu cevaplamiyor. Bu adim play moda girip Start()
    # sirasinda cikan runtime hatalarini toplayip modele geri verir. Olculdu: iki
    # ayri vaka (playbackTime, Play'in yanlis asiri yuklemesi) yalnizca burada
    # gorunur oldu; ikisi de 0 derleme hatasiyla gecmisti.
    rt = []
    play_dogrulandi = False
    if play_check and not errs:
        for tur in range(max(1, play_repairs) + 1):
            rt = play_probe(srv, verbose=verbose)
            if rt is None:
                # Play moda GIRILEMEDI. Bunu "temiz" saymak yanlis olur: dogrulama
                # yapilmadi demek, hata yok demek degil. Ilk surum ikisini ayirt
                # etmiyordu ve dogrulanmamis bir kosu "TEMIZ" raporlaniyordu.
                rt = []
                break
            play_dogrulandi = True
            if not rt or tur >= play_repairs:
                break
            if verbose:
                print("   ! CALISMA ZAMANI hatasi (%d) - play onarim turu %d"
                      % (len(rt), tur + 1), flush=True)
                print("     %s" % rt[0][:150], flush=True)
            msgs.append({"role": "user", "content":
                         "CALISMA ZAMANI HATASI (Unity play modda, konsoldan):\n"
                         + "\n".join(rt[:6])
                         + "\nKod DERLENIYOR ama calisirken hata veriyor. Ilgili "
                           "dosyayi read_script ile oku, sebebi bul ve write_script "
                           "ile duzeltilmis TAM dosyayi yaz. Yalnizca hatanin "
                           "sebebini degistir, calisan kismi bozma."})
            res = run_agent(msgs, tools, dispatch, max_steps=12, model=model,
                            think=False, num_ctx=NUM_CTX, temperature=0.0,
                            num_predict=6000, retries=2,
                            extra_options={"num_batch": NUM_BATCH})
            msgs[:] = res.messages
            _flush(dispatch)
            refresh(srv)
            errs = compile_errors(srv)
            if errs:                            # onarim derlemeyi bozduysa dur
                break
            if verbose:
                for n, a in res.calls:
                    print("   %-16s %s" % (n, a.get("path", "")
                                           if isinstance(a, dict) else ""), flush=True)

    return {"errors": errs, "warnings": warns, "runtime": rt,
            "play_dogrulandi": play_dogrulandi, "rounds": rounds,
            "wall": time.time() - t0, "text": res.final_text or "",
            "calls": [n for n, _ in res.calls]}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("request", nargs="*", help="ne istedigin, duz Turkce")
    p.add_argument("--attach", default="", metavar="OBJE",
                   help="derlendikten sonra bu sahne objesine bileseni ekle")
    p.add_argument("--class-name", default="", help="--attach icin sinif adi")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--repairs", type=int, default=3, help="otomatik onarim turu siniri")
    p.add_argument("--play", action="store_true",
                   help="is bitince play moda girip CALISMA ZAMANI hatalarini "
                        "topla ve modele onart (~15-20 sn ek)")
    p.add_argument("--play-repairs", type=int, default=2,
                   help="calisma zamani onarim turu siniri")
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--url", default=U.URL)
    a = p.parse_args()

    if not a.request and not a.interactive:
        p.error("bir istek yaz ya da --interactive kullan")

    srv = MCPHttpServer(a.url, name="unity")
    try:
        srv.start()
    except MCPError as e:
        print("Unity MCP sunucusuna ulasilamadi: %s" % str(e)[:150])
        return 1
    inst = "".join(c.get("text", "") for c in
                   srv.read_resource("mcpforunity://instances").get("contents", []))
    if '"instance_count": 0' in inst:
        print("Unity Editor bagli degil - MCP for Unity penceresinde Connect'e basin.")
        return 1

    tools = build_tools(srv)
    written: list = []
    dispatch = guarded_dispatch(tools, make_dispatch(srv, written))
    msgs = [{"role": "system", "content": SYSTEM.format(dir=SCRIPT_DIR)}]
    print("model=%s  klasor=%s  onarim_siniri=%d" % (a.model, SCRIPT_DIR, a.repairs))

    queue = [" ".join(a.request)] if a.request else []
    try:
        while True:
            if not queue:
                if not a.interactive:
                    break
                try:
                    line = input("\n> ").strip()
                except EOFError:
                    break
                if not line or line.lower() in ("exit", "quit", "cikis"):
                    break
                queue.append(line)
            req = queue.pop(0)
            print("\n" + "=" * 88)
            print("ISTEK: %s" % req)
            before = len(written)
            r = one_request(srv, tools, dispatch, msgs, req, a.model, a.repairs,
                            play_check=a.play, play_repairs=a.play_repairs)
            new_files = written[before:]
            ok = not r["errors"]
            print("-" * 88)
            print("%s  %.0fs  onarim=%d  yazilan: %s"
                  % ("DERLENDI" if ok else "DERLEME HATASI VAR", r["wall"], r["rounds"],
                     ", ".join(dict.fromkeys(new_files)) or "(yok)"))
            if not ok:
                for e in r["errors"][:3]:
                    print("   %s" % e[:150])
            if a.play:
                rt = r.get("runtime") or []
                # Play modda hata kalmadiysa bu, derlemeden DAHA GUCLU bir kanit:
                # kod yalnizca derlenmiyor, gercekten calisiyor.
                if not r.get("play_dogrulandi"):
                    print("   calisma zamani: DOGRULANAMADI (play moda girilemedi)")
                else:
                    print("   calisma zamani: %s"
                          % ("TEMIZ (play modda dogrulandi)" if not rt
                             else "%d HATA KALDI" % len(rt)))
                for e in rt[:2]:
                    print("      %s" % e[:150])
            if ok and a.attach:
                cls = a.class_name or (new_files[-1].rsplit("/", 1)[-1][:-3]
                                       if new_files else "")
                if cls:
                    st = attach(srv, a.attach, cls)
                    print("   attach %s -> %s : %s" % (cls, a.attach, st))
            if r["text"]:
                print("   model: %s" % r["text"][:220].replace("\n", " "))
    finally:
        srv.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
