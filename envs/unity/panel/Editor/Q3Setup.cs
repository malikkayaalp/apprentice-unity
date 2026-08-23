// Assets/Editor/Q3CNFU/Q3Setup.cs
// Kurulum durumu: Python var mi, ajan betikleri nerede, Ollama ayakta mi,
// model cekilmis mi, Unity MCP koprusu dinliyor mu. Hepsi ARKA PLANDA sorgulanir;
// surec baslatmak ve HTTP beklemek ana is parcaciginda editoru takar.
//
// Sira onemli: her adim bir oncekine bagli. Python yoksa ajan calisamaz, Ollama
// yoksa model sorgulanamaz. Ilk eksik adimda durup onu gosteriyoruz.

using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEditor;
using UnityEngine;

namespace Q3CNFU.EditorTools
{
    internal enum SetupState
    {
        Unknown,
        NoPython,
        NoAgent,
        NoOllama,
        NoModel,
        NoBridge,
        Ready,
    }

    internal class SetupSnapshot
    {
        public SetupState State = SetupState.Unknown;
        public string Detail = "";
        public string PythonExe = "";
        public string PythonVersion = "";
        public List<ModelInfo> Models = new List<ModelInfo>();
    }

    internal static class Q3Setup
    {
        public const string PrefPython = "Q3CNFU.PythonExe";
        public const string PrefAgentDir = "Q3CNFU.AgentDir";
        public const string PrefOllama = "Q3CNFU.OllamaUrl";
        public const string PrefBridge = "Q3CNFU.BridgeUrl";

        public const string DefaultOllama = "http://localhost:11434";
        public const string DefaultBridge = "http://127.0.0.1:8080/mcp";
        public const string RunnerScript = "panel_runner.py";

        private static SetupSnapshot _current = new SetupSnapshot();
        private static double _checkedAt = -1;

        private static volatile bool _running;
        private static volatile bool _hasResult;
        private static SetupSnapshot _pending;

        public static SetupState State { get { return _current.State; } }
        public static string Detail { get { return _current.Detail; } }
        public static string PythonExe { get { return _current.PythonExe; } }
        public static List<ModelInfo> Models { get { return _current.Models; } }
        public static bool IsChecking { get { return _running; } }

        // --- ayarlar ---------------------------------------------------------

        public static string OllamaUrl
        {
            get { return EditorPrefs.GetString(PrefOllama, DefaultOllama).TrimEnd('/'); }
        }

        public static string BridgeUrl
        {
            get { return EditorPrefs.GetString(PrefBridge, DefaultBridge); }
        }

        /// <summary>panel_runner.py'nin bulundugu klasor. Once ayar, sonra paket ici
        /// Agent~ klasoru (Unity '~' ile biten klasorleri derlemez, dosyalar durur).</summary>
        public static string AgentDir
        {
            get
            {
                string manual = EditorPrefs.GetString(PrefAgentDir, "");
                if (!string.IsNullOrEmpty(manual))
                {
                    if (File.Exists(Path.Combine(manual, RunnerScript))) return manual;

                    string sub = Path.Combine(manual, "envs", "unity");
                    if (File.Exists(Path.Combine(sub, RunnerScript))) return sub;
                }

                foreach (string guid in AssetDatabase.FindAssets("t:Script Q3Setup"))
                {
                    string scriptPath = AssetDatabase.GUIDToAssetPath(guid);
                    string dir = Path.GetDirectoryName(Path.GetFullPath(scriptPath)) ?? "";
                    string packaged = Path.Combine(dir, "Agent~");

                    // Iki yerlesim: (a) paketlenmis - betik dogrudan Agent~ icinde,
                    // (b) gelistirme - Agent~ Apprentice deposuna junction, betik
                    // envs/unity altinda.
                    if (File.Exists(Path.Combine(packaged, RunnerScript))) return packaged;

                    string dev = Path.Combine(packaged, "envs", "unity");
                    if (File.Exists(Path.Combine(dev, RunnerScript))) return dev;
                }

                return manual;
            }
        }

        public static string RunnerPath
        {
            get
            {
                string dir = AgentDir;
                return string.IsNullOrEmpty(dir) ? "" : Path.Combine(dir, RunnerScript);
            }
        }

        // --- sorgulama -------------------------------------------------------

        public static SetupState Check(string model, bool force)
        {
            ApplyPendingResult();

            double now = EditorApplication.timeSinceStartup;
            bool stale = _checkedAt < 0 ||
                         now - _checkedAt > (_current.State == SetupState.Ready ? 300 : 5);

            if (!_running && (force || stale)) StartBackgroundCheck(model);

            return _current.State;
        }

        public static bool ApplyPendingResult()
        {
            if (!_hasResult) return false;

            _hasResult = false;
            _current = _pending ?? new SetupSnapshot();
            _checkedAt = EditorApplication.timeSinceStartup;
            return true;
        }

