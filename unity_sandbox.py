"""Kapali alan dosya islemleri: yeniden adlandirma, tasima, kopyalama, SILME.

NEDEN AYRI MODUL: silme, bu projede bir kez gercek zarar verdi (kullanicinin
Assets/Scripts agaci silindi). Bu yuzden silme yetkisi ana arac setinde YOK ve burada
da yalnizca SANDBOX onekinin altinda calisiyor.

HAPISHANE - iki katmanli, ikisi de bagimsiz:
  1. Python tarafi: her yol normalize edilir ve SANDBOX onekiyle baslamiyorsa C# hic
     uretilmez. '..' , mutlak yol, ters bolu, cift bolu hepsi normalize edilir.
  2. C# tarafi: ayni kontrol Unity icinde TEKRAR yapilir. Python katmani atlansa bile
     (arac cagrisi elle uretilse bile) islem reddedilir.
Iki katman kasten fazlalik: tek kontrol yaziminda bir hata olursa digeri tutar.

UNITY'YE OZGU: dosya islemleri System.IO ile DEGIL AssetDatabase ile yapilir. Aksi
halde .meta dosyalari yetim kalir, referanslar kirilir ve Unity "missing" gosterir.
AssetDatabase.MoveAsset/CopyAsset/RenameAsset/DeleteAsset .meta'yi birlikte tasir.

SILME davranisi: DeleteAsset cop kutusuna DEGIL kalici siler. Bu yuzden silme aracinda
ek bir kural var: silinecek yol tek tek verilmeli, joker/klasor toplu silme YOK.
"""
from __future__ import annotations

import json
import posixpath

SANDBOX = "Assets/_ModelSandbox"


class HapisHatasi(ValueError):
    """Yol sandbox disinda - islem hic uretilmedi."""


def _guvenli(yol: str) -> str:
    """Yolu normalize et ve sandbox icinde oldugunu DOGRULA.

    Reddedilenler: mutlak yol, sandbox disi, '..' ile disari cikma, bos yol.
    Kabul: 'Assets/_ModelSandbox/...' ya da sandbox'a gore goreli ('alt/x.txt')."""
    ham = str(yol or "").strip().replace("\\", "/")
    if not ham:
        raise HapisHatasi("bos yol")
    if ham.startswith("/") or (len(ham) > 1 and ham[1] == ":"):
        raise HapisHatasi("mutlak yol reddedildi: %s" % yol)
    if not ham.startswith("Assets/"):
        ham = posixpath.join(SANDBOX, ham)
    # normpath '..' ve '//' temizler; SONRA kontrol ediyoruz ki 'a/../../x' kacamasin
    duz = posixpath.normpath(ham)
    if duz != SANDBOX and not duz.startswith(SANDBOX + "/"):
        raise HapisHatasi("sandbox disi: %s -> %s (izin verilen kok: %s)"
                          % (yol, duz, SANDBOX))
    return duz


# C# tarafinda TEKRARLANAN kontrol. Python katmani atlansa bile burasi tutar.
_JAIL_CS = """
var KOK = %s;
System.Func<string,bool> Icerde = delegate(string p) {
    if (string.IsNullOrEmpty(p)) return false;
    var d = p.Replace((char)92, (char)47);
    while (d.Contains("//")) d = d.Replace("//", "/");
    if (d.Contains("..")) return false;
    return d == KOK || d.StartsWith(KOK + "/");
};
""" % json.dumps(SANDBOX)


def _cs(govde: str) -> str:
    return _JAIL_CS + "var NL = ((char)10).ToString();\n" + govde


# =====================================================================================
def liste_cs(klasor: str | None = None) -> str:
    kl = _guvenli(klasor) if klasor else SANDBOX
    return _cs("""
var kl = %s;
if (!Icerde(kl)) return "REDDEDILDI (sandbox disi): " + kl;
if (!System.IO.Directory.Exists(kl)) return "KLASOR YOK: " + kl;
var sb = new System.Text.StringBuilder();
sb.Append("klasor=" + kl + NL);
// AssetDatabase.FindAssets DEGIL System.IO: FindAssets yalnizca Unity'nin TANIDIGI
// varlik tiplerini indeksler; .tmp gibi uzantilar diskte var olsa bile listede
// gorunmez. Model goremedigi dosyayi yonetemez, o yuzden diskin gercegini gosteriyoruz.
// .meta dosyalari gizlenir - onlar Unity'nin defteri, kullanicinin dosyasi degil.
var klasorler = System.IO.Directory.GetDirectories(kl, "*", System.IO.SearchOption.AllDirectories);
System.Array.Sort(klasorler);
foreach (var k in klasorler) sb.Append("[klasor] " + k.Replace((char)92, (char)47) + NL);
var dosyalar = System.IO.Directory.GetFiles(kl, "*", System.IO.SearchOption.AllDirectories);
System.Array.Sort(dosyalar);
int n = 0;
foreach (var f in dosyalar) {
    if (f.EndsWith(".meta")) continue;
    var y = f.Replace((char)92, (char)47);
    var varlikMi = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(y) != null;
    sb.Append("         " + y + (varlikMi ? "" : "  (Unity varligi degil)") + NL);
    n++;
}
sb.Append("toplam dosya=" + n + "  klasor=" + klasorler.Length + NL);
return sb.ToString();
""" % json.dumps(kl))


