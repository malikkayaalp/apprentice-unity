"""Proje varliklarini ve derin hiyerarsiyi gormek + Inspector'a yazmak icin araclar.

NEDEN: unity_code.py'nin araclari sahneyi yuzeysel okuyup yalnizca DOSYAYA yazabiliyordu.
Kullanicinin tarif ettigi is akisi (bir Crowd objesinin altindaki onlarca karakteri
bulup, Assets/Animation'daki klipleri onlara dagitmak, materyal uretip renk vermek,
sahnedeki bir listeyi referanslarla doldurmak) uc yetenek daha istiyor:

  1. VARLIK GORME    Assets altinda ne var? (klip, materyal, texture, controller)
  2. DERIN HIYERARSI Bir kokun altindaki TUM torunlar ve bilesenleri
  3. INSPECTOR YAZMA Alan degeri, obje referansi ve DIZI doldurma

GUVENLIK CIZGISI - kapsam degil, geri alinabilirlik uzerine kurulu:
  * Silme araci YOK. ("tasi -> sil" reflexi dort testte gorildi; bir kez de bu
    projede Assets/Scripts agaci silindi.)
  * Her yazma Undo.RecordObject ile kaydedilir -> Ctrl+Z calisir.
  * Uzerine yazilan ESKI deger raporlanir; sessiz ezme yok.
  * Olmayan obje/bilesen/alan -> islem yapilmaz, acik hata doner.
  * Tip uyusmazliginda reddedilir (Transform alanina Material atanamaz).

Transform, kamera, isik dahil her seye yazabilir: kullanici bunlari kisit olarak
degil genel cerceve olarak tarif etti; bazi islerde transform yazmak gerekiyor.
"""
from __future__ import annotations

import json

# --- yardimci C# ---------------------------------------------------------------------
# Bu blok her cagriya onek olarak eklenir. Newline'lar (char)10 ile uretiliyor:
# Python -> JSON -> C# yolculugunda "\n" gercek satir sonuna donusup string sabitini
# bozuyor ("Newline in constant"). Bu ders bu projede iki kez odendi.
# Yardimci lambdalarin ICINDEKI degisken adlari kasten "__" onekli. Sebep: C#, dis
# kapsamda IC kapsamda kullanilmis bir adi yeniden tanimlamaya izin vermiyor
# ("cannot be declared in this scope because it would give a different meaning").
# Ilk surumde lambdalar g/t/c kullaniyordu ve govdedeki "var g = Bul(...)" satiri
# derlenmedi; okuma araclari tesadufen bu adlari kullanmadigi icin calisiyordu.
YARDIMCI = """
var NL = ((char)10).ToString();
System.Func<GameObject,string> Yol = null;
Yol = delegate(GameObject __g) {
    var __s = __g.name; var __p = __g.transform.parent;
    while (__p != null) { __s = __p.name + "/" + __s; __p = __p.parent; }
    return __s;
};
System.Func<string,GameObject> Bul = delegate(string __ad) {
    var __d = GameObject.Find(__ad);
    if (__d != null) return __d;
    // MCP for Unity'nin compat sarmalayicisi: FindObjectsByType imzasi 6.5'te
    // degisiyor (sort parametresi kalkti); surum kapisini paket tasisin.
    foreach (GameObject __o in MCPForUnity.Runtime.Helpers.UnityFindObjectsCompat
                 .FindAll(typeof(GameObject), true))
        if (__o.name == __ad || Yol(__o) == __ad) return __o;
    return null;
};
System.Func<GameObject,string,Component> BilesenBul = delegate(GameObject __g, string __tip) {
    foreach (var __c in __g.GetComponents<Component>()) {
        if (__c == null) continue;
        var __t = __c.GetType();
        if (__t.Name == __tip || __t.FullName == __tip) return __c;
    }
    return null;
};
"""


def _cs(govde):
    return YARDIMCI + govde


# =====================================================================================
# OKUMA
# =====================================================================================
def list_assets_cs(filtre, klasor, limit):
    """Varlik arama. Klasor listesi C# dizi baslaticisi olarak uretilir.

    Ilk surum json.dumps(["Assets/Art"]) kullaniyordu; bu JSON sozdizimi C#'ta
    derlenmedi (Unity'nin CodeDom derleyicisi koleksiyon ifadesini kabul etmiyor).
    Dogrusu: new string[]{"Assets/Art"}."""
    kls = "new string[]{%s}" % json.dumps(klasor) if klasor else "null"
    return _cs("""
var sb = new System.Text.StringBuilder();
string[] klasorler = KLASORLER;
var idler = UnityEditor.AssetDatabase.FindAssets(FILTRE, klasorler);
sb.Append("bulunan=" + idler.Length + NL);
int n = 0;
foreach (var id in idler) {
    if (n++ >= LIMIT) { sb.Append("... (" + (idler.Length - LIMIT) + " tane daha)" + NL); break; }
    var yol = UnityEditor.AssetDatabase.GUIDToAssetPath(id);
    var tip = UnityEditor.AssetDatabase.GetMainAssetTypeAtPath(yol);
    sb.Append(yol + "  [" + (tip != null ? tip.Name : "?") + "]" + NL);
}
return sb.ToString();
""".replace("KLASORLER", kls).replace("FILTRE", json.dumps(filtre))
   .replace("LIMIT", str(int(limit))))


