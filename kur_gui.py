"""Apprentice Setup - grafik kurulum (tkinter, ek bagimlilik yok).

Her yerden calisir: Apprentice dosyalari exe'nin icinde gomulu (payload.zip), kullanici kurulum
klasorunu secer, dosyalar oraya acilir; sonra kur.py motoru adim adim kosar:
Python (gerekirse gomulu) -> Ollama -> model (ilerleme cubugu) -> IDE ayarlari -> oz-test.

Gelistirme: python kur_gui.py  (payload yerine bu depo klasoru kopyalanir)
Paketleme: python kur_build.py  ->  dist/Apprentice-Setup.exe
"""
from __future__ import annotations
import os, subprocess, sys, threading, zipfile, webbrowser, shutil, queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

BURASI = os.path.dirname(os.path.abspath(__file__))
DONMUS = getattr(sys, "frozen", False)
PAYLOAD = os.path.join(getattr(sys, "_MEIPASS", BURASI), "payload.zip")
VARSAYILAN_KOK = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Apprentice") \
    if os.name == "nt" else os.path.join(os.path.expanduser("~"), "apprentice")

# Tema: koyu, sicak (Claude paleti). Kil vurgu, kemik metin.
T = {"bg": "#1f1d1a", "panel": "#2a2724", "panel2": "#33302c", "cizgi": "#3f3b36",
     "metin": "#f1ede6", "soluk": "#a39d94", "vurgu": "#d97757", "vurgu2": "#e8956f",
     "ok": "#6fc28a", "hata": "#ee6b5b", "uyari": "#e9b85c"}
FONT = "Segoe UI" if os.name == "nt" else "Helvetica"

ADIMLAR = [("dosyalar", "Apprentice dosyaları"), ("python", "Python"), ("ollama", "Ollama"),
           ("model", "Yerel model (Qwen3-Coder-Next, ~20 GB)"), ("ide", "IDE bağlantıları"),
           ("cli", "Ajan CLI'ları"), ("kisayol", "Panel kısayolu"), ("test", "Öz-test")]


def dosyalari_ac(kok: str, log) -> bool:
    """payload.zip'i (exe) ya da gelistirme klasorunu kuruluma kopyala."""
    os.makedirs(kok, exist_ok=True)
    if os.path.isfile(PAYLOAD):
        with zipfile.ZipFile(PAYLOAD) as z:
            z.extractall(kok)
            n = len(z.namelist())
        log("[ok]  %d dosya açıldı → %s" % (n, kok))
        return True
    # gelistirme: depo klasorunu kopyala (kendi kendine kopyalama yok)
    if os.path.abspath(kok) == os.path.abspath(BURASI):
        log("[ok]  Geliştirme kipi: depo klasörü kurulum klasörü olarak kullanılıyor")
        return True
    for ad in ("core", "mcpbridge", "server", "envs", "clients", "tests",
               "apprentice.config.template.json", ".mcp.json", "kur.py", "README.md",
               # panel/izleyici dosyalari eksikti: kisayol sessizce atlaniyor, "Paneli ac"
               # "once kurulumu tamamla" diyordu ama adim listesi hepsini ✓ gosteriyordu
               "panel_ac.py", "izle.py", "STATE.md"):
        src = os.path.join(BURASI, ad)
        dst = os.path.join(kok, ad)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "unity", ".apprentice_test_home"))
        elif os.path.isfile(src):
            shutil.copy2(src, dst)
    log("[ok]  Dosyalar kopyalandı → %s" % kok)
    return True


