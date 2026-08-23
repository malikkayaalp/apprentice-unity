// Assets/Editor/Q3CNFU/Q3Window.cs
// Unity icinde yerel model (Ollama) ajan sohbeti.
//
// Menu: Window > Q3CNFU (Ctrl+Shift+Q)
//
// Ajan (panel_runner.py) AYRIK bir surectir ve ciktisini bir dosyaya yazar;
// pencere dosyayi takip eder. Unity script derleyip domain reload yapsa bile
// akis kopmaz ve ana is parcacigi 60-200 saniyelik model cevaplarinda bloke
// olmaz. Sohbet baglami da surec disinda, Library/Q3CNFU/sessions'ta yasar.
//
// Bilerek OLMAYAN sey: "onaysiz calistir" anahtari. Koruma panelde degil,
// Python tarafindaki arac hapishanesinde (unity_sandbox.py); reddedilen bir
// komutun yine de calistigi bir vaka yasandi, o yuzden panel yetki dagitmaz.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Q3CNFU.EditorTools
{
    [Serializable]
    internal class Q3Message
    {
        public const int RoleUser = 0;
        public const int RoleAgent = 1;
        public const int RoleTool = 2;
        public const int RoleNote = 3;
        public const int RoleError = 4;

        public int Role;
        public string Text = "";
        public bool Streaming;

        // Arac satirlari icin: argumanlar + sonuc. Tiklayinca acilir.
        public string Detail = "";
        public bool Expanded;

        // Gorunum onbellegi: domain reload'da yeniden uretilir.
        [NonSerialized] public List<MdBlock> Blocks;
        [NonSerialized] public string[] Display;
        [NonSerialized] public bool[] RichText;
        [NonSerialized] public string CacheKey;
    }

    public class Q3Window : EditorWindow
    {
        private const string PrefModel = "Q3CNFU.Model";
        private const string PrefPlay = "Q3CNFU.Play";
        private const string PrefRepairs = "Q3CNFU.Repairs";
        private const string PrefErrors = "Q3CNFU.IncludeErrors";
        private const string PrefHighlight = "Q3CNFU.Highlight";
        private const string PrefAutoOpenDiff = "Q3CNFU.AutoOpenDiff";
        private const string PrefScale = "Q3CNFU.Scale";

        // Olculen: 6 model icinde kod yazmada anlamli bicimde onde olan tek model.
        private const string DefaultModel = "hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL";

        private const int MaxDisplayChars = 12000;

        // --- kalici durum (domain reload'i asar) ---
        [SerializeField] private List<Q3Message> _messages = new List<Q3Message>();
        [SerializeField] private List<string> _touched = new List<string>();
        [SerializeField] private RunHandle _run;
        [SerializeField] private long _runStartedAtMs;
        [SerializeField] private string _chatId = "";
        [SerializeField] private string _input = "";
        [SerializeField] private Vector2 _scroll;
        [SerializeField] private int _streamIndex = -1;
        [SerializeField] private bool _showSettings;
        [SerializeField] private bool _showHistory;
        [SerializeField] private Vector2 _historyScroll;

        // --- ayarlar ---
        private string _model = "";
        private bool _play;
        private int _repairs = 3;
        private bool _includeErrors;
        private bool _highlight = true;
        private bool _autoOpenDiff;
        private float _scale = 1f;
        private string _agentDir = "";
        private string _pythonExe = "";
        private string _ollamaUrl = "";
        private string _bridgeUrl = "";

        // --- calisma zamani ---
        [NonSerialized] private bool _reloading;
        [NonSerialized] private bool _pendingSend;
        [NonSerialized] private bool _clearFocus;
        [NonSerialized] private bool _stickToBottom = true;
        [NonSerialized] private double _lastLivenessCheck;
        [NonSerialized] private string _renamingChatId;
        [NonSerialized] private string _renameBuffer = "";

        private bool Busy { get { return _run != null && _run.Active; } }

        [MenuItem("Window/Q3CNFU %#q")]
        public static void Open()
        {
            var w = GetWindow<Q3Window>("Q3CNFU");
            w.minSize = new Vector2(420, 420);
            w.Show();
        }

        private void OnEnable()
        {
            _model = EditorPrefs.GetString(PrefModel, DefaultModel);
            _play = EditorPrefs.GetBool(PrefPlay, false);
            _repairs = Mathf.Clamp(EditorPrefs.GetInt(PrefRepairs, 3), 0, 6);
            _includeErrors = EditorPrefs.GetBool(PrefErrors, false);
            _highlight = EditorPrefs.GetBool(PrefHighlight, true);
            _autoOpenDiff = EditorPrefs.GetBool(PrefAutoOpenDiff, false);
            _scale = Mathf.Clamp(EditorPrefs.GetFloat(PrefScale, 1f), Q3Styles.MinScale, Q3Styles.MaxScale);
            _agentDir = EditorPrefs.GetString(Q3Setup.PrefAgentDir, "");
            _pythonExe = EditorPrefs.GetString(Q3Setup.PrefPython, "");
            _ollamaUrl = EditorPrefs.GetString(Q3Setup.PrefOllama, Q3Setup.DefaultOllama);
            _bridgeUrl = EditorPrefs.GetString(Q3Setup.PrefBridge, Q3Setup.DefaultBridge);

            _reloading = false;

            EditorApplication.update += Pump;
            EditorApplication.quitting += OnQuitting;
            AssemblyReloadEvents.beforeAssemblyReload += OnBeforeAssemblyReload;
        }

        private void OnDisable()
        {
            EditorApplication.update -= Pump;
            EditorApplication.quitting -= OnQuitting;
            AssemblyReloadEvents.beforeAssemblyReload -= OnBeforeAssemblyReload;

            Q3History.Save(_chatId, _messages, _model);

            // Domain reload sirasinda pencere yeniden kurulacak; sureci
            // oldurmuyoruz, cikti dosyasindan kaldigi yerden devam edecek.
            if (!_reloading) StopRun(false);
        }

        private void OnBeforeAssemblyReload()
        {
            _reloading = true;
        }

        private void OnQuitting()
        {
            StopRun(false);
        }

        private void OnFocus()
        {
            if (!Busy) Q3Setup.Invalidate();
        }

        // ===================================================================
        // GUI
        // ===================================================================

        private void OnGUI()
        {
            Q3Styles s = Q3Styles.Get(_scale);
            HandleShortcuts();

            if (_clearFocus && Event.current.type == EventType.Layout)
            {
                GUIUtility.keyboardControl = 0;
                _clearFocus = false;
            }

            DrawToolbar(s);
            if (_showSettings) DrawSettings(s);
            DrawSetupPanel(s);

            if (_showHistory) DrawHistoryPanel(s);

            DrawTranscript(s);
            DrawComposer(s);
        }

        private void HandleShortcuts()
        {
            Event e = Event.current;
            if (e.type != EventType.KeyDown) return;

            bool enter = e.keyCode == KeyCode.Return || e.keyCode == KeyCode.KeypadEnter;
            if (!enter || (!e.control && !e.command)) return;

            // Gonderimi Pump'a birakiyoruz: OnGUI ortasinda duzen degistirmek
            // IMGUI'de layout uyumsuzlugu hatasi verir.
            if (!Busy && !string.IsNullOrWhiteSpace(_input)) _pendingSend = true;
            e.Use();
        }

        private void DrawToolbar(Q3Styles s)
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                GUILayout.Label(Busy ? "● Calisiyor" : "○ Hazir", EditorStyles.miniLabel, GUILayout.Width(74));

                GUILayout.Label(string.IsNullOrEmpty(_chatId) ? "yeni sohbet" : "#" + Shorten(_chatId),
                                s.Caption, GUILayout.Width(96));

                GUILayout.FlexibleSpace();

                if (GUILayout.Button("Yeni sohbet", EditorStyles.toolbarButton, GUILayout.Width(84)))
                    NewChat();

                int changeCount = Q3Changes.All.Count;
                if (GUILayout.Button(new GUIContent("Degisiklikler (" + changeCount + ")",
                                                    "Ajanin degistirdigi dosyalari ayri pencerede goster."),
                                     EditorStyles.toolbarButton, GUILayout.Width(120)))
                    Q3DiffWindow.Reveal();

                bool wantHistory = GUILayout.Toggle(_showHistory, "Gecmis", EditorStyles.toolbarButton,
                                                    GUILayout.Width(60));
                if (wantHistory != _showHistory)
                {
                    _showHistory = wantHistory;
                    if (_showHistory) Q3History.Save(_chatId, _messages, _model);
                }

                _showSettings = GUILayout.Toggle(_showSettings, "Ayarlar", EditorStyles.toolbarButton,
                                                 GUILayout.Width(60));
            }
        }

        // --- kurulum paneli --------------------------------------------------

        private void DrawSetupPanel(Q3Styles s)
        {
            if (Busy) return;

            SetupState state = Q3Setup.Check(_model, false);
            if (state == SetupState.Ready) return;

            using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
            {
                switch (state)
                {
                    case SetupState.Unknown:
                        GUILayout.Label(Q3Setup.IsChecking
                                            ? "Kurulum durumu kontrol ediliyor..."
                                            : "Kurulum durumu: " + Q3Setup.Detail,
                                        s.Caption);
                        break;

                    case SetupState.NoPython:
                        EditorGUILayout.HelpBox(
                            "1/5  Python 3 bulunamadi.\n" +
                            "python.org'dan kur (kurulumda \"Add to PATH\" isaretli olsun) ya da " +
                            "Ayarlar'dan python.exe yolunu ver. Unity acilmadan once kurulduysa " +
                            "Unity'nin PATH'i eski olabilir; yeniden baslat.",
                            MessageType.Info);
                        DrawRetry("Yeniden ara");
                        break;

                    case SetupState.NoAgent:
                        EditorGUILayout.HelpBox(
                            "2/5  Ajan betikleri (panel_runner.py) bulunamadi.\n" +
                            "Paketin yanindaki Agent~ klasorunde aranir; baska yerdeyse " +
                            "Ayarlar > Ajan klasoru.",
                            MessageType.Info);
                        using (new EditorGUILayout.HorizontalScope())
                        {
                            if (GUILayout.Button("Klasor sec...", GUILayout.Height(22), GUILayout.Width(110)))
                                PickAgentDir();
                            DrawRetry("Yeniden ara");
                        }
                        break;

                    case SetupState.NoOllama:
                        EditorGUILayout.HelpBox(
                            "3/5  Ollama cevap vermiyor: " + Q3Setup.OllamaUrl + "\n" +
                            "Ollama'yi baslat (tepsi uygulamasi ya da terminalde `ollama serve`). " +
                            "Bu pencere durumu kendisi izler.",
                            MessageType.Warning);
                        DrawRetry("Tekrar dene");
                        break;

                    case SetupState.NoModel:
                        EditorGUILayout.HelpBox(
                            "4/5  Model cekilmemis: " + _model + "\n" +
                            "Indirme on GB'larca surebilir; dugme gorunur bir terminalde " +
                            "`ollama pull` baslatir, ilerlemeyi orada gorursun.",
                            MessageType.Info);
                        using (new EditorGUILayout.HorizontalScope())
                        {
                            if (GUILayout.Button("Modeli indir", GUILayout.Height(22), GUILayout.Width(110)))
                                RunPull();
                            DrawRetry("Tekrar dene");
                        }
                        break;

                    case SetupState.NoBridge:
                        EditorGUILayout.HelpBox(
                            "5/5  Unity MCP koprusu dinlemiyor: " + Q3Setup.BridgeUrl + "\n" +
                            "Window > MCP for Unity penceresinde Connect'e bas.",
                            MessageType.Warning);
                        DrawRetry("Tekrar dene");
                        break;
                }

                if (!string.IsNullOrEmpty(Q3Setup.Detail) && state != SetupState.Unknown)
                    GUILayout.Label(Q3Setup.Detail, s.Caption);
            }
        }

        private void DrawRetry(string label)
        {
            if (GUILayout.Button(label, GUILayout.Height(22), GUILayout.Width(110)))
            {
                Q3Setup.Invalidate();
                Q3Setup.Check(_model, true);
                Repaint();
            }
        }

        private void RunPull()
        {
            string error;
            if (!Q3Models.StartPull(_model, out error))
            {
                AddMessage(Q3Message.RoleError, "Indirme baslatilamadi: " + error);
                return;
            }

            AddMessage(Q3Message.RoleNote,
                       "Indirme penceresi acildi. Bitince bu pencere modeli kendisi gorur.");
            Repaint();
        }

        private void PickAgentDir()
        {
            string picked = EditorUtility.OpenFolderPanel("panel_runner.py klasoru", _agentDir, "");
            if (string.IsNullOrEmpty(picked)) return;

            _agentDir = picked;
            EditorPrefs.SetString(Q3Setup.PrefAgentDir, _agentDir);
            Q3Setup.Invalidate();
            Repaint();
        }

        // --- gecmis ----------------------------------------------------------

        private void DrawHistoryPanel(Q3Styles s)
        {
            List<HistoryEntry> entries = Q3History.List();

            using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    GUILayout.Label("Gecmis sohbetler (" + entries.Count + ")", s.RoleLabel);
                    GUILayout.FlexibleSpace();
                    if (GUILayout.Button("Kapat", s.MiniButton, GUILayout.Width(56)))
                        _showHistory = false;
                }

                if (entries.Count == 0)
                {
                    GUILayout.Label("Henuz kayitli sohbet yok.", s.Caption);
                    return;
                }

                _historyScroll = EditorGUILayout.BeginScrollView(
                    _historyScroll, GUILayout.MinHeight(80), GUILayout.MaxHeight(220 * s.Scale));

                foreach (HistoryEntry entry in entries)
                    DrawHistoryRow(s, entry);

                EditorGUILayout.EndScrollView();
            }
        }

        private void DrawHistoryRow(Q3Styles s, HistoryEntry entry)
        {
            bool isCurrent = string.Equals(entry.ChatId, _chatId, StringComparison.OrdinalIgnoreCase);
            bool renaming = string.Equals(entry.ChatId, _renamingChatId, StringComparison.OrdinalIgnoreCase);

            using (new EditorGUILayout.VerticalScope(isCurrent ? s.UserBubble : s.HistoryRow))
            {
                if (renaming)
                {
                    using (new EditorGUILayout.HorizontalScope())
                    {
                        _renameBuffer = EditorGUILayout.TextField(_renameBuffer, s.Input);

                        if (GUILayout.Button("Kaydet", s.MiniButton, GUILayout.Width(58)))
                        {
                            Q3History.SetTitle(entry.ChatId, _renameBuffer);
                            _renamingChatId = null;
                            GUI.FocusControl(null);
                            Repaint();
                        }

                        if (GUILayout.Button("Iptal", s.MiniButton, GUILayout.Width(50)))
                        {
                            _renamingChatId = null;
                            GUI.FocusControl(null);
                            Repaint();
                        }
                    }
                }
                else
                {
                    GUILayout.Label((isCurrent ? "● " : "") + entry.Title, s.RoleLabel);
                }

                if (!string.IsNullOrEmpty(entry.Preview))
                    GUILayout.Label(entry.Preview, s.Caption);

                using (new EditorGUILayout.HorizontalScope())
                {
                    string info = entry.UpdatedAt.ToString("dd.MM.yyyy HH:mm");
                    if (entry.MessageCount > 0) info += "   •   " + entry.MessageCount + " mesaj";

                    GUILayout.Label(info, s.Caption);
                    GUILayout.FlexibleSpace();

                    using (new EditorGUI.DisabledScope(Busy || isCurrent))
                    {
                        if (GUILayout.Button("Ac", s.MiniButton, GUILayout.Width(44)))
                            OpenHistory(entry);
                    }

                    if (GUILayout.Button(new GUIContent("Ad ver", "Basligi elle yaz"),
                                         s.MiniButton, GUILayout.Width(60)))
                    {
                        _renamingChatId = entry.ChatId;
                        _renameBuffer = entry.Title;
                        Repaint();
                    }

                    if (GUILayout.Button("Sil", s.MiniButton, GUILayout.Width(44)))
                        DeleteHistory(entry);
                }
            }
        }

        private void OpenHistory(HistoryEntry entry)
        {
            Q3History.Save(_chatId, _messages, _model);

            _messages = Q3History.Load(entry.ChatId);
            _chatId = entry.ChatId;
            _streamIndex = -1;
            _touched.Clear();
            _scroll = new Vector2(0, float.MaxValue);
            _showHistory = false;

            Repaint();
        }

        private void DeleteHistory(HistoryEntry entry)
        {
            if (!EditorUtility.DisplayDialog("Q3CNFU",
                    "Bu sohbet silinsin mi?\n\n" + entry.Title +
                    "\n\nHem panel dokumu hem modelin baglam dosyasi silinir.",
                    "Sil", "Vazgec"))
                return;

            Q3History.Delete(entry.ChatId);
            DeleteSessionFile(entry.ChatId);

            if (string.Equals(entry.ChatId, _chatId, StringComparison.OrdinalIgnoreCase))
            {
                _messages.Clear();
                _chatId = "";
            }

            Repaint();
        }

        /// <summary>Modelin gordugu baglam panel_runner.py'nin dosyasinda; dokum
        /// silinip baglam kalirsa "bos" gorunen sohbet aslinda dolu olur.</summary>
        private static void DeleteSessionFile(string chatId)
        {
            try
            {
                string p = Path.Combine(Q3Runner.ProjectRoot(), "Library", "Q3CNFU", "sessions",
                                        chatId + ".json");
                if (File.Exists(p)) File.Delete(p);
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[Q3CNFU] Baglam dosyasi silinemedi: " + ex.Message);
            }
        }

        // --- ayarlar ---------------------------------------------------------

        private void DrawSettings(Q3Styles s)
        {
            using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
            {
                EditorGUI.BeginChangeCheck();

                using (new EditorGUILayout.HorizontalScope())
                {
                    _agentDir = EditorGUILayout.TextField(
                        new GUIContent("Ajan klasoru", "panel_runner.py'nin bulundugu klasor. " +
                                                       "Bos birakilirsa paket ici Agent~ aranir."),
                        _agentDir);
                    if (GUILayout.Button("...", GUILayout.Width(26))) PickAgentDir();
                }

                using (new EditorGUILayout.HorizontalScope())
                {
                    _pythonExe = EditorGUILayout.TextField(
                        new GUIContent("Python", "Bos birakilirsa PATH'te python/py aranir."), _pythonExe);
                    if (GUILayout.Button("...", GUILayout.Width(26)))
                    {
                        string picked = EditorUtility.OpenFilePanel("python.exe", "", "exe");
                        if (!string.IsNullOrEmpty(picked)) _pythonExe = picked;
                    }
                }

                _ollamaUrl = EditorGUILayout.TextField(new GUIContent("Ollama", "Varsayilan " + Q3Setup.DefaultOllama),
                                                       _ollamaUrl);
                _bridgeUrl = EditorGUILayout.TextField(new GUIContent("Unity MCP", "MCP for Unity HTTP koprusu"),
                                                       _bridgeUrl);

                _model = EditorGUILayout.TextField(
                    new GUIContent("Model kimligi", "Normalde alttaki acilirdan sec; bu alan elle giris icin."),
                    _model);

                _repairs = EditorGUILayout.IntSlider(
                    new GUIContent("Onarim turu siniri",
                                   "Derleme hatasi modele kac kez geri verilir. Olculen: cogu is 0-1 turda biter."),
                    _repairs, 0, 6);

                _highlight = EditorGUILayout.Toggle(
                    new GUIContent("Sozdizimi renklendirme", "Kod bloklarini renklendirir."), _highlight);

                _autoOpenDiff = EditorGUILayout.Toggle(
                    new GUIContent("Ilk degisiklikte Diff penceresini ac",
                                   "Kapaliysa pencereyi Degisiklikler dugmesinden kendin acarsin."),
                    _autoOpenDiff);

                _scale = EditorGUILayout.Slider(new GUIContent("Punto olcegi", "4K ekranlar icin"),
                                                _scale, Q3Styles.MinScale, Q3Styles.MaxScale);

                if (EditorGUI.EndChangeCheck())
                {
                    EditorPrefs.SetString(Q3Setup.PrefAgentDir, _agentDir.Trim());
                    EditorPrefs.SetString(Q3Setup.PrefPython, _pythonExe.Trim());
                    EditorPrefs.SetString(Q3Setup.PrefOllama, _ollamaUrl.Trim());
                    EditorPrefs.SetString(Q3Setup.PrefBridge, _bridgeUrl.Trim());
                    EditorPrefs.SetString(PrefModel, _model.Trim());
                    EditorPrefs.SetInt(PrefRepairs, _repairs);
                    EditorPrefs.SetBool(PrefHighlight, _highlight);
                    EditorPrefs.SetBool(PrefAutoOpenDiff, _autoOpenDiff);
                    EditorPrefs.SetFloat(PrefScale, _scale);
                    Q3Setup.Invalidate();
                }

                GUILayout.Label(Q3Setup.State == SetupState.Ready
                                    ? "Hazir: " + Q3Setup.Detail
                                    : "Durum: " + Q3Setup.State + "  " + Q3Setup.Detail,
                                s.Caption);
            }
        }

        // --- sohbet ----------------------------------------------------------

        private void DrawTranscript(Q3Styles s)
        {
            _scroll = EditorGUILayout.BeginScrollView(_scroll, GUILayout.ExpandHeight(true));

            if (_messages.Count == 0)
            {
                EditorGUILayout.Space(16);
                GUILayout.Label("Yerel modelle bu pencereden konus. Ne istedigini duz Turkce yaz; " +
                                "model C# yazar, Unity derler, hata varsa modele geri gider.\n" +
                                "Proje: " + Q3Runner.ProjectRoot(),
                                s.Caption);
            }

            for (int i = 0; i < _messages.Count; i++)
                DrawMessage(s, _messages[i]);

            if (Busy && _streamIndex < 0)
            {
                using (new EditorGUILayout.VerticalScope(s.AgentBubble))
                    GUILayout.Label("Model calisiyor..." + ElapsedLabel(), s.Caption);
            }

            EditorGUILayout.EndScrollView();
        }

        private string ElapsedLabel()
        {
            if (_runStartedAtMs <= 0) return "";
            long sec = (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _runStartedAtMs) / 1000;
            return "  " + sec + " sn";
        }

        private void DrawMessage(Q3Styles s, Q3Message m)
        {
            if (m.Role == Q3Message.RoleTool)
            {
                bool hasDetail = !string.IsNullOrEmpty(m.Detail);
                string prefix = hasDetail ? (m.Expanded ? "▾ " : "▸ ") : "   ";

                if (GUILayout.Button(prefix + "↳ " + m.Text, s.ToolLine) && hasDetail)
                    m.Expanded = !m.Expanded;

                if (hasDetail && m.Expanded)
                {
                    using (new EditorGUILayout.VerticalScope(s.CodeBox))
                    {
                        using (new EditorGUILayout.HorizontalScope(s.CodeHeader))
                        {
                            GUILayout.Label("arac ayrintisi", s.Caption);
                            GUILayout.FlexibleSpace();
                            float codeIcon = Mathf.Round(16 * s.Scale);
                            if (GUILayout.Button(Q3Styles.CopyIcon("Ayrintiyi kopyala"), s.IconButton,
                                                 GUILayout.Width(codeIcon + 6), GUILayout.Height(codeIcon)))
                                EditorGUIUtility.systemCopyBuffer = m.Detail;
                        }
                        GUILayout.Label(Truncate(m.Detail), s.CodePlain);
                    }
                }
                return;
            }

            GUIStyle bubble;
            string role;

            switch (m.Role)
            {
                case Q3Message.RoleUser: bubble = s.UserBubble; role = "Sen"; break;
                case Q3Message.RoleNote: bubble = s.NoteBubble; role = "Bilgi"; break;
                case Q3Message.RoleError: bubble = s.ErrorBubble; role = "Hata"; break;
                default: bubble = s.AgentBubble; role = "Model"; break;
            }

            EnsureBlocks(s, m);

            using (new EditorGUILayout.VerticalScope(bubble))
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    GUILayout.Label(m.Streaming ? role + " …" : role, s.RoleLabel);
                    GUILayout.FlexibleSpace();

                    float icon = Mathf.Round(18 * s.Scale);
                    if (GUILayout.Button(Q3Styles.CopyIcon("Mesaji kopyala"), s.IconButton,
                                         GUILayout.Width(icon + 6), GUILayout.Height(icon)))
                        EditorGUIUtility.systemCopyBuffer = m.Text;
                }

                for (int i = 0; i < m.Blocks.Count; i++)
                {
                    MdBlock b = m.Blocks[i];

                    if (!b.IsCode)
                    {
                        GUILayout.Label(m.Display[i], s.Prose);
                        continue;
                    }

                    using (new EditorGUILayout.VerticalScope(s.CodeBox))
                    {
                        using (new EditorGUILayout.HorizontalScope(s.CodeHeader))
                        {
                            GUILayout.Label(string.IsNullOrEmpty(b.Language) ? "kod" : b.Language, s.Caption);
                            GUILayout.FlexibleSpace();

                            float codeIcon = Mathf.Round(16 * s.Scale);
                            if (GUILayout.Button(Q3Styles.CopyIcon("Kod blogunu kopyala"), s.IconButton,
                                                 GUILayout.Width(codeIcon + 6), GUILayout.Height(codeIcon)))
                                EditorGUIUtility.systemCopyBuffer = b.Text;
                        }

                        GUILayout.Label(m.Display[i], m.RichText[i] ? s.Code : s.CodePlain);
                    }
                }
            }
        }

        private void DrawComposer(Q3Styles s)
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUI.BeginChangeCheck();
                _includeErrors = EditorGUILayout.ToggleLeft(
                    new GUIContent(string.Format("Konsol hatalarini ekle ({0})", Q3Console.Count),
                                   "Konsoldaki hatalari istegin sonuna ekler."),
                    _includeErrors, GUILayout.Width(190));

                _play = EditorGUILayout.ToggleLeft(
                    new GUIContent("Play'de dogrula",
                                   "Is bitince play moda girip calisma zamani hatalarini toplar ve " +
                                   "modele onartir (~15-20 sn ek). Derleyicinin goremedigi hatalari yakalar."),
                    _play, GUILayout.Width(120));
                if (EditorGUI.EndChangeCheck())
                {
                    EditorPrefs.SetBool(PrefErrors, _includeErrors);
                    EditorPrefs.SetBool(PrefPlay, _play);
                }

                GUILayout.FlexibleSpace();
                _stickToBottom = EditorGUILayout.ToggleLeft("Alta kilitle", _stickToBottom, GUILayout.Width(92));
            }

            GUI.SetNextControlName("Q3Input");
            _input = EditorGUILayout.TextArea(_input, s.Input, GUILayout.MinHeight(52), GUILayout.MaxHeight(120));

            using (new EditorGUILayout.HorizontalScope())
            {
                DrawModelPicker();

                GUILayout.FlexibleSpace();

                bool canSend = !Busy && !string.IsNullOrWhiteSpace(_input) &&
                               Q3Setup.State == SetupState.Ready;

                using (new EditorGUI.DisabledScope(!canSend))
                {
                    if (GUILayout.Button("Gonder   (Ctrl+Enter)", GUILayout.Height(22), GUILayout.Width(150)))
                        _pendingSend = true;
                }

                using (new EditorGUI.DisabledScope(!Busy))
                {
                    if (GUILayout.Button("Durdur", GUILayout.Height(22), GUILayout.Width(64)))
                        StopRun(true);
                }
            }
        }

        private void DrawModelPicker()
        {
            string current = Q3Models.LabelFor(_model);
            var content = new GUIContent(current + " ▾", "Model sec (Ollama'da cekili olanlar).");
            Rect r = GUILayoutUtility.GetRect(content, EditorStyles.popup, GUILayout.Width(260), GUILayout.Height(22));

            if (!EditorGUI.DropdownButton(r, content, FocusType.Keyboard, EditorStyles.popup)) return;

            var menu = new GenericMenu();

            if (Q3Models.HasList)
            {
                foreach (KeyValuePair<string, List<ModelInfo>> group in Q3Models.Grouped())
                {
                    foreach (ModelInfo m in group.Value)
                    {
                        // GenericMenu '/' karakterini alt menu ayraci sayar.
                        string path = group.Key.Replace('/', '-') + "/" + m.Label.Replace('/', '-');

                        string id = m.Id;
                        menu.AddItem(new GUIContent(path),
                                     string.Equals(_model, id, StringComparison.OrdinalIgnoreCase),
                                     () => SetModel(id));
                    }
                }

                menu.AddSeparator("");
            }
            else
            {
                menu.AddDisabledItem(new GUIContent("Liste henuz alinmadi (Ollama ayakta mi?)"));
                menu.AddSeparator("");
            }

            menu.AddItem(new GUIContent("Listeyi yenile"), false, () =>
            {
                Q3Setup.Invalidate();
                Q3Setup.Check(_model, true);
            });
            menu.DropDown(r);
        }

        private void SetModel(string id)
        {
            _model = id ?? "";
            EditorPrefs.SetString(PrefModel, _model);
            Q3Setup.Invalidate();
            Repaint();
        }

        // ===================================================================
        // Blok onbellegi
        // ===================================================================

        private void EnsureBlocks(Q3Styles s, Q3Message m)
        {
            bool highlight = _highlight && !m.Streaming;
            string key = (highlight ? "h|" : "p|") + (s.Pro ? "d|" : "l|") + m.Text;

            if (m.CacheKey == key && m.Blocks != null) return;

            m.Blocks = Q3Markdown.Parse(m.Text);
            m.Display = new string[m.Blocks.Count];
            m.RichText = new bool[m.Blocks.Count];

            for (int i = 0; i < m.Blocks.Count; i++)
            {
                MdBlock b = m.Blocks[i];
                string text = Truncate(b.Text);

                if (!b.IsCode)
                {
                    m.Display[i] = Q3Markdown.FormatProse(text, s.Pro);
                    m.RichText[i] = true;
                    continue;
                }

                string colored = highlight ? Q3Markdown.Highlight(text, b.Language, s.Pro) : null;
                m.Display[i] = colored ?? text;
                m.RichText[i] = colored != null;
            }

            m.CacheKey = key;
        }

        private static string Truncate(string text)
        {
            if (string.IsNullOrEmpty(text) || text.Length <= MaxDisplayChars) return text;
            return text.Substring(0, MaxDisplayChars) + "\n… (kisaltildi, tamami icin Kopyala)";
        }

        // ===================================================================
        // Gonderim
        // ===================================================================

        private void Send()
        {
            string text = (_input ?? "").Trim();
            if (text.Length == 0) return;

            if (Q3Setup.State != SetupState.Ready)
            {
                AddMessage(Q3Message.RoleError, "Kurulum tamam degil: " + Q3Setup.Detail);
                Repaint();
                return;
            }

            string prompt = text;
            if (_includeErrors)
            {
                string report = Q3Console.BuildReport(15);
                if (!string.IsNullOrEmpty(report)) prompt += "\n" + report;
            }

            if (string.IsNullOrEmpty(_chatId))
                _chatId = Guid.NewGuid().ToString("N").Substring(0, 12);

            AddMessage(Q3Message.RoleUser, text);
            _input = "";
            _clearFocus = true;
            _touched.Clear();
            _runStartedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            var req = new RunRequest
            {
                Prompt = prompt,
                SessionId = _chatId,
                Model = _model,
                Repairs = _repairs,
                Play = _play,
            };

            string error;
            _run = Q3Runner.Start(req, out error);

            if (_run == null)
            {
                AddMessage(Q3Message.RoleError, "Ajan baslatilamadi: " + error);
                Repaint();
                return;
            }

            _lastLivenessCheck = EditorApplication.timeSinceStartup;
            Repaint();
        }

        private void StopRun(bool announce)
        {
            if (_run == null) return;

            if (_run.Active && _run.Pid > 0) Q3Proc.KillTree(_run.Pid);

            _run.Active = false;
            CloseStream();

            if (announce)
                AddMessage(Q3Message.RoleNote,
                           "Durduruldu. Model yarim kaldiysa yazdigi dosya Degisiklikler'de; " +
                           "derlenmemis olabilir.");
            Repaint();
        }

        private void NewChat()
        {
            if (Busy && !EditorUtility.DisplayDialog("Q3CNFU",
                    "Ajan hala calisiyor. Durdurup yeni sohbet baslatilsin mi?", "Evet", "Vazgec"))
                return;

            StopRun(false);
            Q3History.Save(_chatId, _messages, _model);

            _messages.Clear();
            _touched.Clear();
            _chatId = "";
            _streamIndex = -1;
            _scroll = Vector2.zero;
            _run = null;
            Repaint();
        }

        // ===================================================================
        // Ana is parcacigi dongusu
        // ===================================================================

        private void Pump()
        {
            if (_pendingSend && !Busy)
            {
                _pendingSend = false;
                Send();
            }

            PumpSetup();

            if (_run == null || !_run.Active) return;

            var lines = new List<string>();
            long next = Q3Tail.ReadLines(_run.OutputPath, _run.Offset, lines);

            if (next != _run.Offset) _run.Offset = next;

            foreach (string line in lines) HandleLine(line);

            if (lines.Count > 0)
            {
                if (_stickToBottom) _scroll.y = float.MaxValue;
                Repaint();
            }

            double now = EditorApplication.timeSinceStartup;
            if (_run.Active && now - _lastLivenessCheck > 2.0)
            {
                _lastLivenessCheck = now;
                Repaint();   // gecen sure etiketi

                if (!Q3Proc.IsAlive(_run.Pid))
                {
                    // Son bir okuma: cikis satiri henuz diske inmemis olabilir.
                    var tail = new List<string>();
                    _run.Offset = Q3Tail.ReadLines(_run.OutputPath, _run.Offset, tail);
                    foreach (string line in tail) HandleLine(line);

                    if (_run.Active)
                        FinishRun(-1, "Ajan sureci cikis satiri yazmadan sonlandi (python cokmus olabilir).");
                }
            }
        }

        private void PumpSetup()
        {
            if (Busy) return;
            if (Q3Setup.ApplyPendingResult()) Repaint();
            Q3Setup.Check(_model, false);
        }

        /// <summary>Sadece degisen dosyalari ice aktarir; tam Refresh buyuk projelerde
        /// dakikalar surebilir. panel_runner.py zaten her yazmada Refresh cagiriyor,
        /// bu son bir guvence.</summary>
        private void RefreshChangedAssets()
        {
            int imported = 0;

            foreach (FileChange change in Q3Changes.All)
            {
                if (change.AtMs < _runStartedAtMs) continue;

                string relative = Q3Changes.ToAssetPath(change.Path);
                if (relative == null) continue;

                Q3Changes.ImportLater(relative);
                imported++;
            }

            if (imported == 0)
                EditorApplication.delayCall += () => AssetDatabase.Refresh(ImportAssetOptions.Default);
        }

        private void FinishRun(int exitCode, string extraError)
        {
            if (_run != null) _run.Active = false;

            CloseStream();

            if (!string.IsNullOrEmpty(extraError))
                AddMessage(Q3Message.RoleError, extraError);

            if (_touched.Count > 0)
            {
                var sb = new StringBuilder("Dokunulan dosyalar:");
                foreach (string f in _touched) sb.Append("\n  • ").Append(f);
                AddMessage(Q3Message.RoleNote, sb.ToString());
            }

            Q3History.Save(_chatId, _messages, _model);

            if (exitCode == 0) RefreshChangedAssets();

            Repaint();
        }

        // ===================================================================
        // panel_runner.py olaylari
        // ===================================================================

        private void HandleLine(string raw)
        {
            object node = Q3Json.Parse(raw);

            if (node == null)
            {
                string t = raw.Trim();
                if (t.Length > 0) AddMessage(Q3Message.RoleError, t);
                return;
            }

            switch (Q3Json.Str(node, "type"))
            {
                case "system":
                    HandleSystem(node);
                    break;

                case "tool":
                    HandleTool(node);
                    break;

                case "tool_result":
                    HandleToolResult(node);
                    break;

                case "write":
                    HandleWrite(node);
                    break;

                case "assistant":
                    AppendAgentText(Q3Json.Str(node, "text"));
                    CloseStream();
                    break;

                case "result":
                    HandleResult(node);
                    break;

                case "error":
                    AddMessage(Q3Message.RoleError, Q3Json.Str(node, "message") ?? "?");
                    break;

                case "exit":
                    object codeValue = Q3Json.Get(node, "code");
                    FinishRun(codeValue is double ? (int)(double)codeValue : -1, null);
                    break;
            }
        }

        private void HandleSystem(object node)
        {
            string id = Q3Json.Str(node, "session_id");
            if (!string.IsNullOrEmpty(id)) _chatId = id;

            if (Q3Json.Str(node, "subtype") != "init") return;

            string model = Q3Json.Str(node, "model");
            if (!string.IsNullOrEmpty(model)) AddMessage(Q3Message.RoleTool, "model: " + model);
        }

        private void HandleTool(object node)
        {
            CloseStream();

            string name = Q3Json.Str(node, "name") ?? "?";
            string detail = Q3Json.Str(node, "detail") ?? "";

            string label = PrettyToolName(name);
            var m = new Q3Message
            {
                Role = Q3Message.RoleTool,
                Text = string.IsNullOrEmpty(detail) ? label : label + "  " + Clip(detail),
                Detail = FormatArgs(Q3Json.Obj(Q3Json.Get(node, "args"))),
            };
            _messages.Add(m);
        }

        private void HandleToolResult(object node)
        {
            string name = Q3Json.Str(node, "name") ?? "";
            string text = Q3Json.Str(node, "text") ?? "";
            object sure = Q3Json.Get(node, "sure");

            // Sonucu, sonucu henuz olmayan son arac satirina ekle.
            for (int i = _messages.Count - 1; i >= 0; i--)
            {
                Q3Message m = _messages[i];
                if (m.Role != Q3Message.RoleTool) continue;
                if (m.Detail.IndexOf("SONUC", StringComparison.Ordinal) >= 0) continue;

                string baslik = "SONUC" + (sure is double ? " (" + ((double)sure).ToString("0.0") + " sn)" : "") + ":";
                m.Detail = (string.IsNullOrEmpty(m.Detail) ? "" : m.Detail + "\n\n") + baslik + "\n" + text;
                if (sure is double) m.Text += "  •  " + ((double)sure).ToString("0") + " sn";
                return;
            }
        }

        /// <summary>Arac argumanlarini okunur metne cevirir; cok satirli degerler
        /// (kod gibi) kendi blogunda gosterilir.</summary>
        private static string FormatArgs(Dictionary<string, object> args)
        {
            if (args == null || args.Count == 0) return "";

            var sb = new StringBuilder("ARGUMANLAR:");
            foreach (KeyValuePair<string, object> kv in args)
            {
                string v = kv.Value is string ? (string)kv.Value
                         : kv.Value is double ? ((double)kv.Value).ToString("0.##")
                         : kv.Value is bool ? ((bool)kv.Value ? "true" : "false")
                         : kv.Value == null ? "null" : kv.Value.ToString();

                if (v.IndexOf('\n') >= 0)
                    sb.Append("\n  ").Append(kv.Key).Append(":\n").Append(v.Replace("\r", ""));
                else
                    sb.Append("\n  ").Append(kv.Key).Append(": ").Append(v);
            }
            return sb.ToString();
        }

        private void HandleWrite(object node)
        {
            int before = Q3Changes.All.Count;
            if (!Q3Changes.TryRecord(node)) return;

            FileChange change = Q3Changes.All[Q3Changes.All.Count - 1];
            if (!_touched.Contains(change.DisplayPath)) _touched.Add(change.DisplayPath);

            if (_autoOpenDiff && before == 0) Q3DiffWindow.Reveal();
        }

        private void HandleResult(object node)
        {
            CloseStream();

            object okValue = Q3Json.Get(node, "ok");
            bool ok = okValue is bool && (bool)okValue;

            object wall = Q3Json.Get(node, "wall");
            object rounds = Q3Json.Get(node, "rounds");

            var sb = new StringBuilder();
            sb.Append(ok ? "DERLENDI" : "DERLEME HATASI VAR");
            if (wall is double) sb.Append("  •  ").Append(((double)wall).ToString("0")).Append(" sn");
            if (rounds is double) sb.Append("  •  onarim: ").Append((int)(double)rounds);

            List<object> errors = Q3Json.Arr(Q3Json.Get(node, "errors"));
            if (errors != null)
                foreach (object e in errors)
                    sb.Append("\n  ").Append(Q3Json.Str(e) ?? "");

            // Uc durumu ayri raporla: temiz / hata kaldi / dogrulanamadi.
            // Dogrulanmamis kosuyu dogrulanmis gostermek en tehlikeli hata sinifi.
            object play = Q3Json.Get(node, "play");
            if (play != null)
            {
                object verified = Q3Json.Get(play, "dogrulandi");
                List<object> rt = Q3Json.Arr(Q3Json.Get(play, "hatalar"));

                if (!(verified is bool && (bool)verified))
                    sb.Append("\nCalisma zamani: DOGRULANAMADI (play moda girilemedi)");
                else if (rt == null || rt.Count == 0)
                    sb.Append("\nCalisma zamani: TEMIZ (play modda dogrulandi)");
                else
                {
                    sb.Append("\nCalisma zamani: ").Append(rt.Count).Append(" HATA KALDI");
                    foreach (object e in rt) sb.Append("\n  ").Append(Q3Json.Str(e) ?? "");
                }
            }

            AddMessage(ok ? Q3Message.RoleNote : Q3Message.RoleError, sb.ToString());
        }

        private static string PrettyToolName(string key)
        {
            switch (key)
            {
                case "write_script": return "Yazdi";
                case "read_script": return "Okudu";
                case "list_scripts": return "Listeledi";
                case "inspect_object": return "Inceledi";
                case "scene_objects": return "Sahneye bakti";
                case "read_console": return "Konsolu okudu";
                case "validate_script": return "Dogruladi";
                case "hierarchy": return "Hiyerarsi";
                case "project_assets": return "Varliklar";
                case "play_observe": return "Play'de olctu";
                case "list_assets": return "Varlik aradi";
                case "inspect_asset": return "Varliga bakti";
                case "add_component": return "Bilesen ekledi";
                case "set_field": return "Alan yazdi";
                case "create_asset": return "Varlik uretti";
                case "set_material": return "Materyal yazdi";
                default: return key;
            }
        }

        private static string Clip(string s)
        {
            s = s.Replace("\r", "").Replace("\n", " ⏎ ").Trim();
            return s.Length > 140 ? s.Substring(0, 140) + " …" : s;
        }

        // ===================================================================
        // Mesaj yardimcilari
        // ===================================================================

        private void AddMessage(int role, string text)
        {
            _messages.Add(new Q3Message { Role = role, Text = text ?? "" });
        }

        private Q3Message CurrentStream()
        {
            if (_streamIndex < 0 || _streamIndex >= _messages.Count) return null;
            Q3Message m = _messages[_streamIndex];
            return m.Role == Q3Message.RoleAgent ? m : null;
        }

        private void AppendAgentText(string text)
        {
            if (string.IsNullOrEmpty(text)) return;

            Q3Message m = CurrentStream();
            if (m == null)
            {
                m = new Q3Message { Role = Q3Message.RoleAgent, Streaming = true };
                _messages.Add(m);
                _streamIndex = _messages.Count - 1;
            }

            // Ollama saf delta yollar; CursorBridge'deki tekrar-korumasina gerek yok.
            m.Text += text;
            m.CacheKey = null;
        }

        private void CloseStream()
        {
            Q3Message m = CurrentStream();
            if (m != null)
            {
                m.Streaming = false;
                m.CacheKey = null;

                if (string.IsNullOrWhiteSpace(m.Text)) _messages.RemoveAt(_streamIndex);
            }

            _streamIndex = -1;
        }

        private static string Shorten(string id)
        {
            return id.Length <= 8 ? id : id.Substring(0, 8);
        }
    }
}
