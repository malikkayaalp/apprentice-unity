// Assets/Editor/Q3CNFU/Q3Markdown.cs
// Ajan cevabini metin / kod bloklarina ayirir ve kod icin sozdizimi renklendirmesi uretir.
//
// IMGUI'nin zengin metin ayristiricisi sadece <b> <i> <size> <color> <material>
// <quad> etiketlerini yorumlar; digerleri (ornegin C# generic'leri: List<string>)
// oldugu gibi cizilir. Yine de kodun icinde bu alti etiketten biri gecerse
// renklendirmeyi tamamen kapatiyoruz, yoksa kod bozuk gorunur.

using System;
using System.Collections.Generic;
using System.Text;

namespace Q3CNFU.EditorTools
{
    internal class MdBlock
    {
        public bool IsCode;
        public string Language = "";
        public string Text = "";
    }

    internal static class Q3Markdown
    {
        // --- blok ayristirma ------------------------------------------------

        public static List<MdBlock> Parse(string source)
        {
            var blocks = new List<MdBlock>();
            if (string.IsNullOrEmpty(source)) return blocks;

            string[] lines = source.Replace("\r\n", "\n").Replace('\r', '\n').Split('\n');

            var buffer = new StringBuilder();
            bool inCode = false;
            string language = "";
            string fence = null;   // acilis citasi (``` veya ~~~ ve uzunlugu)

            foreach (string line in lines)
            {
                string trimmed = line.TrimStart();
                string opener = FenceToken(trimmed);

                if (!inCode && opener != null)
                {
                    Flush(blocks, buffer, false, "");
                    inCode = true;
                    fence = opener;
                    language = trimmed.Substring(opener.Length).Trim();
                    continue;
                }

                // Kapanis citasi en az acilis kadar uzun ve ayni karakterde olmali.
                if (inCode && opener != null && opener[0] == fence[0] && opener.Length >= fence.Length)
                {
                    Flush(blocks, buffer, true, language);
                    inCode = false;
                    language = "";
                    fence = null;
                    continue;
                }

                buffer.Append(line).Append('\n');
            }

            // Akis sirasinda blok henuz kapanmamis olabilir; yine de gosterelim.
            Flush(blocks, buffer, inCode, language);
            return blocks;
        }

        private static string FenceToken(string trimmedLine)
        {
            if (trimmedLine.Length < 3) return null;

            char c = trimmedLine[0];
            if (c != '`' && c != '~') return null;

            int n = 0;
            while (n < trimmedLine.Length && trimmedLine[n] == c) n++;
            return n >= 3 ? trimmedLine.Substring(0, n) : null;
        }

        private static void Flush(List<MdBlock> blocks, StringBuilder buffer, bool isCode, string language)
        {
            if (buffer.Length == 0) return;

            string text = buffer.ToString();
            buffer.Length = 0;

            if (!isCode && string.IsNullOrWhiteSpace(text)) return;

            blocks.Add(new MdBlock
            {
                IsCode = isCode,
                Language = language ?? "",
                Text = isCode ? text.TrimEnd('\n') : text.Trim('\n')
            });
        }

        // --- duz metin icin hafif bicimlendirme ------------------------------

