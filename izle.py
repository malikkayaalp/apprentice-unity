"""Apprentice Izleyici - masaustu canli izleme (web arayuzu DEGIL; tkinter, bagimliliksiz).

    python izle.py                    # ~/.apprentice icindeki isleri izler
    python izle.py --home <klasor>    # baska ev (or. .apprentice_test_home)

Sunucuya baglanmaz; iscinin yazdigi is klasorunu okur (job.json + events.jsonl) - bu yuzden
hangi istemci baslatmis olursa olsun (Claude Code, Cursor, olcum betigi) her is gorunur.
Paneller: is listesi / canli olay akisi (arac cagrilari, yazimlar, hatalar) / is ozeti
(durum, tur, token, uyarilar: duragan-ruff-butce-hafiza) / son yazilan dosya onizleme.
Ust satirda sistem durumu: yuklu model (ollama ps) + VRAM (nvidia-smi), 3 sn'de bir.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time

# ------------------------------------------------------------------ veri katmani (GUI'siz test edilir)


class IsDeposu:
    """Is klasorunu artimli okur: events.jsonl'da yalnizca yeni satirlar islenir."""

    def __init__(self, home: str):
        self.home = os.path.expanduser(home)
        self.jobs_dir = os.path.join(self.home, "jobs")
        self.durumlar: dict = {}          # jid -> ozet
        self.olaylar: dict = {}           # jid -> [olay]
        self._ofset: dict = {}            # jid -> okunan bayt

    def is_listesi(self) -> list:
        if not os.path.isdir(self.jobs_dir):
            return []
        adlar = [a for a in os.listdir(self.jobs_dir)
                 if os.path.isdir(os.path.join(self.jobs_dir, a))]
        return sorted(adlar, reverse=True)

    def tazele(self, jid: str) -> bool:
        """Yeni olay varsa isler, True doner."""
        p = os.path.join(self.jobs_dir, jid, "events.jsonl")
        try:
            boyut = os.path.getsize(p)
        except OSError:
            return False
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
        self.olaylar[jid].extend(yeni)
        self._ozeti_isle(jid, yeni)
        self._sure_guncelle(jid)
        return bool(yeni)

    def _is_bilgisi(self, jid: str) -> dict:
        try:
            with open(os.path.join(self.jobs_dir, jid, "job.json"), encoding="utf-8") as f:
                job = json.load(f)
        except Exception:
            job = {}
        return {"id": jid, "ortam": job.get("ortam", "?"), "gorev": job.get("gorev", ""),
                "dogrulama": job.get("dogrulama", "tam"), "baslangic": job.get("baslangic"),
                "durum": "calisiyor", "derleme": "-", "tur": 0, "sure": None, "kullanim": {},
                "dosyalar": [], "uyarilar": [], "hatalar": [], "ozet": "", "son_yazim": None}

    def _ozeti_isle(self, jid: str, yeni: list):
        s = self.durumlar[jid]
        for e in yeni:
            t = e.get("type")
            if t == "write":
                s["dosyalar"].append(e.get("path"))
                s["son_yazim"] = {"path": e.get("path"), "icerik": e.get("after") or ""}
            elif t == "assistant":
                s["ozet"] = e.get("text", "")
            elif t == "result":
                s["derleme"] = "derlendi" if e.get("ok") else "hata"
                s["tur"] = int(e.get("rounds", 0)) + 1
                s["sure"] = e.get("wall")
                s["kullanim"] = e.get("kullanim") or {}
                s["hatalar"] = e.get("errors") or []
                for alan, etiket in (("duragan", "DURAGANLIK: isci ilerleyemiyor, usta gerekli"),
                                     ("butce_uyarisi", None), ("hafiza_uyarisi", None),
                                     ("durum_uyarisi", None)):
                    v = e.get(alan)
                    if v:
                        s["uyarilar"].append(etiket or str(v))
                if e.get("ruff"):
                    s["uyarilar"].extend("ruff: " + str(u) for u in e["ruff"][:4])
            elif t == "error":
                s["hatalar"].append(e.get("message", ""))
                s["derleme"] = "calistirilamadi"
            elif t == "exit":
                s["durum"] = "bitti"

    def _sure_guncelle(self, jid: str):
        s = self.durumlar.get(jid)
        if s and s["durum"] == "calisiyor" and s.get("baslangic"):
            s["sure"] = round(time.time() - s["baslangic"], 1)


