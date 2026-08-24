# STATE.md — iş devri (en yeni üstte; kendi OpenMemory kuralımızın bu depoya uygulanması)

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
