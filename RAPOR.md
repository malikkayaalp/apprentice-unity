# RAPOR — Apprentice MCP sunucusu, aşama 1 (2026-08-22 gece, otonom oturum)

## Ne yapıldı

| # | istek | durum | nerede |
|---|---|---|---|
| 1 | `server/apprentice_server.py`: tek araç `worker_run(gorev, kabul_kriterleri, ortam)` | **bitti** | `server/apprentice_server.py` |
| 2 | `server/README.md`: sözleşme, örnek, Cursor/Claude Code bağlantısı | **bitti** | `server/README.md`, `.mcp.json` |
| 3 | Unity'siz duman testi (fake_unity_server) + `tests/test_server.py` | **bitti, GEÇTİ** | `envs/fake/fake_runner.py`, `tests/test_server.py` |
| 4 | Gerçek test: Suru görevi, `play_observe` ile sayıyla rapor | **bitti, 1. turda GEÇTİ** | `tests/suru_kabul.py`, `tests/suru_kabul.son.json` |
| 5 | Hata düzelt, tekrar (≤5 tur) | 2 altyapı hatası bulundu/düzeltildi; görev 1 turda geçtiği için onarım turu gerekmedi | aşağıda |
| 6 | Yerel commit (push yok) | **bitti**: `02ee981` (ilk sürüm), `35b6618` (bu çalışma) | `git log` |
| 7 | RAPOR.md | bu dosya | |
| 8 | `envs/code/` taslak + kendi deposunda küçük görev | **bitti, GEÇTİ** (27 s, 3 test) | `envs/code/code_runner.py`, `tests/test_code_env.py` |

Unity paneline (`clients/unity/`) dokunulmadı. Unity edit modunda bırakıldı (doğrulandı: `isPlaying=false`).

## Sözleşme (uygulanan)

```
worker_run(gorev, kabul_kriterleri[], ortam="unity"|"code"|"fake", calisma_dizini?, oturum?, play?, onarim?, zaman_asimi_s?)
  -> { yazilan_dosyalar[{yol, yeni, eklendi, silindi, satir}], derleme_durumu, hatalar[],
       tur_sayisi, sure, ozet, olcumler[{arac, sonuc, sure_s}], araclar[], play, oturum, is_id }
derleme_durumu ∈ { derlendi, derleme_hatasi, calistirilamadi, zaman_asimi }
```

- Kabul kriterleri göreve "KABUL KRİTERLERİ (denetçi yazdı)" bloğu olarak eklenir + kural: "ölç, ham raporla, ölçüm-düzeltme döngüsüne girme".
- `derlendi` yalnızca derleyici/doğrulayıcı onayı; kriter kararı denetçide, `olcumler` ham.
- İşçi ayrık süreç (`envs/<ortam>/*_runner.py`), olaylar `~/.apprentice/jobs/<id>/events.jsonl`; sunucu bunları rapora çevirir. Zaman aşımı varsayılan 1800 s (bir tur 60–300 s ölçüldü; Suru 286 s).

## Testler

### 3) Duman testi — `python tests/test_server.py` → **GEÇTİ**
Gerçek stdio istemcisi gibi konuşur: initialize/ping/tools/list, 4 hata yolu, fake ortamla 4 senaryo
(başarı → `derlendi`, `HATA_URET` → `derleme_hatasi` tur 2, `COK` → `calistirilamadi` + "sonuç yazmadan çıktı",
`YAVAS` → `zaman_asimi`). Fake koşucu `mcpbridge/fake_unity_server.py`'ye stdio ile gerçekten bağlanıp
`read_console` çağırır (köprü katmanı da testte). Şema alanları ve tipleri her senaryoda kontrol edilir.

### 4) Gerçek test — `python tests/suru_kabul.py` → **GEÇTİ (1 tur)**

Görev: "Suru altındaki 8 küre XZ düzleminde rastgele hareket etsin." Kriterler: çiftler ≥ 2 birim, |x|,|z| ≤ 5,
15 sn doğrula, script `SuruYoneticisi.cs` + `add_component`.

