// Assets/Editor/Q3CNFU/Q3Styles.cs
// Sohbet balonlari ve kod kutulari icin IMGUI stilleri.
// EditorStyles yalnizca OnGUI icinde gecerli oldugundan tembel olusturulur.
// Punto olcegi (4K ekranlar icin) degistiginde stiller yeniden uretilir.

using UnityEditor;
using UnityEngine;

namespace Q3CNFU.EditorTools
{
    internal class Q3Styles
    {
        public const float MinScale = 0.8f;
        public const float MaxScale = 2.5f;

        private const int BaseProseSize = 12;
        private const int BaseCodeSize = 12;
        private const int BaseCaptionSize = 10;

        private static Q3Styles _instance;
        private static bool _cachedPro;
        private static float _cachedScale;

        public static Q3Styles Get(float scale)
        {
            scale = Mathf.Clamp(scale, MinScale, MaxScale);
            bool pro = EditorGUIUtility.isProSkin;

            if (_instance == null || _cachedPro != pro || !Mathf.Approximately(_cachedScale, scale))
            {
                _instance = new Q3Styles(pro, scale);
                _cachedPro = pro;
                _cachedScale = scale;
            }

            return _instance;
        }

        public readonly bool Pro;
        public readonly float Scale;

        public GUIStyle UserBubble;
        public GUIStyle AgentBubble;
        public GUIStyle NoteBubble;
        public GUIStyle ErrorBubble;
        public GUIStyle CodeBox;
        public GUIStyle CodeHeader;
        public GUIStyle HistoryRow;

        public GUIStyle RoleLabel;
        public GUIStyle Prose;
        public GUIStyle Code;        // renklendirilmis kod (zengin metin acik)
        public GUIStyle CodePlain;   // renklendirilemeyen kod (zengin metin kapali)
        public GUIStyle ToolLine;
        public GUIStyle Caption;
        public GUIStyle IconButton;
        public GUIStyle MiniButton;
        public GUIStyle Input;

        /// <summary>Olcege gore satir yuksekligi; dugme/acilir boylari icin.</summary>
        public float RowHeight { get { return Mathf.Round(22 * Scale); } }

        private static Font _mono;
        private static int _monoSize;

        public Font MonoFont
        {
            get
            {
                int want = Mathf.RoundToInt(BaseCodeSize * Scale);
                if (_mono == null || _monoSize != want)
                {
                    _mono = Font.CreateDynamicFontFromOSFont(
                        new[]
                        {
                            "Consolas", "Cascadia Mono", "JetBrains Mono",
                            "Menlo", "Monaco", "DejaVu Sans Mono", "Courier New",
                        },
                        want);
                    _monoSize = want;
                }
                return _mono;
            }
        }

