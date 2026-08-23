# Apprentice MCP sunucusu

**A local model does the work, a frontier model supervises.**

`server/apprentice_server.py` bağımlılıksız (stdlib) bir stdio MCP sunucusudur. Denetçi
(IDE'nizdeki Claude / GPT / Gemini ya da Claude Code) buna bağlanır ve iş aracını çağırır
(`worker_run`; yardımcı: `worker_status`);
işi Ollama'daki yerel model yapar, sonucu derleyici/doğrulayıcı onaylar.

## Sözleşme

```
worker_run(gorev, kabul_kriterleri, ortam="code", calisma_dizini?, oturum?, play?, onarim?, araclar_kapali?, bekle?, zaman_asimi_s?)
```

| girdi | tip | anlam |
|---|---|---|
| `gorev` | string | ne yapılacak, düz dille; dosya/obje adlarını ver |
| `kabul_kriterleri` | string[] | **denetçi yazar**, somut ve ölçülebilir; göreve metin olarak eklenir |
| `ortam` | `code` (+ kurulu eklentiler) | araç seti + doğrulayıcı; `envs/*/env.json` ile keşfedilir. `fake` = modelsiz duman testi |
| `calisma_dizini` | string | `code`: workspace köküne **göreli** alt klasör; boş = kökün kendisi. Kök, IDE'nin bildirdiği workspace'tir (MCP `roots`); dışına çıkılamaz |
| `oturum` | string | önceki çağrının `oturum`u verilirse işçi aynı bağlamla devam eder |
| `play` | bool | ortama özgü ek çalışma-zamanı doğrulaması (eklenti destekliyorsa; vars. false) |
| `onarim` | int | azami derleme onarım turu (vars. 3) |
| `dogrulama` | `tam` \| `derleme` | `tam` (vars.): işçi testleri de koşar, ham test çıktısı döner. `derleme`: işçi **yalnızca yazar** — test/shell araçları kapalı, harness test koşmaz, ölçüm dönmez; kodu denetçi okur ve onaylar. Ölçüldü: dönüş ~3000 → **~480 token**, süre 139 → 36 s |
| `araclar_kapali` | string[] | bu turda işçiden saklanacak araçlar (ör. bir ölçüm aracı) — ölçümü denetçi yapar, işçi ölçüm-düzeltme döngüsüne giremez (ölçüldü: talimatla söylenince işçi iki turda yine ölçtü, ~400 s/tur) |
| `zaman_asimi_s` | number | üst sınır (vars. 1800); aşılırsa işçi durdurulur |
| `bekle` | bool | `false`: hemen `is_id` ile dön, `worker_status(is_id)` ile yokla. **Cursor için gerekli** (ölçüldü: Cursor'ın araç zaman aşımı ~2.5 dk, bir motor-eklentisi turu 2–8 dk) |

Dönüş:

```json
{
  "yazilan_dosyalar": [{"yol": "app.py", "yeni": true, "eklendi": 41, "silindi": 0, "satir": 41, "icerik": "dosyanın son hali (12k karaktere kadar)"}],
  "derleme_durumu": "derlendi | derleme_hatasi | calistirilamadi | zaman_asimi",
  "hatalar": ["...doğrulayıcı / çalışma zamanı / altyapı..."],
  "tur_sayisi": 1,
  "sure": 73.4,
  "ozet": "işçinin kendi anlatımı — beyan, kanıt değil",
  "olcumler": [{"arac": "run_tests", "sonuc": "HAM çıktı", "sure_s": 1.2}],
  "araclar": ["read_file app.py", "write_file app.py", "run_tests", "..."],
  "play": null,
  "oturum": "20260822-231500-a1b2c3",
  "is_id": "...", "is_klasoru": "~/.apprentice/jobs/<id>"
}
```

Kurallar:

- `ozet` boşsa `hatalar`a "işçi nihai özet yazmadı" düşer (adım sınırı dolmuş demektir; sessiz başarı sanma).
- `derleme_durumu == "derlendi"` yalnızca **derleyicinin** onayıdır. Kabul kriterlerinin
  sağlanıp sağlanmadığına `olcumler`e bakarak **denetçi** karar verir.
- Ölçümler ham gelir. Ölçülen: işçi kendi ölçümünü yorumlayıp düzeltmeye kalkınca
  yakınsamadı (en küçük mesafe 1.15 → 0.01); aynı ölçüm özetlenip "sert kısıt gerek"
  diye verilince 2 turda çözdü. Bu yüzden denetçi özetler, aynı `oturum` ile yeni
  `worker_run` çağırır.
- Bir tur 60–300 s sürer; `play` ile daha uzun. İstemcinin araç zaman aşımını buna göre
  ayarla (Claude Code: `MCP_TOOL_TIMEOUT` ms cinsinden, ör. `1800000`). Ayarlanamıyorsa (Cursor)
  `bekle=false` + `worker_status`. İstemci çağrıyı iptal ederse (`notifications/cancelled`) sunucu
  işçiyi öldürür — ölçüldü: iptal dinlenmeyince işçi zombi olarak devam edip ikinci çağrıyla aynı
  dosyaya paralel yazdı.
- İş dosyaları: `~/.apprentice/jobs/<id>/` → `prompt.txt` (işçinin gördüğü tam metin),
  `events.jsonl` (ham olay akışı), `stderr.txt`, `job.json`. Sohbet bağlamı
  `~/.apprentice/sessions/<ortam>/<oturum>.json`. Ev `APPRENTICE_HOME` ile değişir.

## Canlı akış

Tur sürerken sunucu her olay için `notifications/progress` (istek `_meta.progressToken` taşıyorsa) ve
`notifications/message` (log) gönderir: "arac: write_file app.py", "yazdi: app.py (88 satir)", "run_tests -> …", "isci ozeti: …". Cursor ve Claude Code bunları araç kutusunda gösterir; dönüşteki
`yazilan_dosyalar[].icerik` ise yazılan dosyanın son halidir.

## Örnek çağrı

```json
{
  "name": "worker_run",
  "arguments": {
    "gorev": "sure.py: parse_sure('1h30m') gibi metinleri saniyeye çeviren fonksiyon + test_sure.py (unittest).",
    "kabul_kriterleri": [
      "parse_sure('1h30m') == 5400, parse_sure('45s') == 45, parse_sure('10m5s') == 605",
      "Geçersiz girdide ValueError: '', 'abc', '5x', '1h1h'",
      "run_tests hatasız geçer; yalnızca sure.py ve test_sure.py yazılır"
    ],
    "ortam": "code"
  }
}
```

## Bağlanma

**Claude Code** — depo kökündeki `.mcp.json` otomatik görülür; `claude` bu klasörde
açılınca "apprentice" sunucusunu onaylaması istenir. Başka bir projeden:

```bash
claude mcp add apprentice -- python C:/yol/Apprentice/server/apprentice_server.py
```

**Cursor** — `.cursor/mcp.json` (proje) ya da `~/.cursor/mcp.json` (genel):

```json
{ "mcpServers": { "apprentice": { "command": "python",
    "args": ["C:/yol/Apprentice/server/apprentice_server.py"],
    "env": { "PYTHONIOENCODING": "utf-8" } } } }
```

**VS Code (Copilot)** — `.vscode/mcp.json`, aynı `command`/`args` ile `"servers"` altında.

**Çalışma kökü (dağıtılabilir, sabit yol yok):** sunucu `initialize` sonrası istemciden `roots/list` ister;
Cursor / Claude Code / VS Code açık workspace'ini bildirir, kök o olur. Kullanıcı prompt'a yol yazmaz.
Roots desteklemeyen istemci için `APPRENTICE_WORKDIR_ROOT`; o da yoksa sunucunun çalışma dizini.
Ölçüldü: IDE'nin açık klasörü sunucuyu kendiliğinden sınırlamaz — sınır bu mekanizmadır.

Ortam değişkenleri: `APPRENTICE_WORKDIR_ROOT`, `APPRENTICE_HOME`, `APPRENTICE_TIMEOUT_S`, `APPRENTICE_PYTHON`
(işçi için ayrı yorumlayıcı), `APPRENTICE_MODEL`, `APPRENTICE_CTX`, `APPRENTICE_BATCH`. Diğer ayarlar
`apprentice.config.json` (şablon: `apprentice.config.template.json`; öncelik env >
dosya > şablon > kod).

## Ortamlar

| ortam | araçlar | doğrulayıcı | koşucu |
|---|---|---|---|
| `code` | read_file, write_file, list_files, run_shell, run_tests, **ara** (anlamsal kod araması, bge-m3) | `compile()` + pytest (yoksa stdlib unittest) | `envs/code/code_runner.py` |

`code` ortamı ayrıca: **proje hafızası** — workspace kökünde `HAFIZA.md` varsa içeriği (3000 karaktere kadar)
işçinin sistem istemine eklenir; ustanın kalıcı dersleri yazdığı yerdir. **`ara` araci** — çalışma dizinini
parçalayıp bge-m3 ile gömer (`ollama pull bge-m3`), indeks `~/.apprentice/rag/` altında, dosya değişince
yalnızca değişen yeniden gömülür; işçi "neyi okuyacağını" körlemesine okumadan bulur.
| `fake` | — | — | `envs/fake/fake_runner.py` (olay şemasını taklit eder, model gerektirmez) |
| eklentiler | ortamın kendi seti | ortamın kendi doğrulayıcısı (ör. derleyici + play) | `envs/<ad>/` — `env.json` ile tanımlanır, klonlanınca belirir |

`code` ortamında silme aracı yoktur; `run_shell` içinde `git push` ve özyinelemeli silme komutları reddedilir.
Git okuma/commit `run_shell` üzerinden serbesttir.

Eklenti yazmak: `envs/<ad>/env.json` → `{"ad", "kosucu", "aciklama", "on_kosul": ["ollama"], "kopru": {...},
"olcum_araclari": [...], "ayarlar": {...}}`; koşucu `panel_runner`/`code_runner` ile aynı komut satırını ve
olay şemasını (system/tool/tool_result/write/assistant/result/exit) uygular.

## İzleme

`python clients/web/monitor.py [--port 8765] [--home ~/.apprentice]` — sunucuya bağlanmaz, iş
klasörünü okur; hangi istemci başlatmış olursa olsun her iş listede: durum, doğrulama, dosyalar, araç akışı
(argüman + sonuç), ölçümler, işçinin özeti. `/api/jobs` aynı veriyi JSON verir.

## Ölçüm kampanyası

`python tests/code_kampanya.py` — 6 kod görevi; denetçi (betik) kriter yazar, işçi yazar, denetçi
**işçiye verilmeyen gizli kontrolleri** koşar, tutmayanları somut geri bildirime çevirip aynı
`oturum` ile 2. tur ister. Sonuç `tests/code_kampanya.son.json`.

## Test

```bash
python tests/test_server.py          # model gerekmez: el sıkışma, şema, hata yolları, roots, iptal,
                                     # fake ortamla 4 senaryo (başarı / doğrulama hatası / çökme / zaman aşımı)
python tests/test_server.py --live   # + gerçek code turu (Ollama açık)
python tests/test_code_env.py [--live]   # code ortamı: hapis/araçlar/doğrulayıcı; --live gerçek görev
```

Ön koşullar `worker_run` içinde kontrol edilir: Ollama kapalıysa, model yüklü değilse ya da ortamın
köprüsü yoksa işçi hiç başlatılmaz, `derleme_durumu: calistirilamadi` ve sebep `hatalar`da döner.

## Tasarım notları

- İşçi **ayrık süreç** (`envs/<ortam>/` koşucusu): tur dakikalar sürer, işçi çökse sunucu ayakta kalır. Prompt komut satırından değil dosyadan
  geçer (kaçış kazaları).
- Çocuğun stdin/stdout'u `DEVNULL`: ikisi de MCP kanalı. Ölçülen: stdin miras alınınca
  çocuk Windows'ta ilk satırını bile yazmadan takıldı.
- `tools/call` ayrı iş parçacığında; `ping` uzun tur sırasında da cevaplanır.
- Eklenti panelleri (ör. apprentice-unity'nin Editor paneli) aynı koşucuyu sunucusuz kullanabilir.