def inspect_asset_cs(yol):
    return _cs("""
var yol = %s;
var o = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(yol);
if (o == null) return "BULUNAMADI: " + yol;
var sb = new System.Text.StringBuilder();
sb.Append("yol=" + yol + NL + "tip=" + o.GetType().Name + NL + "ad=" + o.name + NL);
var klip = o as AnimationClip;
if (klip != null) {
    sb.Append("sure=" + klip.length.ToString("F2") + "s  fps=" + klip.frameRate
              + "  dongu=" + klip.isLooping + "  humanoid=" + klip.humanMotion + NL);
}
var mat = o as Material;
if (mat != null) {
    sb.Append("shader=" + (mat.shader != null ? mat.shader.name : "?") + NL);
    if (mat.HasProperty("_BaseColor")) sb.Append("_BaseColor=" + mat.GetColor("_BaseColor") + NL);
    else if (mat.HasProperty("_Color")) sb.Append("_Color=" + mat.GetColor("_Color") + NL);
    foreach (var pn in new string[]{"_BaseMap","_MainTex"}) {
        if (mat.HasProperty(pn)) {
            var t = mat.GetTexture(pn);
            sb.Append(pn + "=" + (t != null ? UnityEditor.AssetDatabase.GetAssetPath(t) : "<bos>") + NL);
        }
    }
}
var tex = o as Texture;
if (tex != null) sb.Append("boyut=" + tex.width + "x" + tex.height + NL);
var go = o as GameObject;
if (go != null) {
    sb.Append("bilesenler:");
    foreach (var c in go.GetComponentsInChildren<Component>(true))
        if (c != null) sb.Append(" " + c.GetType().Name);
    sb.Append(NL);
}
return sb.ToString();
""" % json.dumps(yol))


def hierarchy_cs(kok, derinlik, limit):
    return _cs("""
var kokAd = %s;
var sb = new System.Text.StringBuilder();
var kok = string.IsNullOrEmpty(kokAd) ? null : Bul(kokAd);
if (!string.IsNullOrEmpty(kokAd) && kok == null) return "BULUNAMADI: " + kokAd;
int sayac = 0; int maks = %d; int maksDerinlik = %d;
System.Action<Transform,int> yaz = null;
yaz = delegate(Transform t, int d) {
    if (sayac >= maks || d > maksDerinlik) return;
    sayac++;
    var g = t.gameObject;
    sb.Append(new string(' ', d * 2) + g.name);
    var bl = new System.Collections.Generic.List<string>();
    foreach (var c in g.GetComponents<Component>())
        bl.Add(c == null ? "<EKSIK SCRIPT>" : c.GetType().Name);
    if (bl.Count > 1) sb.Append("  [" + string.Join(", ", bl.ToArray()) + "]");
    if (!g.activeSelf) sb.Append("  (pasif)");
    // Renderer'in KULLANDIGI materyal yollari. Bunlar olmadan model bir objeye
    // materyal yazabiliyor ama hangi materyalin uzerinde oldugunu goremiyordu;
    // texture atama gorevinde tam bu yuzden takildi ve adim butcesini tuketti.
    var rnd = g.GetComponent<Renderer>();
    if (rnd != null) {
        var mats = rnd.sharedMaterials;
        sb.Append("  materyal:");
        if (mats == null || mats.Length == 0) sb.Append(" <yok>");
        foreach (var mm in mats) {
            if (mm == null) { sb.Append(" <bos>"); continue; }
            var mp = UnityEditor.AssetDatabase.GetAssetPath(mm);
            sb.Append(" " + (string.IsNullOrEmpty(mp) ? mm.name + "(gomulu)" : mp));
        }
    }
    sb.Append(NL);
    foreach (Transform c in t) yaz(c, d + 1);
};
if (kok != null) yaz(kok.transform, 0);
else foreach (var g in UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects()) yaz(g.transform, 0);
if (sayac >= maks) sb.Append("... (sinir " + maks + " objede kesildi)" + NL);
sb.Append("toplam gosterilen=" + sayac + NL);
return sb.ToString();
""" % (json.dumps(kok or ""), limit, derinlik))


# =====================================================================================
# YAZMA - hepsi Undo kaydeder ve eski degeri raporlar
# =====================================================================================
def add_component_cs(obje, tip):
    return _cs("""
var g = Bul(%s);
if (g == null) return "OBJE YOK: " + %s;
var tipAd = %s;
System.Type t = null;
foreach (var a in System.AppDomain.CurrentDomain.GetAssemblies()) {
    t = a.GetType(tipAd);
    if (t == null) t = a.GetType("UnityEngine." + tipAd);
    if (t != null) break;
}
if (t == null) return "TIP YOK: " + tipAd;
if (!typeof(Component).IsAssignableFrom(t)) return "BILESEN DEGIL: " + tipAd;
var mevcut = g.GetComponent(t);
if (mevcut != null) return "ZATEN VAR: " + Yol(g) + " -> " + t.Name;
UnityEditor.Undo.AddComponent(g, t);
UnityEditor.EditorUtility.SetDirty(g);
return "EKLENDI: " + Yol(g) + " -> " + t.Name;
""" % (json.dumps(obje), json.dumps(obje), json.dumps(tip)))


def remove_missing_cs(obje):
    """YALNIZCA kirik (script'i kayip, 'Missing Script') bilesenleri kaldirir.

    Neden var (olculdu, Cursor denetci deneyi): isci bir yardimci scripti "silmek" icin
    dosyayi bosaltti; sinif kaybolunca objede kirik bilesen kaldi, 'The referenced script
    is missing' hatasi cikti ve isci bunu 16 kez dosya yazarak duzeltmeye calisti.
    Saglam hicbir bileseni kaldiramaz: Unity'nin kendi RemoveMonoBehavioursWithMissingScript'i."""
    return _cs("""
var g = Bul(%s);
if (g == null) return "OBJE YOK: " + %s;
int n = UnityEditor.GameObjectUtility.RemoveMonoBehavioursWithMissingScript(g);
UnityEditor.EditorUtility.SetDirty(g);
return "KALDIRILDI: " + n + " kirik bilesen (" + Yol(g) + ")";
""" % (json.dumps(obje), json.dumps(obje)))


