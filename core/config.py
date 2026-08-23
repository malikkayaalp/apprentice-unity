"""Apprentice tek ayar evi: apprentice.config.json okuyucusu.

Oncelik: ortam degiskeni > apprentice.config.json > apprentice.config.template.json
> kodun icindeki varsayilan. Sablon depoda, kullanici kopyasi gitignore'da.

Dosya aranan yerler (ilk bulunan):
  1. APPRENTICE_CONFIG ortam degiskeni (tam yol)
  2. calisma dizini / apprentice.config.json
  3. depo koku / apprentice.config.json
Sablon her zaman depo kokunden okunur ve taban olarak kullanilir; kullanici dosyasi
uzerine yazar (ic ice sozlukler anahtar anahtar birlesir).

Kullanim:
    from core import config
    config.get("ollama.model")                 # "hf.co/unsloth/..."
    config.get("makine.num_batch", 512)
    config.env_or("APPRENTICE_MODEL", "ollama.model")   # env once, sonra dosya
"""
from __future__ import annotations
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "apprentice.config.template.json")
USER_NAME = "apprentice.config.json"

_cache: dict | None = None
_source: str = ""


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def user_path() -> str:
    """Kullanici ayar dosyasinin yolu (var olsun olmasin)."""
    env = os.environ.get("APPRENTICE_CONFIG")
    if env:
        return env
    cwd = os.path.join(os.getcwd(), USER_NAME)
    if os.path.exists(cwd):
        return cwd
    return os.path.join(ROOT, USER_NAME)


def load(force: bool = False) -> dict:
    global _cache, _source
    if _cache is not None and not force:
        return _cache
    cfg = _read(TEMPLATE)
    # Eklenti ayarlari: envs/<ad>/env.json icindeki "ayarlar" bolumu <ad> anahtari altina
    # girer (ornek: apprentice-unity -> cfg["unity"]). Cekirdek sablonu eklentileri bilmez.
    envs = os.path.join(ROOT, "envs")
    if os.path.isdir(envs):
        for ad in sorted(os.listdir(envs)):
            meta = _read(os.path.join(envs, ad, "env.json"))
            if meta.get("ayarlar"):
                cfg = _merge(cfg, {meta.get("ad", ad): meta["ayarlar"]})
    up = user_path()
    if os.path.exists(up):
        cfg = _merge(cfg, _read(up))
        _source = up
    else:
        _source = TEMPLATE
    _cache = cfg
    return cfg


def source() -> str:
    load()
    return _source


def get(path: str, default=None):
    """Noktali yol: 'ollama.model'. Yoksa default."""
    cur: object = load()
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def env_or(env_name, path: str, default=None, cast=None):
    """Ortam degiskeni varsa o, yoksa dosyadaki deger, yoksa default.

    env_name tek ad ya da ad listesi olabilir (ilk dolu olan kazanir) - eski adlar
    (UNITY_CODE_*) uyumluluk icin ikinci sirada verilir."""
    names = [env_name] if isinstance(env_name, str) else list(env_name)
    v = None
    for n in names:
        v = os.environ.get(n)
        if v not in (None, ""):
            break
    if v is None or v == "":
        v = get(path, default)
    if cast is not None and v is not None:
        try:
            return cast(v)
        except Exception:
            return default
    return v
