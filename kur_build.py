"""Apprentice-Setup.exe uret: depo dosyalarini payload.zip'e koyar, PyInstaller ile paketler.

    python kur_build.py            # dist/Apprentice-Setup.exe
Gereksinim (yalnizca gelistirici): pip install pyinstaller. Kullaniciya hicbir sey gerekmez.
Pakete giren: git'in izledigi dosyalar (dist/build/runtime haric) - yani kullanici depoyu
ayrica indirmez; exe her yerden calisir.
"""
from __future__ import annotations
import os, subprocess, sys, zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
BUILD = os.path.join(ROOT, "build")
os.makedirs(BUILD, exist_ok=True)
payload = os.path.join(BUILD, "payload.zip")

dosyalar = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
dosyalar = [d for d in dosyalar if d and os.path.isfile(d) and not d.startswith(("dist/", "build/", "runtime/"))]
with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as z:
    for d in dosyalar:
        z.write(d, d)
    # WebView2 kabugu (varsa): kurulum klasorune acilir, kisayol dogrudan onu gosterir.
    # Yoksa sistem yine calisir - panel Edge/Chrome --app kipinde acilir.
    kabuk = os.path.join(ROOT, "dist", "Apprentice-Panel.exe")
    if os.path.isfile(kabuk):
        z.write(kabuk, "Apprentice-Panel.exe")
        print("  + Apprentice-Panel.exe (WebView2 kabugu, %.0f MB)" % (os.path.getsize(kabuk) / 1e6))
print("payload.zip: %d dosya, %.1f MB" % (len(dosyalar), os.path.getsize(payload) / 1e6))

sep = ";" if os.name == "nt" else ":"
cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--windowed", "--name", "Apprentice-Setup",
       "--add-data", payload + sep + ".",
       "--exclude-module", "core", "--exclude-module", "tests", "--exclude-module", "test_server",
       "--exclude-module", "kur",
       # kur.py ve core/config.py exe DISINDA (kurulum klasorunden yuklenir); onlarin stdlib
       # bagimliliklari analiz edilmez, burada acikca paketlenir.
       "--hidden-import", "platform", "--hidden-import", "argparse", "--hidden-import", "urllib.request",
       "--hidden-import", "urllib.error", "--hidden-import", "zipfile", "--hidden-import", "io",
       "--hidden-import", "subprocess", "--hidden-import", "shutil", "--hidden-import", "json",
       "--hidden-import", "importlib", "--hidden-import", "traceback", "--hidden-import", "time",
       "--distpath", os.path.join(ROOT, "dist"), "--workpath", BUILD, "--specpath", BUILD,
       os.path.join(ROOT, "kur_gui.py")]
r = subprocess.run(cmd)
sys.exit(r.returncode)
