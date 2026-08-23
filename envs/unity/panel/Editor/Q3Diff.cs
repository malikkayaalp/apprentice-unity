// Assets/Editor/Q3CNFU/Q3Diff.cs
// Satir bazli unified diff. CursorBridge'de diff'i CLI hazir veriyordu; burada
// panel_runner.py yalnizca before/after yollar, diff'i biz uretiriz.
//
// LCS tablosu O(n*m) bellek: 3000x3000 satir = 36 MB int, editor icin fazla.
// Bu sinirin ustunde diff uretmeyi birakip "tum dosya degisti" gosteriyoruz;
// Diff penceresi zaten After'i oldugu gibi cizebiliyor.

using System;
using System.Collections.Generic;
using System.Text;

namespace Q3CNFU.EditorTools
{
    internal static class Q3Diff
    {
        private const int MaxLines = 3000;
        private const int Context = 3;

        public static string Unified(string before, string after, string label,
                                     out int added, out int removed)
        {
            added = 0;
            removed = 0;

            string[] a = Split(before);
            string[] b = Split(after);

            if (before == null)
            {
                added = b.Length;
                var nb = new StringBuilder();
                nb.Append("--- /dev/null\n+++ ").Append(label).Append('\n');
                nb.Append("@@ -0,0 +1,").Append(b.Length).Append(" @@\n");
                foreach (string line in b) nb.Append('+').Append(line).Append('\n');
                return nb.ToString();
            }

            if (a.Length > MaxLines || b.Length > MaxLines)
            {
                added = b.Length;
                removed = a.Length;
                return "";   // pencere "diff gelmedi" yoluna duser ve After'i gosterir
            }

            // LCS uzunluk tablosu (geriden ileri), sonra yurutme.
            var lcs = new int[a.Length + 1, b.Length + 1];
            for (int i = a.Length - 1; i >= 0; i--)
                for (int j = b.Length - 1; j >= 0; j--)
                    lcs[i, j] = string.Equals(a[i], b[j], StringComparison.Ordinal)
                        ? lcs[i + 1, j + 1] + 1
                        : Math.Max(lcs[i + 1, j], lcs[i, j + 1]);

            // Op listesi: ' ' ortak, '-' silindi, '+' eklendi.
            var ops = new List<KeyValuePair<char, string>>();
            int x = 0, y = 0;
            while (x < a.Length && y < b.Length)
            {
                if (string.Equals(a[x], b[y], StringComparison.Ordinal))
                {
                    ops.Add(new KeyValuePair<char, string>(' ', a[x])); x++; y++;
                }
                else if (lcs[x + 1, y] >= lcs[x, y + 1])
                {
                    ops.Add(new KeyValuePair<char, string>('-', a[x])); x++;
                }
                else
                {
                    ops.Add(new KeyValuePair<char, string>('+', b[y])); y++;
                }
            }
            while (x < a.Length) { ops.Add(new KeyValuePair<char, string>('-', a[x])); x++; }
            while (y < b.Length) { ops.Add(new KeyValuePair<char, string>('+', b[y])); y++; }

            foreach (var op in ops)
            {
                if (op.Key == '+') added++;
                else if (op.Key == '-') removed++;
            }

            if (added == 0 && removed == 0) return "";

            // Baglamli hunk'lar.
            var sb = new StringBuilder();
            sb.Append("--- ").Append(label).Append("\n+++ ").Append(label).Append('\n');

            int n = ops.Count;
            int idx = 0;
            int aLine = 0, bLine = 0;   // sifir tabanli, ops uzerinde yurutulen konum

            while (idx < n)
            {
                // Sonraki degisikligi bul.
                while (idx < n && ops[idx].Key == ' ') { idx++; aLine++; bLine++; }
                if (idx >= n) break;

                int start = Math.Max(0, idx - Context);
                int aStart = aLine - (idx - start);
                int bStart = bLine - (idx - start);

                // Hunk sonu: arka arkaya 2*Context'ten fazla ortak satir gelene kadar uzat.
                int end = idx;
                int lastChange = idx;
                while (end < n)
                {
                    if (ops[end].Key != ' ') lastChange = end;
                    else if (end - lastChange > 2 * Context) break;
                    end++;
                }
                end = Math.Min(n, lastChange + Context + 1);

                int aCount = 0, bCount = 0;
                for (int k = start; k < end; k++)
                {
                    if (ops[k].Key != '+') aCount++;
                    if (ops[k].Key != '-') bCount++;
                }

                sb.Append("@@ -").Append(aStart + 1).Append(',').Append(aCount)
                  .Append(" +").Append(bStart + 1).Append(',').Append(bCount).Append(" @@\n");

                for (int k = start; k < end; k++)
                    sb.Append(ops[k].Key).Append(ops[k].Value).Append('\n');

                // Konumlari end'e tasi.
                for (int k = idx; k < end; k++)
                {
                    if (ops[k].Key != '+') aLine++;
                    if (ops[k].Key != '-') bLine++;
                }
                idx = end;
            }

            return sb.ToString();
        }

        private static string[] Split(string s)
        {
            if (string.IsNullOrEmpty(s)) return new string[0];
            string norm = s.Replace("\r\n", "\n").Replace('\r', '\n');
            if (norm.EndsWith("\n", StringComparison.Ordinal)) norm = norm.Substring(0, norm.Length - 1);
            return norm.Split('\n');
        }
    }
}
