// Assets/Editor/Q3CNFU/Q3Models.cs
// Ollama /api/tags ciktisindan model listesi. Liste Q3Setup'in arka plan
// sorgusuyla gelir; burada yalnizca ayristirma ve gruplama var.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEditor;
using UnityEngine;

namespace Q3CNFU.EditorTools
{
    internal class ModelInfo
    {
        public string Id;        // "hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL"
        public string Label;     // "Qwen3-Coder-Next  UD-Q4_K_XL  (~49 GB)"
        public string Family;    // details.family ("qwen3next") ya da ad govdesi
        public string Quant;     // details.quantization_level
        public long SizeBytes;
    }

    internal static class Q3Models
    {
        public static List<ModelInfo> All { get { return Q3Setup.Models; } }
        public static bool HasList { get { return All.Count > 0; } }

        public static string LabelFor(string id)
        {
            if (string.IsNullOrWhiteSpace(id)) return "(model secilmedi)";

            foreach (ModelInfo m in All)
                if (string.Equals(m.Id, id, StringComparison.OrdinalIgnoreCase))
                    return m.Label;

            return id;
        }

        public static bool Contains(List<ModelInfo> list, string id)
        {
            foreach (ModelInfo m in list)
                if (string.Equals(m.Id, id, StringComparison.OrdinalIgnoreCase)) return true;

            // Ollama ":latest" ekini gizleyebilir.
            foreach (ModelInfo m in list)
                if (string.Equals(m.Id, id + ":latest", StringComparison.OrdinalIgnoreCase)) return true;

            return false;
        }

        // --- /api/tags -------------------------------------------------------

        public static List<ModelInfo> ParseTags(string json)
        {
            var list = new List<ModelInfo>();
            object root = Q3Json.Parse(json);
            List<object> models = Q3Json.Arr(Q3Json.Get(root, "models"));
            if (models == null) return list;

            foreach (object m in models)
            {
                string id = Q3Json.Str(m, "name") ?? Q3Json.Str(m, "model");
                if (string.IsNullOrEmpty(id)) continue;

                object details = Q3Json.Get(m, "details");
                object size = Q3Json.Get(m, "size");

                var info = new ModelInfo
                {
                    Id = id,
                    Quant = Q3Json.Str(details, "quantization_level") ?? "",
                    Family = Q3Json.Str(details, "family") ?? "",
                    SizeBytes = size is double ? (long)(double)size : 0,
                };

                if (string.IsNullOrEmpty(info.Family)) info.Family = FamilyFromId(id);
                info.Label = BuildLabel(info);
                list.Add(info);
            }

            list.Sort((a, b) => string.Compare(a.Id, b.Id, StringComparison.OrdinalIgnoreCase));
            return list;
        }

        private static string FamilyFromId(string id)
        {
            // "hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL" -> "Qwen3-Coder-Next-GGUF"
            string body = id;
            int colon = body.IndexOf(':');
            if (colon > 0) body = body.Substring(0, colon);
            int slash = body.LastIndexOf('/');
            if (slash >= 0) body = body.Substring(slash + 1);
            return body;
        }

        private static string BuildLabel(ModelInfo m)
        {
            string name = m.Id;
            int slash = name.LastIndexOf('/');
            if (slash >= 0) name = name.Substring(slash + 1);

            string size = m.SizeBytes > 0
                ? "  (~" + (m.SizeBytes / (1024.0 * 1024 * 1024)).ToString("0") + " GB)"
                : "";

            return name + size;
        }

        /// <summary>Aile sirasini koruyarak gruplar (acilir menu icin).</summary>
        public static List<KeyValuePair<string, List<ModelInfo>>> Grouped()
        {
            var order = new List<string>();
            var map = new Dictionary<string, List<ModelInfo>>(StringComparer.OrdinalIgnoreCase);

            foreach (ModelInfo m in All)
            {
                List<ModelInfo> bucket;
                if (!map.TryGetValue(m.Family, out bucket))
                {
                    bucket = new List<ModelInfo>();
                    map[m.Family] = bucket;
                    order.Add(m.Family);
                }
                bucket.Add(m);
            }

            var result = new List<KeyValuePair<string, List<ModelInfo>>>();
            foreach (string family in order)
                result.Add(new KeyValuePair<string, List<ModelInfo>>(family, map[family]));

            return result;
        }

        // --- cekme -----------------------------------------------------------

        /// <summary>'ollama pull' komutunu GORUNUR bir terminalde baslatir: indirme
        /// onlarca GB surebilir, ilerlemeyi kullanici gorsun.</summary>
        public static bool StartPull(string model, out string error)
        {
            error = null;

            if (string.IsNullOrWhiteSpace(model))
            {
                error = "Model adi bos.";
                return false;
            }

            if (Application.platform != RuntimePlatform.WindowsEditor)
            {
                error = "Terminalde calistir: ollama pull " + model;
                return false;
            }

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "powershell.exe",
                    UseShellExecute = true,
                    CreateNoWindow = false,
                    Arguments = "-NoExit -NoProfile -Command \"ollama pull '" +
                                model.Replace("'", "''") + "'\"",
                };

                Process.Start(psi);
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }
    }
}
