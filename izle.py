"""Apprentice Izleyici - masaustu canli izleme (tkinter, bagimliliksiz).

    python izle.py                    # ~/.apprentice icindeki isleri izler
    python izle.py --home <klasor>    # baska ev (or. .apprentice_test_home)

Sunucuya baglanmaz; is klasorunu okur (job.json + events.jsonl + canli.txt) - hangi istemci
baslatmis olursa olsun her is gorunur. v3 (kullanici geri bildirimiyle):
  - Asama kutulari TIKLANABILIR FILTRE: BASLANGIC (gorev+baglam) / URETIM (arac+kod) /
    DOGRULAMA (kanit+sonuc) / ONARIM (geri gonderim+duzeltme) / USTA (rapor). TUMU = hepsi.
  - Kod bloklari sozdizimi renklendirmeli (Python + C#), akisin icinde.
  - Canli daktilo (canli=true kipinde): uretim hafif gecikmeli, KADEMELI damla akisiyla
    surekli akar - parca parca sicrama yok. Panolar dikey surukleyerek boyutlanir.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time

# Konsolsuz kipte (exe/pythonw) alt surecler kendi konsol penceresini ACMASIN:
# olculdu - nvidia-smi/tasklist her 3 sn'de bir pencere parlatiyordu.
PENCERESIZ = 0x08000000 if os.name == "nt" else 0

# ------------------------------------------------------------------ veri katmani (GUI'siz test edilir)


class IsDeposu:
    """Is klasorunu artimli okur: events.jsonl'da yalnizca yeni satirlar islenir.
    Her olaya islenirken _asama etiketi vurulur (filtreleme icin)."""

    def __init__(self, home: str):
        self.home = os.path.expanduser(home)
        self.jobs_dir = os.path.join(self.home, "jobs")
        self.durumlar: dict = {}
        self.olaylar: dict = {}
        self._ofset: dict = {}

    def is_listesi(self) -> list:
        if not os.path.isdir(self.jobs_dir):
            return []
        return sorted((a for a in os.listdir(self.jobs_dir)
                       if os.path.isdir(os.path.join(self.jobs_dir, a))), reverse=True)

    def tazele(self, jid: str) -> bool:
        p = os.path.join(self.jobs_dir, jid, "events.jsonl")
        try:
            boyut = os.path.getsize(p)
            mtime = os.path.getmtime(p)
        except OSError:
            return False
        if jid in self.durumlar:
            self.durumlar[jid]["son_olay_t"] = mtime
        eski = self._ofset.get(jid, 0)
        if boyut <= eski and jid in self.durumlar:
            self._sure_guncelle(jid)
            return False
        yeni = []
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                f.seek(eski)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            yeni.append(json.loads(line))
                        except Exception:
                            pass
                self._ofset[jid] = f.tell()
        except OSError:
            return False
        if jid not in self.durumlar:
            self.durumlar[jid] = self._is_bilgisi(jid)
            self.olaylar[jid] = []
        self.durumlar[jid]["son_olay_t"] = mtime
        self._ozeti_isle(jid, yeni)
        self.olaylar[jid].extend(yeni)
        if yeni:
            self.durumlar[jid]["son_olay"] = olay_satiri(yeni[-1])[1][:60]
        self._sure_guncelle(jid)
        return bool(yeni)

    def _is_bilgisi(self, jid: str) -> dict:
        try:
            with open(os.path.join(self.jobs_dir, jid, "job.json"), encoding="utf-8") as f:
                job = json.load(f)
        except Exception:
            job = {}
        return {"id": jid, "ortam": job.get("ortam", "?"), "gorev": job.get("gorev", ""),
                "kaynak": job.get("kaynak", ""),
                "dogrulama": job.get("dogrulama", "tam"), "baslangic": job.get("baslangic"),
                "durum": "calisiyor", "derleme": "-", "tur": 0, "sure": None, "kullanim": {},
                "dosyalar": [], "uyarilar": [], "hatalar": [], "ozet": "", "son_yazim": None,
                "asama": "baslama", "baglam": {}, "son_olay_t": 0.0, "son_olay": "",
                "sayac": {"arac": 0, "yazim": 0, "noop": 0, "izin_red": 0,
                          "kanit_hata": 0, "onarim": 0}}

    def _ozeti_isle(self, jid: str, yeni: list):
        s = self.durumlar[jid]
        for e in yeni:
            t = e.get("type")
            if t == "baglam":
                s["asama"] = "baslama"
                s["baglam"] = {k: e.get(k) for k in ("sistem", "hafiza", "durum", "harita")}
                s["baglam"]["araclar"] = e.get("araclar") or []
            elif t == "tool":
                s["sayac"]["arac"] += 1
                if s["asama"] not in ("onarim",):          # onarimdaki araclar onarima aittir
                    s["asama"] = "uretim"
            elif t == "tool_result":
                if e.get("name") == "write_file":
                    k = kanit_coz(e.get("text") or "")
                    if k:
                        s["sayac"][k["sayac"]] = s["sayac"].get(k["sayac"], 0) + 1
            elif t == "onarim":
                s["sayac"]["onarim"] = max(s["sayac"]["onarim"], int(e.get("tur", 0)))
                s["asama"] = "onarim"
            elif t == "duraganlik":
                s["asama"] = "duraganlik"
                s["uyarilar"].append("DURAGANLIK: %s imza %s turda degismedi"
                                     % (e.get("imza_sayisi"), e.get("tur")))
            elif t == "usta_rapor":
                s["asama"] = "usta"
            elif t == "write":
                s["dosyalar"].append(e.get("path"))
                s["sayac"]["yazim"] += 1
                s["son_yazim"] = {"path": e.get("path"), "icerik": e.get("after") or ""}
                s.setdefault("yazimlar", {})[e.get("path")] = e.get("after") or ""
            elif t == "assistant":
                s["ozet"] = e.get("text", "")
            elif t == "result":
                if s["asama"] not in ("duraganlik", "usta"):
                    s["asama"] = "dogrulama"
                s["derleme"] = "derlendi" if e.get("ok") else "hata"
                s["tur"] = int(e.get("rounds", 0)) + 1
                s["sure"] = e.get("wall")
                s["kullanim"] = e.get("kullanim") or {}
                s["hatalar"] = e.get("errors") or []
                for alan, etiket in (("duragan", "DURAGANLIK: isci ilerleyemiyor, usta gerekli"),
                                     ("butce_uyarisi", None), ("hafiza_uyarisi", None),
                                     ("durum_uyarisi", None)):
                    if e.get(alan):
                        s["uyarilar"].append(etiket or str(e[alan]))
                if e.get("ruff"):
                    s["uyarilar"].extend("ruff: " + str(u) for u in e["ruff"][:4])
            elif t == "error":
                s["hatalar"].append(e.get("message", ""))
                s["derleme"] = "calistirilamadi"
            elif t == "exit":
                s["durum"] = "bitti"
            # filtreleme icin: sonuc/kanit olaylari dogrulamaya, digerleri o anki asamaya
            if t == "result":
                e["_asama"] = "dogrulama"
            elif t == "tool_result" and e.get("name") == "write_file" and kanit_coz(e.get("text") or ""):
                e["_asama"] = "dogrulama"
            elif t in ("system", "baglam"):
                e["_asama"] = "baslama"
            elif t in ("onarim", "duraganlik"):
                e["_asama"] = "onarim"
            elif t == "usta_rapor":
                e["_asama"] = "usta"
            elif t == "exit":
                e["_asama"] = "usta"
            else:
                e["_asama"] = s["asama"] if s["asama"] != "duraganlik" else "onarim"

    def _sure_guncelle(self, jid: str):
        s = self.durumlar.get(jid)
        if s and s["durum"] == "calisiyor" and s.get("baslangic"):
            s["sure"] = round(time.time() - s["baslangic"], 1)


def kanit_coz(metin: str) -> dict | None:
    """write_file cevabindaki kanit katmanini ayristirir (derleme/ruff/no-op/izin)."""
    try:
        d = json.loads(metin.rstrip(" …"))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    if "yazma izni yok" in str(d.get("error") or ""):
        return {"sayac": "izin_red", "etiket": "hata", "metin": "IZIN RED  " + str(d["error"])[:110]}
    if d.get("degisiklik") is False:
        return {"sayac": "noop", "etiket": "hata",
                "metin": "NO-OP     ayni icerik reddedildi (%s)" % d.get("path")}
    parca = []
    derleme = str(d.get("derleme") or "")
    if derleme:
        parca.append("derleme " + ("TEMIZ" if derleme.startswith("temiz") else derleme[:90]))
    for u in (d.get("ruff") or [])[:3]:
        parca.append("ruff " + str(u).split(":", 1)[-1].strip()[:80])
    if not parca:
        return None
    hatali = (derleme and not derleme.startswith("temiz")) or d.get("ruff")
    return {"sayac": "kanit_hata" if hatali else "arac",
            "etiket": "hata" if hatali else "yazim", "metin": "KANIT     " + " | ".join(parca)}


KOD_SATIR_SINIRI = 100


def olay_satirlari(e: dict) -> list:
    """Bir olayi akis satirlarina acar; yazilan kod basligiyla blok halinde akisa girer."""
    et, metin = olay_satiri(e)
    out = [(et, metin)]
    if e.get("type") == "write":
        icerik = (e.get("after") or "").splitlines()
        out = [("yazim", ""), (et, metin),
               ("bilgi", "─" * 8 + " %s " % e.get("path") + "─" * 30)]
        for s in icerik[:KOD_SATIR_SINIRI]:
            out.append(("kod", s))                     # girinti AYNEN korunur
        if len(icerik) > KOD_SATIR_SINIRI:
            out.append(("bilgi", "  ... (+%d satir - tamami sag panelde)" %
                        (len(icerik) - KOD_SATIR_SINIRI)))
        out.append(("bilgi", "─" * 48))
    elif e.get("type") in ("result", "usta_rapor", "onarim", "duraganlik", "baglam"):
        out = [("bilgi", ""), (et, metin)]
    return out


def olay_satiri(e: dict) -> tuple:
    t = e.get("type")
    if t == "tool":
        det = e.get("detail") or json.dumps(e.get("args") or {}, ensure_ascii=False)[:80]
        return "arac", "ARAC  %s %s" % (e.get("name"), det)
    if t == "tool_result":
        if e.get("name") == "write_file":
            k = kanit_coz(e.get("text") or "")
            if k:
                return k["etiket"], k["metin"]
        m = str(e.get("text") or "")[:120].replace("\n", " ")
        return "bilgi", "  -> %s" % (m or "ok")
    if t == "baglam":
        return "sonuc", ("BAGLAM sistem %s kr | hafiza %s | durum(STATE) %s | harita %s | araclar: %s" % (
            e.get("sistem"), e.get("hafiza") or "-", e.get("durum") or "-",
            e.get("harita") or "-", ",".join(e.get("araclar") or [])))
    if t == "onarim":
        return "arac", "GERI GONDERIM (onarim turu %s) -> isciye: %s" % (
            e.get("tur"), str(e.get("mesaj", ""))[:160].replace("\n", " | "))
    if t == "duraganlik":
        return "hata", "DURAGANLIK: ayni hata imzasi degismiyor - isci kesildi, USTAYA devir"
    if t == "usta_rapor":
        return "sonuc", "USTAYA RAPOR: %s | dosya %s | uyari: %s | prompt %s tok" % (
            e.get("derleme_durumu"), ",".join(e.get("dosya") or []) or "-",
            ",".join(e.get("uyarilar") or []) or "-",
            (e.get("kullanim") or {}).get("prompt_tokens", "-"))
    if t == "write":
        n = (e.get("after") or "").count("\n") + 1
        return "yazim", "YAZDI %s (%d satir)" % (e.get("path"), n)
    if t == "assistant":
        return "sonuc", "ISCI OZETI:\n%s" % str(e.get("text", ""))[:1500]
    if t == "result":
        durum = "derlendi" if e.get("ok") else ("HATA: " + "; ".join(e.get("errors") or [])[:150])
        return ("sonuc" if e.get("ok") else "hata"), "SONUC %s (tur %s, %.0f s)" % (
            durum, int(e.get("rounds", 0)) + 1, e.get("wall") or 0)
    if t == "error":
        return "hata", "HATA  %s" % e.get("message", "")
    if t == "system":
        return "bilgi", "sistem: %s" % (e.get("subtype") or "")
    if t == "exit":
        return "bilgi", "cikis (kod %s)" % e.get("code")
    return "bilgi", str(e)[:120]


# ------------------------------------------------------------------ sozdizimi renklendirme
_KW = (r"\b(def|class|if|elif|else|for|while|return|import|from|raise|try|except|finally|"
       r"with|as|in|not|and|or|is|None|True|False|lambda|pass|break|continue|yield|self|"
       r"public|private|protected|static|void|var|new|using|namespace|int|float|string|bool|"
       r"foreach|null|this|override|virtual)\b")
_RENK_DESEN = re.compile(
    r"(?P<yorum>#[^\n]*|//[^\n]*)|(?P<metin>\"[^\"\n]*\"?|'[^'\n]*'?)|"
    r"(?P<kw>%s)|(?P<sayi>\b\d[\d_.]*\b)" % _KW)


def renkle(satir: str) -> list:
    """Kod satirini [(etiket, parca)] boler: kw / metin / yorum / sayi / kod."""
    out = []
    son = 0
    for m in _RENK_DESEN.finditer(satir):
        if m.start() > son:
            out.append(("kod", satir[son:m.start()]))
        out.append((m.lastgroup, m.group()))
        son = m.end()
    if son < len(satir):
        out.append(("kod", satir[son:]))
    return out or [("kod", satir)]


def sistem_satiri() -> str:
    parcalar = []
    try:
        # 'ollama ps' KOMUTU degil API: komut farkli sunucu ornegine baglanabiliyor
        # (olculdu: model API'de yukluyken CLI bos tablo gosterdi - cift serve mirasi).
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=4) as r:
            modeller = (json.load(r).get("models") or [])
        if modeller:
            m = modeller[0]
            parcalar.append("model: %s (%.0f GB yuklu)" % (
                m.get("name", "?").split("/")[-1][:40], m.get("size", 0) / 1e9))
        else:
            parcalar.append("model: yuklu degil")
    except Exception:
        parcalar.append("ollama: erisilemedi")
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=4,
                             creationflags=PENCERESIZ).stdout.strip()
        k, t, u = [x.strip() for x in out.split(",")[:3]]
        parcalar.append("VRAM %s/%s MiB  GPU %%%s" % (k, t, u))
    except Exception:
        pass
    return "   |   ".join(parcalar)


# ------------------------------------------------------------------ arayuz (koyu Claude temasi)
T = {"bg": "#1f1d1a", "panel": "#2a2724", "panel2": "#33302c", "cizgi": "#3f3b36",
     "metin": "#f1ede6", "soluk": "#a39d94", "vurgu": "#d97757",
     "arac": "#e0b345", "yazim": "#7fbf6f", "hata": "#e06c5f", "sonuc": "#7fb4d9",
     "kod": "#c8d8b0", "kw": "#7fb4d9", "metin_s": "#e0b345", "yorum": "#8a9a7a",
     "sayi": "#d0a0d0"}
FONT = "Segoe UI"
FILTRELER = [("tumu", "TUMU"), ("baslama", "BASLANGIC"), ("uretim", "URETIM"),
             ("dogrulama", "DOGRULAMA"), ("onarim", "ONARIM"), ("usta", "USTA RAPORU")]


def gui(home: str):
    import tkinter as tk
    from tkinter import ttk

    depo = IsDeposu(home)
    kok = tk.Tk()
    kok.title("Apprentice Izleyici")
    kok.geometry("1360x820")
    kok.configure(bg=T["bg"])
    st = ttk.Style(kok); st.theme_use("clam")
    st.configure(".", background=T["bg"], foreground=T["metin"], font=(FONT, 10),
                 bordercolor=T["cizgi"])
    st.configure("TCheckbutton", background=T["bg"], foreground=T["soluk"])
    st.map("TCheckbutton", background=[("active", T["bg"])])

    ust = tk.Frame(kok, bg=T["bg"]); ust.pack(fill="x", padx=10, pady=(8, 2))
    tk.Label(ust, text="Apprentice Izleyici", bg=T["bg"], fg=T["metin"],
             font=(FONT, 15, "bold")).pack(side="left")
    sistem_lbl = tk.Label(ust, text="", bg=T["bg"], fg=T["soluk"], font=(FONT, 9))
    sistem_lbl.pack(side="right")
    tk.Label(kok, text="ev: " + os.path.expanduser(home), bg=T["bg"], fg=T["soluk"],
             font=(FONT, 9)).pack(anchor="w", padx=12)

    govde = tk.Frame(kok, bg=T["bg"]); govde.pack(fill="both", expand=True, padx=10, pady=6)

    # sol: is listesi
    sol = tk.Frame(govde, bg=T["panel"]); sol.pack(side="left", fill="y")
    tk.Label(sol, text="ISLER", bg=T["panel"], fg=T["soluk"], font=(FONT, 9, "bold")).pack(
        anchor="w", padx=8, pady=(6, 2))
    takip = tk.BooleanVar(value=True)
    ttk.Checkbutton(sol, text="en yeniyi takip et", variable=takip).pack(anchor="w", padx=8)
    hepsi = tk.BooleanVar(value=False)
    ttk.Checkbutton(sol, text="eski isleri de goster", variable=hepsi).pack(anchor="w", padx=8)
    liste = tk.Listbox(sol, width=32, height=34, bg=T["panel2"], fg=T["metin"],
                       selectbackground=T["vurgu"], selectforeground="#ffffff",
                       borderwidth=0, highlightthickness=0, font=("Consolas", 9))
    liste.pack(fill="y", expand=True, padx=8, pady=6)

    # orta: filtre kutulari + (dikey bolunmus) akis + daktilo
    orta = tk.Frame(govde, bg=T["bg"]); orta.pack(side="left", fill="both", expand=True, padx=(8, 8))
    serit = tk.Frame(orta, bg=T["bg"]); serit.pack(fill="x", pady=(0, 4))
    kutular = {}
    durum = {"secili": None, "gosterilen": 0, "sistem_t": 0.0, "filtre": "tumu",
             "canli_metin": "", "canli_ciz": 0}

    canli_lbl = tk.Label(orta, text="", bg=T["bg"], fg=T["arac"], font=(FONT, 10, "bold"),
                         anchor="w")
    canli_lbl.pack(fill="x", pady=(0, 2))

    pw = tk.PanedWindow(orta, orient="vertical", bg=T["cizgi"], sashwidth=5, borderwidth=0)
    pw.pack(fill="both", expand=True)

    akis_kap = tk.Frame(pw, bg=T["bg"])
    tk.Label(akis_kap, text="CANLI OLAY AKISI  (asama kutusuna tiklayarak filtrele)",
             bg=T["bg"], fg=T["soluk"], font=(FONT, 9, "bold")).pack(anchor="w")
    akis = tk.Text(akis_kap, bg=T["panel"], fg=T["metin"], insertbackground=T["metin"],
                   borderwidth=0, highlightthickness=0, font=("Consolas", 9), wrap="word")
    akis.pack(fill="both", expand=True, pady=(2, 0))
    for ad in ("arac", "yazim", "hata", "sonuc", "kod", "kw", "yorum", "sayi"):
        akis.tag_configure(ad, foreground=T[ad])
    akis.tag_configure("metin_s", foreground=T["metin_s"])
    akis.tag_configure("bilgi", foreground=T["soluk"])
    akis.configure(state="disabled")
    pw.add(akis_kap, minsize=160, stretch="always")

    dak_kap = tk.Frame(pw, bg=T["bg"])
    tk.Label(dak_kap, text="MODEL SU AN YAZIYOR  (canli=true kipinde token akisi)",
             bg=T["bg"], fg=T["arac"], font=(FONT, 9, "bold")).pack(anchor="w")
    daktilo_kutu = tk.Text(dak_kap, bg="#242220", fg=T["kod"], borderwidth=0,
                           highlightthickness=0, font=("Consolas", 9), wrap="word")
    daktilo_kutu.pack(fill="both", expand=True, pady=(2, 0))
    for ad in ("kw", "yorum", "sayi", "kod"):
        daktilo_kutu.tag_configure(ad, foreground=T[ad])
    daktilo_kutu.tag_configure("metin_s", foreground=T["metin_s"])
    daktilo_gorunur = [False]

    # sag: ozet + son yazim
    sag = tk.Frame(govde, bg=T["panel"], width=360); sag.pack(side="left", fill="y")
    sag.pack_propagate(False)
    tk.Label(sag, text="IS OZETI", bg=T["panel"], fg=T["soluk"], font=(FONT, 9, "bold")).pack(
        anchor="w", padx=8, pady=(6, 2))
    ozet_lbl = tk.Label(sag, text="-", bg=T["panel"], fg=T["metin"], justify="left",
                        anchor="nw", wraplength=330, font=(FONT, 9))
    ozet_lbl.pack(fill="x", padx=8)
    tk.Label(sag, text="YAZILAN DOSYALAR  (tikla -> asagida goster)", bg=T["panel"],
             fg=T["soluk"], font=(FONT, 9, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
    dosya_liste = tk.Listbox(sag, height=5, bg=T["panel2"], fg=T["yazim"],
                             selectbackground=T["vurgu"], selectforeground="#ffffff",
                             borderwidth=0, highlightthickness=0, font=("Consolas", 9))
    dosya_liste.pack(fill="x", padx=8)
    secili_dosya = {"yol": None, "elle": False}

    def dosya_tikla(_e=None):
        sec = dosya_liste.curselection()
        if sec:
            secili_dosya["yol"] = dosya_liste.get(sec[0])
            secili_dosya["elle"] = True
    dosya_liste.bind("<<ListboxSelect>>", dosya_tikla)
    onizleme = tk.Text(sag, bg=T["panel2"], fg=T["kod"], borderwidth=0, highlightthickness=0,
                       font=("Consolas", 8), wrap="none", height=20)
    for ad in ("kw", "yorum", "sayi", "kod"):
        onizleme.tag_configure(ad, foreground=T[ad])
    onizleme.tag_configure("metin_s", foreground=T["metin_s"])
    onizleme.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    onizleme.configure(state="disabled")

    bekleyen: list = []

    def kod_ekle(widget, satir: str):
        for et, parca in renkle(satir):
            widget.insert("end", parca, "metin_s" if et == "metin" else (et or "kod"))
        widget.insert("end", "\n")

    def daktilo():
        # akis kuyrugu: olaylar kademeli dokulur (adim adim his)
        if bekleyen:
            akis.configure(state="normal")
            hiz = 4 if bekleyen[0][0] == "kod" else 2
            for _ in range(min(hiz, len(bekleyen))):
                etiket, metin = bekleyen.pop(0)
                if etiket == "kod":
                    akis.insert("end", "  ", "kod")    # blok girintisi; satirin kendi girintisi korunur
                    kod_ekle(akis, metin)
                else:
                    akis.insert("end", metin + "\n", etiket)
            akis.see("end")
            akis.configure(state="disabled")
        # canli.txt damlasi: okunan metin ekrana KARAKTER KARAKTER akar (hafif gecikmeli)
        hedef = durum["canli_metin"]
        ciz = durum["canli_ciz"]
        if ciz < len(hedef):
            geri = len(hedef) - ciz
            adim = 12 if geri < 900 else 80              # geride kalirsa hizlanir
            parca = hedef[ciz:ciz + adim]
            durum["canli_ciz"] = ciz + len(parca)
            daktilo_kutu.configure(state="normal")
            daktilo_kutu.insert("end", parca, "kod")
            daktilo_kutu.see("end")
            daktilo_kutu.configure(state="disabled")
        kok.after(45, daktilo)

    def filtre_sec(ad):
        durum["filtre"] = ad
        durum["gosterilen"] = 0
        bekleyen.clear()
        akis.configure(state="normal"); akis.delete("1.0", "end"); akis.configure(state="disabled")

    for ad, etiket in FILTRELER:
        k = tk.Label(serit, text=etiket, bg=T["panel2"], fg=T["soluk"],
                     font=(FONT, 8, "bold"), padx=8, pady=3, cursor="hand2")
        k.pack(side="left", padx=(0, 4))
        k.bind("<Button-1>", lambda _e, a=ad: filtre_sec(a))
        kutular[ad] = k

    def is_sec(jid: str):
        if durum["secili"] != jid:
            durum["secili"] = jid
            durum["gosterilen"] = 0
            durum["canli_metin"] = ""; durum["canli_ciz"] = 0
            secili_dosya["yol"] = None; secili_dosya["elle"] = False
            bekleyen.clear()
            akis.configure(state="normal"); akis.delete("1.0", "end"); akis.configure(state="disabled")
            daktilo_kutu.configure(state="normal"); daktilo_kutu.delete("1.0", "end")
            daktilo_kutu.configure(state="disabled")

    def tikla(_e=None):
        sec = liste.curselection()
        if sec:
            takip.set(False)
            is_sec(liste.get(sec[0]).split()[0])
    liste.bind("<<ListboxSelect>>", tikla)

    def gecen(e: dict) -> bool:
        return durum["filtre"] == "tumu" or e.get("_asama") == durum["filtre"]

    def guncelle():
        adlar = depo.is_listesi()[:60 if hepsi.get() else 12]
        for jid in adlar[:8]:
            depo.tazele(jid)
        if durum["secili"] and durum["secili"] not in depo.olaylar:
            depo.tazele(durum["secili"])
        secili_gorunum = liste.curselection()
        liste.delete(0, "end")
        for i, jid in enumerate(adlar):
            s = depo.durumlar.get(jid) or {}
            liste.insert("end", "%s  %-5s %s" % (jid, s.get("ortam", "?"),
                                                 s.get("durum", "?") if s else "?"))
            renk = T["yazim"] if s.get("durum") == "bitti" and s.get("derleme") == "derlendi" \
                else (T["hata"] if s.get("derleme") in ("hata", "calistirilamadi") else T["arac"])
            liste.itemconfig(i, foreground=renk)
        if takip.get() and adlar:
            is_sec(adlar[0])
        if secili_gorunum and not takip.get():
            liste.selection_set(secili_gorunum[0])

        jid = durum["secili"]
        if jid and jid in depo.olaylar:
            s = depo.durumlar[jid]
            olaylar = depo.olaylar[jid]
            if durum["gosterilen"] == 0 and durum["filtre"] in ("tumu", "baslama") and s["gorev"]:
                bekleyen.append(("sonuc", "GOREV (ustadan): " + s["gorev"][:400]))
            if durum["gosterilen"] < len(olaylar):
                for e in olaylar[durum["gosterilen"]:]:
                    if gecen(e):
                        bekleyen.extend(olay_satirlari(e))
                durum["gosterilen"] = len(olaylar)
            # canli.txt: hedef metni oku; daktilo dongusu damlatir. Tur bitiminde dosya
            # bosalir -> pano temizlenir.
            canli_txt = ""
            if s["durum"] == "calisiyor":
                try:
                    with open(os.path.join(depo.jobs_dir, jid, "canli.txt"),
                              encoding="utf-8", errors="replace") as f:
                        canli_txt = f.read()
                except OSError:
                    pass
            if canli_txt and not canli_txt.startswith(durum["canli_metin"][:200]):
                durum["canli_metin"] = canli_txt          # yeni tur: bastan
                durum["canli_ciz"] = 0
                daktilo_kutu.configure(state="normal"); daktilo_kutu.delete("1.0", "end")
                daktilo_kutu.configure(state="disabled")
            elif canli_txt:
                durum["canli_metin"] = canli_txt
            elif not canli_txt and durum["canli_metin"] and s["durum"] != "calisiyor":
                durum["canli_metin"] = ""; durum["canli_ciz"] = 0
            if canli_txt and not daktilo_gorunur[0]:
                pw.add(dak_kap, minsize=120, stretch="always")
                daktilo_gorunur[0] = True
            elif not canli_txt and daktilo_gorunur[0] and s["durum"] != "calisiyor":
                pw.forget(dak_kap)
                daktilo_gorunur[0] = False

            aktif = s.get("asama", "baslama")
            for ad, _e in FILTRELER:
                k = kutular[ad]
                secili_f = durum["filtre"] == ad
                if ad == aktif:
                    k.configure(bg=T["vurgu"], fg="#ffffff")
                elif secili_f:
                    k.configure(bg=T["cizgi"], fg=T["metin"])
                else:
                    k.configure(bg=T["panel2"], fg=T["soluk"])
            if s["durum"] == "calisiyor" and s.get("son_olay_t"):
                sessiz = time.time() - s["son_olay_t"]
                if sessiz > 2 and not canli_txt:
                    yanip = "..." if int(time.time() * 2) % 2 else "   "
                    canli_lbl.configure(text="MODEL URETIYOR%s  %d sn  (son: %s)" % (
                        yanip, sessiz, s.get("son_olay") or "-"), fg=T["arac"])
                else:
                    canli_lbl.configure(text="", fg=T["soluk"])
            else:
                canli_lbl.configure(text="", fg=T["soluk"])

            ku = s.get("kullanim") or {}
            b = s.get("baglam") or {}
            sy = s.get("sayac") or {}
            satirlar = ["is: %s   ortam: %s   dogrulama: %s" % (jid, s["ortam"], s["dogrulama"]),
                        "durum: %s   derleme: %s   tur: %s   sure: %s s" % (
                            s["durum"], s["derleme"], s["tur"] or "-", s["sure"] or "-"),
                        "token: prompt %s / uretim %s / cagri %s" % (
                            ku.get("prompt_tokens", "-"), ku.get("gen_tokens", "-"),
                            ku.get("model_cagrisi", "-")),
                        "baglam: sistem %s kr, hafiza %s, STATE %s, harita %s" % (
                            b.get("sistem", "-"), b.get("hafiza") or "-",
                            b.get("durum") or "-", b.get("harita") or "-"),
                        "sayac: %d arac, %d yazim, %d no-op, %d izin reddi, %d kanit hatasi, %d onarim" % (
                            sy.get("arac", 0), sy.get("yazim", 0), sy.get("noop", 0),
                            sy.get("izin_red", 0), sy.get("kanit_hata", 0), sy.get("onarim", 0))]
            for u in s["uyarilar"][:4]:
                satirlar.append("UYARI: " + str(u)[:110])
            for h in s["hatalar"][:2]:
                satirlar.append("HATA: " + str(h)[:110])
            ozet_lbl.configure(text="\n".join(satirlar))
            yazimlar = s.get("yazimlar") or {}
            if list(yazimlar) != list(dosya_liste.get(0, "end")):
                dosya_liste.delete(0, "end")
                for yol in yazimlar:
                    dosya_liste.insert("end", yol)
            hedef_yol = secili_dosya["yol"] if (secili_dosya["elle"] and
                                                secili_dosya["yol"] in yazimlar) \
                else (list(yazimlar)[-1] if yazimlar else None)
            if hedef_yol and getattr(onizleme, "_gosterilen", None) != (hedef_yol, len(yazimlar.get(hedef_yol, ""))):
                onizleme._gosterilen = (hedef_yol, len(yazimlar[hedef_yol]))
                onizleme.configure(state="normal")
                onizleme.delete("1.0", "end")
                onizleme.insert("end", "# %s\n" % hedef_yol, "yorum")
                for satir in yazimlar[hedef_yol].splitlines()[:150]:
                    kod_ekle(onizleme, satir)
                onizleme.configure(state="disabled")
        if time.time() - durum["sistem_t"] > 3:
            durum["sistem_t"] = time.time()
            sistem_lbl.configure(text=sistem_satiri())
        kok.after(400, guncelle)

    guncelle()
    daktilo()
    kok.mainloop()


def calisan_izleyici(home: str) -> int | None:
    """Ayni ev icin acik izleyici var mi? Varsa PID'i doner (tekil pencere kilidi)."""
    p = os.path.join(os.path.expanduser(home), "izleyici.pid")
    try:
        pid = int(open(p, encoding="utf-8").read().strip())
    except Exception:
        return None
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                             capture_output=True, text=True, timeout=5,
                             creationflags=PENCERESIZ).stdout.lower()
        # pid tek basina yetmez (geri kazanilmis olabilir): surec adi da izleyici olmali
        return pid if (str(pid) in out and
                       ("izleyici" in out or "python" in out)) else None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=os.environ.get("APPRENTICE_HOME") or
                    os.path.join(os.path.expanduser("~"), ".apprentice"))
    ap.add_argument("--coklu", action="store_true", help="acik pencere olsa da yenisini ac")
    a = ap.parse_args()
    if not a.coklu and calisan_izleyici(a.home):
        return 0                                       # zaten acik: sessizce cik
    pid_yolu = os.path.join(os.path.expanduser(a.home), "izleyici.pid")
    try:
        os.makedirs(os.path.dirname(pid_yolu), exist_ok=True)
        with open(pid_yolu, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        import atexit
        atexit.register(lambda: os.path.exists(pid_yolu) and os.remove(pid_yolu))
    except OSError:
        pass
    gui(a.home)
    return 0


if __name__ == "__main__":
    sys.exit(main())
