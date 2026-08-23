// Assets/Editor/Q3CNFU/Q3Proc.cs
// Surec baslatma yardimcilari.
//
// ProcessStartInfo.ArgumentList Unity'nin API uyumluluk seviyesine gore var
// olmayabilir. Derleme zamani bagimliligi kurmamak icin yansimayla ariyoruz;
// yoksa Windows'un CommandLineToArgvW kurallarina gore elle tirnakliyoruz.
// Boylece 2022.3 / 2023.2 / 6000.x ve her iki API seviyesi ayni kodu kullanir.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using System.Text;

namespace Q3CNFU.EditorTools
{
    internal static class Q3Proc
    {
        private static readonly PropertyInfo ArgumentListProperty =
            typeof(ProcessStartInfo).GetProperty("ArgumentList");

        private static readonly char[] NeedsQuoting = { ' ', '\t', '\n', '\r', '\v', '"' };

        public static bool HasArgumentList { get { return ArgumentListProperty != null; } }

        public static void SetArgs(ProcessStartInfo psi, IList<string> args)
        {
            if (ArgumentListProperty != null)
            {
                var list = ArgumentListProperty.GetValue(psi, null) as ICollection<string>;
                if (list != null)
                {
                    foreach (string a in args) list.Add(a);
                    return;
                }
            }

            var sb = new StringBuilder();
            foreach (string a in args)
            {
                if (sb.Length > 0) sb.Append(' ');
                AppendQuoted(sb, a ?? "");
            }
            psi.Arguments = sb.ToString();
        }

        /// <summary>Windows komut satiri tirnaklama kurallari (ters bolu ciftleme dahil).</summary>
        private static void AppendQuoted(StringBuilder sb, string arg)
        {
            if (arg.Length > 0 && arg.IndexOfAny(NeedsQuoting) < 0)
            {
                sb.Append(arg);
                return;
            }

            sb.Append('"');

            int i = 0;
            while (i < arg.Length)
            {
                int slashes = 0;
                while (i < arg.Length && arg[i] == '\\') { slashes++; i++; }

                if (i == arg.Length)
                {
                    // Kapanis tirnagindan onceki ters bolular ciftlenir.
                    sb.Append('\\', slashes * 2);
                    break;
                }

                if (arg[i] == '"')
                {
                    sb.Append('\\', slashes * 2 + 1).Append('"');
                }
                else
                {
                    sb.Append('\\', slashes).Append(arg[i]);
                }
                i++;
            }

            sb.Append('"');
        }

        public static void ApplyCommonEnvironment(ProcessStartInfo psi)
        {
            psi.EnvironmentVariables["NO_COLOR"] = "1";
            psi.EnvironmentVariables["TERM"] = "dumb";

            // Python: Windows'ta varsayilan konsol kodlamasi cp1254; Turkce metin
            // ve model ciktisi bozulmasin. Tamponsuz cikti, olay dosyasina aninda
            // dusmesi icin.
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
            psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        }

        /// <summary>Kisa suren bir komutu calistirip ciktisini toplar (python --version vb).</summary>
        public static bool RunCapture(string fileName, IList<string> args,
                                     string workingDirectory, int timeoutMs,
                                     out string stdout, out string stderr, out int exitCode)
        {
            stdout = "";
            stderr = "";
            exitCode = -1;

            if (string.IsNullOrEmpty(fileName)) return false;

            var all = new List<string>(args);

            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };

            if (!string.IsNullOrEmpty(workingDirectory)) psi.WorkingDirectory = workingDirectory;

            SetArgs(psi, all);
            ApplyCommonEnvironment(psi);

            var errors = new StringBuilder();

            using (var p = Process.Start(psi))
            {
                if (p == null) return false;

                // Iki akisi da ReadToEnd ile okumak kilitlenebilir; stderr asenkron.
                p.ErrorDataReceived += (s, e) => { if (e.Data != null) errors.AppendLine(e.Data); };
                p.BeginErrorReadLine();

                stdout = p.StandardOutput.ReadToEnd();

                if (!p.WaitForExit(timeoutMs))
                {
                    TryKillTree(p);
                    stderr = "Zaman asimi.";
                    return false;
                }

                exitCode = p.ExitCode;
            }

            stderr = errors.ToString().Trim();
            return true;
        }

        public static void TryKillTree(Process p)
        {
            try
            {
                if (p == null || p.HasExited) return;
                KillTree(p.Id);
            }
            catch (Exception)
            {
                // Surec zaten kapanmis olabilir.
            }
        }

        /// <summary>Surec agacini oldurur (python kabuk uzerinden baslamis olabilir).</summary>
        public static void KillTree(int pid)
        {
            if (pid <= 0) return;

            bool windows = Environment.OSVersion.Platform != PlatformID.Unix &&
                           Environment.OSVersion.Platform != PlatformID.MacOSX;

            var psi = new ProcessStartInfo
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };

            if (windows)
            {
                psi.FileName = "taskkill";
                SetArgs(psi, new List<string> { "/PID", pid.ToString(), "/T", "/F" });
            }
            else
            {
                psi.FileName = "/bin/sh";
                SetArgs(psi, new List<string> { "-c", "kill -TERM -" + pid + " 2>/dev/null || kill -TERM " + pid });
            }

            try
            {
                using (var k = Process.Start(psi))
                    if (k != null) k.WaitForExit(5000);
            }
            catch (Exception)
            {
                // taskkill/kill yoksa yapacak bir sey kalmiyor.
            }
        }

        public static bool IsAlive(int pid)
        {
            if (pid <= 0) return false;

            try
            {
                using (Process p = Process.GetProcessById(pid))
                    return p != null && !p.HasExited;
            }
            catch (ArgumentException)
            {
                return false;   // boyle bir surec yok
            }
            catch (InvalidOperationException)
            {
                return false;
            }
        }

        /// <summary>Minimal JSON metin kacisi (gecmis/degisiklik kayitlari icin).</summary>
        public static string JsonString(string s)
        {
            var sb = new StringBuilder("\"");
            foreach (char c in s ?? "")
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    default:
                        if (c < ' ') sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.Append('"').ToString();
        }
    }
}