def set_field_cs(obje, bilesen, alan, deger_json):
    """SerializedProperty ile alan yaz: sayi, bool, string, Vector3, obje referansi,
    ve obje referansi DIZISI. Eski deger raporlanir, Undo kaydedilir."""
    return _cs("""
var g = Bul(%s);
if (g == null) return "OBJE YOK: " + %s;
var c = BilesenBul(g, %s);
if (c == null) return "BILESEN YOK: " + %s + " -> " + %s;
var so = new UnityEditor.SerializedObject(c);
var alanAd = %s;
var p = so.FindProperty(alanAd);
if (p == null) p = so.FindProperty("_" + alanAd);
if (p == null) p = so.FindProperty("m_" + alanAd);
if (p == null) {
    var mv = new System.Text.StringBuilder("ALAN YOK: " + alanAd + " | mevcut alanlar:");
    var it = so.GetIterator();
    while (it.NextVisible(true)) if (it.depth == 0 && it.name != "m_Script") mv.Append(" " + it.name);
    return mv.ToString();
}
var ham = %s;
var eski = "";
UnityEditor.Undo.RecordObject(c, "set_field " + alanAd);

if (p.isArray && p.propertyType != UnityEditor.SerializedPropertyType.String) {
    eski = "dizi[" + p.arraySize + "]";
    var parcalar = ham.Split('\\u0001');
    p.arraySize = parcalar.Length;
    for (int i = 0; i < parcalar.Length; i++) {
        var hedef = Bul(parcalar[i]);
        UnityEngine.Object deger = null;
        if (hedef != null) {
            var el0 = p.GetArrayElementAtIndex(i);
            // Dizi elemani Transform mu GameObject mi bekliyor: mevcut tipe bak
            deger = hedef;
            if (el0.type != null && el0.type.Contains("Transform")) deger = hedef.transform;
        } else {
            deger = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(parcalar[i]);
        }
        if (deger == null) return "DIZI ELEMANI BULUNAMADI: " + parcalar[i];
        p.GetArrayElementAtIndex(i).objectReferenceValue = deger;
    }
    so.ApplyModifiedProperties();
    UnityEditor.EditorUtility.SetDirty(c);
    return "YAZILDI dizi: " + Yol(g) + "." + %s + "." + alanAd
           + "  eski=" + eski + "  yeni=dizi[" + p.arraySize + "]";
}

switch (p.propertyType) {
  case UnityEditor.SerializedPropertyType.Integer:
      eski = p.intValue.ToString(); p.intValue = int.Parse(ham); break;
  case UnityEditor.SerializedPropertyType.Float:
      eski = p.floatValue.ToString("F3");
      p.floatValue = float.Parse(ham, System.Globalization.CultureInfo.InvariantCulture); break;
  case UnityEditor.SerializedPropertyType.Boolean:
      eski = p.boolValue.ToString(); p.boolValue = (ham == "true" || ham == "1"); break;
  case UnityEditor.SerializedPropertyType.String:
      eski = p.stringValue; p.stringValue = ham; break;
  case UnityEditor.SerializedPropertyType.Color: {
      eski = p.colorValue.ToString();
      Color renk;
      if (!ColorUtility.TryParseHtmlString(ham, out renk)) {
          var q = ham.Split(',');
          renk = new Color(float.Parse(q[0], System.Globalization.CultureInfo.InvariantCulture),
                           float.Parse(q[1], System.Globalization.CultureInfo.InvariantCulture),
                           float.Parse(q[2], System.Globalization.CultureInfo.InvariantCulture),
                           q.Length > 3 ? float.Parse(q[3], System.Globalization.CultureInfo.InvariantCulture) : 1f);
      }
      p.colorValue = renk; break; }
  case UnityEditor.SerializedPropertyType.Vector3: {
      eski = p.vector3Value.ToString("F2");
      var q = ham.Split(',');
      p.vector3Value = new Vector3(
          float.Parse(q[0], System.Globalization.CultureInfo.InvariantCulture),
          float.Parse(q[1], System.Globalization.CultureInfo.InvariantCulture),
          float.Parse(q[2], System.Globalization.CultureInfo.InvariantCulture)); break; }
  case UnityEditor.SerializedPropertyType.ObjectReference: {
      var o = p.objectReferenceValue;
      eski = (o == null ? "<bos>" : o.name);
      UnityEngine.Object yeni = null;
      var hedef = Bul(ham);
      if (hedef != null) {
          yeni = hedef;
          if (p.type != null && p.type.Contains("Transform")) yeni = hedef.transform;
          else if (p.type != null && !p.type.Contains("GameObject")) {
              var bl = BilesenBul(hedef, p.type.Replace("PPtr<$", "").Replace(">", ""));
              if (bl != null) yeni = bl;
          }
      } else {
          yeni = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(ham);
      }
      if (yeni == null) return "HEDEF BULUNAMADI: " + ham;
      p.objectReferenceValue = yeni; break; }
  default:
      return "DESTEKLENMEYEN TIP: " + p.propertyType + " (alan " + alanAd + ")";
}
so.ApplyModifiedProperties();
UnityEditor.EditorUtility.SetDirty(c);
return "YAZILDI: " + Yol(g) + "." + %s + "." + alanAd + "  eski=" + eski + "  yeni=" + ham;
""" % (json.dumps(obje), json.dumps(obje), json.dumps(bilesen), json.dumps(obje),
       json.dumps(bilesen), json.dumps(alan), json.dumps(deger_json),
       json.dumps(bilesen), json.dumps(bilesen)))


