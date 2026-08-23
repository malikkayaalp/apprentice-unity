"""Apprentice izleme sayfasi: ~/.apprentice/jobs altindaki isleri canli gosterir.

    python clients/web/monitor.py [--port 8765] [--home ~/.apprentice]

Bagimlilik yok (http.server). Sunucuya baglanmaz; iscinin yazdigi dosyalari (job.json,
events.jsonl, stderr.txt) okur - bu yuzden hangi istemci (Claude Code, Cursor, panel,
test betigi) baslatmis olursa olsun her is burada gorunur. Sayfa 3 sn'de bir yenilenir.
  /            is listesi (en yeni ustte): ortam, durum, sure, derleme, dosyalar
  /is/<id>     tek is: gorev + kriterler, arac akisi, olcumler, iscinin ozeti, hatalar
  /api/jobs    ayni veri JSON (baska arayuzler icin)
"""
from __future__ import annotations
import argparse, html, json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.environ.get("APPRENTICE_HOME") or os.path.join(os.path.expanduser("~"), ".apprentice")


def _read_events(p: str) -> list:
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass
    return out


def job_summary(jid: str) -> dict:
    d = os.path.join(HOME, "jobs", jid)
    try:
        with open(os.path.join(d, "job.json"), encoding="utf-8") as f:
            job = json.load(f)
    except Exception:
        job = {"id": jid}
    ev = _read_events(os.path.join(d, "events.jsonl"))
    s = {"id": jid, "ortam": job.get("ortam", "?"), "gorev": job.get("gorev", ""),
         "kriterler": job.get("kabul_kriterleri", []), "oturum": job.get("oturum", ""),
         "baslangic": job.get("baslangic"), "durum": "calisiyor", "derleme": "-",
         "dosyalar": [], "araclar": [], "olcumler": [], "ozet": "", "hatalar": [], "sure": None}
    for e in ev:
        t = e.get("type")
        if t == "tool":
            s["araclar"].append({"ad": e.get("name"), "detay": e.get("detail", ""), "args": e.get("args")})
        elif t == "tool_result":
            if s["araclar"]:
                s["araclar"][-1]["sonuc"] = e.get("text", "")
                s["araclar"][-1]["sure"] = e.get("sure")
        elif t == "write":
            s["dosyalar"].append(e.get("path"))
        elif t == "assistant":
            s["ozet"] = e.get("text", "")
        elif t == "result":
            s["derleme"] = "derlendi" if e.get("ok") else "hata"
            s["hatalar"] = e.get("errors", [])
            s["sure"] = e.get("wall")
        elif t == "error":
            s["hatalar"].append(e.get("message", ""))
            s["derleme"] = "calistirilamadi"
        elif t == "exit":
            s["durum"] = "bitti"
    if s["durum"] == "calisiyor" and s["baslangic"]:
        s["sure"] = round(time.time() - s["baslangic"], 1)
    s["olcumler"] = [a for a in s["araclar"] if a["ad"] in ("play_observe", "run_tests", "read_console")]
    return s


def list_jobs() -> list:
    d = os.path.join(HOME, "jobs")
    if not os.path.isdir(d):
        return []
    return [job_summary(j) for j in sorted(os.listdir(d), reverse=True)[:200]]


CSS = """body{font:14px/1.4 system-ui,sans-serif;margin:0;background:#111;color:#ddd}
a{color:#8cf}header{padding:10px 16px;background:#1b1b1b;border-bottom:1px solid #333}
table{border-collapse:collapse;width:100%}td,th{padding:6px 10px;border-bottom:1px solid #2a2a2a;text-align:left;vertical-align:top}
.ok{color:#6d6}.bad{color:#e66}.run{color:#fc6}pre{white-space:pre-wrap;background:#181818;padding:8px;border-radius:4px;max-height:320px;overflow:auto}
details{margin:4px 0}summary{cursor:pointer}.k{color:#999}main{padding:12px 16px}"""


