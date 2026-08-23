"""Hapishane oz-testi: modele arac vermeden ONCE kacis denemelerini dogrula.

Bu projede bir kez gercek zarar olustu (Assets/Scripts agaci silindi), o yuzden silme
yetkisi verilmeden once hapishanenin tutugu KANITLANMALI.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # apprentice-unity koku
import unity_sandbox as S

KACISLAR = [
    "../Scripts/PlayerMove.cs",
    "Assets/Scripts/PlayerMove.cs",
    "/etc/passwd",
    "C:/Windows/system32/x.dll",
    "Assets/_ModelSandbox/../Scripts/x.cs",
    "a/../../../Assets/Scripts/x.cs",
    "..\\..\\Scripts\\x.cs",
    "",
    "Assets/_ModelSandboxKotu/x.txt",     # onek benzeri ama farkli klasor
]
GECERLI = ["a.txt", "notlar/b.txt", "Assets/_ModelSandbox/c.txt", "./d.txt",
           "alt/../e.txt", "derin/alt/klasor/f.txt"]


def main():
    print("KACIS DENEMELERI (hepsi reddedilmeli):")
    sizinti = 0
    for k in KACISLAR:
        try:
            r = S._guvenli(k)
            print("   %-40r -> GECTI!! %s   <-- TEHLIKE" % (k, r))
            sizinti += 1
        except S.HapisHatasi:
            print("   %-40r -> reddedildi" % k)

    print()
    print("GECERLI YOLLAR (kabul edilmeli):")
    hata = 0
    for k in GECERLI:
        try:
            print("   %-32r -> %s" % (k, S._guvenli(k)))
        except S.HapisHatasi as e:
            print("   %-32r -> YANLIS REDDEDILDI: %s" % (k, e))
            hata += 1

    print()
    print("yeni_ad yol icermemeli:")
    for ad in ["x.txt", "../x.txt", "alt/x.txt", ""]:
        try:
            S.adlandir_cs("a.txt", ad)
            durum = "kabul" if ad == "x.txt" else "GECTI!! <-- TEHLIKE"
            if ad != "x.txt":
                sizinti += 1
        except S.HapisHatasi:
            durum = "reddedildi"
        print("   %-12r -> %s" % (ad, durum))

    print()
    print("C# katmani da kontrol iceriyor mu:")
    kod = S.sil_cs("a.txt")
    print("   _JAIL_CS gomulu :", "Icerde(" in kod)
    print("   klasor silme kapali:", "klasor silme kapali" in kod)

    print()
    print("SONUC: %d sizinti, %d yanlis red" % (sizinti, hata))
    return 1 if (sizinti or hata) else 0


if __name__ == "__main__":
    raise SystemExit(main())
