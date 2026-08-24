"""Apprentice Panel baslatici - cift tikla ac, tarayicida panel.

    python panel_ac.py            # panel sunucusunu baslatir + tarayiciyi acar
    pythonw panel_ac.py           # konsolsuz (kisayol bunu kullanir)

Panel zaten calisiyorsa yeni sunucu BASLATMAZ, yalnizca tarayiciyi acar (port yoklanir).
Kurulum bu betige masaustu/baslat kisayolu koyar; kullanici komut satiri bilmek zorunda degil.
"""
from __future__ import annotations
import os, socket, subprocess, sys, time, urllib.request, webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
PENCERESIZ = 0x08000000 if os.name == "nt" else 0


def ayakta(port: int) -> bool:
    # ucuz uc: /api/isler sistem yoklamasi yaptigi icin saniyeler suruyordu (olculdu 2.1 sn)
    for uc in ("/api/hazir", "/api/isler"):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, uc), timeout=1.5):
                return True
        except Exception:
            continue
    return False


def bos_port(baslangic: int = 8788) -> int:
    for p in range(baslangic, baslangic + 12):
        if ayakta(p):
            return p                                  # zaten bizim panel
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p                              # bos
    return baslangic


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


def main() -> int:
    tarayici_kipi = "--tarayici" in sys.argv        # istege bagli: normal sekmede ac
    port = int(os.environ.get("APPRENTICE_PANEL_PORT") or bos_port())
    if not ayakta(port):
        py = sys.executable
        if py.lower().endswith("pythonw.exe"):        # sunucu icin normal python daha guvenli
            aday = py[:-len("pythonw.exe")] + "python.exe"
            if os.path.isfile(aday):
                py = aday
        cmd = [py, os.path.join(ROOT, "clients", "web", "panel.py"), "--port", str(port)]
        subprocess.Popen(cmd, cwd=ROOT, creationflags=PENCERESIZ,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        for _ in range(120):                           # ayaga kalkmasini bekle
            time.sleep(0.08)
            if ayakta(port):
                break
    url = "http://127.0.0.1:%d" % port
    if tarayici_kipi or not uygulama_penceresi(url):
        webbrowser.open(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