def page(body: str, title: str = "Apprentice") -> bytes:
    return ("<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=3><title>%s</title>"
            "<style>%s</style><header><b>Apprentice</b> · <a href=/>isler</a> · <span class=k>%s</span></header>"
            "<main>%s</main>" % (html.escape(title), CSS, html.escape(HOME), body)).encode("utf-8")


def render_list(jobs: list) -> str:
    rows = []
    for s in jobs:
        cls = "run" if s["durum"] == "calisiyor" else ("ok" if s["derleme"] == "derlendi" else "bad")
        rows.append("<tr><td><a href=/is/%s>%s</a></td><td>%s</td><td class=%s>%s / %s</td><td>%s</td>"
                    "<td>%s</td><td>%s</td></tr>" % (
                        s["id"], s["id"], s["ortam"], cls, s["durum"], s["derleme"],
                        "%.0fs" % s["sure"] if s["sure"] is not None else "-",
                        html.escape(", ".join(dict.fromkeys(s["dosyalar"]))[:120]),
                        html.escape(s["gorev"][:110])))
    return ("<table><tr><th>is</th><th>ortam</th><th>durum</th><th>sure</th><th>dosyalar</th><th>gorev</th></tr>%s</table>"
            % "".join(rows) or "<p>henuz is yok</p>")


def render_job(s: dict) -> str:
    h = ["<h3>%s <span class=k>%s · oturum %s</span></h3>" % (s["id"], s["ortam"], html.escape(s["oturum"]))]
    h.append("<pre>%s</pre>" % html.escape(s["gorev"]))
    if s["kriterler"]:
        h.append("<b>Kabul kriterleri</b><ul>%s</ul>" % "".join("<li>%s</li>" % html.escape(k) for k in s["kriterler"]))
    cls = "run" if s["durum"] == "calisiyor" else ("ok" if s["derleme"] == "derlendi" else "bad")
    h.append("<p class=%s>%s · %s · %s</p>" % (cls, s["durum"], s["derleme"],
                                              "%.0fs" % s["sure"] if s["sure"] is not None else ""))
    if s["hatalar"]:
        h.append("<b class=bad>Hatalar</b><pre>%s</pre>" % html.escape("\n".join(s["hatalar"])))
    h.append("<b>Arac akisi (%d)</b>" % len(s["araclar"]))
    for a in s["araclar"]:
        h.append("<details><summary>%s <span class=k>%s %s</span></summary><pre>%s</pre><pre>%s</pre></details>" % (
            html.escape(a["ad"] or ""), html.escape(a.get("detay") or ""),
            ("%.1fs" % a["sure"]) if a.get("sure") is not None else "",
            html.escape(json.dumps(a.get("args"), ensure_ascii=False, indent=1) if a.get("args") else ""),
            html.escape(a.get("sonuc") or "")))
    if s["ozet"]:
        h.append("<b>Iscinin ozeti</b><pre>%s</pre>" % html.escape(s["ozet"]))
    return "".join(h)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # sessiz
        pass

    def _send(self, body: bytes, ctype="text/html; charset=utf-8", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self._send(page(render_list(list_jobs())))
        if p == "/api/jobs":
            return self._send(json.dumps(list_jobs(), ensure_ascii=False).encode("utf-8"),
                              "application/json; charset=utf-8")
        if p.startswith("/is/"):
            jid = os.path.basename(p[4:])
            if not os.path.isdir(os.path.join(HOME, "jobs", jid)):
                return self._send(page("<p>is yok</p>"), code=404)
            return self._send(page(render_job(job_summary(jid)), jid))
        return self._send(page("<p>yok</p>"), code=404)


def main() -> int:
    global HOME
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--home", default=HOME)
    a = ap.parse_args()
    HOME = a.home
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print("Apprentice izleme: http://127.0.0.1:%d  (ev: %s)" % (a.port, HOME), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