SHADER_BUL = """
// Shader.Find yalnizca YUKLU shader'lari bulur. Bulunamazsa projedeki TUM shader
// adlarindan benzerleri dondurulur ki model ad uydurmak yerine listeden secsin
// (set_field/set_material'daki "yanlista listele" deseninin shader hali).
System.Func<string, Shader> ShaderBul = delegate(string __ad) {
    if (string.IsNullOrEmpty(__ad)) return null;
    return Shader.Find(__ad);
};
System.Func<string, string> ShaderOner = delegate(string __ad) {
    var __sb = new System.Text.StringBuilder();
    var __k = (__ad ?? "").ToLowerInvariant().Replace("shaders/", "");
    int __n = 0;
    foreach (var __si in UnityEditor.ShaderUtil.GetAllShaderInfo()) {
        var __l = __si.name.ToLowerInvariant();
        if (__l.StartsWith("hidden/")) continue;
        bool __benzer = __l.Contains(__k) || __k.Contains(__l) ||
                        (__k.Contains("standard") && __l.StartsWith("standard")) ||
                        (__k.Contains("lit") && __l.EndsWith("/lit"));
        if (!__benzer) continue;
        if (__n++ > 0) __sb.Append(", ");
        __sb.Append(__si.name);
        if (__n >= 12) break;
    }
    return __n == 0 ? "(benzer yok; orn 'Standard', 'Universal Render Pipeline/Lit', 'Unlit/Color')"
                    : __sb.ToString();
};
"""


def create_asset_cs(tur, yol, ozellik_json, shader=""):
    return _cs(SHADER_BUL + """
var tur = %s; var yol = %s; var oz = %s; var shAdi = %s;
var klasor = System.IO.Path.GetDirectoryName(yol).Replace("\\\\", "/");
if (!UnityEditor.AssetDatabase.IsValidFolder(klasor)) {
    var parcalar = klasor.Split('/');
    var birikim = parcalar[0];
    for (int i = 1; i < parcalar.Length; i++) {
        var sonraki = birikim + "/" + parcalar[i];
        if (!UnityEditor.AssetDatabase.IsValidFolder(sonraki))
            UnityEditor.AssetDatabase.CreateFolder(birikim, parcalar[i]);
        birikim = sonraki;
    }
}
if (UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(yol) != null)
    return "ZATEN VAR: " + yol;
if (tur == "Material") {
    // Shader.Find yalnizca YUKLU shader'lari bulur; URP projesinde bile bazen
    // null doner ve Standard'a duseriz. Hangisi kullanildigi RAPORLANIR, cunku
    // ozellik adlari shader'a gore degisiyor (_BaseMap vs _MainTex).
    Shader sh = null;
    if (!string.IsNullOrEmpty(shAdi)) {
        sh = ShaderBul(shAdi);
        if (sh == null) return "SHADER BULUNAMADI: " + shAdi + " | benzerler: " + ShaderOner(shAdi);
    } else {
        sh = Shader.Find("Universal Render Pipeline/Lit");
        if (sh == null) sh = Shader.Find("Lit");
        if (sh == null) sh = Shader.Find("Standard");
        if (sh == null) return "SHADER BULUNAMADI (URP Lit / Standard)";
    }
    var m = new Material(sh);
    if (!string.IsNullOrEmpty(oz)) {
        Color renk;
        if (ColorUtility.TryParseHtmlString(oz, out renk)) {
            if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", renk);
            if (m.HasProperty("_Color")) m.SetColor("_Color", renk);
        }
    }
    UnityEditor.AssetDatabase.CreateAsset(m, yol);
} else if (tur == "AnimatorController") {
    UnityEditor.Animations.AnimatorController.CreateAnimatorControllerAtPath(yol);
} else {
    return "DESTEKLENMEYEN TUR: " + tur + " (Material, AnimatorController)";
}
UnityEditor.AssetDatabase.SaveAssets();
UnityEditor.AssetDatabase.Refresh();
var son = UnityEditor.AssetDatabase.LoadAssetAtPath<Material>(yol);
var shAd = (son != null && son.shader != null) ? son.shader.name : "-";
return "OLUSTURULDU: " + yol + (tur == "Material" ? "  shader=" + shAd : "");
""" % (json.dumps(tur), json.dumps(yol), json.dumps(ozellik_json or ""),
       json.dumps(shader or "")))


# =====================================================================================
# ANIMATOR
# =====================================================================================
# Kalabalik senaryosunun dogru Unity cozumu: TEK temel controller + her karakter icin
# hafif bir AnimatorOverrideController. Yuzlerce ayri controller uretmek yerine yalnizca
# klipler override edilir. Karakter basina zamanlama farki iki yerden gelir:
#   - state.cycleOffset  (controller icinde, override ile karakter basina degistirilemez)
#   - Animator.Play(state, layer, normalizedTime)  (calisma aninda, karakter basina)
# Ikincisi Crowd uzerindeki yonetici script'in isi; buradaki araclar birinciyi kurar.

