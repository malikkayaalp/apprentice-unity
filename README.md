# apprentice-unity

[Apprentice](https://github.com/malikkayaalp/apprentice) için Unity eklentisi: çırağın Unity araç seti,
derleme/play doğrulaması ve Q3CNFU Editor paneli. Çekirdek (`apprentice`) olmadan çalışmaz; Cursor/Claude
Code ile yalnızca kod işi yapanların buna ihtiyacı yoktur.

## Kurulum

1. Çekirdeği kur: `git clone https://github.com/malikkayaalp/apprentice`
2. Bu depoyu çekirdeğin `envs/unity` klasörü olarak klonla:
   ```bash
   git clone https://github.com/malikkayaalp/apprentice-unity apprentice/envs/unity
   ```
   Bundan sonra `worker_run`'da `ortam="unity"` seçeneği belirir (Cursor / Claude Code).
3. Unity tarafı: Unity 6000.0.x + [MCP for Unity](https://github.com/CoplayDev/unity-mcp) **v10.1.2**,
   HTTP Local `http://127.0.0.1:8080/mcp` (Editor'de Connect).

## Q3CNFU paneli (Unity içinden, IDE'siz)

1. `panel/Editor/` → projenin `Assets/Editor/Q3CNFU/` altına kopyala.
2. Aynı klasörde `Agent~` adında junction oluştur, **çekirdek** depoya baksın:
   `mklink /J Agent~ C:\yol\apprentice` (panel `Agent~/envs/unity/panel_runner.py`'yi bulur).
3. Window > Q3CNFU (Ctrl+Shift+Q). Pencere python / ajan / Ollama / model / köprüyü kendisi kontrol eder.

## İçerik

```
env.json             ortam tanımı (çekirdek bunu keşfeder)
panel_runner.py      tek isteği ayrı süreçte koşturan koşucu (panel ve sunucu ortak)
unity_code.py        araçlar (write/read_script, add_component, set_field, play_observe…) + derleme/play döngüsü
unity_assets.py      varlık/sahne araçları (C# üretir, execute_code ile çalıştırır)
unity_csharp_eval.py MCP for Unity köprüsü yardımcıları
unity_sandbox.py     kapalı alan dosya araçları (varsayılan kapalı)
panel/Editor/        Q3CNFU paneli (C#, 15 dosya)
tests/               kabul ve ölçüm betikleri (suru_kabul, lider_olc, devriye_olc, panel_drive, test_jail)
```

Komut satırından: `python unity_code.py "Player objesine WASD ile hareket eden bir script yaz"`.

## Ölçülmüş kararlar

- Başarı **Unity derleyicisiyle** doğrulanır, modelin beyanıyla değil. Play modu derleyicinin görmediği
  3 hata sınıfını yakaladı; `play_observe` davranışı sayıyla ölçer (editör arka planda da çalışır,
  örnekler Unity içinde 0.5 sn'de biriktirilir).
- Araç seti 1.2k token (MCP for Unity'nin tam yüzeyi 20k; her turda yeniden gönderilir).
- Silme aracı yok; tek istisna `remove_missing_components` (yalnızca kırık bileşen).
- Kanıtlar: [apprentice-lab](https://github.com/malikkayaalp/apprentice-lab).
