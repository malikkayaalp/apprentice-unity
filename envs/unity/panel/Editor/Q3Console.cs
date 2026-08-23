// Assets/Editor/Q3CNFU/Q3Console.cs
// Unity konsolundaki hatalari okur ve prompt'a eklenecek metni uretir.
//
// Birincil yol UnityEditor.LogEntries yansimasi: derleme hatalari dahil
// konsolda ne varsa onu gorur ve domain reload'dan etkilenmez.
// Yansima bir Unity surumunde bozulursa Application.logMessageReceived ile
// toplanan yedek listeye duser.

using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Q3CNFU.EditorTools
{
    [InitializeOnLoad]
    internal static class Q3Console
    {
        private const int MaxFallbackEntries = 60;
        private static readonly List<string> Fallback = new List<string>();

        // ConsoleWindow.Mode bayraklarindan hata anlamina gelenler.
        private const int ErrorMask =
            (1 << 0)  |  // kError
            (1 << 1)  |  // kAssert
            (1 << 4)  |  // kFatal
            (1 << 6)  |  // kAssetImportError
            (1 << 8)  |  // kScriptingError
            (1 << 11) |  // kScriptCompileError
            (1 << 17) |  // kScriptingException
            (1 << 20) |  // kGraphCompileError
            (1 << 21);   // kScriptingAssertion

        private static bool _reflectionBroken;

        static Q3Console()
        {
            Application.logMessageReceived -= OnLog;
            Application.logMessageReceived += OnLog;
        }

        private static void OnLog(string condition, string stackTrace, LogType type)
        {
            if (type != LogType.Error && type != LogType.Exception && type != LogType.Assert) return;

            lock (Fallback)
            {
                Fallback.Add(condition);
                if (Fallback.Count > MaxFallbackEntries) Fallback.RemoveAt(0);
            }
        }

        private static int _cachedCount;
        private static double _cachedAt = -1;

        /// <summary>Konsoldaki hata sayisi. OnGUI'den her karede cagrilabilmesi icin onbellekli.</summary>
        public static int Count
        {
            get
            {
                double now = EditorApplication.timeSinceStartup;
                if (_cachedAt < 0 || now - _cachedAt > 0.5)
                {
                    _cachedCount = Read(200).Count;
                    _cachedAt = now;
                }
                return _cachedCount;
            }
        }

        /// <summary>Prompt'a eklenecek hata blogunu uretir. Hata yoksa bos metin doner.</summary>
        public static string BuildReport(int maxEntries)
        {
            List<string> entries = Read(maxEntries);
            if (entries.Count == 0) return "";

            var sb = new StringBuilder();
            sb.AppendLine();
            sb.AppendLine("--- Unity Console: aktif hatalar ---");
            foreach (string e in entries)
            {
                string line = e.Replace("\r\n", "\n").Trim();
                if (line.Length > 800) line = line.Substring(0, 800) + " ...";
                sb.AppendLine(line);
                sb.AppendLine();
            }
            return sb.ToString();
        }

        private static List<string> Read(int maxEntries)
        {
            if (!_reflectionBroken)
            {
                try
                {
                    List<string> viaReflection = ReadFromConsoleWindow(maxEntries);
                    if (viaReflection != null) return viaReflection;
                }
                catch (Exception ex)
                {
                    _reflectionBroken = true;
                    Debug.LogWarning("[Q3CNFU] Konsol okunamadi, yedek listeye gecildi: " + ex.Message);
                }
            }

            lock (Fallback)
            {
                int start = Mathf.Max(0, Fallback.Count - maxEntries);
                return Fallback.GetRange(start, Fallback.Count - start);
            }
        }

        private static List<string> ReadFromConsoleWindow(int maxEntries)
        {
            Assembly editorAsm = typeof(EditorWindow).Assembly;
            Type entriesType = editorAsm.GetType("UnityEditor.LogEntries");
            Type entryType = editorAsm.GetType("UnityEditor.LogEntry");
            if (entriesType == null || entryType == null) return null;

            MethodInfo start = entriesType.GetMethod("StartGettingEntries", BindingFlags.Public | BindingFlags.Static);
            MethodInfo end = entriesType.GetMethod("EndGettingEntries", BindingFlags.Public | BindingFlags.Static);
            MethodInfo getEntry = entriesType.GetMethod("GetEntryInternal", BindingFlags.Public | BindingFlags.Static);
            FieldInfo messageField = entryType.GetField("message", BindingFlags.Public | BindingFlags.Instance);
            FieldInfo modeField = entryType.GetField("mode", BindingFlags.Public | BindingFlags.Instance);
            // Dosya/satir istege bagli: bir surumde ad degisirse sadece konum dusur.
            // Ders: bu projede yigin izi olmayan konsol okumasi her runtime hatasini
            // filtreye yedirdi; mesaj tek basina yetmiyor, konum sart.
            FieldInfo fileField = entryType.GetField("file", BindingFlags.Public | BindingFlags.Instance);
            FieldInfo lineField = entryType.GetField("line", BindingFlags.Public | BindingFlags.Instance);

            if (start == null || end == null || getEntry == null || messageField == null || modeField == null)
                return null;

            var result = new List<string>();
            object count = start.Invoke(null, null);

            try
            {
                int total = count is int ? (int)count : 0;
                object entry = Activator.CreateInstance(entryType);
                var args = new object[2];

                for (int i = 0; i < total; i++)
                {
                    args[0] = i;
                    args[1] = entry;
                    getEntry.Invoke(null, args);

                    int mode = (int)modeField.GetValue(entry);
                    if ((mode & ErrorMask) == 0) continue;

                    string message = messageField.GetValue(entry) as string;
                    if (string.IsNullOrEmpty(message)) continue;

                    string file = fileField != null ? fileField.GetValue(entry) as string : null;
                    object line = lineField != null ? lineField.GetValue(entry) : null;

                    // Derleme hatalari mesajin icinde zaten "yol(satir,sutun)" tasir;
                    // tekrar eklemeyelim.
                    if (!string.IsNullOrEmpty(file) && message.IndexOf(file, StringComparison.Ordinal) < 0)
                        message += "\n    at " + file + (line is int ? ":" + (int)line : "");

                    result.Add(message);
                }
            }
            finally
            {
                end.Invoke(null, null);
            }

            if (result.Count > maxEntries)
                result.RemoveRange(0, result.Count - maxEntries);

            return result;
        }
    }
}
