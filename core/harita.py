"""Proje haritasi (MAP.md): dosya -> semboller -> boyut. OpenMemory'nin MAP fikri.

Neden: sakli-hedef olcumu (2026-08-23) gosterdi ki hedef ISIMSIZKEN isci adressiz kaliyor
(120 dosyayi sirayla okuyup cokuyor). `ara` bunu embedding ile cozer; MAP ayni adresi
SIFIR sorguyla, sistem istemine gomulu statik bir haritayla verir. Hangisinin ne zaman
kazandigi olculur (tests/map_ab.py).

Tasarim:
  - Python: stdlib ast (bagimliliksiz). C#: tree-sitter varsa o, yoksa regex yedegi.
  - Cikti bilerek YOGUN: "yol (satir): sembol1, sembol2" - dosya basina tek satir.
    Harita baglama girecegi icin her karakter faturadir.
  - Uretim `uret(workdir)` ile aninda; MAP.md diske yazmak istege bagli (kaydet=True).
    Bayatlama riskine karsi varsayilan akis her iste yeniden uretmektir (~ms mertebesi).
"""
from __future__ import annotations
import ast, os, re

from core.rag import ATLA_KLASOR, DOSYA_SINIRI

HARITA_UZANTILAR = (".py", ".cs")
CS_DESEN = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)*(?:public|private|protected|internal|static|sealed|abstract|"
    r"partial|override|virtual|async|\s)+\s*"
    r"(?:class|struct|interface|enum|[A-Za-z_<>\[\],\s]+?)\s+([A-Za-z_]\w*)\s*[({:]", re.M)


def _py_semboller(kaynak: str) -> list:
    try:
        agac = ast.parse(kaynak)
    except SyntaxError:
        return ["<sozdizimi hatasi>"]
    out = []
    for dugum in agac.body:
        if isinstance(dugum, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(dugum.name + "()")
        elif isinstance(dugum, ast.ClassDef):
            metotlar = [n.name for n in dugum.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not n.name.startswith("_")][:6]
            out.append(dugum.name + (".{%s}" % ",".join(metotlar) if metotlar else ""))
    return out


def _cs_semboller_ts(kaynak: str) -> list | None:
    try:
        import tree_sitter, tree_sitter_c_sharp
    except ImportError:
        return None
    dil = tree_sitter.Language(tree_sitter_c_sharp.language())
    p = tree_sitter.Parser(dil)
    agac = p.parse(kaynak.encode("utf-8"))
    out = []

    def gez(dugum, sinif_ici=False):
        for c in dugum.children:
            tip = c.type
            if tip in ("class_declaration", "struct_declaration", "interface_declaration",
                       "enum_declaration"):
                ad = c.child_by_field_name("name")
                metotlar = []
                govde = c.child_by_field_name("body")
                if govde is not None:
                    for m in govde.children:
                        if m.type in ("method_declaration", "constructor_declaration"):
                            ma = m.child_by_field_name("name")
                            if ma is not None:
                                metotlar.append(ma.text.decode())
                if ad is not None:
                    out.append(ad.text.decode() +
                               (".{%s}" % ",".join(metotlar[:6]) if metotlar else ""))
            elif tip in ("namespace_declaration", "file_scoped_namespace_declaration",
                         "declaration_list", "compilation_unit"):
                gez(c, sinif_ici)
    gez(agac.root_node)
    return out


def _cs_semboller(kaynak: str) -> list:
    ts = _cs_semboller_ts(kaynak)
    if ts is not None:
        return ts
    return list(dict.fromkeys(CS_DESEN.findall(kaynak)))[:12]      # regex yedegi


def uret(workdir: str, kaydet: bool = False) -> str:
    """Haritayi metin olarak uret; kaydet=True ise workdir/MAP.md'ye de yazar."""
    satirlar = []
    for kok, klasorler, dosyalar in os.walk(workdir):
        klasorler[:] = sorted(k for k in klasorler
                              if k not in ATLA_KLASOR and not k.startswith("."))
        for ad in sorted(dosyalar):
            if not ad.lower().endswith(HARITA_UZANTILAR):
                continue
            tam = os.path.join(kok, ad)
            try:
                if os.path.getsize(tam) > DOSYA_SINIRI:
                    continue
                with open(tam, encoding="utf-8", errors="replace") as f:
                    kaynak = f.read()
            except OSError:
                continue
            rel = os.path.relpath(tam, workdir).replace("\\", "/")
            semboller = _py_semboller(kaynak) if ad.endswith(".py") else _cs_semboller(kaynak)
            n = kaynak.count("\n") + 1
            satirlar.append("%s (%d): %s" % (rel, n, ", ".join(semboller) if semboller else "-"))
    metin = "PROJE HARITASI (dosya (satir): semboller):\n" + "\n".join(satirlar)
    if kaydet:
        with open(os.path.join(workdir, "MAP.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(metin + "\n")
    return metin
