# Apprentice

**A local model does the work, a frontier model supervises.**

Yerel bir kodlama modeli (Ollama, Qwen3-Coder-Next) işi yapar: dosya yazar, araç çağırır,
test koşar, hatayı düzeltir. Büyük bir model (IDE'nizdeki Claude/GPT/Gemini ya da Claude Code)
denetler: görevi kabul kriterleriyle verir, dönen ölçümü yorumlar, ne zaman durulacağına karar
verir. Kod dışarı çıkmaz, kota yoktur; denetçiye yalnızca özetler ve ölçümler gider.

Türkçede *Çırak*. Usta bakar, çırak yapar.

## Neden bu bölünme (ölçüldü)

- Aynı işçi, aynı görev: ham ölçümü kendisi yorumlayıp düzeltmeye kalkınca yakınsamadı; ölçüm
  **özetlenip** "şu kural tutmuyor" diye verilince 2 turda çözdü.
- 6 görevlik kod kampanyası (gizli denetçi kontrolleri): tur-1 34/36 → denetçinin somut geri
  bildirimiyle 36/36. Genel geri bildirim ("test tutmuyor") 2×1000 sn'de çözemediğini, somut özet
  130 sn'de çözdü.
- Kriterler baştan sayıyla verilince işçi sonradan öğretilmesi gereken deseni kendiliğinden kurdu.

Kanıtlar ve bütün deneyler [apprentice-lab](https://github.com/malikkayaalp/apprentice-lab) deposunda.

## Yapı

```
server/          MCP sunucusu: worker_run(görev, kabul_kriterleri, ortam) — bkz. server/README.md
core/            Ollama istemcisi, şema koruması, ayar yükleyici, ilk-çalıştırma ölçümü
mcpbridge/       MCP taşıma (stdio + Streamable HTTP), bağımlılıksız; test için fake_server
envs/code/       kod ortamı: dosya oku/yaz, shell, test; workspace'e hapis; compile()+unittest/pytest doğrulayıcı
envs/fake/       duman testi ortamı (model gerektirmez)
envs/<eklenti>/  eklentiler buraya klonlanır ve otomatik keşfedilir (örn. apprentice-unity)
clients/web/     canlı izleme sayfası: python clients/web/monitor.py → http://127.0.0.1:8765
tests/           sözleşme testleri, kod ortamı testi, ölçüm kampanyası
```

## Gereksinimler

- Python 3.10+ (ek paket yok, stdlib)
- [Ollama](https://ollama.com) + `ollama pull hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL` (~20 GB)

## Kurulum (Cursor / Claude Code / VS Code)

```bash
git clone https://github.com/malikkayaalp/apprentice
```

Claude Code: depodaki `.mcp.json` otomatik görülür. Cursor: `~/.cursor/mcp.json`'a ekle:

```json
{ "mcpServers": { "apprentice": { "command": "python", "args": ["<depo>/server/apprentice_server.py"] } } }
```

Yol yazmanız gerekmez: işçi, IDE'nin bildirdiği workspace köküne hapsedilir (MCP `roots`).
Sohbette: *"Sen denetçisin; kodu kendin yazma, apprentice.worker_run'a ver. Kabul kriterlerini
sayıyla yaz, dönen sonucu kendin doğrula."* Araçlar, dönüş şeması ve kurallar: [server/README.md](server/README.md).

İlk çalıştırmada makineye özel hız ayarı için `python core/olcum.py --yaz` (num_batch; ölçüldü: 512 → 4096 arası +%342 prefill).

## Eklentiler

Ortamlar `envs/<ad>/env.json` ile keşfedilir; çekirdek yalnızca `code` içerir. Oyun motoru gibi
alanlar ayrı depolardır ve `envs/<ad>` olarak klonlanır:

- [apprentice-unity](https://github.com/malikkayaalp/apprentice-unity) — Unity araç seti + derleme/play
  doğrulaması + Q3CNFU Editor paneli. Klonlanınca `worker_run`'da `ortam="unity"` belirir.

## Ölçülmüş tasarım kararları

- Başarı **doğrulayıcıyla** (derleyici, test) belirlenir, modelin beyanıyla değil; `ozet` beyandır.
- Ölçüm ham döner, yorum denetçide; işçi ölçüm-düzeltme döngüsüne sokulmaz (`araclar_kapali`).
- Silme aracı yok; `run_shell`'de silme ve `git push` reddedilir.
- İşçi ayrık süreç; istemci iptal ederse öldürülür (Cursor'ın ~150 sn zaman aşımı ölçüldü →
  `bekle=false` + `worker_status`).
- Araç bloğu küçük ve sabit tutulur: her turda yeniden gönderilir, kullanılmayan araç kalıcı vergidir.

## Test

```bash
python tests/test_server.py        # model gerekmez
python tests/test_code_env.py      # kod ortamı; --live ile gerçek görev
python tests/code_kampanya.py      # 6 görevlik ölçüm kampanyası (Ollama gerekir)
```