def list_animator_states_cs(controller):
    return _cs("""
var yol = %s;
var ac = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEditor.Animations.AnimatorController>(yol);
if (ac == null) {
    var ovr = UnityEditor.AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(yol);
    if (ovr == null) return "CONTROLLER YOK: " + yol;
    var sbo = new System.Text.StringBuilder();
    sbo.Append("override controller, temel=" +
               (ovr.runtimeAnimatorController != null ? ovr.runtimeAnimatorController.name : "?") + NL);
    var lst = new System.Collections.Generic.List<
        System.Collections.Generic.KeyValuePair<AnimationClip, AnimationClip>>();
    ovr.GetOverrides(lst);
    foreach (var kv in lst)
        sbo.Append("  " + (kv.Key != null ? kv.Key.name : "?") + " -> " +
                   (kv.Value != null ? kv.Value.name : "<override yok>") + NL);
    return sbo.ToString();
}
var sb = new System.Text.StringBuilder();
sb.Append("controller=" + yol + "  katman=" + ac.layers.Length + NL);
foreach (var lay in ac.layers) {
    sb.Append("katman: " + lay.name + NL);
    var sm = lay.stateMachine;
    foreach (var cs in sm.states) {
        var st = cs.state;
        sb.Append("  state: " + st.name);
        sb.Append("  klip=" + (st.motion != null ? st.motion.name : "<yok>"));
        sb.Append("  hiz=" + st.speed.ToString("F2"));
        sb.Append("  ofset=" + st.cycleOffset.ToString("F2"));
        if (sm.defaultState == st) sb.Append("  [VARSAYILAN]");
        sb.Append(NL);
    }
    foreach (var par in ac.parameters)
        sb.Append("  parametre: " + par.name + " (" + par.type + ")" + NL);
}
return sb.ToString();
""" % json.dumps(controller))


def add_animator_state_cs(controller, state, klip, varsayilan, hiz, ofset):
    return _cs("""
var yol = %s; var stAd = %s; var klipYol = %s;
var ac = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEditor.Animations.AnimatorController>(yol);
if (ac == null) return "CONTROLLER YOK (ya da override controller): " + yol;
AnimationClip klip = null;
if (!string.IsNullOrEmpty(klipYol)) {
    klip = UnityEditor.AssetDatabase.LoadAssetAtPath<AnimationClip>(klipYol);
    if (klip == null) return "KLIP BULUNAMADI: " + klipYol;
}
var sm = ac.layers[0].stateMachine;
UnityEditor.Animations.AnimatorState st = null;
foreach (var cs in sm.states) if (cs.state.name == stAd) { st = cs.state; break; }
var yeniMi = (st == null);
if (st == null) st = sm.AddState(stAd);
UnityEditor.Undo.RecordObject(ac, "add_animator_state");
var eskiKlip = (st.motion != null ? st.motion.name : "<yok>");
if (klip != null) st.motion = klip;
st.speed = %s;
st.cycleOffset = %s;
if (%s) sm.defaultState = st;
UnityEditor.EditorUtility.SetDirty(ac);
UnityEditor.AssetDatabase.SaveAssets();
return (yeniMi ? "STATE EKLENDI: " : "STATE GUNCELLENDI: ") + stAd
       + "  klip=" + (klip != null ? klip.name : eskiKlip)
       + "  hiz=" + st.speed.ToString("F2") + "  ofset=" + st.cycleOffset.ToString("F2")
       + (sm.defaultState == st ? "  [VARSAYILAN]" : "");
""" % (json.dumps(controller), json.dumps(state), json.dumps(klip or ""),
       _f(hiz, 1.0), _f(ofset, 0.0),
       "true" if str(varsayilan).lower() in ("true", "1", "evet") else "false"))


def create_override_controller_cs(temel, yol, eslemeler):
    """eslemeler: 'EskiKlipAdi=Assets/.../Yeni.anim' ciftleri, \\u0001 ile ayrilmis."""
    return _cs("""
var temelYol = %s; var yeniYol = %s; var ham = %s;
var temel = UnityEditor.AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(temelYol);
if (temel == null) return "TEMEL CONTROLLER YOK: " + temelYol;
var klasor = System.IO.Path.GetDirectoryName(yeniYol).Replace((char)92, (char)47);
if (!UnityEditor.AssetDatabase.IsValidFolder(klasor)) {
    var parcalar = klasor.Split((char)47);
    var birikim = parcalar[0];
    for (int i = 1; i < parcalar.Length; i++) {
        var sonraki = birikim + "/" + parcalar[i];
        if (!UnityEditor.AssetDatabase.IsValidFolder(sonraki))
            UnityEditor.AssetDatabase.CreateFolder(birikim, parcalar[i]);
        birikim = sonraki;
    }
}
var ovr = new AnimatorOverrideController(temel);
var lst = new System.Collections.Generic.List<
    System.Collections.Generic.KeyValuePair<AnimationClip, AnimationClip>>();
ovr.GetOverrides(lst);
var rapor = new System.Text.StringBuilder();
if (!string.IsNullOrEmpty(ham)) {
    foreach (var ciftHam in ham.Split((char)1)) {
        var ix = ciftHam.IndexOf('=');
        if (ix < 0) { rapor.Append("  ATLANDI (biçim): " + ciftHam + NL); continue; }
        var eskiAd = ciftHam.Substring(0, ix).Trim();
        var yeniKlipYol = ciftHam.Substring(ix + 1).Trim();
        var yeniKlip = UnityEditor.AssetDatabase.LoadAssetAtPath<AnimationClip>(yeniKlipYol);
        if (yeniKlip == null) return "KLIP BULUNAMADI: " + yeniKlipYol;
        bool bulundu = false;
        for (int i = 0; i < lst.Count; i++) {
            if (lst[i].Key != null && lst[i].Key.name == eskiAd) {
                lst[i] = new System.Collections.Generic.KeyValuePair<AnimationClip, AnimationClip>(
                    lst[i].Key, yeniKlip);
                bulundu = true;
                rapor.Append("  " + eskiAd + " -> " + yeniKlip.name + NL);
                break;
            }
        }
        if (!bulundu) {
            var mv = new System.Text.StringBuilder("OVERRIDE EDILECEK KLIP YOK: " + eskiAd + " | temelde olanlar:");
            foreach (var kv in lst) if (kv.Key != null) mv.Append(" " + kv.Key.name);
            return mv.ToString();
        }
    }
}
ovr.ApplyOverrides(lst);
UnityEditor.AssetDatabase.CreateAsset(ovr, yeniYol);
UnityEditor.AssetDatabase.SaveAssets();
UnityEditor.AssetDatabase.Refresh();
return "OVERRIDE CONTROLLER OLUSTURULDU: " + yeniYol + NL + rapor.ToString();
""" % (json.dumps(temel), json.dumps(yol), json.dumps(eslemeler or "")))


