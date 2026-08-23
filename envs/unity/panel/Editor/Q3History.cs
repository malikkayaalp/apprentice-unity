// Assets/Editor/Q3CNFU/Q3History.cs
// Sohbet gecmisi.
//
// Dokum: Library/Q3CNFU/history/<chatId>.json - pencerede gorunen mesajlarin
// tamami burada; pencere kapansa da kalir. Modelin gordugu asil baglam ise
// panel_runner.py'nin yazdigi Library/Q3CNFU/sessions/<chatId>.json dosyasinda;
// ikisi ayni kimligi paylasir.
//
// Baslik: varsayilan olarak ilk kullanici mesajindan turetilir. Kullanici elle
// ad verirse ya da modele urettirirse "titleLocked" isaretlenir ve otomatik
// turetme bir daha uzerine yazmaz.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

namespace Q3CNFU.EditorTools
{
    internal class HistoryEntry
    {
        public string ChatId = "";
        public string Title = "";
        public string Preview = "";
        public long UpdatedAtMs;
        public int MessageCount;
        public bool HasLocalTranscript;
        public bool TitleLocked;

        public DateTime UpdatedAt
        {
            get { return DateTimeOffset.FromUnixTimeMilliseconds(UpdatedAtMs).LocalDateTime; }
        }
    }

    internal static class Q3History
    {
        private const int MaxKept = 60;

        private static string HistoryDirectory
        {
            get
            {
                string dir = Path.Combine(Q3Runner.ProjectRoot(),
                                          "Library", "Q3CNFU", "history");
                Directory.CreateDirectory(dir);
                return dir;
            }
        }

        private static string TranscriptPath(string chatId)
        {
            return Path.Combine(HistoryDirectory, SafeName(chatId) + ".json");
        }

        private static string SafeName(string id)
        {
            var sb = new StringBuilder();
            foreach (char c in id ?? "")
                sb.Append(char.IsLetterOrDigit(c) || c == '-' || c == '_' ? c : '_');
            return sb.Length > 0 ? sb.ToString() : "unnamed";
        }

        // --- yazma -----------------------------------------------------------

        public static void Save(string chatId, List<Q3Message> messages, string model)
        {
            if (string.IsNullOrEmpty(chatId) || messages == null || messages.Count == 0) return;

            // Elle verilmis ya da uretilmis basligi ezmeyelim.
            string title = null;
            bool locked = false;

            object existing = ReadJson(TranscriptPath(chatId));
            if (existing != null)
            {
                object lockedValue = Q3Json.Get(existing, "titleLocked");
                locked = lockedValue is bool && (bool)lockedValue;
                if (locked) title = Q3Json.Str(existing, "title");
            }

            if (string.IsNullOrEmpty(title)) title = DeriveTitle(messages);

            Write(chatId, title, locked, model, messages);
        }

        /// <summary>Baslik elle verilmis ya da uretilmis mi.</summary>
        public static bool IsTitleLocked(string chatId)
        {
            if (string.IsNullOrEmpty(chatId)) return false;

            object existing = ReadJson(TranscriptPath(chatId));
            object locked = Q3Json.Get(existing, "titleLocked");
            return locked is bool && (bool)locked;
        }

        /// <summary>Basligi sabitler; otomatik turetme bir daha uzerine yazmaz.</summary>
        public static void SetTitle(string chatId, string title)
        {
            if (string.IsNullOrEmpty(chatId) || string.IsNullOrWhiteSpace(title)) return;

            object existing = ReadJson(TranscriptPath(chatId));
            if (existing == null) return;

            List<Q3Message> messages = MessagesFrom(existing);
            Write(chatId, title.Trim(), true, Q3Json.Str(existing, "model") ?? "", messages);
        }

        private static void Write(string chatId, string title, bool titleLocked,
                                  string model, List<Q3Message> messages)
        {
            try
            {
                long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

                var sb = new StringBuilder();
                sb.Append('{');
                sb.Append("\"chatId\":").Append(Q3Proc.JsonString(chatId)).Append(',');
                sb.Append("\"title\":").Append(Q3Proc.JsonString(title)).Append(',');
                sb.Append("\"titleLocked\":").Append(titleLocked ? "true" : "false").Append(',');
                sb.Append("\"model\":").Append(Q3Proc.JsonString(model ?? "")).Append(',');
                sb.Append("\"updatedAtMs\":").Append(now.ToString(CultureInfo.InvariantCulture)).Append(',');
                sb.Append("\"messages\":[");

                for (int i = 0; i < messages.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append("{\"role\":").Append(messages[i].Role.ToString(CultureInfo.InvariantCulture))
                      .Append(",\"text\":").Append(Q3Proc.JsonString(messages[i].Text))
                      .Append('}');
                }

                sb.Append("]}");

                File.WriteAllText(TranscriptPath(chatId), sb.ToString(), new UTF8Encoding(false));
                Prune();
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[Q3CNFU] Gecmis kaydedilemedi: " + ex.Message);
            }
        }

        // --- baslik turetme --------------------------------------------------

