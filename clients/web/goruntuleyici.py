"""Dosya goruntuleyici: AYRI PENCERE (panel alanini kaplamasin).

Kullanici istegi: "oluşturulan dosyalara tıklayınca içeriği panel içinde açılmasın, ayrı bir
arayüz gibi dışarıda açılsın ki alan kaplamasın." Panel yalnizca DOSYA LISTESI tutar;
tiklayinca burasi acilir (WebView2 kabugunda gercek ikinci pencere, tarayicida yeni pencere).

Icerik 2 saniyede bir tazelenir: model dosyayi yeniden yazarsa degisen satirlar parlar.
"""
from __future__ import annotations
import json, os

SAYFA = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>{ad} - Apprentice</title>
<style>
:root{{--zemin:#141210;--panel:#1c1a17;--cizgi:#332f2a;--metin:#f1ede6;--soluk:#8f8880;
 --vurgu:#d97757;--yesil:#6fc28a;--mavi:#7fb2e5;--sari:#e9b85c;--mor:#b99cd8;
 --mono:'JetBrains Mono','Cascadia Code',Consolas,monospace}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--zemin);color:var(--metin);font:13px/1.55 var(--mono);
 display:flex;flex-direction:column;height:100vh}}
header{{display:flex;align-items:center;gap:12px;padding:9px 14px;background:var(--panel);
 border-bottom:1px solid var(--cizgi);flex-shrink:0}}
header b{{color:var(--vurgu)}}
header .k{{color:var(--soluk);font-size:11px}}
header .sag{{margin-left:auto;display:flex;gap:8px;align-items:center}}
button{{background:transparent;border:1px solid var(--cizgi);color:var(--soluk);
 border-radius:7px;padding:4px 10px;cursor:pointer;font:11px var(--mono)}}
button:hover{{color:var(--metin);border-color:var(--vurgu)}}
#kod{{flex:1;overflow:auto;padding:12px 14px}}
table{{border-collapse:collapse;width:100%}}
td.n{{color:#5a544d;text-align:right;padding-right:14px;user-select:none;width:1%;
 white-space:nowrap;vertical-align:top}}
td.s{{white-space:pre;padding-right:18px}}
tr:hover td.s{{background:rgba(217,119,87,.07)}}
.kw{{color:var(--mor)}} .st{{color:var(--sari)}} .cm{{color:#6b645c;font-style:italic}}
.nu{{color:var(--mavi)}} .fn{{color:var(--yesil)}}
.degisti{{animation:parla 1.4s ease}}
@keyframes parla{{from{{background:rgba(111,194,138,.28)}}to{{background:transparent}}}}
</style></head><body>
<header>
  <b>{ad}</b><span class="k">{bilgi}</span>
  <span class="sag"><span class="k" id="durum">yükleniyor…</span>
    <button id="kopyala">kopyala</button><button id="yenile">yenile</button>
    <label class="k"><input type="checkbox" id="oto" checked> otomatik</label></span>
</header>
<div id="kod"></div>
<script>
const IS={is_json}, YOL={yol_json};
const KW=/\\b(def|class|if|elif|else|for|while|return|import|from|raise|try|except|finally|with|as|in|not|and|or|is|None|True|False|lambda|pass|break|continue|yield|self|public|private|protected|static|void|var|new|using|namespace|int|float|string|bool|foreach|null|this|override|virtual|async|await|const|let|function)\\b/g;
function kacir(s){{return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}}
function renkle(s){{
  return kacir(s)
    .replace(/(#.*$|\\/\\/.*$)/g,'<span class="cm">$1</span>')
    .replace(/(&#39;[^&]*?&#39;|"[^"\\n]*")/g,'<span class="st">$1</span>')
    .replace(KW,'<span class="kw">$&</span>')
    .replace(/\\b(\\d+\\.?\\d*)\\b/g,'<span class="nu">$1</span>')
    .replace(/\\b([a-zA-Z_][\\w]*)\\s*\\(/g,'<span class="fn">$1</span>(');
}}
function ciz(metin, eski){{
  const s=metin.split("\\n"), e=(eski||"").split("\\n");
  let h='<table>';
  for(let i=0;i<s.length;i++){{
    const yeni = eski!==undefined && e[i]!==s[i];
    h+='<tr><td class="n">'+(i+1)+'</td><td class="s'+(yeni?' degisti':'')+'">'+
       (renkle(s[i])||"&nbsp;")+'</td></tr>';
  }}
  return h+'</table>';
}}
let son=null;
async function cek(){{
  try{{
    const r=await(await fetch("/api/dosya?is="+encodeURIComponent(IS)+"&yol="+encodeURIComponent(YOL))).json();
    const d=document.getElementById("durum");
    if(r.hata){{d.textContent="hata: "+r.hata; return}}
    if(r.icerik!==son){{
      const eski=son;
      document.getElementById("kod").innerHTML=ciz(r.icerik, eski===null?undefined:eski);
      son=r.icerik;
      d.textContent=(r.satir||0)+" satır · "+(r.bayt||0)+" bayt"+(eski!==null?" · güncellendi":"");
    }}
  }}catch(e){{document.getElementById("durum").textContent="bağlantı yok"}}
}}
document.getElementById("yenile").onclick=cek;
document.getElementById("kopyala").onclick=()=>navigator.clipboard.writeText(son||"");
setInterval(()=>{{if(document.getElementById("oto").checked)cek()}},2000);
cek();
</script></body></html>"""


def sayfa(jid: str, yol: str) -> str:
    ad = os.path.basename(yol) or "dosya"
    kacir = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return SAYFA.format(ad=kacir(ad), bilgi=kacir("%s · %s" % (yol, jid[:15])),
                        is_json=json.dumps(jid), yol_json=json.dumps(yol))


def oku(jobs_dir: str, jid: str, yol: str) -> dict:
    """Dosyanin GUNCEL icerigi: once diskten (model sonradan degistirmis olabilir),
    bulunamazsa olay akisindaki son 'write' kaydindan."""
    yol = (yol or "").replace("\\", "/").strip("/")
    if not yol or ".." in yol.split("/") or os.path.isabs(yol) or os.path.splitdrive(yol)[0]:
        return {"hata": "gecersiz yol"}
    try:
        with open(os.path.join(jobs_dir, jid, "job.json"), encoding="utf-8") as f:
            kayit = json.load(f)
    except Exception:
        return {"hata": "is bulunamadi"}
    kok = kayit.get("calisma_dizini") or ""
    if kok:
        tam = os.path.realpath(os.path.join(kok, yol))
        kok_ger = os.path.realpath(kok)
        if tam.startswith(kok_ger + os.sep) and os.path.isfile(tam):
            try:
                with open(tam, encoding="utf-8", errors="replace") as f:
                    icerik = f.read()[:400000]
                return {"icerik": icerik, "satir": icerik.count("\n") + 1,
                        "bayt": os.path.getsize(tam), "kaynak": "disk"}
            except OSError:
                pass
    son = None
    try:
        with open(os.path.join(jobs_dir, jid, "events.jsonl"), encoding="utf-8",
                  errors="replace") as f:
            for satir in f:
                if '"write"' not in satir:
                    continue
                try:
                    e = json.loads(satir)
                except Exception:
                    continue
                if e.get("type") == "write" and (e.get("path") or "").replace("\\", "/") == yol:
                    son = e.get("after")
    except OSError:
        pass
    if son is None:
        return {"hata": "dosya bulunamadi"}
    return {"icerik": son, "satir": son.count("\n") + 1,
            "bayt": len(son.encode("utf-8")), "kaynak": "olay"}