        /// <summary>**kalin**, *egik*, `kod`, ## baslik ve - madde isaretlerini IMGUI etiketlerine cevirir.</summary>
        public static string FormatProse(string text, bool proSkin)
        {
            if (string.IsNullOrEmpty(text)) return "";

            string inlineCode = proSkin ? "#DCDCAA" : "#A31515";
            var sb = new StringBuilder(text.Length + 64);
            string[] lines = text.Split('\n');

            for (int li = 0; li < lines.Length; li++)
            {
                string line = lines[li];
                string trimmed = line.TrimStart();

                // Basliklar
                int hashes = 0;
                while (hashes < trimmed.Length && trimmed[hashes] == '#') hashes++;
                if (hashes > 0 && hashes <= 6 && hashes < trimmed.Length && trimmed[hashes] == ' ')
                {
                    sb.Append("<b>").Append(InlineSpans(trimmed.Substring(hashes + 1), inlineCode)).Append("</b>");
                    if (li < lines.Length - 1) sb.Append('\n');
                    continue;
                }

                // Madde isaretleri
                if (trimmed.StartsWith("- ", StringComparison.Ordinal) ||
                    trimmed.StartsWith("* ", StringComparison.Ordinal))
                {
                    int indent = line.Length - trimmed.Length;
                    sb.Append(new string(' ', indent)).Append("• ")
                      .Append(InlineSpans(trimmed.Substring(2), inlineCode));
                    if (li < lines.Length - 1) sb.Append('\n');
                    continue;
                }

                sb.Append(InlineSpans(line, inlineCode));
                if (li < lines.Length - 1) sb.Append('\n');
            }

            return sb.ToString();
        }

        private static string InlineSpans(string s, string inlineCodeColor)
        {
            s = Wrap(s, "**", "<b>", "</b>");
            s = Wrap(s, "`", "<color=" + inlineCodeColor + ">", "</color>");
            return s;
        }

        // Ayni satirda esleseen sinirlayici ciftlerini etiketlere cevirir.
        private static string Wrap(string s, string delimiter, string open, string close)
        {
            if (s.IndexOf(delimiter, StringComparison.Ordinal) < 0) return s;

            var sb = new StringBuilder(s.Length + 32);
            int i = 0;
            bool opened = false;

            while (i < s.Length)
            {
                if (i + delimiter.Length <= s.Length &&
                    string.CompareOrdinal(s, i, delimiter, 0, delimiter.Length) == 0)
                {
                    // Kapanis esi yoksa sinirlayiciyi oldugu gibi birak.
                    if (!opened && s.IndexOf(delimiter, i + delimiter.Length, StringComparison.Ordinal) < 0)
                    {
                        sb.Append(delimiter);
                        i += delimiter.Length;
                        continue;
                    }

                    sb.Append(opened ? close : open);
                    opened = !opened;
                    i += delimiter.Length;
                    continue;
                }

                sb.Append(s[i++]);
            }

            if (opened) sb.Append(close);
            return sb.ToString();
        }

        // --- sozdizimi renklendirme -----------------------------------------

        private static readonly string[] ImguiTags = { "<b>", "</b>", "<i>", "</i>", "<color", "<size", "<material", "<quad" };

        private static readonly HashSet<string> Keywords = new HashSet<string>(StringComparer.Ordinal)
        {
            // C#
            "abstract","as","base","bool","break","byte","case","catch","char","checked","class","const",
            "continue","decimal","default","delegate","do","double","else","enum","event","explicit","extern",
            "false","finally","fixed","float","for","foreach","goto","if","implicit","in","int","interface",
            "internal","is","lock","long","namespace","new","null","object","operator","out","override",
            "params","private","protected","public","readonly","ref","return","sbyte","sealed","short",
            "sizeof","stackalloc","static","string","struct","switch","this","throw","true","try","typeof",
            "uint","ulong","unchecked","unsafe","ushort","using","var","virtual","void","volatile","while",
            "async","await","yield","get","set","nameof","when","where","partial",
            // JS / TS / Python / shell tarafindan da sik kullanilanlar
            "function","let","const","export","import","from","def","elif","None","True","False","self",
            "lambda","pass","raise","except","with","echo","then","fi","do","done","esac",
        };