        /// <summary>Ilk kullanici mesajindan okunabilir bir baslik cikarir.</summary>
        public static string DeriveTitle(List<Q3Message> messages)
        {
            foreach (Q3Message m in messages)
            {
                if (m.Role != Q3Message.RoleUser || string.IsNullOrWhiteSpace(m.Text)) continue;

                string text = m.Text;

                // Prompt'a eklenmis konsol hatasi blogunu basliga katmayalim.
                int marker = text.IndexOf("--- Unity Console", StringComparison.Ordinal);
                if (marker > 0) text = text.Substring(0, marker);

                // Ilk anlamli cumle ya da satir.
                string flat = Flatten(text);
                int stop = flat.IndexOfAny(new[] { '.', '?', '!', ';' });
                if (stop >= 12 && stop < 64) flat = flat.Substring(0, stop);

                return Ellipsis(flat, 64);
            }

            return "(bos sohbet)";
        }

        /// <summary>Listede tanimayi kolaylastiran, son ajan cevabindan kisa alinti.</summary>
        private static string DerivePreview(List<Q3Message> messages)
        {
            for (int i = messages.Count - 1; i >= 0; i--)
            {
                Q3Message m = messages[i];
                if (m.Role != Q3Message.RoleAgent || string.IsNullOrWhiteSpace(m.Text)) continue;

                // Kod bloklarini onizlemeden cikar.
                var sb = new StringBuilder();
                bool inCode = false;

                foreach (string line in m.Text.Replace("\r\n", "\n").Split('\n'))
                {
                    string t = line.TrimStart();
                    if (t.StartsWith("```", StringComparison.Ordinal) ||
                        t.StartsWith("~~~", StringComparison.Ordinal))
                    {
                        inCode = !inCode;
                        continue;
                    }
                    if (!inCode) sb.Append(line).Append(' ');
                }

                string flat = Flatten(sb.ToString());
                if (flat.Length == 0) flat = "(kod)";
                return Ellipsis(flat, 110);
            }

            return "";
        }

        private static string Flatten(string s)
        {
            string flat = (s ?? "").Replace("\r", " ").Replace("\n", " ").Replace('\t', ' ');
            flat = flat.Replace("**", "").Replace("`", "").Trim();
            while (flat.Contains("  ")) flat = flat.Replace("  ", " ");
            return flat;
        }

        private static string Ellipsis(string s, int max)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Length > max ? s.Substring(0, max).TrimEnd() + "…" : s;
        }

        // --- okuma -----------------------------------------------------------

        private static object ReadJson(string path)
        {
            if (!File.Exists(path)) return null;

            try { return Q3Json.Parse(File.ReadAllText(path, Encoding.UTF8)); }
            catch (IOException) { return null; }
            catch (Exception) { return null; }
        }

        private static List<Q3Message> MessagesFrom(object root)
        {
            var result = new List<Q3Message>();
            List<object> items = Q3Json.Arr(Q3Json.Get(root, "messages"));
            if (items == null) return result;

            foreach (object item in items)
            {
                object roleValue = Q3Json.Get(item, "role");
                result.Add(new Q3Message
                {
                    Role = roleValue is double ? (int)(double)roleValue : Q3Message.RoleNote,
                    Text = Q3Json.Str(item, "text") ?? "",
                });
            }

            return result;
        }

        public static List<Q3Message> Load(string chatId)
        {
            object root = ReadJson(TranscriptPath(chatId));
            return root == null ? new List<Q3Message>() : MessagesFrom(root);
        }

        /// <summary>Bu projeye ait sohbetleri, en yenisi basta olacak sekilde listeler.</summary>
        public static List<HistoryEntry> List()
        {
            var byId = new Dictionary<string, HistoryEntry>(StringComparer.OrdinalIgnoreCase);

            AddLocalTranscripts(byId);

            var list = new List<HistoryEntry>(byId.Values);
            list.Sort((a, b) => b.UpdatedAtMs.CompareTo(a.UpdatedAtMs));
            return list;
        }

        private static void AddLocalTranscripts(Dictionary<string, HistoryEntry> byId)
        {
            try
            {
                foreach (string file in Directory.GetFiles(HistoryDirectory, "*.json"))
                {
                    object root = ReadJson(file);
                    if (root == null) continue;

                    string id = Q3Json.Str(root, "chatId");
                    if (string.IsNullOrEmpty(id)) continue;

                    object updated = Q3Json.Get(root, "updatedAtMs");
                    object locked = Q3Json.Get(root, "titleLocked");
                    List<Q3Message> messages = MessagesFrom(root);

                    byId[id] = new HistoryEntry
                    {
                        ChatId = id,
                        Title = Q3Json.Str(root, "title") ?? id,
                        Preview = DerivePreview(messages),
                        UpdatedAtMs = updated is double ? (long)(double)updated : 0,
                        MessageCount = messages.Count,
                        HasLocalTranscript = true,
                        TitleLocked = locked is bool && (bool)locked,
                    };
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[Q3CNFU] Gecmis klasoru taranamadi: " + ex.Message);
            }
        }

        // --- bakim -----------------------------------------------------------

        public static void Delete(string chatId)
        {
            try
            {
                string path = TranscriptPath(chatId);
                if (File.Exists(path)) File.Delete(path);
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[Q3CNFU] Gecmis silinemedi: " + ex.Message);
            }
        }

        private static void Prune()
        {
            try
            {
                string[] files = Directory.GetFiles(HistoryDirectory, "*.json");
                if (files.Length <= MaxKept) return;

                Array.Sort(files, (a, b) => File.GetLastWriteTimeUtc(b).CompareTo(File.GetLastWriteTimeUtc(a)));
                for (int i = MaxKept; i < files.Length; i++)
                {
                    try { File.Delete(files[i]); }
                    catch (IOException) { }
                }
            }
            catch (Exception)
            {
                // Budama basarisiz olsa da calismayi engellememeli.
            }
        }
    }
}
