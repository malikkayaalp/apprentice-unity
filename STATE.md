# STATE.md — iş devri (en yeni üstte; kendi OpenMemory kuralımızın bu depoya uygulanması)

## 2026-08-24 (gece 2): derin denetim + dizilim presetleri

**Yapilan:** dort paralel denetci (kurulum / panel arka uc / panel on uc / cekirdek) tum yapiyi
okudu; bulunan hatalarin agir olanlari duzeltildi ve CANLI dogrulandi. Panele "dizilim"
(preset) sistemi eklendi: 7 hazir yerlesim + kullanicinin 💾 duzeni, elle tasiyinca secici
"ozel"e duser. tests/test_panel.py presetleri de denetler (cakisma/tasma/eksik panel).

**Kapatilan agir kusurlar (hepsi olculu/dogrulanmis):**
- GUVENLIK: panel uclari CSRF'ye acikti - tarayicidaki herhangi bir site 127.0.0.1'e "basit
  istek" atip /api/usta uzerinden KEYFI KOMUT calistirabiliyordu. Cozum: Origin/Referer
  dogrulamasi + zorunlu "X-Apprentice: panel" basligi (capraz kokenden preflight'siz
  gonderilemez). Dogrulandi: basliksiz 403, yabanci Origin 403, panel 200.
- GUVENLIK: calisma_dizini "C:kotu" gibi SURUCU-GORELI yolla calisma alanindan cikabiliyordu
  (ntpath.isabs False der ama join kokeni yok sayar). splitdrive + realpath kontrolu eklendi.
- Kurulum: tek yorum satirli (JSONC) bir IDE ayar dosyasi TUM kurulumu "EKSIK" yapiyordu
  (ide adimi False -> ozet penceresi hic acilmiyordu). Yorum soyucu + "okunamazsa DOKUNMA,
  kurulumu dusurme" kurali.
- Panel on uc: 500 olaydan sonra GOREV/PROMPT/SISTEM kartlari kalici siliniyordu (budama
  akisin ilk cocugunu, yani giris kabini yiyordu).
- Panel on uc: is degistirince ucustaki cevap ESKI isin olaylarini yeni akisa basip imleci
  ileri aliyordu -> yeni isin olaylari kalici kayip. Istek kimligi dogrulanarak cozuldu.
- Panel on uc: tek "takip" bayragi hem "akisi dibe kilitle" hem "en yeni isi sec" demekti;
  akisi kaydirinca panel kullanicinin baktigi isi caliyordu. Iki ayri bayrak (otoSec/dibeKilit).
- Panel on uc: "Claude'a giris yap" dugmesi 2.5 sn sonra sohbet yeniden cizilince siliniyordu
  (fiilen tiklanamaz). Uyari artik durumda yasar, olay delegasyonu ile baglanir.
- Panel on uc: usta sohbeti her yoklamada TAMAMLANMIS her cevap icin ayri HTTP istegi atiyordu
  (30 mesaj = tur basina 30 istek). Onbellek eklendi.
- Panel on uc: is ozetinde kacis yoktu (baslik/ortam/durum ham innerHTML) - "<b" iceren baslik
  paneli bozardi. Ayrica sohbet kipinde cift gonderim korumasi yoktu.
- Izgara: dikey kaydirma cubugu belirince ic genislik daraliyor, en sag sutun ~6 px tasip
  overflow-x:hidden ile ERISILEMEZ oluyordu (boyutlandirma tutamagi dahil). hucre() artik
  clientWidth/Height okur + scrollbar-gutter:stable + tek seferlik yeniden yerlestirme.
- Sunucu: Windows'ta proc.kill() torun surecleri (pytest/run_shell/ruff) OLDURMUYORDU - is
  "bitti" gorunurken calisma dizinine yazmaya devam edebiliyordu. taskkill /T + iptalde
  gercek olume kadar sinirli bekleme (exit olayi eksik kalmiyor).
- Izleyici: events.jsonl artimli okumada YARIM SATIR "bozuk JSON" diye atlanip ofset
  ilerletiliyordu -> 20 KB'lik bir olay bir daha hic okunmuyordu (MCP raporu dogru, izleyici
  eksik). Artik yalniz tam satirlar islenir.
- core/client.py: OLLAMA adresi SABITTI; ollama.url ayari yalniz rag/precheck tarafindan
  okundugu icin uzak sunucu tanimlayan kullanicida on kontrol "model var" derken isci
  localhost'a gidip dusuyordu. Artik ayardan okunur.
- canli kipte BOS CEVAP korumasi yoktu (native yolda EMPTY_NUDGE var): is bos halde
  "basarili" bitebiliyordu. Iki kip artik ayni sozlesmeyi verir.
- panel.py: --home ile verilen ev, ortamda APPRENTICE_HOME varsa EZILMIYORDU (setdefault) ->
  isler baska eve yazilip listede hic gorunmuyordu.
- panel.py: model karti ctx kiyaslamasi olmayan bir ayar anahtarini (ollama.num_ctx) okuyordu;
  dogrusu makine.num_ctx.