        private Q3Styles(bool pro, float scale)
        {
            Pro = pro;
            Scale = scale;

            Color userBg  = pro ? new Color32(0x30, 0x3C, 0x4E, 0xFF) : new Color32(0xDC, 0xE7, 0xF7, 0xFF);
            Color agentBg = pro ? new Color32(0x2B, 0x2B, 0x2B, 0xFF) : new Color32(0xF6, 0xF6, 0xF6, 0xFF);
            Color noteBg  = pro ? new Color32(0x25, 0x2E, 0x25, 0xFF) : new Color32(0xE8, 0xF2, 0xE6, 0xFF);
            Color errBg   = pro ? new Color32(0x3E, 0x26, 0x26, 0xFF) : new Color32(0xFA, 0xE2, 0xE2, 0xFF);
            Color codeBg  = pro ? new Color32(0x1D, 0x1D, 0x1D, 0xFF) : new Color32(0xFB, 0xFB, 0xFB, 0xFF);
            Color codeHdr = pro ? new Color32(0x2A, 0x2A, 0x2A, 0xFF) : new Color32(0xEE, 0xEE, 0xEE, 0xFF);
            Color rowBg   = pro ? new Color32(0x32, 0x32, 0x32, 0xFF) : new Color32(0xEC, 0xEC, 0xEC, 0xFF);

            UserBubble  = Bubble(userBg, scale);
            AgentBubble = Bubble(agentBg, scale);
            NoteBubble  = Bubble(noteBg, scale);
            ErrorBubble = Bubble(errBg, scale);
            HistoryRow  = Bubble(rowBg, scale);

            CodeBox = new GUIStyle
            {
                normal = { background = Solid(codeBg) },
                margin = Pad(0, 0, 4, 6, scale),
            };

            CodeHeader = new GUIStyle
            {
                normal = { background = Solid(codeHdr) },
                padding = Pad(8, 4, 3, 3, scale),
            };

            RoleLabel = new GUIStyle(EditorStyles.miniBoldLabel)
            {
                fontSize = Size(BaseCaptionSize + 1, scale),
                margin = Pad(0, 0, 0, 2, scale),
            };

            Prose = new GUIStyle(EditorStyles.label)
            {
                wordWrap = true,
                richText = true,
                alignment = TextAnchor.UpperLeft,
                fontSize = Size(BaseProseSize, scale),
                padding = Pad(2, 2, 2, 2, scale),
            };

            Code = new GUIStyle(EditorStyles.label)
            {
                wordWrap = true,
                richText = true,
                alignment = TextAnchor.UpperLeft,
                font = MonoFont,
                fontSize = Size(BaseCodeSize, scale),
                padding = Pad(8, 8, 6, 8, scale),
            };
            Code.normal.textColor = pro ? new Color32(0xD4, 0xD4, 0xD4, 0xFF) : new Color32(0x1E, 0x1E, 0x1E, 0xFF);

            CodePlain = new GUIStyle(Code) { richText = false };

            ToolLine = new GUIStyle(EditorStyles.miniLabel)
            {
                wordWrap = true,
                richText = true,
                fontSize = Size(BaseCaptionSize + 1, scale),
                padding = Pad(2, 2, 1, 1, scale),
            };
            ToolLine.normal.textColor = pro ? new Color(0.62f, 0.72f, 0.85f) : new Color(0.25f, 0.38f, 0.58f);

            Caption = new GUIStyle(EditorStyles.miniLabel)
            {
                richText = true,
                wordWrap = true,
                fontSize = Size(BaseCaptionSize, scale),
            };
            Caption.normal.textColor = pro ? new Color(0.62f, 0.62f, 0.62f) : new Color(0.42f, 0.42f, 0.42f);

            IconButton = new GUIStyle(EditorStyles.miniButton)
            {
                fontSize = Size(BaseCaptionSize, scale),
                padding = Pad(3, 3, 1, 1, scale),
                margin = Pad(2, 0, 0, 0, scale),
            };

            MiniButton = new GUIStyle(EditorStyles.miniButton)
            {
                fontSize = Size(BaseCaptionSize, scale),
                padding = Pad(6, 6, 1, 1, scale),
            };

            Input = new GUIStyle(EditorStyles.textArea)
            {
                wordWrap = true,
                fontSize = Size(BaseProseSize, scale),
                padding = Pad(6, 6, 5, 5, scale),
            };
        }

        private static int Size(int baseSize, float scale)
        {
            return Mathf.Max(8, Mathf.RoundToInt(baseSize * scale));
        }

        private static RectOffset Pad(int left, int right, int top, int bottom, float scale)
        {
            return new RectOffset(Mathf.RoundToInt(left * scale), Mathf.RoundToInt(right * scale),
                                  Mathf.RoundToInt(top * scale), Mathf.RoundToInt(bottom * scale));
        }

        private static GUIStyle Bubble(Color background, float scale)
        {
            return new GUIStyle
            {
                normal = { background = Solid(background) },
                padding = Pad(8, 8, 6, 8, scale),
                margin = Pad(2, 2, 3, 3, scale),
            };
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

        // --- ikonlar ---------------------------------------------------------

        private static Texture _copyIcon;
        private static bool _copyIconSearched;

        /// <summary>Kopyala ikonu. Unity surumleri arasinda ad degistigi icin
        /// birkac aday denenir; hicbiri yoksa metin glifine duser.</summary>
        public static GUIContent CopyIcon(string tooltip)
        {
            if (!_copyIconSearched)
            {
                _copyIconSearched = true;
                foreach (string name in new[]
                {
                    "Clipboard", "d_Clipboard",
                    "TreeEditor.Duplicate", "d_TreeEditor.Duplicate",
                    "UnityEditor.ConsoleWindow", "d_UnityEditor.ConsoleWindow",
                })
                {
                    Texture t = EditorGUIUtility.FindTexture(name);
                    if (t == null) continue;
                    _copyIcon = t;
                    break;
                }
            }

            return _copyIcon != null
                ? new GUIContent(_copyIcon, tooltip)
                : new GUIContent("⧉", tooltip);
        }
    }
}