def olustur_cs(yol: str, icerik: str) -> str:
    y = _guvenli(yol)
    return _cs("""
var y = %s; var ic = %s;
if (!Icerde(y)) return "REDDEDILDI (sandbox disi): " + y;
var kl = System.IO.Path.GetDirectoryName(y).Replace((char)92, (char)47);
if (!UnityEditor.AssetDatabase.IsValidFolder(kl)) {
    var parcalar = kl.Split((char)47);
    var birikim = parcalar[0];
    for (int i = 1; i < parcalar.Length; i++) {
        var sonraki = birikim + "/" + parcalar[i];
        if (!UnityEditor.AssetDatabase.IsValidFolder(sonraki))
            UnityEditor.AssetDatabase.CreateFolder(birikim, parcalar[i]);
        birikim = sonraki;
    }
}
if (System.IO.File.Exists(y)) return "ZATEN VAR: " + y;
System.IO.File.WriteAllText(y, ic);
UnityEditor.AssetDatabase.ImportAsset(y);
return "OLUSTURULDU: " + y;
""" % (json.dumps(y), json.dumps(icerik)))


def adlandir_cs(yol: str, yeni_ad: str) -> str:
    y = _guvenli(yol)
    ad = str(yeni_ad or "").strip()
    if "/" in ad or "\\" in ad or not ad:
        raise HapisHatasi("yeni ad yol icermemeli, yalnizca dosya adi: %r" % yeni_ad)
    return _cs("""
var y = %s; var ad = %s;
if (!Icerde(y)) return "REDDEDILDI (sandbox disi): " + y;
// Diskte var mi diye bak; AssetDatabase tanimayan uzantilarda (.tmp) LoadAssetAtPath
// null doner ve "kaynak yok" yanilgisi olusur.
if (!System.IO.File.Exists(y) && !UnityEditor.AssetDatabase.IsValidFolder(y))
    return "KAYNAK YOK: " + y;
if (UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(y) == null
    && !UnityEditor.AssetDatabase.IsValidFolder(y))
    return "BU DOSYA UNITY VARLIGI DEGIL (" + y + "); RenameAsset calismaz. "
           + "Once .txt gibi taninan bir uzantiya cevrilmeli ya da silinmeli.";
var hata = UnityEditor.AssetDatabase.RenameAsset(y, ad);
if (!string.IsNullOrEmpty(hata)) return "BASARISIZ: " + hata;
UnityEditor.AssetDatabase.SaveAssets();
var kl = System.IO.Path.GetDirectoryName(y).Replace((char)92, (char)47);
var uzanti = System.IO.Path.GetExtension(y);
var yeni = kl + "/" + ad + (ad.Contains(".") ? "" : uzanti);
return "ADLANDIRILDI: " + y + "  ->  " + yeni;
""" % (json.dumps(y), json.dumps(ad)))


def tasi_cs(yol: str, hedef_klasor: str) -> str:
    y = _guvenli(yol)
    h = _guvenli(hedef_klasor)
    return _cs("""
var y = %s; var h = %s;
if (!Icerde(y) || !Icerde(h)) return "REDDEDILDI (sandbox disi)";
if (!UnityEditor.AssetDatabase.IsValidFolder(h)) {
    var parcalar = h.Split((char)47);
    var birikim = parcalar[0];
    for (int i = 1; i < parcalar.Length; i++) {
        var sonraki = birikim + "/" + parcalar[i];
        if (!UnityEditor.AssetDatabase.IsValidFolder(sonraki))
            UnityEditor.AssetDatabase.CreateFolder(birikim, parcalar[i]);
        birikim = sonraki;
    }
}
var hedefYol = h + "/" + System.IO.Path.GetFileName(y);
if (!Icerde(hedefYol)) return "REDDEDILDI (hedef sandbox disi): " + hedefYol;
var hata = UnityEditor.AssetDatabase.MoveAsset(y, hedefYol);
if (!string.IsNullOrEmpty(hata)) return "BASARISIZ: " + hata;
UnityEditor.AssetDatabase.SaveAssets();
return "TASINDI: " + y + "  ->  " + hedefYol;
""" % (json.dumps(y), json.dumps(h)))