| ölçüm | değer |
|---|---|
| Başlangıç (script yokken, 5 sn) | 4 örnek, min mesafe 2.000, hareket **yok** |
| İşçi | 286 s, 1 tur, derlendi, 11 araç çağrısı (scene_objects, inspect_object×2, hierarchy, list_scripts, write_script×2, add_component, read_script, play_observe×2), dosya +156/−10 |
| **Denetçi bağımsız ölçümü (15 sn)** | **10 örnek**, en küçük çift mesafesi **2.003**, max \|x\| **4.986**, max \|z\| **4.709**, hareket var |
| K1 (≥2) ihlal | **0/10** |
| K2 (≤5) ihlal | **0/10** |
| K3 (15 sn, hareketli) | sağlandı |

İşçi beyanı ("tüm ölçümlerde TUM KRITERLER SAGLANDI") bağımsız ölçümle uyuştu. Yazdığı kod, önceki deneyde
sonradan öğrettiğimiz deseni bu kez kendiliğinden kurdu: yeni konumu önce dene, 2 birimden yakın düşüyorsa adımı atla
(sert kısıt), sınırlarda `Clamp`. Fark: kriterler **baştan, somut ve ölçülebilir** verildi — denetçinin işi tam olarak bu.

Not: 15 sn'de 10 örnek (0.5 sn hedefin altında) — her örnek bir MCP `execute_code` gidiş-dönüşü (~1 s). Kriter
değerlendirmesi için yeterli; daha sık örnek istenirse ölçüm kodu Unity tarafında biriktirilmeli.

Denetçi döngüsü (ölçüm özeti → aynı `oturum` ile düzeltme, ≤5 tur) betikte hazır ama bu koşuda tetiklenmedi.

### 8) Code ortamı — `python tests/test_code_env.py --live` → **GEÇTİ**
Modelsiz: hapis (`../` reddi), dosya araçları, `compile()` doğrulayıcı, unittest doğrulayıcı (bozuk → hata, düzeltince temiz), shell.
Canlı (sunucu üzerinden, `.apprentice_test_home/code_task/`): "toplam(a,b) + en az 3 test" → 27 s, 1 tur, 4 araç
(list_files, write_file×2, run_tests), `derlendi`; denetçi testleri kendisi koştu: **Ran 3 tests, OK**.

## Bulunan ve düzeltilen hatalar

1. **Çocuk süreç takılması (Windows)** — sunucu içinden başlatılan işçi ilk satırını bile yazmadan duruyordu; tek başına
   sorunsuzdu. Sebep: çocuk sunucunun stdin'ini (MCP borusu) miras alıyordu. Düzeltme: `stdin=DEVNULL` (stdout zaten DEVNULL).
2. **Bayat `.pyc`** (code ortamı) — aynı saniyede aynı boyutta yeniden yazılan test dosyası için Python eski bytecode'u
   kullandı (mtime+boyut aynı), düzeltilmiş test eski haliyle koştu. Düzeltme: doğrulayıcı `py_compile` yerine
   `compile()` (pyc yazmaz), test/shell koşuları `-B` + `PYTHONDONTWRITEBYTECODE=1`.
3. Zaman aşımı senaryosu fake işçi 0.5 sn'den hızlı bittiği için test edilemiyordu → `YAVAS` anahtarı.
4. Test çıktısı cp1252 konsolda Türkçe karakterde çöktü → `stdout.reconfigure(utf-8)`.
5. Önceki oturumdan: Python `open(...,'w')` Windows'ta CRLF yazıyor, diff tüm dosya oluyordu → `newline="\n"`.

## Kararlar ve gerekçeleri

- **Tek araç.** İlk sürümdeki `worker_status`/`worker_env` kaldırıldı; ön koşul kontrolü (Ollama, model, köprü)
  `worker_run` içine alındı ve sebep `hatalar`da döner. Denetçi tek şeyi öğrenir.
- **İşçi ayrık süreç, olay dosyası üzerinden.** Unity paneliyle aynı koşucu (`panel_runner.py`) — iki istemci tek
  işçi yolu. Çökme/zaman aşımı sunucuyu düşürmez.