def olay_satiri(e: dict) -> tuple:
    """(etiket, metin) - GUI renk siniflari: arac / yazim / hata / sonuc / bilgi."""
    t = e.get("type")
    if t == "tool":
        det = e.get("detail") or json.dumps(e.get("args") or {}, ensure_ascii=False)[:80]
        return "arac", "ARAC  %s %s" % (e.get("name"), det)
    if t == "tool_result":
        m = str(e.get("text") or "")[:120].replace("\n", " ")
        return "bilgi", "  -> %s" % (m or "ok")
    if t == "write":
        n = (e.get("after") or "").count("\n") + 1
        return "yazim", "YAZDI %s (%d satir)" % (e.get("path"), n)
    if t == "assistant":
        return "sonuc", "ISCI OZETI: %s" % str(e.get("text", ""))[:200].replace("\n", " ")
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


def sistem_satiri() -> str:
    parcalar = []
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=4).stdout
        satirlar = [x for x in out.splitlines()[1:] if x.strip()]
        parcalar.append(("model: " + satirlar[0].split()[0].split("/")[-1][:40]) if satirlar
                        else "model: yuklu degil")
    except Exception:
        parcalar.append("ollama: erisilemedi")
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=4).stdout.strip()
        k, t, u = [x.strip() for x in out.split(",")[:3]]
        parcalar.append("VRAM %s/%s MiB  GPU %%%s" % (k, t, u))
    except Exception:
        pass
    return "   |   ".join(parcalar)


# ------------------------------------------------------------------ arayuz (koyu Claude temasi)
T = {"bg": "#1f1d1a", "panel": "#2a2724", "panel2": "#33302c", "cizgi": "#3f3b36",
     "metin": "#f1ede6", "soluk": "#a39d94", "vurgu": "#d97757",
     "arac": "#e0b345", "yazim": "#7fbf6f", "hata": "#e06c5f", "sonuc": "#7fb4d9"}
FONT = "Segoe UI"