        /// <summary>Kod blogunu renklendirir. Renklendirme guvenli degilse null doner (duz cizilmeli).</summary>
        public static string Highlight(string code, string language, bool proSkin)
        {
            if (string.IsNullOrEmpty(code)) return "";

            foreach (string tag in ImguiTags)
                if (code.IndexOf(tag, StringComparison.OrdinalIgnoreCase) >= 0)
                    return null;   // IMGUI bu etiketleri yutar, renklendirmeyi atla

            string cKeyword = proSkin ? "#569CD6" : "#0000FF";
            string cString  = proSkin ? "#CE9178" : "#A31515";
            string cComment = proSkin ? "#6A9955" : "#008000";
            string cNumber  = proSkin ? "#B5CEA8" : "#098658";

            bool hashComments = IsHashCommentLanguage(language);

            var sb = new StringBuilder(code.Length + 256);
            int i = 0;
            int n = code.Length;

            while (i < n)
            {
                char c = code[i];

                // // satir yorumu
                if (c == '/' && i + 1 < n && code[i + 1] == '/')
                {
                    int start = i;
                    while (i < n && code[i] != '\n') i++;
                    Span(sb, cComment, code, start, i);
                    continue;
                }

                // /* blok yorumu */
                if (c == '/' && i + 1 < n && code[i + 1] == '*')
                {
                    int start = i;
                    i += 2;
                    while (i + 1 < n && !(code[i] == '*' && code[i + 1] == '/')) i++;
                    i = Math.Min(n, i + 2);
                    Span(sb, cComment, code, start, i);
                    continue;
                }

                // # satir yorumu (python / shell / yaml)
                if (c == '#' && hashComments)
                {
                    int start = i;
                    while (i < n && code[i] != '\n') i++;
                    Span(sb, cComment, code, start, i);
                    continue;
                }

                // @"verbatim" metin
                if (c == '@' && i + 1 < n && code[i + 1] == '"')
                {
                    int start = i;
                    i += 2;
                    while (i < n)
                    {
                        if (code[i] == '"')
                        {
                            if (i + 1 < n && code[i + 1] == '"') { i += 2; continue; }
                            i++;
                            break;
                        }
                        i++;
                    }
                    Span(sb, cString, code, start, i);
                    continue;
                }

                // "metin" ve 'karakter'
                if (c == '"' || c == '\'')
                {
                    int start = i;
                    char quote = c;
                    i++;
                    while (i < n)
                    {
                        if (code[i] == '\\') { i += 2; continue; }
                        if (code[i] == quote) { i++; break; }
                        if (code[i] == '\n') break;      // kapanmamis metin satiri asmasin
                        i++;
                    }
                    Span(sb, cString, code, start, Math.Min(i, n));
                    continue;
                }

                // sayilar
                if (char.IsDigit(c) && (i == 0 || !IsWordChar(code[i - 1])))
                {
                    int start = i;
                    while (i < n && (char.IsLetterOrDigit(code[i]) || code[i] == '.' || code[i] == '_')) i++;
                    Span(sb, cNumber, code, start, i);
                    continue;
                }

                // tanimlayici / anahtar kelime
                if (IsWordStart(c))
                {
                    int start = i;
                    while (i < n && IsWordChar(code[i])) i++;
                    string word = code.Substring(start, i - start);

                    if (Keywords.Contains(word)) Span(sb, cKeyword, code, start, i);
                    else sb.Append(word);
                    continue;
                }

                sb.Append(c);
                i++;
            }

            return sb.ToString();
        }

        private static bool IsHashCommentLanguage(string language)
        {
            if (string.IsNullOrEmpty(language)) return false;

            switch (language.Trim().ToLowerInvariant())
            {
                case "py":
                case "python":
                case "sh":
                case "bash":
                case "shell":
                case "zsh":
                case "ps1":
                case "powershell":
                case "yaml":
                case "yml":
                case "toml":
                case "ini":
                case "makefile":
                case "dockerfile":
                    return true;
                default:
                    return false;
            }
        }

        private static void Span(StringBuilder sb, string color, string source, int start, int end)
        {
            sb.Append("<color=").Append(color).Append('>')
              .Append(source, start, end - start)
              .Append("</color>");
        }

        private static bool IsWordStart(char c) { return char.IsLetter(c) || c == '_'; }
        private static bool IsWordChar(char c) { return char.IsLetterOrDigit(c) || c == '_'; }
    }
}