- **pytest kurulmadı.** Hiçbir yorumlayıcıda yoktu; kurmak depo dışına yazmak olurdu (yasak) ve "ek paket yok"
  ilkesine ters. Doğrulayıcı pytest varsa onu, yoksa stdlib `unittest discover` kullanır; model hangisinin
  aktif olduğunu sistem isteminden bilir.
- **Silme aracı yok** (code ortamında da) — Unity'deki kazanın dersi.
- **Ölçüm ham döner, yorum denetçide.** Sunucu "kriter tuttu" demez; yalnızca derleyici sonucunu ve ham ölçümü verir.
- Unity zaten açıktı (23:09); yanlışlıkla ikinci örnek açtım, "proje zaten açık" hatasıyla kapattım; mevcut
  örnekle devam edildi.

## Sırada ne var

1. Denetçi olarak **gerçek IDE**: Claude Code'u `.mcp.json` ile bağlayıp Suru görevini sohbetten verdirmek (kriterleri
   Claude yazsın). Cursor'da aynı. Ölçüm: Cursor kendi ajanı vs Cursor→XL (aşama 2'nin ölçüm sorusu).
2. `envs/code` taslağını büyütmek: git (diff/status, commit yok), çok dosyalı görevlerde `64k + prefix cache` için
   araç bloğunu sabit tutma, büyük dosya okuma kırpması (şu an 60k karakter).
