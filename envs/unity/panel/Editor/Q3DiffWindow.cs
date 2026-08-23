// Assets/Editor/Q3CNFU/Q3DiffWindow.cs
// Ajanin degistirdigi dosyalari ve ne degistirdigini gosteren AYRI pencere.
// Salt goruntuleme: buradan mesaj yazilmaz, sadece bakilir ve geri alinir.
//
// Diff satirlari zengin metin YERINE arka plan rengiyle boyanir. Kod icinde
// gecen <b>, <color=...> gibi diziler IMGUI'nin zengin metin ayristiricisina
// yakalanmasin diye; boylece kod her zaman oldugu gibi gorunur.

using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace Q3CNFU.EditorTools
{
    public class Q3DiffWindow : EditorWindow
    {
        private const int MaxRenderedLines = 1500;

        [SerializeField] private int _selected = -1;
        [SerializeField] private Vector2 _listScroll;
        [SerializeField] private Vector2 _diffScroll;
        [SerializeField] private bool _followLatest = true;

        [NonSerialized] private int _seenVersion = -1;
        [NonSerialized] private DiffStyles _styles;

        [MenuItem("Window/Q3CNFU Degisiklikler")]
        public static Q3DiffWindow Open()
        {
            var w = GetWindow<Q3DiffWindow>("Q3 Diff");
            w.minSize = new Vector2(420, 300);
            w.Show();
            return w;
        }

        /// <summary>Pencere aciksa one alir, kapaliysa acar. Sohbet penceresi cagirir.</summary>
        public static void Reveal()
        {
            Q3DiffWindow[] existing = Resources.FindObjectsOfTypeAll<Q3DiffWindow>();
            if (existing != null && existing.Length > 0)
            {
                existing[0].Focus();
                existing[0].Repaint();
                return;
            }

            Open();
        }

        private void OnEnable()
        {
            EditorApplication.update += Watch;
        }

        private void OnDisable()
        {
            EditorApplication.update -= Watch;
        }

        /// <summary>Depo degistiginde gercek zamanli yenilenmek icin.</summary>
        private void Watch()
        {
            if (_seenVersion == Q3Changes.Version) return;

            _seenVersion = Q3Changes.Version;

            if (_followLatest) _selected = Q3Changes.All.Count - 1;
            Repaint();
        }

        private void OnGUI()
        {
            if (_styles == null || _styles.Pro != EditorGUIUtility.isProSkin)
                _styles = new DiffStyles(EditorGUIUtility.isProSkin);

            List<FileChange> changes = Q3Changes.All;

            DrawToolbar(changes);

            if (changes.Count == 0)
            {
                EditorGUILayout.Space(20);
                GUILayout.Label("Henuz degisiklik yok.\n" +
                                "Ajan bir dosya yazdiginda burada aninda gorunur.",
                                _styles.Caption);
                return;
            }

            DrawFileList(changes);

            if (_selected < 0 || _selected >= changes.Count) _selected = changes.Count - 1;
            DrawDiff(changes[_selected]);
        }

        private void DrawToolbar(List<FileChange> changes)
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                GUILayout.Label(changes.Count + " degisiklik", EditorStyles.miniLabel, GUILayout.Width(96));

                _followLatest = GUILayout.Toggle(_followLatest, "Sonuncuyu izle",
                                                 EditorStyles.toolbarButton, GUILayout.Width(104));

                GUILayout.FlexibleSpace();

                using (new EditorGUI.DisabledScope(changes.Count == 0))
                {
                    if (GUILayout.Button("Listeyi temizle", EditorStyles.toolbarButton, GUILayout.Width(100)))
                    {
                        if (EditorUtility.DisplayDialog("Q3CNFU",
                                "Degisiklik listesi temizlensin mi?\n\n" +
                                "Dosyalar oldugu gibi kalir; sadece kayit silinir ve " +
                                "geri alma imkani kaybolur.",
                                "Temizle", "Vazgec"))
                        {
                            Q3Changes.Clear();
                            _selected = -1;
                        }
                    }
                }
            }
        }

        private void DrawFileList(List<FileChange> changes)
        {
            _listScroll = EditorGUILayout.BeginScrollView(_listScroll,
                                                          GUILayout.MinHeight(74), GUILayout.MaxHeight(150));

            for (int i = changes.Count - 1; i >= 0; i--)
            {
                FileChange c = changes[i];
                bool isSelected = i == _selected;

                using (new EditorGUILayout.HorizontalScope(isSelected ? _styles.RowSelected : _styles.Row))
                {
                    string stats = "+" + c.LinesAdded + " / -" + c.LinesRemoved;
                    string label = c.DisplayPath;

                    if (c.Reverted) label = "[geri alindi] " + label;
                    else if (c.Before == null) label = "[yeni] " + label;

                    if (GUILayout.Button(label, _styles.RowLabel))
                    {
                        _selected = i;
                        _followLatest = false;
                        _diffScroll = Vector2.zero;
                    }

                    GUILayout.Label(stats, _styles.Stats, GUILayout.Width(90));
                    GUILayout.Label(c.At.ToString("HH:mm:ss"), _styles.Caption, GUILayout.Width(58));
                }
            }

            EditorGUILayout.EndScrollView();
        }

        private void DrawDiff(FileChange change)
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                GUILayout.Label(change.DisplayPath, EditorStyles.miniBoldLabel);
                GUILayout.FlexibleSpace();

                if (GUILayout.Button("Dosyayi ac", EditorStyles.toolbarButton, GUILayout.Width(80)))
                    OpenInEditor(change);

                if (GUILayout.Button("Kopyala", EditorStyles.toolbarButton, GUILayout.Width(66)))
                    EditorGUIUtility.systemCopyBuffer = change.After ?? change.Diff;

                using (new EditorGUI.DisabledScope(change.Reverted))
                {
                    if (GUILayout.Button("Geri al", EditorStyles.toolbarButton, GUILayout.Width(66)))
                        RevertChange(change);
                }
            }

            if (!change.Reverted && !Q3Changes.MatchesDisk(change))
            {
                EditorGUILayout.HelpBox(
                    "Bu dosya ajan yazdiktan sonra baska bir yerden daha degisti. " +
                    "Geri alirsan o degisiklikler de kaybolur.",
                    MessageType.Warning);
            }

            _diffScroll = EditorGUILayout.BeginScrollView(_diffScroll, GUILayout.ExpandHeight(true));

            string diff = change.Diff;
            if (string.IsNullOrEmpty(diff))
            {
                GUILayout.Label("Bu degisiklik icin diff gelmedi. Dosyanin son hali:", _styles.Caption);
                GUILayout.Label(Clip(change.After ?? ""), _styles.Context);
            }
            else
            {
                DrawDiffLines(diff);
            }

            EditorGUILayout.EndScrollView();
        }

        private void DrawDiffLines(string diff)
        {
            string[] lines = diff.Replace("\r\n", "\n").Split('\n');
            int shown = 0;

            foreach (string line in lines)
            {
                // Dosya yolu basliklarini atliyoruz; yol zaten ustte yaziyor.
                if (line.StartsWith("--- ", StringComparison.Ordinal) ||
                    line.StartsWith("+++ ", StringComparison.Ordinal))
                    continue;

                if (shown++ >= MaxRenderedLines)
                {
                    GUILayout.Label("… diff kisaltildi (" + (lines.Length - shown) + " satir daha). " +
                                    "Tamami icin Kopyala.", _styles.Caption);
                    break;
                }

                GUIStyle style;

                if (line.StartsWith("@@", StringComparison.Ordinal)) style = _styles.Hunk;
                else if (line.StartsWith("+", StringComparison.Ordinal)) style = _styles.Added;
                else if (line.StartsWith("-", StringComparison.Ordinal)) style = _styles.Removed;
                else style = _styles.Context;

                // Bos satirin da arka plani cizilsin diye tek bosluk veriyoruz.
                GUILayout.Label(line.Length == 0 ? " " : line, style);
            }
        }

        private static string Clip(string s)
        {
            const int max = 12000;
            if (string.IsNullOrEmpty(s) || s.Length <= max) return s;
            return s.Substring(0, max) + "\n… (kisaltildi)";
        }

        private void RevertChange(FileChange change)
        {
            // Onay penceresini ve dosya islemini GUI olayinin ICINDE calistirmak,
            // Unity'nin "Hold on (busy)" ekranina MouseUp olarak yansiyor. Bir
            // sonraki editor adimina erteliyoruz ki tiklama hemen tamamlansin.
            EditorApplication.delayCall += () =>
            {
                string what = change.Before == null
                    ? "Bu dosya ajan tarafindan olusturuldu. Geri alma dosyayi SILER.\n\n"
                    : "Dosya, ajanin degisikliginden onceki haline dondurulecek.\n\n";

                string note = IsScript(change.Path)
                    ? "\n\nBu bir script; Unity degisiklikten sonra yeniden derleyecek."
                    : "";

                if (!EditorUtility.DisplayDialog("Q3CNFU", what + change.DisplayPath + note,
                                                 "Geri al", "Vazgec"))
                    return;

                string error;
                if (Q3Changes.Revert(change, out error))
                    Repaint();
                else
                    EditorUtility.DisplayDialog("Q3CNFU", "Geri alinamadi:\n" + error, "Tamam");
            };
        }

        private static bool IsScript(string path)
        {
            return !string.IsNullOrEmpty(path) &&
                   path.EndsWith(".cs", StringComparison.OrdinalIgnoreCase);
        }

        private static void OpenInEditor(FileChange change)
        {
            string root = Q3Runner.ProjectRoot();

            if (change.Path.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            {
                string rel = change.Path.Substring(root.Length).TrimStart('\\', '/').Replace('\\', '/');
                var asset = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(rel);

                if (asset != null)
                {
                    AssetDatabase.OpenAsset(asset);
                    return;
                }
            }

            EditorUtility.RevealInFinder(change.Path);
        }

        // -------------------------------------------------------------------

        private class DiffStyles
        {
            public readonly bool Pro;

            public GUIStyle Added;
            public GUIStyle Removed;
            public GUIStyle Context;
            public GUIStyle Hunk;
            public GUIStyle Row;
            public GUIStyle RowSelected;
            public GUIStyle RowLabel;
            public GUIStyle Stats;
            public GUIStyle Caption;

            public DiffStyles(bool pro)
            {
                Pro = pro;

                Font mono = Font.CreateDynamicFontFromOSFont(
                    new[] { "Consolas", "Cascadia Mono", "Menlo", "Monaco", "DejaVu Sans Mono", "Courier New" },
                    12);

                Added = Line(mono,
                             pro ? new Color32(0x1E, 0x3A, 0x24, 0xFF) : new Color32(0xDD, 0xF5, 0xE1, 0xFF),
                             pro ? new Color32(0x9C, 0xE8, 0xB0, 0xFF) : new Color32(0x0B, 0x50, 0x21, 0xFF));

                Removed = Line(mono,
                               pro ? new Color32(0x44, 0x20, 0x22, 0xFF) : new Color32(0xFB, 0xE1, 0xE3, 0xFF),
                               pro ? new Color32(0xF0, 0xA5, 0xA9, 0xFF) : new Color32(0x69, 0x11, 0x17, 0xFF));

                Context = Line(mono,
                               pro ? new Color32(0x1F, 0x1F, 0x1F, 0xFF) : new Color32(0xFC, 0xFC, 0xFC, 0xFF),
                               pro ? new Color32(0xB8, 0xB8, 0xB8, 0xFF) : new Color32(0x33, 0x33, 0x33, 0xFF));

                Hunk = Line(mono,
                            pro ? new Color32(0x25, 0x30, 0x40, 0xFF) : new Color32(0xE4, 0xEC, 0xF7, 0xFF),
                            pro ? new Color32(0x86, 0xB4, 0xEC, 0xFF) : new Color32(0x1B, 0x40, 0x70, 0xFF));

                Row = new GUIStyle { padding = new RectOffset(4, 4, 1, 1) };
                RowSelected = new GUIStyle
                {
                    normal = { background = Solid(pro ? new Color32(0x2C, 0x3B, 0x50, 0xFF)
                                                      : new Color32(0xD6, 0xE4, 0xF7, 0xFF)) },
                    padding = new RectOffset(4, 4, 1, 1),
                };

                RowLabel = new GUIStyle(EditorStyles.label)
                {
                    alignment = TextAnchor.MiddleLeft,
                    fontSize = 11,
                };

                Stats = new GUIStyle(EditorStyles.miniLabel) { alignment = TextAnchor.MiddleRight };
                Caption = new GUIStyle(EditorStyles.miniLabel) { wordWrap = true };
            }

            private static GUIStyle Line(Font mono, Color background, Color text)
            {
                var style = new GUIStyle
                {
                    font = mono,
                    fontSize = 12,
                    wordWrap = false,
                    richText = false,          // kod icindeki <...> dizileri bozulmasin
                    alignment = TextAnchor.MiddleLeft,
                    padding = new RectOffset(6, 6, 1, 1),
                    normal = { background = Solid(background), textColor = text },
                };
                return style;
            }

            private static Texture2D Solid(Color c)
            {
                var t = new Texture2D(1, 1, TextureFormat.RGBA32, false)
                {
                    hideFlags = HideFlags.HideAndDontSave,
                    filterMode = FilterMode.Point,
                };
                t.SetPixel(0, 0, c);
                t.Apply();
                return t;
            }
        }
    }
}