def kopyala_cs(yol: str, hedef_yol: str) -> str:
    y = _guvenli(yol)
    h = _guvenli(hedef_yol)
    return _cs("""
var y = %s; var h = %s;
if (!Icerde(y) || !Icerde(h)) return "REDDEDILDI (sandbox disi)";
if (System.IO.File.Exists(h)) return "HEDEF ZATEN VAR: " + h;
if (!System.IO.File.Exists(y)) return "KAYNAK YOK: " + y;
var kl = System.IO.Path.GetDirectoryName(h).Replace((char)92, (char)47);
if (!UnityEditor.AssetDatabase.IsValidFolder(kl)) {
    var parcalar = kl.Split((char)47);
    var birikim = parcalar[0];
    for (int i = 1; i < parcalar.Length; i++) {
        var sonraki = birikim + "/" + parcalar[i];
        if (!UnityEditor.AssetDatabase.IsValidFolder(sonraki))
            UnityEditor.AssetDatabase.CreateFolder(birikim, parcalar[i]);
        birikim = sonraki;
    }
}
if (!UnityEditor.AssetDatabase.CopyAsset(y, h)) return "BASARISIZ: kopyalanamadi";
UnityEditor.AssetDatabase.SaveAssets();
return "KOPYALANDI: " + y + "  ->  " + h;
""" % (json.dumps(y), json.dumps(h)))


def sil_cs(yol: str) -> str:
    """TEK dosya siler. Klasor silme ve joker YOK - toplu silme bu projede zarar verdi."""
    y = _guvenli(yol)
    return _cs("""
var y = %s;
if (!Icerde(y)) return "REDDEDILDI (sandbox disi): " + y;
if (UnityEditor.AssetDatabase.IsValidFolder(y))
    return "REDDEDILDI: klasor silme kapali, tek tek dosya sil";
// Varlik olup olmadigina DEGIL, diskte olup olmadigina bak. Ilk surum
// LoadAssetAtPath null donunce "ZATEN YOK" diyordu; .tmp gibi Unity'nin tanimadigi
// uzantilar diskte dururken "yok" raporlaniyordu. Arac gercek durumu bildirmeli.
if (!System.IO.File.Exists(y)) return "ZATEN YOK: " + y;
var varlikMi = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(y) != null;
if (varlikMi) {
    if (!UnityEditor.AssetDatabase.DeleteAsset(y)) return "BASARISIZ: " + y;
} else {
    // Unity varligi degil: System.IO ile sil, varsa .meta'sini da temizle
    System.IO.File.Delete(y);
    if (System.IO.File.Exists(y + ".meta")) System.IO.File.Delete(y + ".meta");
    UnityEditor.AssetDatabase.Refresh();
}
UnityEditor.AssetDatabase.SaveAssets();
if (System.IO.File.Exists(y)) return "BASARISIZ (dosya hala duruyor): " + y;
return "SILINDI: " + y + (varlikMi ? "" : "  (Unity varligi degildi, dosya sistemi ile)");
""" % json.dumps(y))


# =====================================================================================
def tanimlar():
    kok = SANDBOX
    return [
        {"type": "function", "function": {
            "name": "sb_list",
            "description": "Kapali alandaki (%s) dosya ve klasorleri listeler." % kok,
            "parameters": {"type": "object", "properties": {
                "klasor": {"type": "string", "description": "alt klasor (bos = kok)"}},
                "required": []}}},
        {"type": "function", "function": {
            "name": "sb_create",
            "description": "Kapali alanda yeni metin dosyasi olusturur. Klasor yoksa acar.",
            "parameters": {"type": "object", "properties": {
                "yol": {"type": "string", "description": "orn 'notlar/a.txt'"},
                "icerik": {"type": "string", "description": "dosya icerigi"}},
                "required": ["yol", "icerik"]}}},
        {"type": "function", "function": {
            "name": "sb_rename",
            "description": "Dosyayi YENIDEN ADLANDIRIR (ayni klasorde kalir). "
                           "yeni_ad yol icermez, yalnizca dosya adi.",
            "parameters": {"type": "object", "properties": {
                "yol": {"type": "string", "description": "mevcut yol"},
                "yeni_ad": {"type": "string", "description": "yeni dosya adi"}},
                "required": ["yol", "yeni_ad"]}}},
        {"type": "function", "function": {
            "name": "sb_move",
            "description": "Dosyayi baska bir klasore TASIR (adi degismez). Hedef klasor "
                           "yoksa olusturulur.",
            "parameters": {"type": "object", "properties": {
                "yol": {"type": "string", "description": "mevcut yol"},
                "hedef_klasor": {"type": "string", "description": "hedef klasor"}},
                "required": ["yol", "hedef_klasor"]}}},
        {"type": "function", "function": {
            "name": "sb_copy",
            "description": "Dosyayi KOPYALAR (orijinal kalir). Hedef zaten varsa reddeder.",
            "parameters": {"type": "object", "properties": {
                "yol": {"type": "string", "description": "kaynak yol"},
                "hedef_yol": {"type": "string", "description": "kopyanin tam yolu"}},
                "required": ["yol", "hedef_yol"]}}},
        {"type": "function", "function": {
            "name": "sb_delete",
            "description": "TEK bir dosyayi KALICI siler (geri alinamaz). Klasor silme "
                           "ve toplu silme KAPALI - her dosyayi ayri ayri sil.",
            "parameters": {"type": "object", "properties": {
                "yol": {"type": "string", "description": "silinecek dosyanin yolu"}},
                "required": ["yol"]}}},
    ]