def set_animator_cs(obje, controller):
    return _cs("""
var g = Bul(%s);
if (g == null) return "OBJE YOK: " + %s;
var yol = %s;
var rac = UnityEditor.AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(yol);
if (rac == null) return "CONTROLLER YOK: " + yol;
var an = g.GetComponent<Animator>();
var eklendi = false;
if (an == null) { an = UnityEditor.Undo.AddComponent<Animator>(g); eklendi = true; }
UnityEditor.Undo.RecordObject(an, "set_animator");
var eski = (an.runtimeAnimatorController != null ? an.runtimeAnimatorController.name : "<bos>");
an.runtimeAnimatorController = rac;
UnityEditor.EditorUtility.SetDirty(an);
return "ATANDI: " + Yol(g) + (eklendi ? " (Animator eklendi)" : "")
       + "  eski=" + eski + "  yeni=" + rac.name;
""" % (json.dumps(obje), json.dumps(obje), json.dumps(controller)))


def _f(v, vars):
    """Sayi argumanini guvenli C# float sabitine cevirir; bos/bozuk deger varsayilana
    duser. Model bazen bos string gonderiyor - orada derleme hatasi almak yerine
    makul varsayilanla devam etmek daha kullanisli."""
    try:
        return "%.4ff" % float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return "%.4ff" % vars