class Sihirbaz(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Apprentice Setup")
        self.geometry("980x640")
        self.minsize(940, 600)   # dar pencerede "Kur"
        # dugmesi "K"ya kirpiliyordu (yasandi): alt satirdaki dort dugme sigmali
        self.kuyruk = queue.Queue()
        self.durum = {k: "bekliyor" for k, _ in ADIMLAR}
        self.ollama_eksik = False
        self._kur_ui()
        self.after(50, self._koyu_baslik)
        self.after(100, self._kuyruk_isle)

    def _koyu_baslik(self):
        """Windows 10/11 baslik cubugunu koyu yap (DWMWA_USE_IMMERSIVE_DARK_MODE); diger sistemlerde sessiz."""
        if os.name != "nt":
            return
        try:
            import ctypes
            h = ctypes.windll.user32.GetParent(self.winfo_id())
            deger = ctypes.c_int(1)
            for attr in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(h, attr, ctypes.byref(deger), ctypes.sizeof(deger)) == 0:
                    break
            # yeniden cizim icin boyutu bir tik oynat
            g = self.geometry(); self.geometry(g)
        except Exception:
            pass

    # ---------------------------------------------------------------- UI
    def _tema(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        self.configure(bg=T["bg"])
        st.configure(".", background=T["bg"], foreground=T["metin"], font=(FONT, 10), bordercolor=T["cizgi"],
                     lightcolor=T["panel"], darkcolor=T["bg"], troughcolor=T["panel2"], fieldbackground=T["panel2"])
        st.configure("TFrame", background=T["bg"])
        st.configure("Panel.TFrame", background=T["panel"])
        st.configure("TLabel", background=T["bg"], foreground=T["metin"])
        st.configure("Panel.TLabel", background=T["panel"], foreground=T["metin"])
        st.configure("Soluk.TLabel", background=T["panel"], foreground=T["soluk"])
        st.configure("Baslik.TLabel", background=T["bg"], foreground=T["metin"], font=(FONT, 20, "bold"))
        st.configure("Alt.TLabel", background=T["bg"], foreground=T["soluk"], font=(FONT, 10))
        st.configure("TLabelframe", background=T["panel"], bordercolor=T["cizgi"], relief="flat")
        st.configure("TLabelframe.Label", background=T["panel"], foreground=T["soluk"], font=(FONT, 9, "bold"))
        st.configure("TEntry", fieldbackground=T["panel2"], foreground=T["metin"], insertcolor=T["metin"],
                     bordercolor=T["cizgi"], lightcolor=T["cizgi"], darkcolor=T["cizgi"])
        st.configure("TButton", background=T["panel2"], foreground=T["metin"], bordercolor=T["cizgi"],
                     focuscolor=T["panel2"], padding=(12, 6), font=(FONT, 10))
        st.map("TButton", background=[("active", T["cizgi"]), ("disabled", T["panel"])],
               foreground=[("disabled", T["soluk"])])
        st.configure("Vurgu.TButton", background=T["vurgu"], foreground="#1a1512", bordercolor=T["vurgu"],
                     font=(FONT, 10, "bold"))
        st.map("Vurgu.TButton", background=[("active", T["vurgu2"]), ("disabled", T["panel2"])],
               foreground=[("disabled", T["soluk"])])
        st.configure("TProgressbar", background=T["vurgu"], troughcolor=T["panel2"], bordercolor=T["panel2"],
                     lightcolor=T["vurgu"], darkcolor=T["vurgu"])
        st.configure("Vertical.TScrollbar", background=T["panel2"], troughcolor=T["panel"], bordercolor=T["panel"],
                     arrowcolor=T["soluk"])

    def _kur_ui(self):
        self._tema()
        ust = ttk.Frame(self, padding=(20, 16, 20, 8))
        ust.pack(fill="x")
        sat = ttk.Frame(ust); sat.pack(anchor="w")
        tk.Label(sat, text="✦", bg=T["bg"], fg=T["vurgu"], font=(FONT, 18)).pack(side="left", padx=(0, 8))
        ttk.Label(sat, text="Apprentice", style="Baslik.TLabel").pack(side="left")
        ttk.Label(ust, text="A local model does the work, a frontier model supervises.",
                  style="Alt.TLabel").pack(anchor="w", pady=(2, 0))

        govde = ttk.Frame(self, padding=(16, 4))
        govde.pack(fill="both", expand=True)
        govde.columnconfigure(1, weight=1)
        govde.rowconfigure(2, weight=1)

        # sol: adimlar
        sol = ttk.LabelFrame(govde, text="Adımlar", padding=10)
        sol.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=(0, 12))
        self.adim_etiket = {}
        for k, ad in ADIMLAR:
            e = ttk.Label(sol, text="○  " + ad, style="Panel.TLabel", font=(FONT, 10))
            e.pack(anchor="w", pady=4)
            self.adim_etiket[k] = (e, ad)

        # sag ust: klasor
        kl = ttk.LabelFrame(govde, text="Kurulum klasörü", padding=10)
        kl.grid(row=0, column=1, sticky="ew")
        kl.columnconfigure(0, weight=1)
        self.kok_var = tk.StringVar(value=VARSAYILAN_KOK)
        ttk.Entry(kl, textvariable=self.kok_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(kl, text="Gözat…", command=self._gozat).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(kl, text="Dosyalar bu klasöre açılır; IDE'ler sunucuyu buradan çalıştırır. "
                           "Python yoksa gömülü Python da buraya iner.", style="Soluk.TLabel",
                  wraplength=440).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # sag orta: ilerleme
        il = ttk.Frame(govde)
        il.grid(row=1, column=1, sticky="ew", pady=(10, 4))
        il.columnconfigure(0, weight=1)
        self.ilerleme_var = tk.DoubleVar(value=0)
        self.ilerleme = ttk.Progressbar(il, variable=self.ilerleme_var, maximum=100)
        self.ilerleme.grid(row=0, column=0, sticky="ew")
        self.ilerleme_metin = ttk.Label(il, text="Hazır.", foreground=T["soluk"])
        self.ilerleme_metin.grid(row=1, column=0, sticky="w", pady=(4, 0))

        # sag alt: log
        lg = ttk.LabelFrame(govde, text="Ayrıntı", padding=6)
        lg.grid(row=2, column=1, sticky="nsew")
        lg.rowconfigure(0, weight=1); lg.columnconfigure(0, weight=1)
        self.log_kutu = tk.Text(lg, height=10, wrap="word", font=("Consolas", 9), state="disabled",
                                background=T["panel2"], foreground=T["metin"], insertbackground=T["metin"],
                                relief="flat", highlightthickness=0, padx=8, pady=6)
        self.log_kutu.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lg, command=self.log_kutu.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_kutu.configure(yscrollcommand=sb.set)
        self.log_kutu.tag_configure("ok", foreground=T["ok"])
        self.log_kutu.tag_configure("hata", foreground=T["hata"])
        self.log_kutu.tag_configure("uyari", foreground=T["uyari"])

        # alt: dugmeler
        alt = ttk.Frame(self, padding=(16, 8))
        alt.pack(fill="x")
        self.btn_ollama = ttk.Button(alt, text="Ollama'yı indir", command=lambda: webbrowser.open("https://ollama.com/download"))
        self.btn_kural = ttk.Button(alt, text="Bir projeye bağla…", command=self._kural)
        self.btn_kural.pack(side="left")
        self.btn_panel = ttk.Button(alt, text="Paneli aç", command=self._panel)
        self.btn_panel.pack(side="left", padx=(8, 0))
        ttk.Label(alt, text="Proje klasörüne AGENTS.md + .cursor/rules/apprentice.mdc yazar; IDE o projede\n"
                            "usta rolünü otomatik uygular (kodu kendisi yazmaz, worker_run'a verir).",
                  style="Alt.TLabel", font=(FONT, 8)).pack(side="left", padx=(10, 0))
        self.btn_kapat = ttk.Button(alt, text="Kapat", command=self.destroy)
        self.btn_kapat.pack(side="right")
        self.btn_kur = ttk.Button(alt, text="Kur", command=self._baslat, style="Vurgu.TButton")
        self.btn_kur.pack(side="right", padx=(0, 8))

    def _gozat(self):
        d = filedialog.askdirectory(initialdir=os.path.dirname(self.kok_var.get()) or os.path.expanduser("~"))
        if d:
            self.kok_var.set(os.path.join(d, "Apprentice") if os.path.basename(d).lower() != "apprentice" else d)

    # ---------------------------------------------------------------- log / durum (is parcacigindan)
    def log(self, metin: str):
        self.kuyruk.put(("log", metin))
        try:                                    # pencere kipinde stderr yok: gunluk dosyaya da
            with open(os.path.join(self.kok_var.get() or BURASI, "kurulum.log"), "a", encoding="utf-8") as f:
                f.write(metin.rstrip() + chr(10))
        except Exception:
            pass

    def ilerle(self, yuzde, metin):
        self.kuyruk.put(("ilerleme", (yuzde, metin)))

    def adim_durum(self, k: str, d: str):
        self.kuyruk.put(("adim", (k, d)))

    def _kuyruk_isle(self):
        try:
            while True:
                tur, veri = self.kuyruk.get_nowait()
                if tur == "log":
                    self._log_yaz(veri)
                elif tur == "ilerleme":
                    y, m = veri
                    if y is None:
                        self.ilerleme.configure(mode="indeterminate"); self.ilerleme.start(12)
                    else:
                        self.ilerleme.stop(); self.ilerleme.configure(mode="determinate"); self.ilerleme_var.set(y)
                    self.ilerleme_metin.configure(text=m)
                elif tur == "adim":
                    k, d = veri
                    e, ad = self.adim_etiket[k]
                    sim = {"bekliyor": "○", "calisiyor": "⟳", "ok": "✓", "hata": "✗", "uyari": "!"}[d]
                    renk = {"ok": T["ok"], "hata": T["hata"], "uyari": T["uyari"], "calisiyor": T["vurgu"]}.get(d, T["metin"])
                    e.configure(text="%s  %s" % (sim, ad), foreground=renk)
                elif tur == "bitti":
                    self._bitti(veri)
        except queue.Empty:
            pass
        self.after(100, self._kuyruk_isle)

    def _log_yaz(self, metin: str):
        self.log_kutu.configure(state="normal")
        tag = "ok" if metin.startswith("[ok]") else "hata" if metin.startswith("[X]") else "uyari" if metin.startswith("[!]") else ""
        self.log_kutu.insert("end", metin.rstrip("\n") + "\n", tag)
        self.log_kutu.see("end")
        self.log_kutu.configure(state="disabled")

    # ---------------------------------------------------------------- kurulum
    def _baslat(self):
        kok = self.kok_var.get().strip()
        if not kok:
            messagebox.showerror("Apprentice", "Kurulum klasörü boş.")
            return
        self.btn_kur.configure(state="disabled")
        threading.Thread(target=self._kur, args=(kok,), daemon=True).start()

    def _kur(self, kok: str):
        sonuc = {}
        try:
            self.adim_durum("dosyalar", "calisiyor")
            self.ilerle(None, "Dosyalar açılıyor…")
            ok = dosyalari_ac(kok, self.log)
            self.adim_durum("dosyalar", "ok" if ok else "hata")
            sonuc["dosyalar"] = ok
            if not ok:
                raise RuntimeError("dosyalar açılamadı")

            sys.path.insert(0, kok)
            import importlib
            kur = importlib.import_module("kur") if "kur" not in sys.modules else sys.modules["kur"]
            kur.set_root(kok)
            kur.log = self.log
            kur.ilerleme = self.ilerle
            kur.DEGISTIR = True

            def calistir(k, fn):
                self.adim_durum(k, "calisiyor")
                self.ilerle(None, "%s kontrol ediliyor…" % dict(ADIMLAR)[k])
                try:
                    r = bool(fn())
                except Exception as e:  # noqa: BLE001
                    self.log("[X]   %s: %s" % (k, str(e)[:300]))
                    r = False
                self.adim_durum(k, "ok" if r else "hata")
                self.ilerle(100 if r else 0, "")
                sonuc[k] = r
                return r

            calistir("python", kur.kontrol_python)
            if not calistir("ollama", kur.kontrol_ollama):
                self.ollama_eksik = True
                self.adim_durum("model", "uyari")
                sonuc["model"] = False
            else:
                calistir("model", kur.kontrol_model)
            calistir("ide", lambda: (kur.kontrol_ideler(""), kur.mcp_json_guncelle())[0])
            calistir("cli", kur.kontrol_cli)
            calistir("kisayol", kur.kisayol_yaz)
            calistir("test", kur.oz_test)
        except Exception as e:  # noqa: BLE001
            import traceback
            self.log("[X]   %s" % e)
            self.log(traceback.format_exc())
        self.kuyruk.put(("bitti", sonuc))

    def _bitti(self, sonuc: dict):
        self._son_ok = all(sonuc.get(k) for k, _ in ADIMLAR)
        if getattr(self, "_oto", False):
            self.log("[ok]  sessiz kurulum bitti: %s" % self._son_ok)
            self.after(500, self.destroy)
            return
        self.btn_kur.configure(state="normal", text="Tekrar dene")
        if self.ollama_eksik:
            self.btn_ollama.pack(side="left", padx=(8, 0))
        if all(sonuc.get(k) for k, _ in ADIMLAR):
            self.ilerle(100, "Kurulum tamam.")
            self._ozet_penceresi()
        else:
            eksik = [dict(ADIMLAR)[k] for k, _ in ADIMLAR if not sonuc.get(k)]
            self.ilerle(0, "Eksik: " + ", ".join(eksik) + " — ayrıntı panelindeki [X] satırlarına bak.")

    def _ozet_penceresi(self):
        """Kurulum sonrasi 'ne kuruldu, nasil kullanirim' paneli - tema uyumlu, tek ekran,
        gezinme yok (kullanici istegi: net ama gereksiz gezdirmeden anlat)."""
        kok = self.kok_var.get().strip()
        kur = sys.modules.get("kur")
        ideler, cliler = [], []
        try:
            for ad, (_yol, _a, kurulu) in kur.ide_listesi().items():
                if os.path.isdir(kurulu):
                    ideler.append(ad)
            for ad, _acik, _b in kur.CLI_ADAYLARI:
                if shutil.which(ad):
                    cliler.append(ad)
        except Exception:
            pass
        w = tk.Toplevel(self)
        w.title("Apprentice — kurulum tamam")
        w.configure(bg=T["bg"]); w.geometry("780x640"); w.transient(self)
        ttk.Label(w, text="✦  Kurulum tamamlandı", style="Baslik.TLabel").pack(anchor="w", padx=22, pady=(18, 2))
        ttk.Label(w, text="Çırak (yerel model) hazır. Üç yoldan biriyle kullan:",
                  style="Alt.TLabel").pack(anchor="w", padx=22, pady=(0, 10))
        kut = tk.Text(w, bg=T["panel"], fg=T["metin"], relief="flat", wrap="word",
                      font=(FONT, 10), padx=16, pady=12, height=22, borderwidth=0)
        kut.pack(fill="both", expand=True, padx=18)
        kut.tag_configure("bas", foreground=T["vurgu2"], font=(FONT, 11, "bold"))
        kut.tag_configure("soluk", foreground=T["soluk"])
        kut.tag_configure("ok", foreground=T["ok"])

        def y(metin, tag=""):
            kut.insert("end", metin + "\n", tag)
        y("1) WEB PANELİ — en kolay yol", "bas")
        y("   Masaüstündeki “Apprentice Panel” kısayolu (ya da aşağıdaki “Paneli aç”).")
        y("   Tarayıcıda: çırağa görev/sohbet, Claude'a (usta) prompt, canlı kod akışı,", "soluk")
        y("   yazılan dosyalar, metrikler, boru hattı. Modeli anlık izlersin.", "soluk")
        y("")
        y("2) IDE İÇİNDEN (MCP)", "bas")
        y("   Bulunan ve bağlanan: " + (", ".join(ideler) if ideler else "—"), "ok")
        y("   IDE'yi aç/yenile → MCP listesinde “apprentice” görünür. Sohbette", "soluk")
        y("   “şunu çırağa yaptır” dersin; usta worker_run ile çırağı çalıştırıp doğrular.", "soluk")
        y("   Claude Code: kurulum klasöründe “claude” aç — .mcp.json hazır.", "soluk")
        y("")
        y("3) KOMUT SATIRI CLI'LARI", "bas")
        y("   Sistemde bulunanlar: " + (", ".join(cliler) if cliler else "—"), "ok")
        if "claude" in cliler:
            try:
                import json as _j, subprocess as _sp
                _r = _sp.run([shutil.which("claude"), "auth", "status"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=30,
                             creationflags=0x08000000 if os.name == "nt" else 0)
                _d = _j.loads((_r.stdout or "{}").strip() or "{}")
                if _d.get("loggedIn"):
                    y("   Claude oturumu: açık (%s)" % _d.get("email", "?"), "ok")
                else:
                    y("   ⚠ Claude KURULU ama GİRİŞ YAPILMAMIŞ — aşağıdaki “Claude'a giriş yap”", "bas")
                    y("     düğmesi (Claude Desktop girişi CLI'ya GEÇMEZ, ayrı oturumdur).", "soluk")
                    y("     Çırak/yerel model girişsiz de çalışır; yalnızca usta sohbeti giriş ister.", "soluk")
                    self._giris_gerek = True
            except Exception:
                pass
        y("   Panelin USTA bölümü “claude”u başsız çağırır (model + effort seçilebilir);", "soluk")
        y("   “özel CLI” alanına kendi komutunu yazarak (ör. gemini -p {prompt}) başka", "soluk")
        y("   bir ajanı da usta olarak bağlayabilirsin.", "soluk")
        y("")
        y("BİR PROJEYE BAĞLAMAK", "bas")
        y("   “Bir projeye bağla…” düğmesi, seçtiğin projeye AGENTS.md + Cursor kuralı yazar;", "soluk")
        y("   o projede usta kod işini kendiliğinden çırağa verir.", "soluk")
        y("")
        y("KURULUM KLASÖRÜ", "bas"); y("   " + kok, "soluk")
        kut.configure(state="disabled")
        # kullanici istegi: kurulum bitince panel KENDILIGINDEN acilsin (cerçevesiz
        # uygulama penceresi; Edge/Chrome yoksa normal tarayici)
        self.after(600, self._panel)
        alt = ttk.Frame(w, padding=(18, 12)); alt.pack(fill="x")
        ttk.Button(alt, text="Paneli yeniden aç", style="Vurgu.TButton",
                   command=self._panel).pack(side="left")
        ttk.Button(alt, text="Bir projeye bağla…",
                   command=lambda: (w.destroy(), self._kural())).pack(side="left", padx=8)
        if getattr(self, "_giris_gerek", False):
            ttk.Button(alt, text="Claude'a giriş yap",
                       command=self._claude_giris).pack(side="left", padx=(0, 8))
        ttk.Button(alt, text="Kapat", command=w.destroy).pack(side="right")

    def _claude_giris(self):
        """'claude auth login' akisini gorunur konsolda baslatir (etkilesim gerekir).
        NOT: Claude Desktop girisi CLI'ya gecmez - ayri oturumlardir."""
        try:
            kur = sys.modules.get("kur")
            if kur is None:
                sys.path.insert(0, self.kok_var.get().strip())
                import importlib
                kur = importlib.import_module("kur"); kur.log = self.log
            kur.claude_giris_baslat()
            messagebox.showinfo("Claude girişi",
                "Açılan pencerede/tarayıcıda Anthropic hesabınla giriş yap.\n\n"
                "Bittiğinde bu pencereye dön; panelin USTA sohbeti çalışır hale gelir.\n"
                "(Claude Desktop girişi CLI'ya geçmez — ayrı oturumlardır.)")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Apprentice",
                                 "Giriş başlatılamadı: %s\n\nElle: claude auth login" % e)

    def _panel(self):
        """Web panelini baslat + tarayiciyi ac (konsolsuz)."""
        kok = self.kok_var.get().strip()
        betik = os.path.join(kok, "panel_ac.py")
        if not os.path.isfile(betik):
            messagebox.showwarning("Apprentice", "Once kurulumu tamamla (panel_ac.py bulunamadi).")
            return
        try:
            import kur as _kur
            py = _kur.sistem_python() or sys.executable
            pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
            subprocess.Popen([pyw if os.path.isfile(pyw) else py, betik], cwd=kok,
                             creationflags=0x08000000 if os.name == "nt" else 0,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            self.log("[ok]  Panel baslatildi - tarayici birkac saniye icinde acilir")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Apprentice", "Panel baslatilamadi: %s" % e)

    def _kural(self):
        """Secilen PROJE klasorune usta (denetci) kurallarini yazar: AGENTS.md + Cursor .mdc
        (+ .github varsa Copilot yonlendirmesi). Boylece o projede IDE'nin modeli 'kod yazma
        isini worker_run ile ciraga ver, sen dogrula' seklinde davranir - kullanici her seferinde
        anlatmak zorunda kalmaz."""
        kur = sys.modules.get("kur")
        if kur is None:
            kok = self.kok_var.get().strip()
            if not os.path.isfile(os.path.join(kok, "kur.py")):
                messagebox.showinfo("Apprentice", "Önce 'Kur' ile kurulumu tamamla; sonra bir proje klasörü seçip "
                                    "kural dosyasını ekleyebilirsin.")
                return
            sys.path.insert(0, kok)
            import importlib
            kur = importlib.import_module("kur")
            kur.set_root(kok); kur.log = self.log
        if not messagebox.askokcancel("Bir projeye bağla",
                "Seçeceğin PROJE klasörüne usta (denetçi) kuralları yazılır:\n"
                "  • AGENTS.md — tüm ajanların okuduğu ortak kural\n"
                "  • .cursor/rules/apprentice.mdc — Cursor otomatik uygular\n"
                "  • .github varsa Copilot yönlendirmesi\n\n"
                "Ne işe yarar: o projede IDE'nin modeli (usta) kod yazma işini worker_run ile "
                "ÇIRAĞA verir, kendisi çalıştırarak doğrular. Sen her seferinde bunu anlatmak "
                "zorunda kalmazsın.\n\nDevam edip proje klasörünü seçelim mi?"):
            return
        d = filedialog.askdirectory(title="Kural eklenecek PROJE klasörü (Apprentice kurulumu değil)")
        if not d:
            return
        try:
            kur.kural_yaz(d)
            messagebox.showinfo("Apprentice", "Kural dosyaları yazıldı:\n%s\\AGENTS.md\n%s\\.cursor\\rules\\apprentice.mdc" % (d, d))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Apprentice", str(e))


if __name__ == "__main__":
    app = Sihirbaz()
    oto = os.environ.get("APPRENTICE_SETUP_AUTO")       # sessiz kurulum / test: klasoru ver, kendisi kurar ve kapanir
    if oto:
        app.kok_var.set(oto)
        app._oto = True
        app.after(300, app._baslat)
    app.mainloop()
    sys.exit(0 if getattr(app, "_son_ok", False) else 1)
