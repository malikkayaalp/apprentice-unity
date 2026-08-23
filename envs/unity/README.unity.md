# apprentice-unity

Apprentice'ın Unity ortamı: çırağın Unity araç seti, derleme/play doğrulaması ve Q3CNFU Editor paneli.

## Kurulum

Bu klasör tek başına çalışmaz; kurulum deponun kökündeki [README](../../README.md)'de (çekirdek + Unity tek depoda).

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