# =====================================================================================
# Arac tanimlari (Ollama formatinda)
# =====================================================================================
def tanimlar():
    return [
        {"type": "function", "function": {
            "name": "list_assets",
            "description": "Proje varliklarini ara. Unity arama sozdizimi kullanir: "
                           "'t:AnimationClip', 't:Material', 't:Texture2D', "
                           "'t:AnimatorController', 't:Prefab' ya da duz ad. "
                           "Klasor verilirse yalnizca orada arar.",
            "parameters": {"type": "object", "properties": {
                "filtre": {"type": "string",
                           "description": "orn: 't:AnimationClip' veya 'walk'"},
                "klasor": {"type": "string",
                           "description": "orn: 'Assets/Animation' (bos = tum proje)"},
                "limit": {"type": "integer", "description": "en fazla kac sonuc"}},
                "required": ["filtre"]}}},
        {"type": "function", "function": {
            "name": "inspect_asset",
            "description": "Tek bir varligin detayi: animasyon klibi suresi/dongusu, "
                           "materyal shader ve rengi, texture boyutu, prefab bilesenleri.",
            "parameters": {"type": "object", "properties": {
                "yol": {"type": "string", "description": "orn: Assets/Art/x.mat"}},
                "required": ["yol"]}}},
        {"type": "function", "function": {
            "name": "hierarchy",
            "description": "Bir objenin ALTINDAKI tum torunlari bilesenleriyle listeler. "
                           "Kok bos birakilirsa tum sahne. Cok cocuklu objeleri "
                           "(orn. kalabalik) gormek icin bunu kullan.",
            "parameters": {"type": "object", "properties": {
                "kok": {"type": "string", "description": "orn: 'Crowd' (bos = tum sahne)"},
                "derinlik": {"type": "integer", "description": "kac kademe (varsayilan 3)"},
                "limit": {"type": "integer", "description": "en fazla kac obje"}},
                "required": []}}},
        {"type": "function", "function": {
            "name": "add_component",
            "description": "Sahnedeki bir objeye bilesen ekler (orn: Animator, Rigidbody, "
                           "kendi yazdigin script sinifi). Zaten varsa dokunmaz.",
            "parameters": {"type": "object", "properties": {
                "obje": {"type": "string", "description": "obje adi veya yolu"},
                "tip": {"type": "string", "description": "orn: 'Animator' veya "
                                                         "'WaveDefense.WaveManager'"}},
                "required": ["obje", "tip"]}}},
        {"type": "function", "function": {
            "name": "remove_missing_components",
            "description": "Bir objedeki KIRIK (script'i kayip, Inspector'da 'Missing Script') "
                           "bilesenleri kaldirir. Saglam bilesenlere dokunmaz. 'The referenced "
                           "script ... is missing' hatasinin tek cozumu budur; dosya yazarak "
                           "duzelmez.",
            "parameters": {"type": "object", "properties": {
                "obje": {"type": "string", "description": "obje adi veya yolu"}},
                "required": ["obje"]}}},
        {"type": "function", "function": {
            "name": "set_field",
            "description": "Inspector'da bir alani yazar. Sayi, bool, metin, renk "
                           "(#RRGGBB), Vector3 ('1,2,3'), obje referansi (sahne objesi "
                           "adi VEYA varlik yolu) ve obje DIZISI destekler. Dizi icin "
                           "degerleri \\u0001 ile ayir. Eski degeri raporlar, Undo ile "
                           "geri alinabilir.",
            "parameters": {"type": "object", "properties": {
                "obje": {"type": "string", "description": "sahne objesi adi/yolu"},
                "bilesen": {"type": "string", "description": "orn: 'Animator', "
                                                             "'Transform', 'CrowdManager'"},
                "alan": {"type": "string", "description": "alan adi (bas alt cizgi "
                                                          "olmadan da denenir)"},
                "deger": {"type": "string", "description": "yazilacak deger"}},
                "required": ["obje", "bilesen", "alan", "deger"]}}},
        {"type": "function", "function": {
            "name": "create_asset",
            "description": "Yeni varlik uretir: 'Material' (opsiyonel #RRGGBB renk ve "
                           "shader adi) veya 'AnimatorController'. Klasor yoksa olusturur. "
                           "Shader bulunamazsa projedeki benzer shader adlarini dondurur.",
            "parameters": {"type": "object", "properties": {
                "tur": {"type": "string", "description": "'Material' | 'AnimatorController'"},
                "yol": {"type": "string", "description": "orn: Assets/Materials/Yeni.mat"},
                "ozellik": {"type": "string", "description": "Material icin renk, "
                                                             "orn '#FF8800'"},
                "shader": {"type": "string", "description": "Material icin shader adi, orn "
                           "'Standard', 'Universal Render Pipeline/Lit', 'Unlit/Color'. "
                           "Bos: URP Lit, yoksa Standard"}},
                "required": ["tur", "yol"]}}},
        {"type": "function", "function": {
            "name": "set_material",
            "description": "Bir MATERYAL VARLIGININ shader ozelligini yazar: texture "
                           "atama (_BaseMap/_MainTex icin texture varlik yolu), renk "
                           "(#RRGGBB), sayi (_Metallic, _Smoothness). Ozellik yoksa "
                           "shader'in gercek ozellik listesini dondurur. ozellik='shader' "
                           "ile shader'in KENDISI degistirilir (deger = shader adi).",
            "parameters": {"type": "object", "properties": {
                "yol": {"type": "string", "description": "materyal yolu, "
                                                         "orn Assets/Materials/X.mat"},
                "ozellik": {"type": "string", "description": "orn '_BaseMap', "
                                                             "'_BaseColor', '_Metallic', "
                                                             "ya da 'shader'"},
                "deger": {"type": "string", "description": "texture varlik yolu, "
                                                           "#RRGGBB, sayi, ya da shader adi"}},
                "required": ["yol", "ozellik", "deger"]}}},
        {"type": "function", "function": {
            "name": "list_animator_states",
            "description": "Bir AnimatorController'daki katmanlari, state'leri, bagli "
                           "klipleri, hiz ve cycleOffset degerlerini listeler. "
                           "Override controller verilirse hangi klibin neyle "
                           "degistirildigini gosterir.",
            "parameters": {"type": "object", "properties": {
                "controller": {"type": "string",
                               "description": "orn Assets/Anim/Base.controller"}},
                "required": ["controller"]}}},
        {"type": "function", "function": {
            "name": "add_animator_state",
            "description": "AnimatorController'a state ekler (varsa gunceller) ve "
                           "AnimationClip atar. Oynatma hizi ve cycleOffset "
                           "verilebilir; varsayilan state yapilabilir.",
            "parameters": {"type": "object", "properties": {
                "controller": {"type": "string", "description": "controller yolu"},
                "state": {"type": "string", "description": "state adi, orn 'Walk'"},
                "klip": {"type": "string", "description": "AnimationClip varlik yolu"},
                "varsayilan": {"type": "string",
                               "description": "'true' ise varsayilan state olur"},
                "hiz": {"type": "string", "description": "oynatma hizi, orn '1.0'"},
                "ofset": {"type": "string",
                          "description": "cycleOffset 0-1, orn '0.35'"}},
                "required": ["controller", "state", "klip"]}}},
        {"type": "function", "function": {
            "name": "create_override_controller",
            "description": "Bir temel AnimatorController'in kliplerini degistiren "
                           "AnimatorOverrideController uretir. Kalabalikta her "
                           "karaktere farkli klip vermenin DOGRU yolu budur - "
                           "karakter basina ayri controller uretme.",
            "parameters": {"type": "object", "properties": {
                "temel": {"type": "string", "description": "temel controller yolu"},
                "yol": {"type": "string", "description": "uretilecek override yolu"},
                "eslemeler": {"type": "string",
                              "description": "'EskiKlipAdi=Assets/../Yeni.anim' "
                                             "ciftleri, \\u0001 ile ayrilmis"}},
                "required": ["temel", "yol"]}}},
        {"type": "function", "function": {
            "name": "set_animator",
            "description": "Sahnedeki bir objenin Animator bilesenine controller "
                           "atar. Animator yoksa ekler.",
            "parameters": {"type": "object", "properties": {
                "obje": {"type": "string", "description": "sahne objesi adi/yolu"},
                "controller": {"type": "string",
                               "description": "controller ya da override yolu"}},
                "required": ["obje", "controller"]}}},
    ]


