"""Q3CNFU panelini UI'siz surer: MCP for Unity execute_code + reflection.

Kullanim:  python tests/panel_drive.py "Istek metni" [--url http://127.0.0.1:8080/mcp] [--timeout 600]
Ne yapar: pencereyi acar, _input'u doldurur, _pendingSend'i kaldirir, Busy bitene kadar
_messages listesini yoklar ve son durumu yazdirir. Unity + MCP koprusu + Ollama acik olmali.
"""
from __future__ import annotations
import argparse, json, os, sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # apprentice koku (mcpbridge)
from mcpbridge.http_client import MCPHttpServer  # noqa: E402

SNIPPET_SEND = r'''
var t = System.Type.GetType("Q3CNFU.EditorTools.Q3Window, Q3CNFU.Editor");
var w = UnityEditor.EditorWindow.GetWindow(t, false, "Q3CNFU");
var f = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
t.GetField("_input", f).SetValue(w, @"__PROMPT__");
t.GetField("_pendingSend", f).SetValue(w, true);
w.Repaint();
return "sent";
'''

SNIPPET_POLL = r'''
var t = System.Type.GetType("Q3CNFU.EditorTools.Q3Window, Q3CNFU.Editor");
var w = UnityEditor.EditorWindow.GetWindow(t, false, "Q3CNFU");
var f = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
bool busy = (bool)t.GetProperty("Busy", f).GetValue(w);
var msgs = (System.Collections.IList)t.GetField("_messages", f).GetValue(w);
var sb = new System.Text.StringBuilder();
sb.Append(busy ? "BUSY|" : "IDLE|").Append(msgs.Count).Append('\n');
foreach (var m in msgs) {
    var mt = m.GetType();
    int role = (int)mt.GetField("Role").GetValue(m);
    string text = (string)mt.GetField("Text").GetValue(m) ?? "";
    if (text.Length > 400) text = text.Substring(0, 400) + "...";
    sb.Append(role).Append('|').Append(text.Replace("\n", "\\n")).Append('\n');
}
return sb.ToString();
'''


def run_code(srv: MCPHttpServer, code: str) -> str:
    r = srv.call_tool("execute_code", {"action": "execute", "code": code, "safety_checks": False})
    parts = r.get("content") or []
    text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--url", default="http://127.0.0.1:8080/mcp")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()

    srv = MCPHttpServer(a.url)
    srv.start()
    print(run_code(srv, SNIPPET_SEND.replace("__PROMPT__", a.prompt.replace('"', '""'))))
    t0 = time.time()
    last = ""
    while time.time() - t0 < a.timeout:
        time.sleep(5)
        out = run_code(srv, SNIPPET_POLL)
        if out != last:
            print(f"[{time.time() - t0:5.0f}s] " + out.replace("\n", "\n      "))
            last = out
        if "IDLE|" in out and time.time() - t0 > 10:
            return 0
    print("ZAMAN ASIMI")
    return 1


if __name__ == "__main__":
    sys.exit(main())
