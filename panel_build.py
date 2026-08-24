"""Apprentice-Panel.exe (WebView2 kabugu) uret.

    python panel_build.py

Gereksinim (yalnizca gelistirici): .NET SDK 8+ (dotnet). Kullaniciya .NET GEREKMEZ - exe
self-contained tek dosyadir; tek on kosul Windows'ta zaten bulunan Edge WebView2 calisma
zamanidir (yoksa kabuk bunu soyleyip tarayici yoluna dusmeyi onerir).

Cikti: dist/Apprentice-Panel.exe  (~52 MB)
"""
from __future__ import annotations
import os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJE = os.path.join(ROOT, "shell", "ApprenticePanel")
CIKTI = os.path.join(ROOT, "dist", "panel")
PENCERESIZ = 0x08000000 if os.name == "nt" else 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not shutil.which("dotnet"):
        print("dotnet bulunamadi. .NET SDK kur: https://dotnet.microsoft.com/download")
        print("(Kabuk olmadan da sistem calisir: panel Edge/Chrome --app kipinde acilir.)")
        return 1
    if not os.path.isdir(PROJE):
        print("proje yok:", PROJE)
        return 1
    ikon = os.path.join(ROOT, "assets", "apprentice.ico")
    if not os.path.isfile(ikon):
        print("ikon yok:", ikon)
        return 1
    r = subprocess.run(["dotnet", "publish", "-c", "Release", "-o", CIKTI],
                       cwd=PROJE, creationflags=PENCERESIZ)
    if r.returncode:
        return r.returncode
    kaynak = os.path.join(CIKTI, "Apprentice-Panel.exe")
    hedef = os.path.join(ROOT, "dist", "Apprentice-Panel.exe")
    shutil.copy2(kaynak, hedef)
    print("Apprentice-Panel.exe: %.1f MB -> %s" % (os.path.getsize(hedef) / 1e6, hedef))
    return 0


if __name__ == "__main__":
    sys.exit(main())
