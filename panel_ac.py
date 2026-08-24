"""Apprentice Panel baslatici - cift tikla ac, tarayicida panel.

    python panel_ac.py            # panel sunucusunu baslatir + tarayiciyi acar
    pythonw panel_ac.py           # konsolsuz (kisayol bunu kullanir)

Panel zaten calisiyorsa yeni sunucu BASLATMAZ, yalnizca tarayiciyi acar (port yoklanir).
Kurulum bu betige masaustu/baslat kisayolu koyar; kullanici komut satiri bilmek zorunda degil.
"""
from __future__ import annotations
import json, os, socket, subprocess, sys, time, urllib.request, webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
PENCERESIZ = 0x08000000 if os.name == "nt" else 0


def ayakta(port: int) -> bool:
    """Portta BIZIM panel mi? Yalniz HTTP 200'e bakmak yetmez: yabanci bir uygulama
    (SPA dev sunuculari bilinmeyen yola da 200 doner) 'zaten calisiyor' sanilip
    tarayicida ONUN sayfasi aciliyordu. Uc kimligi dogrulanir."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/hazir" % port, timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}").get("hazir") is True
    except Exception:
        return False


def bos_port(baslangic: int = 8788) -> int:
    for p in range(baslangic, baslangic + 12):
        if ayakta(p):
            return p                                  # zaten bizim panel
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p                              # bos
    return baslangic


def native_kabuk(port: int) -> bool:
    """Apprentice-Panel.exe (WebView2 kabugu): gercek uygulama penceresi - kendi ikonu,
    kendi gorev cubugu kimligi, adres cubugu yok. Olculdu: sicak acilis 0.6 sn
    (Edge --app: ~8 sn ilk acilis). Yoksa False doner, cagiran tarayici yoluna duser."""
    for aday in (os.path.join(ROOT, "Apprentice-Panel.exe"),
                 os.path.join(ROOT, "dist", "Apprentice-Panel.exe")):
        if os.path.isfile(aday):
            try:
                subprocess.Popen([aday, "--kok", ROOT, "--port", str(port)], cwd=ROOT,
                                 creationflags=PENCERESIZ, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                continue
    return False


def uygulama_penceresi(url: str) -> bool:
    """Chromium '--app=' kipi: adres cubugu/sekme YOK, kendi ikonuyla ayri pencere -
    tarayici gibi gorunmez, masaustu uygulamasi hissi. Edge/Chrome/Brave denenir.
    Bulunamazsa False doner (cagiran normal tarayiciya duser)."""
    adaylar = []
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        yerel = os.environ.get("LOCALAPPDATA", "")
        adaylar = [os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
                   os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
                   os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
                   os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
                   os.path.join(yerel, "Google", "Chrome", "Application", "chrome.exe"),
                   os.path.join(pf, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")]
    else:
        import shutil as _sh
        adaylar = [p for p in (_sh.which("google-chrome"), _sh.which("chromium"),
                               _sh.which("microsoft-edge"), _sh.which("brave-browser")) if p]
    profil = os.path.join(os.path.expanduser("~"), ".apprentice", "panel_profil")
    for exe in adaylar:
        if not exe or not os.path.isfile(exe):
            continue
        try:
            subprocess.Popen([exe, "--app=" + url, "--window-size=1500,950",
                              "--user-data-dir=" + profil, "--no-first-run",
                              "--no-default-browser-check"],
                             creationflags=PENCERESIZ,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False


def cmd_of(py: str, betik: str, port: int) -> list:
    return [py, betik, "--port", str(port)]


def _hata(mesaj: str):
    """Kisayoldan calisirken konsol yok - hatayi PENCEREYLE goster (sessiz basarisizlik yerine)."""
    sys.stderr.write(mesaj + chr(10))
    try:
        import tkinter, tkinter.messagebox as mb
        r = tkinter.Tk(); r.withdraw(); r.attributes("-topmost", 1)
        mb.showerror("Apprentice Panel", mesaj)
        r.destroy()
    except Exception:
        pass


def main() -> int:
    tarayici_kipi = "--tarayici" in sys.argv        # istege bagli: normal sekmede ac
    port = int(os.environ.get("APPRENTICE_PANEL_PORT") or bos_port())
    if not ayakta(port):
        py = sys.executable
        if py.lower().endswith("pythonw.exe"):        # sunucu icin normal python daha guvenli
            aday = py[:-len("pythonw.exe")] + "python.exe"
            if os.path.isfile(aday):
                py = aday
        betik = os.path.join(ROOT, "clients", "web", "panel.py")
        if not os.path.isfile(betik):
            _hata("Panel dosyasi bulunamadi:\n%s\n\nKurulum eksik olabilir." % betik)
            return 2
        # stderr YAKALANIR: eskiden DEVNULL'a gidiyordu, sunucu hic kalkmasa bile 10 sn
        # beklenip olu URL aciliyordu - kullanici sebebini goremiyordu.
        p = subprocess.Popen(cmd_of(py, betik, port), cwd=ROOT, creationflags=PENCERESIZ,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
        for _ in range(120):                           # ayaga kalkmasini bekle
            time.sleep(0.08)
            if ayakta(port):
                break
            if p.poll() is not None:                   # surec oldu: sebebi goster
                hata = (p.stderr.read() or b"").decode("utf-8", "replace")[-800:]
                _hata("Panel sunucusu baslatilamadi (cikis %s):\n\n%s" % (p.returncode, hata))
                return 1
        else:
            _hata("Panel sunucusu 10 sn icinde cevap vermedi (port %d)." % port)
            return 1
    url = "http://127.0.0.1:%d" % port
    # Sira: native kabuk -> cercevesiz tarayici penceresi -> normal tarayici
    if not tarayici_kipi and native_kabuk(port):
        return 0
    if tarayici_kipi or not uygulama_penceresi(url):
        webbrowser.open(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
