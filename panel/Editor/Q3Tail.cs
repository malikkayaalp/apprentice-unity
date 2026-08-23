// Assets/Editor/Q3CNFU/Q3Tail.cs
// Cikti dosyasini bayt konumundan artimli okur.
//
// Yalnizca son satir sonuna KADAR cozumluyoruz. Bu iki sorunu birden cozer:
//   - yarim kalmis satirlari islememek
//   - okuma sinirinda ikiye bolunmus UTF-8 karakterlerini bozmamak
// Konum cagiran tarafta saklandigi icin domain reload'dan sonra kaldigi
// yerden devam edilebilir.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace Q3CNFU.EditorTools
{
    internal static class Q3Tail
    {
        private const int MaxChunk = 1 << 20;   // tek turda en fazla 1 MB

        /// <summary>offset'ten itibaren tamamlanmis satirlari okur ve yeni offset'i dondurur.</summary>
        public static long ReadLines(string path, long offset, List<string> into)
        {
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) return offset;

            try
            {
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read,
                                               FileShare.ReadWrite | FileShare.Delete))
                {
                    if (offset > fs.Length) offset = 0;      // dosya sifirlanmis
                    if (offset == fs.Length) return offset;

                    fs.Seek(offset, SeekOrigin.Begin);

                    long available = fs.Length - offset;
                    int count = (int)Math.Min(available, MaxChunk);

                    var buffer = new byte[count];
                    int read = fs.Read(buffer, 0, count);
                    if (read <= 0) return offset;

                    int lastNewline = -1;
                    for (int i = read - 1; i >= 0; i--)
                    {
                        if (buffer[i] != (byte)'\n') continue;
                        lastNewline = i;
                        break;
                    }

                    // Henuz tam satir yok; bir sonraki turu bekle.
                    if (lastNewline < 0) return offset;

                    string text = Encoding.UTF8.GetString(buffer, 0, lastNewline + 1);
                    foreach (string line in text.Split('\n'))
                    {
                        string trimmed = line.TrimEnd('\r');
                        if (trimmed.Length > 0) into.Add(trimmed);
                    }

                    return offset + lastNewline + 1;
                }
            }
            catch (IOException)
            {
                return offset;   // dosya o an yaziliyor olabilir; sonra tekrar denenir
            }
            catch (UnauthorizedAccessException)
            {
                return offset;
            }
        }
    }
}