- kur.py: kisayol_yaz her kosulda True donuyordu (kisayol yokken adim "[ok]"); masaustu
  OneDrive yonlendirmesinde bulunamiyordu; PowerShell tirnak kacisi yoktu. model_uygula()
  hic cagrilmayan olu koddu - artik model dogrulaninca kart bazli ayar yaziyor.
- panel_ac.py: 8788'i tutan YABANCI uygulama "bizim panel" sanilabiliyordu (herhangi bir 200);
  sunucu kalkmazsa sessizce olu URL aciliyordu. Uc kimligi dogrulaniyor, hata penceresi cikiyor.

**Denetimde gorulup DUZELTILMEYENLER (bilincli, sirada):** rapor_diskten ile report()
sozlesme farki (olcumler/kriterler eksik); XML arac ayristiricisinin icerikte </parameter>
gecerse kesmesi; yazilabilir kilidinin run_shell ile delinebilmesi; apprentice.config.json
sampling/prompt bloklarinin hic okunmamasi; RAG gomme parmak izi olmamasi; canli.txt'nin
atomik olmayan yazimi; usta_istekler klasorunun sinirsiz buyumesi.

## 2026-08-24 gece: Web Panel büyük iterasyonu (v3) — devir

**Ne yapıldı:** `clients/web/panel.py` + `panel.html` — çift sohbetli dashboard:
USTA (Claude CLI, başsız `claude -p`, model/effort/özel-CLI seçimli, 📎 dosya+resim ekli, balonlu)
ve ÇIRAK (⚙ görev kipi = worker_run boru hattı + 💬 sohbet kipi = akışlı düz konuşma).
Akıllı ızgara yerleşimi (snap + itme + sıkıştırma, 💾 kalıcı profil), boru hattı filtresi,
kaynak rozetleri (ÇIRAK/USTA→/→USTA/SİSTEM/HARNESS), DOSYA GÖRÜNTÜLEYİCİ, çalışma alanı
seçici (yerel klasör diyaloğu → `panel_ayar.json`), model kartı/ısıt/⏏eject, İLK BAĞLAM metriği.

**Koddan görünmeyen kritik kararlar:**
- Usta prompt'u `claude`ya **STDIN'den** gider. Sebep (yaşandı): `shell=True` + çok satırlı
  prompt argümanında cmd.exe satır sonunu komut ayracı sayar — yalnız İLK satır ulaşır.
  Ek yolları ve `canli:true` notunun sessiz düşmesinin kökü buydu. Bayraklar tek satır kalmalı.
- `canli.txt` **tam metin** yazılır (kayan pencere yasak: ön-ek değişince izleyiciler "yeni tur"
  sanıp daktiloyu baştan oynatır — Kalman sonsuz-tekrar görünümü) ve iş sonunda **silinmez**
  (son üretim panelde kalır); tur sonu yazımı kısma atlar (`zorla`).
- MCP/usta işlerinde `canli` varsayılanı KAPALI; panel, araç izinli usta isteğine
  "worker_run'da canli:true kullan" notunu otomatik ekler.
- Panel işlerinde `usta_rapor` olayını MCP yolu yazmaz → panel `_usta_rapor_tamamla` ile
  iş bitince kendisi işler. `worker_status`'a disk yedeği eklendi (başka sürecin işi görünür).
- Panelden iş → `panel_bekleyen.json` → MCP sunucusu ustanın SONRAKİ her araç sonucuna
  `panel_bildirimi` iliştirir (MCP'de push yok; bu en dürüst kanal).
- Sahipsiz usta isteği: 700 sn üstü "çalışıyor" → "hata" (panel yeniden başlarsa iş parçacığı ölür).
- Yerleşim anahtarı `apprentice_yerlesim_v4`te SABİTLENDİ — göçler yerinde yapılır, anahtar
  bir daha değişmez (v3→v4 kullanıcının düzenini sıfırladı, tekrarlanmayacak).

**Denenip ELENENLER:** reranker (ölçüm: bge-m3 top-1 5/6 yeterli — torch yığını kurulmadı);
token-daktilo native tool kanalında (Ollama argümanları akıtmıyor, ölçüldü: 44 s tek chunk —
çözüm XML-içerik protokolü `canli=true`, ölçüldü: aynı kalite, prompt −%31);
ızgarasız serbest sürükleme (üst üste binme şikâyeti — gridstack-mini'ye geçildi).

**Bekleyenler:** panel testleri yok (test_panel.py yazılmadı — davranışlar tarayıcı içi
programatik sınamayla doğrulandı); usta sohbeti oturum-sürekliliği (`--continue`) bilinçli
kapalı; Unity açılınca: api_ara canlı sınavı + capability-pack A/B.

## 2026-08-24 (daha erken): ölçüm + yardımcı katman devri
Ayrıntı `APPRENTICE_RAPOR.md`'de (lab deposu): dur sinyali, determinizm, ara=adreslenebilirlik,
ruff/harita/reranker/128k kararları, STATE/AGENTS entegrasyonu, izleyici v1-v4.