def gui(home: str):
    import tkinter as tk
    from tkinter import ttk

    depo = IsDeposu(home)
    kok = tk.Tk()
    kok.title("Apprentice Izleyici")
    kok.geometry("1240x760")
    kok.configure(bg=T["bg"])
    st = ttk.Style(kok); st.theme_use("clam")
    st.configure(".", background=T["bg"], foreground=T["metin"], font=(FONT, 10),
                 bordercolor=T["cizgi"])
    st.configure("TCheckbutton", background=T["bg"], foreground=T["soluk"])
    st.map("TCheckbutton", background=[("active", T["bg"])])

    ust = tk.Frame(kok, bg=T["bg"]); ust.pack(fill="x", padx=10, pady=(8, 4))
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
    liste = tk.Listbox(sol, width=34, height=32, bg=T["panel2"], fg=T["metin"],
                       selectbackground=T["vurgu"], selectforeground="#ffffff",
                       borderwidth=0, highlightthickness=0, font=("Consolas", 9))
    liste.pack(fill="y", expand=True, padx=8, pady=6)

    # orta: olay akisi
    orta = tk.Frame(govde, bg=T["bg"]); orta.pack(side="left", fill="both", expand=True, padx=(8, 8))
    tk.Label(orta, text="CANLI OLAY AKISI", bg=T["bg"], fg=T["soluk"],
             font=(FONT, 9, "bold")).pack(anchor="w")
    akis = tk.Text(orta, bg=T["panel"], fg=T["metin"], insertbackground=T["metin"],
                   borderwidth=0, highlightthickness=0, font=("Consolas", 9), wrap="word")
    akis.pack(fill="both", expand=True, pady=(2, 0))
    for ad in ("arac", "yazim", "hata", "sonuc"):
        akis.tag_configure(ad, foreground=T[ad])
    akis.tag_configure("bilgi", foreground=T["soluk"])
    akis.configure(state="disabled")

    # sag: ozet + son yazim
    sag = tk.Frame(govde, bg=T["panel"], width=380); sag.pack(side="left", fill="y")
    sag.pack_propagate(False)
    tk.Label(sag, text="IS OZETI", bg=T["panel"], fg=T["soluk"], font=(FONT, 9, "bold")).pack(
        anchor="w", padx=8, pady=(6, 2))
    ozet_lbl = tk.Label(sag, text="-", bg=T["panel"], fg=T["metin"], justify="left",
                        anchor="nw", wraplength=350, font=(FONT, 9))
    ozet_lbl.pack(fill="x", padx=8)
    tk.Label(sag, text="SON YAZILAN DOSYA", bg=T["panel"], fg=T["soluk"],
             font=(FONT, 9, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
    onizleme = tk.Text(sag, bg=T["panel2"], fg=T["metin"], borderwidth=0, highlightthickness=0,
                       font=("Consolas", 8), wrap="none", height=22)
    onizleme.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    onizleme.configure(state="disabled")

    durum = {"secili": None, "gosterilen": 0, "sistem_t": 0.0}

    def is_sec(jid: str):
        if durum["secili"] != jid:
            durum["secili"] = jid
            durum["gosterilen"] = 0
            akis.configure(state="normal"); akis.delete("1.0", "end"); akis.configure(state="disabled")

    def tikla(_e=None):
        sec = liste.curselection()
        if sec:
            takip.set(False)
            is_sec(liste.get(sec[0]).split()[0])
    liste.bind("<<ListboxSelect>>", tikla)

    def guncelle():
        adlar = depo.is_listesi()[:60]
        for jid in adlar[:8]:                          # en yeni birkaci canli tazelenir
            depo.tazele(jid)
        if durum["secili"] and durum["secili"] not in depo.olaylar:
            depo.tazele(durum["secili"])               # eski ise tiklandi: onu da yukle
        # liste
        secili_gorunum = liste.curselection()
        liste.delete(0, "end")
        for i, jid in enumerate(adlar):
            s = depo.durumlar.get(jid) or {}
            liste.insert("end", "%s  %-5s %s" % (jid, s.get("ortam", "?"),
                                                 s.get("durum", "?") if s else "?"))
            renk = T["yazim"] if s.get("durum") == "bitti" and s.get("derleme") == "derlendi" \
                else (T["hata"] if s.get("derleme") in ("hata", "calistirilamadi")
                      else T["arac"])
            liste.itemconfig(i, foreground=renk)
        if takip.get() and adlar:
            is_sec(adlar[0])
        if secili_gorunum and not takip.get():
            liste.selection_set(secili_gorunum[0])
        # akis + ozet
        jid = durum["secili"]
        if jid and jid in depo.olaylar:
            olaylar = depo.olaylar[jid]
            if durum["gosterilen"] < len(olaylar):
                akis.configure(state="normal")
                for e in olaylar[durum["gosterilen"]:]:
                    etiket, metin = olay_satiri(e)
                    akis.insert("end", metin + "\n", etiket)
                akis.see("end")
                akis.configure(state="disabled")
                durum["gosterilen"] = len(olaylar)
            s = depo.durumlar[jid]
            ku = s.get("kullanim") or {}
            satirlar = ["is: %s   ortam: %s   dogrulama: %s" % (jid, s["ortam"], s["dogrulama"]),
                        "durum: %s   derleme: %s   tur: %s   sure: %s s" % (
                            s["durum"], s["derleme"], s["tur"] or "-", s["sure"] or "-"),
                        "token: prompt %s / uretim %s / cagri %s" % (
                            ku.get("prompt_tokens", "-"), ku.get("gen_tokens", "-"),
                            ku.get("model_cagrisi", "-")),
                        "gorev: " + (s["gorev"][:220] + ("..." if len(s["gorev"]) > 220 else ""))]
            for u in s["uyarilar"][:5]:
                satirlar.append("UYARI: " + str(u)[:120])
            for h in s["hatalar"][:3]:
                satirlar.append("HATA: " + str(h)[:120])
            ozet_lbl.configure(text="\n".join(satirlar))
            y = s.get("son_yazim")
            if y:
                onizleme.configure(state="normal")
                onizleme.delete("1.0", "end")
                icerik = y["icerik"]
                onizleme.insert("end", "# %s\n" % y["path"] +
                                "\n".join(icerik.splitlines()[:120]))
                onizleme.configure(state="disabled")
        # sistem satiri (3 sn'de bir)
        if time.time() - durum["sistem_t"] > 3:
            durum["sistem_t"] = time.time()
            sistem_lbl.configure(text=sistem_satiri())
        kok.after(700, guncelle)

    guncelle()
    kok.mainloop()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=os.environ.get("APPRENTICE_HOME") or
                    os.path.join(os.path.expanduser("~"), ".apprentice"))
    a = ap.parse_args()
    gui(a.home)
    return 0


if __name__ == "__main__":
    sys.exit(main())