3. `play_observe` örnekleme sıklığı: Unity tarafında biriktirip tek seferde almak (15 sn → 30 örnek).
4. Denetçi düzeltme döngüsünü tetikleyen bir vaka (bilerek zayıf kriterle) ile `oturum` sürekliliğini canlı test etmek.
5. İlk çalıştırmada `num_batch` ölçümü ve UPM paket yerleşimi (kullanıcı hedefi: GitHub'dan indiren rahat kursun).

---

# Aşama 2–3 (2026-08-23 gece, otonom devam) — commit `33b2131`

## Ne yapıldı

| iş | durum | kanıt |
|---|---|---|
| Gerçek IDE denetçisi: Claude Code → `worker_run` (MCP, `.mcp.json`) | **çalıştı** | code: parse_sure 2 tur (87 s + 84 s), oturum sürekliliği 23 mesaj; unity: lider takibi 6 tur |
| Code ölçüm kampanyası (6 görev, gizli denetçi kontrolleri) | **bitti** | `tests/code_kampanya.son.json` |
| Denetçi geri bildirimi kalitesi ölçümü (genel vs somut) | **bitti** | roma görevi, aşağıda |
| `clients/web/monitor.py` izleme sayfası | **bitti** | `/` ve `/api/jobs`, tarayıcıda doğrulandı |
| İlk-çalıştırma `num_batch` ölçümü (`core/olcum.py --yaz`) | **bitti** | `apprentice.config.json` yazıldı |
| `play_observe` iyileştirmesi (toplu örnekleme + runInBackground) | **bitti** | 15 sn: 10 → 22 örnek |
| Unity denetçi döngüsü vakası (lider takibi) | **kısmen**: kararlı durumda 21/22, ilk ~3 sn geçiş ihlali | `tests/lider_olc.son.json` |
| Commit (push yok) | `33b2131` | |

## Ölçümler

### Code kampanyası — `python tests/code_kampanya.py`
Denetçi (betik) kriter yazar; işçi yazar; denetçi **işçiye verilmeyen** gizli kontrolleri koşar; tutmayanı somut geri bildirime çevirip aynı `oturum` ile 2. tur ister.

| görev | tur-1 gizli | son | tur | işçi süresi |
|---|---|---|---|---|
| parantez | 6/6 | 6/6 | 1 | 46 s |
| lru | 6/6 | 6/6 | 1 | 53 s |
| roma | 5/6 | 5/6 | 2 | 1094 + 972 s (4'er onarım turu, fazladan `test_debug.py`) |
| satis | 6/6 | 6/6 | 1 | 62 s |
| fib_onar (var olan hatalı dosyayı düzelt) | 6/6 | 6/6 | 1 | 42 s |
| kelime | 5/6 | 6/6 | 2 | 65 + 82 s |
| **toplam** | **34/36** | **35/36** | | |

**Genel vs somut geri bildirim (roma):** betiğin otomatik geri bildirimi ("gidiş-dönüş 1..3999 tutmuyor: ValueError") 2 turda ~2000 sn harcayıp çözemedi; işçi kendi debug çıktısında `s.count('M') = 4` görmesine rağmen çıkarımı yapamadı. Claude Code denetçi olarak **somut özet** verdi ("`count('M')>3` kontrolü `CM` içindeki M'yi de sayıyor; gidiş-dönüş doğrulamaya geç") → **130 sn, 1 tur, 6/6**. Kampanya toplamı **36/36**. Tezin ölçülmüş hâli: işçi ham veriyi yorumlayamıyor, somut özeti uyguluyor.

### Unity — lider takibi (Claude Code denetçi, 6 tur, aynı oturum)
Görev: Lider küre daire çizer (r=3, 10 sn/tur), 8 küre liderden 1.5–4 birimde kalsın, çiftler ≥1.5, |x|,|z| ≤ 7.

| tur | işçi | denetçi ölçümü (15 sn) | denetçi özeti |
|---|---|---|---|
| 1 | 227 s, derlendi, Lider yaratılamadı (araç setinde obje yaratma yok; 15 adımda özet yok) | — | "Lider'i kodda `CreatePrimitive` ile yarat" |
| 2 | 473 s, 3× kendi ölçümü (`OLCUM_SINIRI` durdurdu) | max_lider 7.5–10, küreler |xz|=7 duvarında | "takip yok; d>4 yaklaş, d<1.5 uzaklaş; ölçme" |
| 3 | 108 s, 3 araç, ölçmedi | 10/10 lider ihlali; `min_cift` her örnekte tam 1.500 → **kilitlenme** | "adım atlama kilitliyor; ayrışma kuvveti + sert çözümleme" |
| 4 | 571 s, talimata rağmen 3× ölçtü | 8/10 ihlal ama hepsi kenarda (1.474 vs 1.5), max_lider ≤3.9 | "hedef bandı içe çek 2.0–3.5" |
| 5 | 132 s | mesafeler tamam, **lider sabit** → sebep editör odaksızken play duraklıyor (harness hatası, aşağıda) | — |
| 5' (düzeltilmiş ölçüm) | — | **22 örnek, 21/22 bantta**, lider tam tur; tek ihlal t≈0 | "başlangıç halkası 2.75" |
| 6 | 157 s | 22 örnek, 21/22; ilk örnek (≈3 s) hâlâ geçiş | durduruldu |

Sonuç: kararlı durum kriterleri iki ayrı koşuda 21/22 örnekte tutuyor (min_lider 1.98–2.00, max_lider 3.50–3.57, çift ≥1.5, |xz| ≤6); "her an" kriteri ilk ~3 sn'de tutmuyor. 6 turda durduruldu, kalan iş not edildi.

### `num_batch` (12k token prompt, Qwen3-Coder-Next Q4_K_XL, RTX 5070 Ti)
512: 140 t/s · 1024: 244 · 2048: 418 · **4096: 620 t/s (+%342)** → `apprentice.config.json` makine bölümü yazıldı; yükleyici env > dosya > şablon sırasıyla okuyor.

## Bulunan ve düzeltilen hatalar
1. **Editör odaksızken Unity play döngüsü duruyor** — `play_observe` örnekleri 4–6 sn boyunca birebir aynı geldi, "kod donuyor / lider sabit" sanıldı. Düzeltme: play'e girince `Application.runInBackground = true`.
2. **Örnek başına ayrı `execute_code` derlemesi** editörü takıyor, 15 sn'de 10 örnek → örnekleme Unity içinde `EditorApplication.update` ile 0.5 sn'de biriktirilip tek okumayla alınıyor (22–30 örnek). Kurulum derlenmezse eski yol.
3. Çöken/zaman aşımına uğrayan işçi olay dosyasına `exit` yazmıyordu → izleme sayfasında sonsuza kadar "çalışıyor"; sunucu artık kapatıyor.
4. Code ortamında model mutlak yol verince olaylar mutlak yol taşıyordu → daima göreli.
5. `run_shell`'de `git push` ve özyinelemeli silme reddi (silme yasağı shell'den delinmesin).
6. Heredoc içindeki `
` kaçışları yedinci ve sekizinci kez bozuldu → kaçış içeren her yazma Edit/Write ya da `chr(10)`.

## Gözlemler (tasarım için)
- İşçi "ölçme" talimatını iki turda ihlal etti; `OLCUM_SINIRI=3` onu kilitlenmekten kurtardı ama her ihlal ~400 s. Daha sert çözüm: denetçi `play_observe` aracını isteğe bağlı kapatabilmeli (`araclar_kapali` parametresi) — sırada.
- İşçi, araç setinde olmayan şeyi (obje yaratma) uydurma araçla denemek yerine 15 adım harcadı; `max_steps` dolunca özet de yazmadı. Sunucu `ozet` boşsa bunu `hatalar`a "özet yok: adım sınırı" diye koymalı — sırada.
- Denetçi özetinin değeri sayıyla görüldü: aynı işçi, aynı görev, genel özet 2000 sn/çözüm yok, somut özet 130 sn/çözüm.

## Sırada
1. `worker_run`'a `araclar_kapali` (ör. play_observe'u denetçiye saklamak) ve "özet yok" hatası.
2. Lider takibi: ilk 3 sn geçişi (Start'ta halkayı liderin o anki konumuna göre kurup ilk Update'ten önce bir sert çözümleme).
3. Cursor'dan aynı akış (`.cursor/mcp.json` hazır, denenmedi — bu oturumda Cursor yok).
4. UPM paket yerleşimi + README (TR/EN, ekran görüntülü) — kullanıcı hedefi.