        public static void Invalidate()
        {
            _checkedAt = -1;
            _hasResult = false;
        }

        private static void StartBackgroundCheck(string model)
        {
            _running = true;
            _checkedAt = EditorApplication.timeSinceStartup;

            // Unity API'leri is parcacigina GECMEDEN once okunur.
            string pythonPref = EditorPrefs.GetString(PrefPython, "");
            string agentDir = AgentDir;
            string ollama = OllamaUrl;
            string bridge = BridgeUrl;
            string wantModel = (model ?? "").Trim();

            var thread = new Thread(() =>
            {
                var snap = new SetupSnapshot();
                try
                {
                    Probe(snap, pythonPref, agentDir, ollama, bridge, wantModel);
                }
                catch (Exception ex)
                {
                    snap.State = SetupState.Unknown;
                    snap.Detail = ex.Message;
                }

                _pending = snap;
                _hasResult = true;
                _running = false;
            });

            thread.IsBackground = true;
            thread.Start();
        }

        private static void Probe(SetupSnapshot snap, string pythonPref, string agentDir,
                                  string ollama, string bridge, string wantModel)
        {
            // 1) Python
            string version;
            string exe = FindPython(pythonPref, out version);
            if (exe == null)
            {
                snap.State = SetupState.NoPython;
                snap.Detail = "python bulunamadi (PATH'te python/py yok).";
                return;
            }
            snap.PythonExe = exe;
            snap.PythonVersion = version;

            // 2) Ajan betikleri
            if (string.IsNullOrEmpty(agentDir) || !File.Exists(Path.Combine(agentDir, RunnerScript)))
            {
                snap.State = SetupState.NoAgent;
                snap.Detail = "panel_runner.py bulunamadi. Ayarlar'dan ajan klasorunu sec.";
                return;
            }

            // 3) Ollama
            string tags;
            if (!HttpGet(ollama + "/api/tags", 4000, out tags))
            {
                snap.State = SetupState.NoOllama;
                snap.Detail = ollama + " cevap vermiyor. Ollama'yi baslat.";
                return;
            }

            snap.Models = Q3Models.ParseTags(tags);

            // 4) Model
            if (!string.IsNullOrEmpty(wantModel) && !Q3Models.Contains(snap.Models, wantModel))
            {
                snap.State = SetupState.NoModel;
                snap.Detail = wantModel + " cekilmemis.";
                return;
            }

            // 5) Unity MCP koprusu (TCP kapisi acik mi yeter; protokol konusmuyoruz)
            if (!PortOpen(bridge))
            {
                snap.State = SetupState.NoBridge;
                snap.Detail = bridge + " dinlemiyor. Window > MCP for Unity > Connect.";
                return;
            }

            snap.State = SetupState.Ready;
            snap.Detail = "python " + version + "  •  " + snap.Models.Count + " model";
        }

        // --- python ----------------------------------------------------------

        private static string FindPython(string pref, out string version)
        {
            version = "";

            var candidates = new List<string>();
            if (!string.IsNullOrEmpty(pref)) candidates.Add(pref);
            candidates.Add("python");
            candidates.Add("python3");
            candidates.Add("py");

            foreach (string c in candidates)
            {
                string stdout, stderr;
                int exit;

                var args = new List<string>();
                if (string.Equals(Path.GetFileNameWithoutExtension(c), "py", StringComparison.OrdinalIgnoreCase))
                    args.Add("-3");
                args.Add("--version");

                try
                {
                    if (!Q3Proc.RunCapture(c, args, null, 8000, out stdout, out stderr, out exit)) continue;
                    if (exit != 0) continue;

                    string text = (stdout + " " + stderr).Trim();
                    if (!text.StartsWith("Python 3", StringComparison.Ordinal)) continue;

                    version = text.Substring("Python ".Length).Trim();
                    return c;
                }
                catch (Exception)
                {
                    // Bulunamadi; siradakini dene.
                }
            }

            return null;
        }

        // --- ag --------------------------------------------------------------

        public static bool HttpGet(string url, int timeoutMs, out string body)
        {
            body = "";
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(url);
                req.Method = "GET";
                req.Timeout = timeoutMs;
                req.ReadWriteTimeout = timeoutMs;
                req.Proxy = null;   // localhost icin proxy cozumlemesi saniyeler yiyebilir

                using (var resp = (HttpWebResponse)req.GetResponse())
                using (var reader = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                    body = reader.ReadToEnd();

                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static bool PortOpen(string url)
        {
            try
            {
                var uri = new Uri(url);
                using (var client = new TcpClient())
                {
                    IAsyncResult ar = client.BeginConnect(uri.Host, uri.Port, null, null);
                    if (!ar.AsyncWaitHandle.WaitOne(2000)) return false;
                    client.EndConnect(ar);
                    return client.Connected;
                }
            }
            catch (Exception)
            {
                return false;
            }
        }
    }
}
