// Assets/Editor/Q3CNFU/Q3Runner.cs
// panel_runner.py'yi AYRIK surec olarak baslatir.
//
// CursorBridge'den miras alinan ilke: cikti boru degil DOSYA. Unity script
// derleyip domain reload yaptiginda boru okuyucular olur; dosya olmez. Pencere
// yeniden yuklendiginde RunHandle (serileştirilmis) kaldigi bayt konumundan
// okumaya devam eder.
//
// CursorBridge'in node bootstrap'ina gerek yok: panel_runner.py olaylari ve
// cikis satirini dosyaya kendisi yazar (finally blogu). Prompt komut satirindan
// GECMEZ: prompt.txt'ye yazilir, betik --prompt-file ile okur. Bu projede bes
// kez yasanan kacis/satir-sonu bozulmasi boylece yapisal olarak imkansiz.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

namespace Q3CNFU.EditorTools
{
    [Serializable]
    internal class RunHandle
    {
        public string OutputPath = "";
        public string RunDirectory = "";
        public int Pid;
        public long Offset;
        public bool Active;
    }

    internal class RunRequest
    {
        public string Prompt = "";
        public string SessionId = "";
        public string Model = "";
        public int Repairs = 3;
        public bool Play;
        public int PlayRepairs = 2;
    }

    internal static class Q3Runner
    {
        private static readonly UTF8Encoding Utf8NoBom = new UTF8Encoding(false);

        public static RunHandle Start(RunRequest req, out string error)
        {
            error = null;

            string python = Q3Setup.PythonExe;
            string runner = Q3Setup.RunnerPath;

            if (string.IsNullOrEmpty(python))
            {
                error = "Python bulunamadi.";
                return null;
            }

            if (string.IsNullOrEmpty(runner) || !File.Exists(runner))
            {
                error = "panel_runner.py bulunamadi.";
                return null;
            }

            string runDir;
            try
            {
                runDir = CreateRunDirectory();
            }
            catch (Exception ex)
            {
                error = "Calisma klasoru olusturulamadi: " + ex.Message;
                return null;
            }

            string outPath = Path.Combine(runDir, "out.jsonl");
            string promptPath = Path.Combine(runDir, "prompt.txt");

            File.WriteAllText(outPath, "", Utf8NoBom);
            File.WriteAllText(promptPath, req.Prompt ?? "", Utf8NoBom);

            var args = new List<string>();
            if (string.Equals(Path.GetFileNameWithoutExtension(python), "py", StringComparison.OrdinalIgnoreCase))
                args.Add("-3");

            args.Add(runner);
            args.Add("--jsonl"); args.Add(outPath);
            args.Add("--prompt-file"); args.Add(promptPath);
            args.Add("--session"); args.Add(req.SessionId);
            args.Add("--url"); args.Add(Q3Setup.BridgeUrl);
            args.Add("--repairs"); args.Add(req.Repairs.ToString(CultureInfo.InvariantCulture));

            if (!string.IsNullOrWhiteSpace(req.Model))
            {
                args.Add("--model");
                args.Add(req.Model.Trim());
            }

            if (req.Play)
            {
                args.Add("--play");
                args.Add("--play-repairs");
                args.Add(req.PlayRepairs.ToString(CultureInfo.InvariantCulture));
            }

            var psi = new ProcessStartInfo
            {
                FileName = python,
                WorkingDirectory = ProjectRoot(),   // betik Library/Q3CNFU/sessions'i buradan bulur
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = false,
                RedirectStandardError = false,
                RedirectStandardInput = false,
            };

            Q3Proc.SetArgs(psi, args);
            Q3Proc.ApplyCommonEnvironment(psi);
            psi.EnvironmentVariables["Q3CNFU_RUN_DIR"] = runDir;

            try
            {
                using (Process p = Process.Start(psi))
                {
                    if (p == null) throw new Exception("Surec baslatilamadi.");

                    return new RunHandle
                    {
                        OutputPath = outPath,
                        RunDirectory = runDir,
                        Pid = p.Id,
                        Offset = 0,
                        Active = true,
                    };
                }
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return null;
            }
        }

        // -------------------------------------------------------------------

        private static string CreateRunDirectory()
        {
            string root = Path.Combine(ProjectRoot(), "Library");
            if (!Directory.Exists(root)) root = Path.GetTempPath();

            string baseDir = Path.Combine(root, "Q3CNFU", "runs");
            Directory.CreateDirectory(baseDir);

            CleanupOldRuns(baseDir);

            string dir = Path.Combine(baseDir,
                                      "run-" + DateTime.Now.ToString("yyyyMMdd-HHmmss-fff",
                                                                     CultureInfo.InvariantCulture));
            Directory.CreateDirectory(dir);
            return dir;
        }

        /// <summary>Bir gunden eski calisma klasorlerini siler.</summary>
        private static void CleanupOldRuns(string baseDir)
        {
            try
            {
                DateTime cutoff = DateTime.Now.AddDays(-1);
                foreach (string dir in Directory.GetDirectories(baseDir))
                {
                    try
                    {
                        if (Directory.GetLastWriteTime(dir) < cutoff)
                            Directory.Delete(dir, true);
                    }
                    catch (IOException) { }
                    catch (UnauthorizedAccessException) { }
                }
            }
            catch (Exception)
            {
                // Temizlik basarisiz olsa da calismayi engellememeli.
            }
        }

        public static string ProjectRoot()
        {
            DirectoryInfo parent = Directory.GetParent(Application.dataPath);
            return parent != null ? parent.FullName : Application.dataPath;
        }
    }
}