---

# Cursor denetçi deneyi — A: Cursor→çırak (2026-08-23 03:02–03:30, kullanıcı uzakta, nöbetçi izledi)

Kurulum: `~/.cursor/mcp.json`'a apprentice eklendi (unityMCP ile yan yana). Cursor'ın modeli denetçi,
`worker_run` çırak. Görev: 8 küre r=4 çemberde 45° aralıkla saat yönünde dönsün (12 sn/tur), y=0.5;
eski bileşenler kaldırılmadan kapatılsın. Ölçüm: `tests/devriye_olc.py` (bağımsız, 15 sn, Unity içi toplu örnekleme).

| iş | başlangıç | süre | ne oldu |
|---|---|---|---|
| 1 | 03:02:36 | >150 s → **Cursor iptal etti** | script yazıldı; sunucu iptali dinlemediği için işçi zombi kaldı (elle öldürdüm) |
| 2 | 03:05:06 | >150 s → iptal | Cursor önceki çıktıyı unityMCP ile okuyup "Update hatalı" dedi; `oturum` geçirmedi (yeni bağlam) |
| 3 | 03:07:43 | 143 s ✓ | sahne kurulumu; işçi SuruYoneticisi'ni kapattı ama **SuruDevriye'yi de kapattı**, istenmeyen `SuruDevreDisiYapici.cs` yazdı |
| 4 | 03:11:12 | 355 s → iptal | Cursor "SuruDevreDisiYapici SuruDevriye'yi de kapatıyor" diye yakaladı (doğru) |
| 5 | 03:18:57 | 238 s → iptal | Cursor "ters yön, 33.6 sn/tur" dedi (**yanlış**: yön uzlaşımı ve ölçüm hatası) |
| 6 | 03:23:52 | 359 s → iptal | "missing script" hatası: işçi yardımcı dosyayı **boşaltarak silmiş**, kırık bileşen kalmış; **33 kez** aynı dosyayı yazarak düzeltmeye çalıştı |

**Bağımsız ölçüm (son hal, 20 örnek):** yarıçap 3.999–4.001 (0 ihlal), komşu açı 45.0° (0 ihlal), y=0.5,
**tur 12.0 sn, saat yönü → GEÇTİ.** Kalan: Suru'da kırık bileşen + boş `SuruDevreDisiYapici.cs` (temizlik).

