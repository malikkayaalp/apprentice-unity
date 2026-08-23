// Assets/Editor/Q3CNFU/Q3Json.cs
// panel_runner.py'nin JSONL ciktisini okumak icin minimal JSON okuyucu.
// Unity'nin JsonUtility'si sema bilinmeyen ic ice yapilari cozemedigi icin yazildi.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Q3CNFU.EditorTools
{
    internal static class Q3Json
    {
        /// <summary>Tek satirlik JSON'u ayristirir. Hata olursa null doner.</summary>
        public static object Parse(string json)
        {
            if (string.IsNullOrEmpty(json)) return null;
            int i = 0;
            try
            {
                object v = ParseValue(json, ref i);
                return v;
            }
            catch
            {
                return null;
            }
        }

        // --- erisim yardimcilari -------------------------------------------

        public static object Get(object node, string key)
        {
            var d = node as Dictionary<string, object>;
            if (d == null) return null;
            object v;
            return d.TryGetValue(key, out v) ? v : null;
        }

        public static object Get(object node, string a, string b)
        {
            return Get(Get(node, a), b);
        }

        public static string Str(object node)
        {
            return node as string;
        }

        public static string Str(object node, string key)
        {
            return Get(node, key) as string;
        }

        public static List<object> Arr(object node)
        {
            return node as List<object>;
        }

        public static Dictionary<string, object> Obj(object node)
        {
            return node as Dictionary<string, object>;
        }

        // --- ayristirici ----------------------------------------------------

        private static void SkipWs(string s, ref int i)
        {
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
        }

        private static object ParseValue(string s, ref int i)
        {
            SkipWs(s, ref i);
            if (i >= s.Length) throw new FormatException("beklenmeyen son");

            switch (s[i])
            {
                case '{': return ParseObject(s, ref i);
                case '[': return ParseArray(s, ref i);
                case '"': return ParseString(s, ref i);
                case 't': Expect(s, ref i, "true"); return true;
                case 'f': Expect(s, ref i, "false"); return false;
                case 'n': Expect(s, ref i, "null"); return null;
                default: return ParseNumber(s, ref i);
            }
        }

        private static void Expect(string s, ref int i, string literal)
        {
            if (i + literal.Length > s.Length || string.CompareOrdinal(s, i, literal, 0, literal.Length) != 0)
                throw new FormatException("beklenen: " + literal);
            i += literal.Length;
        }

        private static Dictionary<string, object> ParseObject(string s, ref int i)
        {
            var d = new Dictionary<string, object>();
            i++; // '{'
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return d; }

            while (true)
            {
                SkipWs(s, ref i);
                if (i >= s.Length || s[i] != '"') throw new FormatException("anahtar bekleniyordu");
                string key = ParseString(s, ref i);
                SkipWs(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new FormatException("':' bekleniyordu");
                i++;
                d[key] = ParseValue(s, ref i);
                SkipWs(s, ref i);
                if (i >= s.Length) throw new FormatException("kapanmamis nesne");
                if (s[i] == ',') { i++; continue; }
                if (s[i] == '}') { i++; return d; }
                throw new FormatException("',' veya '}' bekleniyordu");
            }
        }

        private static List<object> ParseArray(string s, ref int i)
        {
            var list = new List<object>();
            i++; // '['
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return list; }

            while (true)
            {
                list.Add(ParseValue(s, ref i));
                SkipWs(s, ref i);
                if (i >= s.Length) throw new FormatException("kapanmamis dizi");
                if (s[i] == ',') { i++; continue; }
                if (s[i] == ']') { i++; return list; }
                throw new FormatException("',' veya ']' bekleniyordu");
            }
        }

        private static string ParseString(string s, ref int i)
        {
            var sb = new StringBuilder();
            i++; // acilis tirnagi

            while (i < s.Length)
            {
                char c = s[i++];
                if (c == '"') return sb.ToString();

                if (c != '\\') { sb.Append(c); continue; }
                if (i >= s.Length) break;

                char esc = s[i++];
                switch (esc)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 > s.Length) throw new FormatException("eksik \\u");
                        sb.Append((char)ushort.Parse(s.Substring(i, 4), NumberStyles.HexNumber,
                                                    CultureInfo.InvariantCulture));
                        i += 4;
                        break;
                    default: sb.Append(esc); break;
                }
            }

            throw new FormatException("kapanmamis metin");
        }

        private static object ParseNumber(string s, ref int i)
        {
            int start = i;
            while (i < s.Length && "+-.eE0123456789".IndexOf(s[i]) >= 0) i++;
            if (i == start) throw new FormatException("sayi bekleniyordu");

            double d;
            if (double.TryParse(s.Substring(start, i - start), NumberStyles.Float,
                                CultureInfo.InvariantCulture, out d))
                return d;

            throw new FormatException("gecersiz sayi");
        }
    }
}
