# Apprentice · Unity

**A local model does the work, a frontier model supervises.**

This repository is the **self-contained** Apprentice distribution for Unity users: the apprentice
core, the Unity tool set (write/read script, add component, play-mode observation), compile and
play-mode verification, and the Q3CNFU Editor panel — plus the optional MCP server for Cursor and
Claude Code. Nothing else to clone.

A local model (Ollama, Qwen3-Coder-Next) writes the C#; **Unity's own compiler** decides whether it
worked, never the model's claim. Compiler errors go straight back to the model until they are gone,
and `play_observe` measures the actual runtime behaviour in numbers. The tool block is kept small on
purpose: 1.2k tokens instead of the full 20k MCP surface, re-sent every turn.

Not using Unity? The Unity-free version is [apprentice](https://github.com/malikkayaalp/apprentice).

---

# Türkçe

**A local model does the work, a frontier model supervises.** Bu depo, Unity kullanıcıları için
**tek başına yeterli** Apprentice dağıtımıdır: çırak çekirdeği + Unity araç seti + Q3CNFU Editor paneli
+ (isteğe bağlı) Cursor/Claude Code için MCP sunucusu. Başka bir depo gerekmez.

Yalnızca kod işi yapacak ve Unity kullanmayacaklar için Unity'siz sürüm: [apprentice](https://github.com/malikkayaalp/apprentice).

## Kurulum

1. **Bu depoyu indir**: `git clone https://github.com/malikkayaalp/apprentice-unity` (ya da zip).
2. **Ollama** kur, modeli indir: `ollama pull hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL` (~20 GB).
   Python 3.10+ gerekir (ek paket yok).
3. **Unity** 6000.0.x + [MCP for Unity](https://github.com/CoplayDev/unity-mcp) **v10.1.2**; pencerede Connect
   (HTTP Local `http://127.0.0.1:8080/mcp`).
4. **Panel**: `envs/unity/panel/Editor/` → projenin `Assets/Editor/Q3CNFU/` altına kopyala; aynı klasörde bu
   depoya bakan `Agent~` junction'ı oluştur: `mklink /J Agent~ C:\yol\apprentice-unity`
5. Unity'de **Window > Q3CNFU** (Ctrl+Shift+Q). Pencere python / ajan / Ollama / model / köprüyü kontrol
   eder, eksik adımı söyler. İstek yaz → çırak yazar, Unity derler, sonuç panelde.

## Cursor / Claude Code ile (isteğe bağlı)

Aynı depo MCP sunucusu da taşır: `~/.cursor/mcp.json` → `{"command": "python", "args": ["<depo>/server/apprentice_server.py"]}`.
`worker_run`'da `ortam="unity"` ve `ortam="code"` seçenekleri gelir. Sözleşme: [server/README.md](server/README.md).

## Yapı

```
envs/unity/          Unity ortamı: araçlar (write/read_script, add_component, play_observe…), derleme/play doğrulama
envs/unity/panel/    Q3CNFU Editor paneli (C#)
envs/unity/tests/    Unity kabul/ölçüm betikleri
envs/code/           genel kod ortamı
core/ mcpbridge/     çırak çekirdeği (apprentice deposuyla aynı; git merge ile güncellenir)
server/ clients/web/ MCP sunucusu ve izleme sayfası
```

Unity'ye özgü ölçülmüş kararlar: [envs/unity/README.unity.md](envs/unity/README.unity.md).
Kanıtlar ve deneyler: [apprentice-lab](https://github.com/malikkayaalp/apprentice-lab).

## Çekirdeği güncellemek (geliştirici)

```bash
git remote add cekirdek https://github.com/malikkayaalp/apprentice.git   # bir kez
git fetch cekirdek main && git merge cekirdek/main
```