## Bulgular
1. **Cursor'ın araç zaman aşımı ~150 sn** < Unity turu (140–360 s). 6 işten 5'i iptal edildi; Cursor sonucu
   görmeden bir sonraki turu başlattı, ama unityMCP ile sahneyi okuyarak yine de doğru teşhis koydu.
   Düzeltme (commit `ff6b8bc`): sunucu `notifications/cancelled` alınca işçiyi öldürür; `bekle=false` +
   `worker_status` eklendi. Cursor'ın sunucu süreci eski koddaydı — MCP yenilenince devreye girer.
2. **Zombi işçiler**: iptal dinlenmeyince iki işçi aynı dosyaya paralel yazdı. Aynı düzeltme.
3. **Dosya boşaltarak silme** → kırık bileşen → düzeltilemez döngü (33 yazma). Düzeltme (`3c6e179`):
   `remove_missing_components` aracı (yalnızca kırık bileşen), hata mesajına çözüm ipucu, sistem istemine "boşaltma".
4. **Denetçi de yanılır**: Cursor yönü ters ve süreyi 33.6 sn okudu; benim ölçüm betiğim de ilk sürümde aynı iki
   hatayı yaptı (açı sarması + Unity saat yönü uzlaşımı). Düzeltilmiş ölçüm 12.0 sn, saat yönü. Denetçinin
   ölçüm aracı da doğrulanmalı — kriter "sayıyla" olunca hata görünür oldu.
5. Cursor `oturum` parametresini hiç kullanmadı (her tur yeni bağlam); görevleri kendi kendine yeterli yazdığı
   için iş yine yürüdü ama işçi her turda dosyaları baştan okudu.

## B: usta tek başına (Claude Code, çırak yok, Unity köprüsüyle doğrudan)

Cursor'ı dışarıdan süremediğim için B'yi kendim koştum: aynı görev, `SuruDevriyeB.cs`, denetçi=işçi=ben.

| tur | süre | ne oldu |
|---|---|---|
| 1 | 22 s | yazdı, ekledi, derlendi; ölçüm: dönüş YOK — Awake kırık bileşenin `null` girdisinde NRE attı (A'nın bıraktığı çöp) |
| 2 | 18 s | `b != null` kontrolü; ölçüm: **GEÇTİ** (r 3.999–4.001, 45.0°, y=0.5, tur 12.0 sn, saat yönü) |

Toplam ≈ 40 s yazma + 3 ölçüm (≈3 dk). A (Cursor→çırak): 6 iş, ≈28 dk, 5 iptal; sonuç aynı ölçümle GEÇTİ ama
sahne hijyeni bozuk kaldı.

## Cursor'ın kendi raporu (kullanıcı iletti)
Cursor 6. kriteri "KALDI: ters yön, 37.8 sn" diye değerlendirdi — **benim `devriye_olc.py`'nin hatalı ilk sürümüyle**
(açı sarması + saat yönü uzlaşımı). Düzeltilmiş ölçüm 12.0 sn / saat yönü. 2. kriter (SuruYoneticisi
açık, kırık bileşen) tespiti doğru. Cursor'ın özeti: "script gövdesi doğru, blokaj sahne hijyeni" — isabetli.

## A/B yorumu
- Bu görevde (küçük, tek dosya, deterministik geometri) **usta tek başına 10× hızlı**. Çırağın değeri bu
  boyutta görünmüyor; değer, usta-token'ının pahalı/kotalı olduğu ve işin uzun-çok dosyalı olduğu yerde.
- A'nın süresinin çoğu altyapı kaybı: zaman aşımı iptalleri (5/6) ve kırık bileşen döngüsü (33 yazma). İkisi de
  düzeltildi (iptal desteği, `remove_missing_components`); aynı deney tekrarlanırsa A'nın ≈10 dk'ya inmesi beklenir.
- Denetçinin ölçüm aracı yanlışsa denetçi yanlış karar verir (Cursor + benim betiğim). "Sayıyla kriter"
  bunu görünür kıldı; ölçüm betikleri artık sarmasız ve Unity uzlaşımıyla.