def set_material_cs(yol, ozellik, deger):
    """Materyal VARLIGINA yazar: texture, renk, sayi.

    set_field'den farki: o sahnedeki bir BILESENIN alanina yazar, bu ise diskteki
    materyal varliginin shader ozelligine. Texture atamak, diffuse rengi degistirmek
    bu yolla olur.

    Ozellik bulunamazsa shader'in GERCEK ozellik listesi dondurulur - set_field ile
    ayni desen: model uydurmak yerine listeden dogrusunu secer. URP'de renk
    _BaseColor, texture _BaseMap; built-in'de _Color ve _MainTex oldugu icin bu
    liste pratikte sart.
    """
    return _cs(SHADER_BUL + """
var yol = %s; var oz = %s; var deger = %s;
var m = UnityEditor.AssetDatabase.LoadAssetAtPath<Material>(yol);
if (m == null) return "MATERYAL YOK: " + yol;
// Shader'in KENDISINI degistirme: ozellik 'shader' (ya da '_Shader'). Bu yol yoktu;
// model "araclarimla yapamiyorum" diye dogru raporladi (eksik yazma yolu, 6. kez).
if (oz == "shader" || oz == "_Shader" || oz == "Shader") {
    var __yeniSh = ShaderBul(deger);
    if (__yeniSh == null) return "SHADER BULUNAMADI: " + deger + " | benzerler: " + ShaderOner(deger);
    var __eskiSh = m.shader != null ? m.shader.name : "-";
    UnityEditor.Undo.RecordObject(m, "set_material shader");
    m.shader = __yeniSh;   // ayni adli ozellikler (_MainTex vb.) korunur, digerleri sifirlanir
    UnityEditor.EditorUtility.SetDirty(m);
    UnityEditor.AssetDatabase.SaveAssets();
    return "SHADER DEGISTI: " + __eskiSh + " -> " + __yeniSh.name + "  (" + yol + ")";
}
var sh = m.shader;
if (sh == null) return "SHADER YOK: " + yol;
// URP <-> built-in ad esleme. URP'de albedo _BaseMap/_BaseColor, built-in Standard'da
// _MainTex/_Color. Model dogal olarak URP adlarini deniyor; shader Standard ise her
// seferinde bir tur bosa gidiyordu. Eslesmeyi yapip RAPORLUYORUZ - sessiz degil.
string eslendi = "";
if (!m.HasProperty(oz)) {
    var esler = new System.Collections.Generic.Dictionary<string,string>() {
        {"_BaseMap","_MainTex"}, {"_MainTex","_BaseMap"},
        {"_BaseColor","_Color"}, {"_Color","_BaseColor"},
        {"_Smoothness","_Glossiness"}, {"_Glossiness","_Smoothness"}
    };
    if (esler.ContainsKey(oz) && m.HasProperty(esler[oz])) {
        eslendi = oz + " -> " + esler[oz];
        oz = esler[oz];
    }
}
if (!m.HasProperty(oz)) {
    var sb2 = new System.Text.StringBuilder("OZELLIK YOK: " + oz + " | shader=" + sh.name + " | mevcut:");
    int say = UnityEditor.ShaderUtil.GetPropertyCount(sh);
    for (int i = 0; i < say; i++)
        sb2.Append(" " + UnityEditor.ShaderUtil.GetPropertyName(sh, i)
                   + "(" + UnityEditor.ShaderUtil.GetPropertyType(sh, i) + ")");
    return sb2.ToString();
}
int idx = -1;
int n = UnityEditor.ShaderUtil.GetPropertyCount(sh);
for (int i = 0; i < n; i++) if (UnityEditor.ShaderUtil.GetPropertyName(sh, i) == oz) { idx = i; break; }
if (idx < 0) return "OZELLIK INDEKSI BULUNAMADI: " + oz;
var tip = UnityEditor.ShaderUtil.GetPropertyType(sh, idx);
UnityEditor.Undo.RecordObject(m, "set_material " + oz);
string eski = "";
if (tip == UnityEditor.ShaderUtil.ShaderPropertyType.TexEnv) {
    var t0 = m.GetTexture(oz);
    eski = (t0 == null ? "<bos>" : UnityEditor.AssetDatabase.GetAssetPath(t0));
    if (deger == "" || deger == "null") { m.SetTexture(oz, null); }
    else {
        var t = UnityEditor.AssetDatabase.LoadAssetAtPath<Texture>(deger);
        if (t == null) return "TEXTURE BULUNAMADI: " + deger;
        m.SetTexture(oz, t);
    }
} else if (tip == UnityEditor.ShaderUtil.ShaderPropertyType.Color) {
    eski = ColorUtility.ToHtmlStringRGBA(m.GetColor(oz));
    Color renk;
    if (!ColorUtility.TryParseHtmlString(deger, out renk)) {
        var q = deger.Split(',');
        if (q.Length < 3) return "RENK COZULEMEDI: " + deger + " (#RRGGBB ya da 'r,g,b' bekleniyor)";
        renk = new Color(
            float.Parse(q[0], System.Globalization.CultureInfo.InvariantCulture),
            float.Parse(q[1], System.Globalization.CultureInfo.InvariantCulture),
            float.Parse(q[2], System.Globalization.CultureInfo.InvariantCulture),
            q.Length > 3 ? float.Parse(q[3], System.Globalization.CultureInfo.InvariantCulture) : 1f);
    }
    m.SetColor(oz, renk);
} else if (tip == UnityEditor.ShaderUtil.ShaderPropertyType.Vector) {
    eski = m.GetVector(oz).ToString("F2");
    var q = deger.Split(',');
    m.SetVector(oz, new Vector4(
        float.Parse(q[0], System.Globalization.CultureInfo.InvariantCulture),
        float.Parse(q[1], System.Globalization.CultureInfo.InvariantCulture),
        q.Length > 2 ? float.Parse(q[2], System.Globalization.CultureInfo.InvariantCulture) : 0f,
        q.Length > 3 ? float.Parse(q[3], System.Globalization.CultureInfo.InvariantCulture) : 0f));
} else {
    eski = m.GetFloat(oz).ToString("F3");
    m.SetFloat(oz, float.Parse(deger, System.Globalization.CultureInfo.InvariantCulture));
}
UnityEditor.EditorUtility.SetDirty(m);
UnityEditor.AssetDatabase.SaveAssets();
return "YAZILDI: " + yol + " . " + oz + " (" + tip + ")  eski=" + eski + "  yeni=" + deger
       + (eslendi == "" ? "" : "  [ad eslendi: " + eslendi + "]");
""" % (json.dumps(yol), json.dumps(ozellik), json.dumps(str(deger))))
