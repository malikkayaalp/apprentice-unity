// Assets/Editor/Q3CNFU/Q3Changes.cs
// Ajanin yaptigi dosya degisikliklerini biriktirir.
//
// panel_runner.py her write_script'te "write" olayi yollar: path, before
// (dosya yoksa null), after. Diff'i burada uretiyoruz (Q3Diff). Geri alma
// before'u dosyaya geri yazmaktan ibaret.
//
// Depo statiktir ve domain reload'da bellekten silinir, bu yuzden
// Library/Q3CNFU/changes.json dosyasindan geri yuklenir.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Q3CNFU.EditorTools
{
    internal class FileChange
    {
        public string Path = "";
        public string Before;          // null = dosya bu degisiklikte olusturuldu
        public string After;
        public string Diff = "";
        public int LinesAdded;
        public int LinesRemoved;
        public long AtMs;
        public bool Reverted;
        public string Tool = "";

        public string DisplayPath
        {
            get
            {
                string root = Q3Runner.ProjectRoot();
                if (Path.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                {
                    string rel = Path.Substring(root.Length).TrimStart('\\', '/');
                    return rel.Length > 0 ? rel : Path;
                }
                return Path;
            }
        }

        public DateTime At
        {
            get { return DateTimeOffset.FromUnixTimeMilliseconds(AtMs).LocalDateTime; }
        }
    }

    internal static class Q3Changes
    {
        private const int MaxKept = 120;

        private static List<FileChange> _changes;
        private static int _version;

        /// <summary>Her degisiklikte artar; pencereler buna bakip kendini yeniler.</summary>
        public static int Version { get { return _version; } }

        public static List<FileChange> All
        {
            get
            {
                if (_changes == null) Load();
                return _changes;
            }
        }

        private static string StorePath
        {
            get
            {
                string dir = Path.Combine(Q3Runner.ProjectRoot(), "Library", "Q3CNFU");
                Directory.CreateDirectory(dir);
                return Path.Combine(dir, "changes.json");
            }
        }

        // --- toplama ---------------------------------------------------------

        /// <summary>panel_runner.py "write" olayindan degisiklik kaydeder.
        /// path proje kokune gore (Assets/...) gelir; mutlak yola ceviriyoruz ki
        /// geri alma ve disk karsilastirmasi dogrudan dosyaya gidebilsin.</summary>
        public static bool TryRecord(object node)
        {
            string rel = Q3Json.Str(node, "path");
            if (string.IsNullOrEmpty(rel)) return false;

            object beforeValue = Q3Json.Get(node, "before");
            string after = Q3Json.Str(node, "after");
            if (after == null) return false;

            string before = beforeValue as string;
            int added, removed;
            string diff = Q3Diff.Unified(before, after, rel, out added, out removed);

            var change = new FileChange
            {
                Path = Path.GetFullPath(Path.Combine(Q3Runner.ProjectRoot(),
                                                     rel.Replace('/', Path.DirectorySeparatorChar))),
                Before = before,
                After = after,
                Diff = diff,
                LinesAdded = added,
                LinesRemoved = removed,
                AtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                Tool = "write_script",
            };

            All.Add(change);
            if (All.Count > MaxKept) All.RemoveRange(0, All.Count - MaxKept);

            _version++;
            Save();
            return true;
        }

        public static void Clear()
        {
            All.Clear();
            _version++;
            Save();
        }

        // --- geri alma -------------------------------------------------------

        /// <summary>Dosyayi degisiklikten onceki haline dondurur.</summary>
        public static bool Revert(FileChange change, out string error)
        {
            error = null;
            if (change == null) { error = "Degisiklik yok."; return false; }

            string relative = ToAssetPath(change.Path);

            try
            {
                if (change.Before == null)
                {
                    // Dosya bu degisiklikte olusturulmus: geri alma = silmek.
                    // Assets altindaysa .meta'yi da dogru sekilde temizlesin diye
                    // AssetDatabase kullaniyoruz.
                    if (relative != null)
                    {
                        AssetDatabase.DeleteAsset(relative);
                    }
                    else
                    {
                        if (File.Exists(change.Path)) File.Delete(change.Path);

                        string meta = change.Path + ".meta";
                        if (File.Exists(meta)) File.Delete(meta);
                    }
                }
                else
                {
                    string dir = Path.GetDirectoryName(change.Path);
                    if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

                    File.WriteAllText(change.Path, change.Before, new UTF8Encoding(false));

                    // TAM Refresh cagirmiyoruz: buyuk projelerde tum Assets agacini
                    // tarar ve dakikalarca surebilir. Tek dosyayi ice aktarmak yeterli.
                    // (Script ise derleme yine tetiklenir, o kacinilmaz.)
                    if (relative != null) ImportLater(relative);
                }

                change.Reverted = true;
                InvalidateDiskCache(change);
                _version++;
                Save();
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        /// <summary>Proje kokune gore "Assets/..." yolu; Assets disindaysa null.</summary>
        public static string ToAssetPath(string absolute)
        {
            if (string.IsNullOrEmpty(absolute)) return null;

            string root = Q3Runner.ProjectRoot();
            if (!absolute.StartsWith(root, StringComparison.OrdinalIgnoreCase)) return null;

            string rel = absolute.Substring(root.Length).TrimStart('\\', '/').Replace('\\', '/');
            return rel.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase) ? rel : null;
        }

        private static readonly List<string> PendingImports = new List<string>();
        private static bool _importScheduled;

        /// <summary>Ice aktarmalari toplayip tek seferde yapar; arka arkaya geri
        /// almalarda her defasinda yeniden derlemeyi onler.</summary>
        public static void ImportLater(string assetPath)
        {
            if (string.IsNullOrEmpty(assetPath)) return;
            if (!PendingImports.Contains(assetPath)) PendingImports.Add(assetPath);

            if (_importScheduled) return;
            _importScheduled = true;

            EditorApplication.delayCall += FlushImports;
        }

        private static void FlushImports()
        {
            _importScheduled = false;
            if (PendingImports.Count == 0) return;

            var paths = new List<string>(PendingImports);
            PendingImports.Clear();

            try
            {
                AssetDatabase.StartAssetEditing();
                foreach (string p in paths)
                    AssetDatabase.ImportAsset(p, ImportAssetOptions.Default);
            }
            finally
            {
                AssetDatabase.StopAssetEditing();
            }
        }

        // --- disk karsilastirmasi (onbellekli) --------------------------------

        private static readonly Dictionary<string, bool> DiskCache = new Dictionary<string, bool>();
        private static double _diskCheckedAt = -1;

        /// <summary>Dosyanin diskteki hali kaydedilen "after" ile ayni mi.
        /// OnGUI'den her karede cagrilabilmesi icin onbelleklidir; dosyayi her
        /// karede okumak buyuk dosyalarda arayuzu takar.</summary>
        public static bool MatchesDisk(FileChange change)
        {
            if (change == null) return true;

            double now = EditorApplication.timeSinceStartup;
            if (_diskCheckedAt < 0 || now - _diskCheckedAt > 2.0)
            {
                DiskCache.Clear();
                _diskCheckedAt = now;
            }

            string key = change.Path + "|" + change.AtMs;

            bool cached;
            if (DiskCache.TryGetValue(key, out cached)) return cached;

            bool result;
            try
            {
                if (change.After == null) result = !File.Exists(change.Path);
                else if (!File.Exists(change.Path)) result = false;
                else result = string.Equals(File.ReadAllText(change.Path, Encoding.UTF8), change.After,
                                            StringComparison.Ordinal);
            }
            catch (IOException)
            {
                result = true;   // okunamiyorsa uyari basmayalim
            }

            DiskCache[key] = result;
            return result;
        }

        private static void InvalidateDiskCache(FileChange change)
        {
            DiskCache.Clear();
            _diskCheckedAt = -1;
        }

        // --- kalicilik -------------------------------------------------------

        private static void Save()
        {
            try
            {
                var sb = new StringBuilder();
                sb.Append("{\"changes\":[");

                for (int i = 0; i < All.Count; i++)
                {
                    FileChange c = All[i];
                    if (i > 0) sb.Append(',');

                    sb.Append('{');
                    sb.Append("\"path\":").Append(Q3Proc.JsonString(c.Path)).Append(',');
                    sb.Append("\"before\":").Append(c.Before == null
                                                        ? "null"
                                                        : Q3Proc.JsonString(c.Before)).Append(',');
                    sb.Append("\"after\":").Append(c.After == null
                                                       ? "null"
                                                       : Q3Proc.JsonString(c.After)).Append(',');
                    sb.Append("\"diff\":").Append(Q3Proc.JsonString(c.Diff)).Append(',');
                    sb.Append("\"added\":").Append(c.LinesAdded.ToString(CultureInfo.InvariantCulture)).Append(',');
                    sb.Append("\"removed\":").Append(c.LinesRemoved.ToString(CultureInfo.InvariantCulture)).Append(',');
                    sb.Append("\"atMs\":").Append(c.AtMs.ToString(CultureInfo.InvariantCulture)).Append(',');
                    sb.Append("\"reverted\":").Append(c.Reverted ? "true" : "false").Append(',');
                    sb.Append("\"tool\":").Append(Q3Proc.JsonString(c.Tool));
                    sb.Append('}');
                }

                sb.Append("]}");
                File.WriteAllText(StorePath, sb.ToString(), new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[Q3CNFU] Degisiklik kaydi yazilamadi: " + ex.Message);
            }
        }

        private static void Load()
        {
            _changes = new List<FileChange>();

            try
            {
                string path = StorePath;
                if (!File.Exists(path)) return;

                object root = Q3Json.Parse(File.ReadAllText(path, Encoding.UTF8));
                List<object> items = Q3Json.Arr(Q3Json.Get(root, "changes"));
                if (items == null) return;

                foreach (object item in items)
                {
                    object added = Q3Json.Get(item, "added");
                    object removed = Q3Json.Get(item, "removed");
                    object atMs = Q3Json.Get(item, "atMs");
                    object reverted = Q3Json.Get(item, "reverted");

                    _changes.Add(new FileChange
                    {
                        Path = Q3Json.Str(item, "path") ?? "",
                        Before = Q3Json.Get(item, "before") as string,
                        After = Q3Json.Get(item, "after") as string,
                        Diff = Q3Json.Str(item, "diff") ?? "",
                        LinesAdded = added is double ? (int)(double)added : 0,
                        LinesRemoved = removed is double ? (int)(double)removed : 0,
                        AtMs = atMs is double ? (long)(double)atMs : 0,
                        Reverted = reverted is bool && (bool)reverted,
                        Tool = Q3Json.Str(item, "tool") ?? "",
                    });
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[Q3CNFU] Degisiklik kaydi okunamadi: " + ex.Message);
            }
        }
    }
}
