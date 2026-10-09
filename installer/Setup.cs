// 安装、更新、卸载的具体步骤。界面只管显示（ISink），这里不碰界面。
//
// 装到哪：Super Aide 的运行环境由 uv 管（和 scripts\install.ps1 装的是同一份，不会装出两份）：
//   程序本体和依赖  %APPDATA%\uv\tools\super-aide   启动器 %USERPROFILE%\.local\bin\super-aide.exe
//   安装器自己      %LOCALAPPDATA%\Programs\Super Aide\SuperAideSetup.exe（更新、卸载用；没有 uv 时 uv.exe 也放这里）
// 下载源：每一样都先花几秒探一下官方的通不通，不通的直接跳过；装失败也换下一个。
//   uv：GitHub → PyPI 国内镜像（阿里云、清华）里 uv 的 wheel
//   Super Aide 本体：GitHub 最新发布 → PyPI → 国内镜像
//   依赖：PyPI → 阿里云 → 清华；Python 本体：GitHub → npmmirror
// 依赖的确切版本跟着本体走（包里的 super_aide/_release/constraints.txt，发版时由 uv.lock 生成）。

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Management;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace SuperAideSetup
{
    class SetupException : Exception
    {
        public SetupException(string message) : base(message) { }
    }

    interface ISink
    {
        void Step(int index);
        void Detail(string text);
        void Progress(double value); // 0..1；-1 = 不知道进度
        void Line(string text);      // 写进详情
    }

    static class Log
    {
        static readonly object Gate = new object();
        public static string FilePath;

        public static void Start(Options options)
        {
            FilePath = Path.Combine(Path.GetTempPath(), "SuperAideSetup.log");
            Write("==== Super Aide setup " + BuildInfo.Version + ", " + options.Mode + ", " + Environment.OSVersion + ", " +
                  System.Globalization.CultureInfo.CurrentUICulture.Name);
        }

        public static void Write(string line)
        {
            if (FilePath == null) return;
            lock (Gate)
            {
                try { File.AppendAllText(FilePath, DateTime.Now.ToString("HH:mm:ss ") + line + "\r\n", Encoding.UTF8); }
                catch (IOException) { }
            }
        }
    }

    /// <summary>装到哪。设了 SUPER_AIDE_SETUP_SANDBOX 时（开发时测试安装器）全部改到那个目录里，不碰真的开始菜单和注册表。</summary>
    static class Places
    {
        public static readonly string Sandbox = Environment.GetEnvironmentVariable("SUPER_AIDE_SETUP_SANDBOX");

        public static bool Sandboxed { get { return !string.IsNullOrEmpty(Sandbox); } }
        static string Home { get { return Environment.GetFolderPath(Environment.SpecialFolder.UserProfile); } }
        static string In(string name, string real) { return Sandboxed ? Path.Combine(Sandbox, name) : real; }

        public static string AppDir
        {
            get { return In("App", Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Super Aide")); }
        }
        public static string Installer { get { return Path.Combine(AppDir, "SuperAideSetup.exe"); } }
        /// <summary>快捷方式按系统语言起名；换过语言的也认（卸载、更新时两个名字都看）。</summary>
        public static readonly string[] LinkNames = { "超级助手.lnk", "Super Aide.lnk" };
        public static string StartMenuDir { get { return In("StartMenu", Environment.GetFolderPath(Environment.SpecialFolder.Programs)); } }
        public static string DesktopDir { get { return In("Desktop", Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory)); } }
        public static string StartMenuLink { get { return Path.Combine(StartMenuDir, L.AppName + ".lnk"); } }
        public static string DesktopLink { get { return Path.Combine(DesktopDir, L.AppName + ".lnk"); } }

        public static bool HasDesktopLink()
        {
            foreach (string name in LinkNames)
                if (File.Exists(Path.Combine(DesktopDir, name))) return true;
            return false;
        }
        public static string DataDir { get { return In("data", Path.Combine(Home, ".super_aide")); } }
        // 设置里换过数据位置的话（设置 → 通用 → 数据位置），数据在 location.json 记的那个文件夹里，设置文件还在 DataDir
        public static string MovedDataDir
        {
            get
            {
                try
                {
                    var record = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
                        File.ReadAllText(Path.Combine(DataDir, "location.json")));
                    object value;
                    string dir = record != null && record.TryGetValue("data", out value) ? value as string : null;
                    if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir)) return null;
                    bool same = string.Equals(Path.GetFullPath(dir).TrimEnd('\\'), Path.GetFullPath(DataDir).TrimEnd('\\'),
                                              StringComparison.OrdinalIgnoreCase);
                    return same ? null : dir;
                }
                catch (Exception) { return null; }
            }
        }
        static string RegistryRoot
        {
            get { return Sandboxed ? @"Software\SuperAideSetupSandbox" : @"Software\Microsoft\Windows\CurrentVersion"; }
        }
        public static string RunKey { get { return RegistryRoot + @"\Run"; } }
        public static string UninstallKey { get { return RegistryRoot + @"\Uninstall\SuperAide"; } }
    }

    static class Net
    {
        static readonly HttpClient Http;

        static Net()
        {
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            HttpClientHandler handler = new HttpClientHandler(); // 默认就用系统代理
            handler.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
            Http = new HttpClient(handler);
            Http.Timeout = Timeout.InfiniteTimeSpan; // 每个请求自己定超时
            Http.DefaultRequestHeaders.UserAgent.ParseAdd("SuperAideSetup/" + BuildInfo.Version);
        }

        public static async Task<bool> Probe(string url)
        {
            using (CancellationTokenSource cts = new CancellationTokenSource(6000))
            {
                try
                {
                    using (HttpRequestMessage request = new HttpRequestMessage(HttpMethod.Head, url))
                    using (HttpResponseMessage response = await Http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cts.Token).ConfigureAwait(false))
                        return (int)response.StatusCode < 500;
                }
                catch (Exception)
                {
                    return false;
                }
            }
        }

        public static async Task<string> Text(string url, CancellationToken token)
        {
            using (CancellationTokenSource cts = CancellationTokenSource.CreateLinkedTokenSource(token))
            {
                cts.CancelAfter(30000);
                using (HttpResponseMessage response = await Http.GetAsync(url, cts.Token).ConfigureAwait(false))
                {
                    if (!response.IsSuccessStatusCode) throw new SetupException(url + L.T(" 返回 ", " returned ") + (int)response.StatusCode);
                    return await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                }
            }
        }

        /// <summary>下载到文件。一分钟没收到数据就算断了。</summary>
        public static async Task Download(string url, string path, Action<long, long> progress, CancellationToken token)
        {
            using (CancellationTokenSource stall = CancellationTokenSource.CreateLinkedTokenSource(token))
            {
                stall.CancelAfter(60000);
                using (HttpResponseMessage response = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, stall.Token).ConfigureAwait(false))
                {
                    if (!response.IsSuccessStatusCode) throw new SetupException(url + L.T(" 返回 ", " returned ") + (int)response.StatusCode);
                    long total = response.Content.Headers.ContentLength ?? -1;
                    using (Stream input = await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                    using (FileStream output = File.Create(path))
                    {
                        byte[] buffer = new byte[81920];
                        long done = 0;
                        int n;
                        while ((n = await input.ReadAsync(buffer, 0, buffer.Length, stall.Token).ConfigureAwait(false)) > 0)
                        {
                            stall.CancelAfter(60000);
                            await output.WriteAsync(buffer, 0, n, token).ConfigureAwait(false);
                            done += n;
                            if (progress != null) progress(done, total);
                        }
                    }
                }
            }
            token.ThrowIfCancellationRequested();
        }

        public static string Sha256(string path)
        {
            using (SHA256 sha = SHA256.Create())
            using (FileStream stream = File.OpenRead(path))
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }

        public static object Json(string text)
        {
            return new JavaScriptSerializer { MaxJsonLength = int.MaxValue }.DeserializeObject(text);
        }

        public static string Host(string url)
        {
            try { return new Uri(url).Host; } catch (UriFormatException) { return url; }
        }
    }

    static class Native
    {
        /// <summary>ARM 版 Windows（x64 程序在上面跑在仿真里）：Python 也要用 x64 的，PySide6 没有 ARM 版。</summary>
        public static bool IsArm64
        {
            get
            {
                using (RegistryKey key = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
                    return key != null && string.Equals(key.GetValue("PROCESSOR_ARCHITECTURE") as string, "ARM64", StringComparison.OrdinalIgnoreCase);
            }
        }

        public static int WindowsBuild
        {
            get
            {
                using (RegistryKey key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion"))
                {
                    int build = 0;
                    if (key != null) int.TryParse(Convert.ToString(key.GetValue("CurrentBuildNumber", "0")), out build);
                    return build;
                }
            }
        }
    }

    static class Uv
    {
        public const string Package = "super-aide";
        public static readonly string[] PypiMirrors = { "https://mirrors.aliyun.com/pypi/simple", "https://pypi.tuna.tsinghua.edu.cn/simple" };
        public const string PythonMirror = "https://registry.npmmirror.com/-/binary/python-build-standalone";

        /// <summary>已经有的 uv：我们自己放的、PATH 里的、官方安装脚本放的。测试模式只认自己放的（顺便测下载）。</summary>
        public static string Find()
        {
            List<string> candidates = new List<string> { Path.Combine(Places.AppDir, "uv.exe") };
            if (!Places.Sandboxed)
            {
                string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                string onPath = Which("uv.exe");
                if (onPath != null) candidates.Add(onPath);
                candidates.Add(Path.Combine(home, @".local\bin\uv.exe"));
                candidates.Add(Path.Combine(home, @".cargo\bin\uv.exe"));
            }
            foreach (string candidate in candidates)
                if (File.Exists(candidate)) return candidate;
            return null;
        }

        static string Which(string exe)
        {
            foreach (string dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
            {
                try
                {
                    string path = Path.Combine(dir.Trim().Trim('"'), exe);
                    if (dir.Trim().Length > 0 && File.Exists(path)) return path;
                }
                catch (ArgumentException) { }
            }
            return null;
        }

        public static string Quote(string arg)
        {
            if (arg.Length > 0 && arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return arg;
            StringBuilder sb = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in arg)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') { sb.Append('\\', slashes * 2 + 1); sb.Append('"'); }
                else { sb.Append('\\', slashes); sb.Append(c); }
                slashes = 0;
            }
            sb.Append('\\', slashes * 2);
            sb.Append('"');
            return sb.ToString();
        }

        public static string Args(IEnumerable<string> args)
        {
            return string.Join(" ", args.Select(Quote));
        }

        /// <summary>运行一个命令，输出一行一行交给 onLine。取消时结束它。阻塞调用。</summary>
        public static int Run(string exe, IEnumerable<string> args, IDictionary<string, string> env, Action<string> onLine, CancellationToken token)
        {
            ProcessStartInfo psi = new ProcessStartInfo(exe, Args(args));
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.StandardOutputEncoding = Encoding.UTF8;
            psi.StandardErrorEncoding = Encoding.UTF8;
            psi.EnvironmentVariables["NO_COLOR"] = "1";
            if (env != null)
            {
                foreach (KeyValuePair<string, string> kv in env)
                {
                    if (kv.Value == null) psi.EnvironmentVariables.Remove(kv.Key);
                    else psi.EnvironmentVariables[kv.Key] = kv.Value;
                }
            }
            using (Process process = new Process())
            {
                process.StartInfo = psi;
                DataReceivedEventHandler handler = delegate(object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null && onLine != null) onLine(e.Data);
                };
                process.OutputDataReceived += handler;
                process.ErrorDataReceived += handler;
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                using (token.Register(delegate { try { if (!process.HasExited) process.Kill(); } catch (Exception) { } }))
                    process.WaitForExit();
                token.ThrowIfCancellationRequested();
                return process.ExitCode;
            }
        }

        public static string Output(string exe, params string[] args)
        {
            StringBuilder sb = new StringBuilder();
            object gate = new object();
            int code = Run(exe, args, null, delegate(string line) { lock (gate) sb.AppendLine(line); }, CancellationToken.None);
            if (code != 0) return null;
            string[] lines = sb.ToString().Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
            return lines.Length > 0 ? lines[lines.Length - 1].Trim() : null;
        }

        public static string ToolDir(string uv)
        {
            string dir = uv != null ? Output(uv, "tool", "dir") : null;
            if (!string.IsNullOrEmpty(dir)) return dir;
            string env = Environment.GetEnvironmentVariable("UV_TOOL_DIR");
            return !string.IsNullOrEmpty(env) ? env : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), @"uv\tools");
        }

        /// <summary>我们自己下载的 uv（放在安装器的文件夹里）：缓存也放那里，卸载时跟着删掉，不碰别人共用的 uv 缓存。
        /// 缓存要留着：uv 在 Windows 上把缓存里的文件硬链接进环境，几乎不多占空间；删了的话每次更新都要重新下载全部依赖。</summary>
        public static bool IsPrivate(string uv)
        {
            return uv != null && string.Equals(Path.GetFullPath(uv), Path.GetFullPath(Path.Combine(Places.AppDir, "uv.exe")), StringComparison.OrdinalIgnoreCase);
        }

        public static string PrivateCache { get { return Path.Combine(Places.AppDir, "cache"); } }

        public static string BinDir(string uv)
        {
            string dir = uv != null ? Output(uv, "tool", "dir", "--bin") : null;
            if (!string.IsNullOrEmpty(dir)) return dir;
            string env = Environment.GetEnvironmentVariable("UV_TOOL_BIN_DIR");
            return !string.IsNullOrEmpty(env) ? env : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), @".local\bin");
        }
    }

    class Probes
    {
        public bool GitHub;
        public bool PyPI;
    }

    class Package
    {
        public string Version;
        public string Wheel;
        public string Source;
    }

    class Setup
    {
        public static string[] InstallSteps
        {
            get
            {
                return new[] { L.T("检查电脑", "Check this PC"), L.T("准备安装工具", "Get the install tool"),
                               L.T("下载超级助手", "Download Super Aide"), L.T("安装运行环境", "Install the runtime"),
                               L.T("完成设置", "Finish setting up") };
            }
        }

        public static string[] UninstallSteps
        {
            get
            {
                return new[] { L.T("关闭超级助手", "Close Super Aide"), L.T("删除程序", "Remove the app"),
                               L.T("删除快捷方式和开机自启", "Remove shortcuts and autostart"), L.T("删除我的数据", "Delete my data") };
            }
        }
        static readonly Regex VersionPart = new Regex(@"^\d+(\.\d+)*$");

        readonly ISink sink;
        readonly CancellationToken token;
        readonly Options options;
        readonly string temp;

        public Setup(ISink sink, CancellationToken token, Options options)
        {
            this.sink = sink;
            this.token = token;
            this.options = options;
            temp = Path.Combine(Path.GetTempPath(), "SuperAideSetup-" + Process.GetCurrentProcess().Id);
            Directory.CreateDirectory(temp);
        }

        // ---------- 安装 / 更新 ----------

        public async Task<string> Install(bool autostart, bool desktop, bool update)
        {
            sink.Step(0);
            CheckSystem();
            Probes probes = await ProbeAll().ConfigureAwait(false);
            sink.Line(L.T("能连上：GitHub ", "Reachable: GitHub ") + YesNo(probes.GitHub) + L.T("，PyPI ", ", PyPI ") + YesNo(probes.PyPI));

            sink.Step(1);
            string uv = await EnsureUv(probes).ConfigureAwait(false);

            sink.Step(2);
            Package package = await GetPackage(probes).ConfigureAwait(false);
            string constraints = ExtractConstraints(package.Wheel);

            sink.Step(3);
            sink.Progress(-1);
            StopApp(uv, options.Pid);
            InstallApp(uv, package, constraints, probes);

            sink.Step(4);
            string launcher = Finish(uv, package.Version, autostart, desktop, update);
            Launch(launcher, update);
            Cleanup();
            return package.Version;
        }

        static string YesNo(bool value) { return value ? L.T("是", "yes") : L.T("否", "no"); }

        void CheckSystem()
        {
            if (!Environment.Is64BitOperatingSystem)
                throw new SetupException(L.T("超级助手需要 64 位的 Windows 10 或 11。", "Super Aide needs 64-bit Windows 10 or 11."));
            int build = Native.WindowsBuild;
            if (build > 0 && build < 17763)
                throw new SetupException(L.T("超级助手需要 Windows 10 1809 或更新的版本（这台电脑是 " + build + "）。",
                                             "Super Aide needs Windows 10 1809 or later (this PC has build " + build + ")."));
            try
            {
                DriveInfo drive = new DriveInfo(Path.GetPathRoot(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)));
                if (drive.AvailableFreeSpace < 3L * 1024 * 1024 * 1024)
                    throw new SetupException(L.T(drive.Name + " 盘的空间不够：至少要留出 3GB（运行环境装好后约 1.5GB）。",
                                                 "Not enough space on " + drive.Name + ": keep at least 3 GB free (the runtime takes about 1.5 GB)."));
            }
            catch (ArgumentException) { }
            catch (IOException) { }
        }

        static async Task<Probes> ProbeAll()
        {
            Task<bool> github = Net.Probe("https://github.com/");
            Task<bool> pypi = Net.Probe("https://pypi.org/simple/");
            await Task.WhenAll(github, pypi).ConfigureAwait(false);
            return new Probes { GitHub = github.Result, PyPI = pypi.Result };
        }

        Action<long, long> Bytes(string what)
        {
            DateTime last = DateTime.MinValue;
            return delegate(long done, long total)
            {
                if ((DateTime.Now - last).TotalMilliseconds < 250 && done != total) return;
                last = DateTime.Now;
                if (total > 0)
                {
                    sink.Progress((double)done / total);
                    sink.Detail(string.Format("{0}… {1:0.0} / {2:0.0} MB", what, done / 1048576.0, total / 1048576.0));
                }
                else sink.Detail(string.Format("{0}… {1:0.0} MB", what, done / 1048576.0));
            };
        }

        string Fail(List<string> errors, string what, Exception ex)
        {
            if (token.IsCancellationRequested) throw new OperationCanceledException(token);
            string message = ex is SetupException ? ex.Message : ex.GetType().Name + ": " + ex.Message;
            errors.Add(what + ": " + message);
            sink.Line(what + L.T(" 没成功：", " failed: ") + message);
            Log.Write(ex.ToString());
            return message;
        }

        async Task<string> EnsureUv(Probes probes)
        {
            string uv = Uv.Find();
            if (uv != null)
            {
                sink.Line("uv：" + uv);
                return uv;
            }
            Directory.CreateDirectory(Places.AppDir);
            string target = Path.Combine(Places.AppDir, "uv.exe");
            List<string> errors = new List<string>();
            if (probes.GitHub)
            {
                try
                {
                    await UvFromGitHub(target).ConfigureAwait(false);
                    return target;
                }
                catch (Exception ex) { Fail(errors, L.T("从 GitHub 下载 uv", "Download uv from GitHub"), ex); }
            }
            foreach (string index in Uv.PypiMirrors)
            {
                try
                {
                    await UvFromMirror(index, target).ConfigureAwait(false);
                    return target;
                }
                catch (Exception ex) { Fail(errors, L.T("从 " + Net.Host(index) + " 下载 uv", "Download uv from " + Net.Host(index)), ex); }
            }
            throw new SetupException(L.T("没装上安装工具 uv。检查网络（或代理）后点重试。",
                                         "Couldn't get the install tool uv. Check your network (or proxy) and click Retry."));
        }

        async Task UvFromGitHub(string target)
        {
            const string url = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip";
            string zip = Path.Combine(temp, "uv.zip");
            await Net.Download(url, zip, Bytes(L.T("从 GitHub 下载 uv", "Downloading uv from GitHub")), token).ConfigureAwait(false);
            string expected = (await Net.Text(url + ".sha256", token).ConfigureAwait(false)).Trim().Split(' ', '\t', '*')[0];
            Verify(zip, expected);
            Extract(zip, delegate(ZipArchiveEntry e) { return e.Name.Equals("uv.exe", StringComparison.OrdinalIgnoreCase); }, target);
            sink.Line(L.T("uv 下载好了（GitHub）：", "Got uv (GitHub): ") + target);
        }

        async Task UvFromMirror(string index, string target)
        {
            string page = await Net.Text(index + "/uv/", token).ConfigureAwait(false);
            Regex wheel = new Regex(@"href=""([^""]*?uv-(\d+(?:\.\d+)+)-py3-none-win_amd64\.whl)#sha256=([0-9a-fA-F]{64})""");
            Match best = null;
            foreach (Match m in wheel.Matches(page))
                if (best == null || CompareVersions(m.Groups[2].Value, best.Groups[2].Value) > 0) best = m;
            if (best == null) throw new SetupException(L.T("镜像里没找到 uv", "uv isn't on the mirror"));
            string url = new Uri(new Uri(index + "/uv/"), best.Groups[1].Value).AbsoluteUri;
            string file = Path.Combine(temp, "uv.whl");
            await Net.Download(url, file, Bytes(L.T("从 " + Net.Host(index) + " 下载 uv", "Downloading uv from " + Net.Host(index))), token).ConfigureAwait(false);
            Verify(file, best.Groups[3].Value);
            Extract(file, delegate(ZipArchiveEntry e) { return e.FullName.EndsWith(".data/scripts/uv.exe", StringComparison.OrdinalIgnoreCase); }, target);
            sink.Line(L.T("uv " + best.Groups[2].Value + " 下载好了（" + Net.Host(index) + "）：",
                          "Got uv " + best.Groups[2].Value + " (" + Net.Host(index) + "): ") + target);
        }

        static void Verify(string path, string expected)
        {
            if (string.IsNullOrEmpty(expected)) return;
            if (!string.Equals(Net.Sha256(path), expected.Trim(), StringComparison.OrdinalIgnoreCase))
                throw new SetupException(L.T("下载的文件校验不通过（可能下载不完整）", "The download failed its checksum (it may be incomplete)"));
        }

        static bool Extract(string zip, Func<ZipArchiveEntry, bool> match, string target)
        {
            using (ZipArchive archive = ZipFile.OpenRead(zip))
            {
                ZipArchiveEntry entry = archive.Entries.FirstOrDefault(match);
                if (entry == null) return false;
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                entry.ExtractToFile(target, true);
                return true;
            }
        }

        public static int CompareVersions(string a, string b)
        {
            int[] x = a.Split('.').Select(int.Parse).ToArray();
            int[] y = b.Split('.').Select(int.Parse).ToArray();
            for (int i = 0; i < Math.Max(x.Length, y.Length); i++)
            {
                int p = i < x.Length ? x[i] : 0;
                int q = i < y.Length ? y[i] : 0;
                if (p != q) return p.CompareTo(q);
            }
            return 0;
        }

        async Task<Package> GetPackage(Probes probes)
        {
            if (options.Wheel != null)
            {
                string path = Path.GetFullPath(options.Wheel);
                if (!File.Exists(path)) throw new SetupException(L.T("没找到安装包：", "Package not found: ") + path);
                Match m = Regex.Match(Path.GetFileName(path), @"^super_aide-([^-]+)-");
                return new Package { Version = m.Success ? m.Groups[1].Value : "?", Wheel = path, Source = L.T("本地", "local") };
            }
            List<string> errors = new List<string>();
            if (BuildInfo.Repo.Length > 0 && probes.GitHub)
            {
                try { return await FromGitHub().ConfigureAwait(false); }
                catch (Exception ex) { Fail(errors, L.T("从 GitHub 下载超级助手", "Download Super Aide from GitHub"), ex); }
            }
            if (probes.PyPI)
            {
                try { return await FromPyPI().ConfigureAwait(false); }
                catch (Exception ex) { Fail(errors, L.T("从 PyPI 下载超级助手", "Download Super Aide from PyPI"), ex); }
            }
            foreach (string index in Uv.PypiMirrors)
            {
                try { return await FromMirror(index).ConfigureAwait(false); }
                catch (Exception ex) { Fail(errors, L.T("从 " + Net.Host(index) + " 下载超级助手", "Download Super Aide from " + Net.Host(index)), ex); }
            }
            throw new SetupException(L.T("没下载到超级助手。检查网络（或代理）后点重试。",
                                         "Couldn't download Super Aide. Check your network (or proxy) and click Retry."));
        }

        async Task<Package> Fetch(string url, string fileName, string sha256, string version, string source)
        {
            if (!Regex.IsMatch(fileName, @"^super_aide-[^-]+-py3-none-any\.whl$"))
                throw new SetupException(L.T("安装包的名字不对：", "Unexpected package name: ") + fileName);
            string path = Path.Combine(temp, fileName);
            await Net.Download(url, path, Bytes(L.T("从 " + source + " 下载超级助手 " + version, "Downloading Super Aide " + version + " from " + source)), token).ConfigureAwait(false);
            Verify(path, sha256);
            sink.Line(L.T("下载好了超级助手 " + version + "（" + source + "）", "Downloaded Super Aide " + version + " (" + source + ")"));
            return new Package { Version = version, Wheel = path, Source = source };
        }

        async Task<Package> FromGitHub()
        {
            Dictionary<string, object> release = (Dictionary<string, object>)Net.Json(
                await Net.Text("https://api.github.com/repos/" + BuildInfo.Repo + "/releases/latest", token).ConfigureAwait(false));
            string version = Convert.ToString(release["tag_name"]).TrimStart('v');
            foreach (object item in (object[])release["assets"])
            {
                Dictionary<string, object> asset = (Dictionary<string, object>)item;
                string name = Convert.ToString(asset["name"]);
                if (!name.EndsWith(".whl", StringComparison.OrdinalIgnoreCase)) continue;
                object digest;
                string sha = asset.TryGetValue("digest", out digest) && Convert.ToString(digest).StartsWith("sha256:")
                    ? Convert.ToString(digest).Substring(7) : null;
                return await Fetch(Convert.ToString(asset["browser_download_url"]), name, sha, version, "GitHub").ConfigureAwait(false);
            }
            throw new SetupException(L.T("GitHub 上最新的发布里没有安装包", "The latest GitHub release has no package"));
        }

        async Task<Package> FromPyPI()
        {
            Dictionary<string, object> data = (Dictionary<string, object>)Net.Json(
                await Net.Text("https://pypi.org/pypi/" + Uv.Package + "/json", token).ConfigureAwait(false));
            string version = Convert.ToString(((Dictionary<string, object>)data["info"])["version"]);
            foreach (object item in (object[])data["urls"])
            {
                Dictionary<string, object> file = (Dictionary<string, object>)item;
                if (Convert.ToString(file["packagetype"]) != "bdist_wheel") continue;
                string sha = Convert.ToString(((Dictionary<string, object>)file["digests"])["sha256"]);
                return await Fetch(Convert.ToString(file["url"]), Convert.ToString(file["filename"]), sha, version, "PyPI").ConfigureAwait(false);
            }
            throw new SetupException(L.T("PyPI 上没有安装包", "PyPI has no package"));
        }

        async Task<Package> FromMirror(string index)
        {
            string page = await Net.Text(index + "/" + Uv.Package + "/", token).ConfigureAwait(false);
            Regex wheel = new Regex(@"href=""([^""]*?(super_aide-(\d+(?:\.\d+)*)-py3-none-any\.whl))#sha256=([0-9a-fA-F]{64})""");
            Match best = null;
            foreach (Match m in wheel.Matches(page))
                if (best == null || CompareVersions(m.Groups[3].Value, best.Groups[3].Value) > 0) best = m;
            if (best == null) throw new SetupException(L.T("镜像里还没有超级助手", "Super Aide isn't on the mirror yet"));
            string url = new Uri(new Uri(index + "/" + Uv.Package + "/"), best.Groups[1].Value).AbsoluteUri;
            return await Fetch(url, best.Groups[2].Value, best.Groups[4].Value, best.Groups[3].Value, Net.Host(index)).ConfigureAwait(false);
        }

        string ExtractConstraints(string wheel)
        {
            string target = Path.Combine(temp, "constraints.txt");
            try
            {
                if (Extract(wheel, delegate(ZipArchiveEntry e) { return e.FullName == "super_aide/_release/constraints.txt"; }, target))
                    return target;
            }
            catch (InvalidDataException) { throw new SetupException(L.T("安装包损坏了，点重试重新下载。", "The package is damaged. Click Retry to download it again.")); }
            sink.Line(L.T("安装包里没有锁定版本的清单，按包里写的版本范围装", "The package has no pinned versions; using its version ranges"));
            return null;
        }

        /// <summary>关掉正在运行的 Super Aide（不然文件被占着换不掉）：只认装在它自己环境里的进程，不碰别的 Python。</summary>
        void StopApp(string uv, int pid)
        {
            if (pid > 0)
            {
                try
                {
                    using (Process process = Process.GetProcessById(pid))
                    {
                        sink.Detail(L.T("等超级助手退出…", "Waiting for Super Aide to exit…"));
                        if (!process.WaitForExit(20000)) process.Kill();
                    }
                }
                catch (ArgumentException) { }
                catch (InvalidOperationException) { }
                catch (Win32Exception) { }
            }
            string env = Path.Combine(Uv.ToolDir(uv), "super-aide") + "\\";
            string launcher = Path.Combine(Uv.BinDir(uv), "super-aide.exe");
            int killed = 0;
            try
            {
                using (ManagementObjectSearcher searcher = new ManagementObjectSearcher("SELECT ProcessId, ExecutablePath FROM Win32_Process"))
                {
                    foreach (ManagementObject process in searcher.Get())
                    {
                        string path = process["ExecutablePath"] as string;
                        if (path == null) continue;
                        if (!path.StartsWith(env, StringComparison.OrdinalIgnoreCase) &&
                            !path.Equals(launcher, StringComparison.OrdinalIgnoreCase)) continue;
                        try
                        {
                            using (Process p = Process.GetProcessById(Convert.ToInt32(process["ProcessId"])))
                            {
                                p.Kill();
                                killed++;
                            }
                        }
                        catch (Exception) { }
                    }
                }
            }
            catch (ManagementException ex) { sink.Line(L.T("没能列出进程：", "Couldn't list processes: ") + ex.Message); }
            if (killed > 0)
            {
                sink.Line(L.T("关掉了 " + killed + " 个超级助手的进程", "Closed " + killed + " Super Aide process(es)"));
                Thread.Sleep(1000);
            }
        }

        void InstallApp(string uv, Package package, string constraints, Probes probes)
        {
            List<KeyValuePair<string, string>> attempts = new List<KeyValuePair<string, string>>();
            string official = L.T("官方源", "the official index");
            if (probes.PyPI) attempts.Add(new KeyValuePair<string, string>(official, null));
            foreach (string mirror in Uv.PypiMirrors)
                attempts.Add(new KeyValuePair<string, string>(L.T("国内镜像 ", "mirror ") + Net.Host(mirror), mirror));
            if (!probes.PyPI) attempts.Add(new KeyValuePair<string, string>(official, null)); // 探不通也最后试一次
            string python = Native.IsArm64 ? "cpython-3.12-windows-x86_64-none" : "3.12";
            string reason = "";
            foreach (KeyValuePair<string, string> attempt in attempts)
            {
                token.ThrowIfCancellationRequested();
                string label = attempt.Key;
                sink.Detail(L.T("从" + label + "下载、安装（第一次约 600MB，要几分钟）…",
                                "Downloading and installing from " + label + " (about 600 MB the first time, takes a few minutes)…"));
                sink.Line(L.T("---- 安装运行环境：", "---- Installing the runtime: ") + label);
                List<string> args = new List<string> { "tool", "install", "--force", "--reinstall-package", Uv.Package, "--python", python };
                if (constraints != null) { args.Add("--constraints"); args.Add(constraints); }
                if (attempt.Value != null) { args.Add("--default-index"); args.Add(attempt.Value); }
                args.Add(package.Wheel);
                Dictionary<string, string> env = new Dictionary<string, string>();
                env["UV_HTTP_TIMEOUT"] = "120";
                if (Uv.IsPrivate(uv)) env["UV_CACHE_DIR"] = Uv.PrivateCache;
                // Python 本体默认从 GitHub 下载：连不上、或者已经在用国内镜像时，一起换成 npmmirror
                env["UV_PYTHON_INSTALL_MIRROR"] = probes.GitHub && attempt.Value == null ? null : Uv.PythonMirror;
                string last = "";
                int code = Uv.Run(uv, args, env, delegate(string line)
                {
                    sink.Line(line);
                    string text = line.Trim();
                    if (text.Length == 0) return;
                    if (text.StartsWith("error", StringComparison.OrdinalIgnoreCase) || text.StartsWith("×") || text.StartsWith("Caused by"))
                        last = text;
                    else
                        sink.Detail(label + L.T("：", ": ") + (text.Length > 64 ? text.Substring(0, 63) + "…" : text));
                }, token);
                if (code == 0) return;
                reason = last;
                sink.Line(L.T(label + " 没装上（" + code + "），换下一个", label + " failed (" + code + "), trying the next one"));
            }
            throw new SetupException(L.T("运行环境没装上", "The runtime didn't install") + (reason.Length > 0 ? L.T("：", ": ") + reason : "") +
                                     L.T("。检查网络（或代理）后点重试。", ". Check your network (or proxy) and click Retry."));
        }

        string Finish(string uv, string version, bool autostart, bool desktop, bool update)
        {
            string launcher = Path.Combine(Uv.BinDir(uv), "super-aide.exe");
            if (!File.Exists(launcher)) throw new SetupException(L.T("装完了却没找到启动器：", "Installed, but the launcher is missing: ") + launcher);
            string env = Path.Combine(Uv.ToolDir(uv), "super-aide");
            string icon = Path.Combine(env, @"Lib\site-packages\super_aide\ui\super_aide.ico");
            string pythonw = Path.Combine(env, @"Scripts\pythonw.exe");
            Directory.CreateDirectory(Places.AppDir);
            CopySelf();
            bool hadDesktop = Places.HasDesktopLink();
            DeleteLinks(Places.StartMenuDir);
            Shortcut(Places.StartMenuLink, launcher, icon);
            if (update ? hadDesktop : desktop)
            {
                DeleteLinks(Places.DesktopDir);
                Shortcut(Places.DesktopLink, launcher, icon);
            }
            else if (!update) DeleteLinks(Places.DesktopDir);
            if (!update) SetAutostart(autostart, pythonw);
            Register(version, File.Exists(icon) ? icon : Places.Installer, env);
            return launcher;
        }

        void CopySelf()
        {
            string self = Process.GetCurrentProcess().MainModule.FileName;
            if (string.Equals(Path.GetFullPath(self), Path.GetFullPath(Places.Installer), StringComparison.OrdinalIgnoreCase)) return;
            try { File.Copy(self, Places.Installer, true); }
            catch (IOException ex) { sink.Line(L.T("没能留一份安装器（更新、卸载时用）：", "Couldn't keep a copy of the installer (used for updates and uninstall): ") + ex.Message); }
            catch (UnauthorizedAccessException ex) { sink.Line(L.T("没能留一份安装器（更新、卸载时用）：", "Couldn't keep a copy of the installer (used for updates and uninstall): ") + ex.Message); }
        }

        void Shortcut(string link, string target, string icon)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(link));
            Type type = Type.GetTypeFromProgID("WScript.Shell");
            dynamic shell = Activator.CreateInstance(type);
            dynamic shortcut = shell.CreateShortcut(link);
            shortcut.TargetPath = target;
            shortcut.WorkingDirectory = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            shortcut.Description = L.T("超级助手（Super Aide）桌面助手", "Super Aide desktop assistant");
            if (File.Exists(icon)) shortcut.IconLocation = icon;
            shortcut.Save();
            sink.Line(L.T("快捷方式：", "Shortcut: ") + link);
        }

        static void DeleteLinks(string dir)
        {
            foreach (string name in Places.LinkNames) Delete(Path.Combine(dir, name));
        }

        /// <summary>和 Super Aide 自己写的自启命令一样（autostart.py）：开机时带 --autostart，安静启动。</summary>
        void SetAutostart(bool on, string pythonw)
        {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(Places.RunKey))
            {
                if (on) key.SetValue("SuperAide", "\"" + pythonw + "\" -m super_aide --autostart");
                else if (IsOurs(key.GetValue("SuperAide") as string)) key.DeleteValue("SuperAide", false);
            }
        }

        static bool IsOurs(string command)
        {
            return command != null && (command.Contains("super_aide") || command.Contains("super-aide"));
        }

        void Register(string version, string icon, string env)
        {
            long size = 0;
            try
            {
                foreach (string file in Directory.EnumerateFiles(env, "*", SearchOption.AllDirectories)) size += new FileInfo(file).Length;
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(Places.UninstallKey))
            {
                key.SetValue("DisplayName", L.AppName);
                key.SetValue("DisplayVersion", version);
                key.SetValue("Publisher", "Super Aide");
                key.SetValue("DisplayIcon", icon);
                key.SetValue("InstallLocation", Places.AppDir);
                key.SetValue("UninstallString", "\"" + Places.Installer + "\" /uninstall");
                if (BuildInfo.Repo.Length > 0) key.SetValue("URLInfoAbout", "https://github.com/" + BuildInfo.Repo);
                key.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
                key.SetValue("EstimatedSize", (int)Math.Min(int.MaxValue, size / 1024), RegistryValueKind.DWord);
                key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }
            sink.Line(L.T("已登记到系统的应用列表（可以在设置 → 应用里卸载）", "Registered in Windows Settings → Apps (uninstall from there)"));
        }

        void Launch(string launcher, bool update)
        {
            if (Places.Sandboxed)
            {
                sink.Line(L.T("测试模式：不打开超级助手", "Test mode: not opening Super Aide"));
                return;
            }
            ProcessStartInfo psi = new ProcessStartInfo(launcher, update ? "--updated" : "");
            psi.UseShellExecute = true;
            psi.WorkingDirectory = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            Process.Start(psi);
            sink.Line(L.T("已打开超级助手", "Opened Super Aide"));
        }

        void Cleanup()
        {
            try { Directory.Delete(temp, true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }

        static void Delete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }

        // ---------- 卸载 ----------

        public Task Uninstall(bool removeData)
        {
            return Task.Run(delegate
            {
                string uv = Uv.Find();
                sink.Step(0);
                StopApp(uv, 0);

                sink.Step(1);
                string env = Path.Combine(Uv.ToolDir(uv), "super-aide");
                string launcher = Path.Combine(Uv.BinDir(uv), "super-aide.exe");
                if (uv != null)
                {
                    int code = Uv.Run(uv, new[] { "tool", "uninstall", Uv.Package }, null, sink.Line, token);
                    sink.Line("uv tool uninstall: " + code);
                }
                try { if (Directory.Exists(env)) Directory.Delete(env, true); }
                catch (IOException ex) { sink.Line(L.T("没删掉 ", "Couldn't delete ") + env + ": " + ex.Message); }
                catch (UnauthorizedAccessException ex) { sink.Line(L.T("没删掉 ", "Couldn't delete ") + env + ": " + ex.Message); }
                Delete(launcher);

                sink.Step(2);
                DeleteLinks(Places.StartMenuDir);
                DeleteLinks(Places.DesktopDir);
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(Places.RunKey, true))
                    if (key != null && IsOurs(key.GetValue("SuperAide") as string)) key.DeleteValue("SuperAide", false);
                Registry.CurrentUser.DeleteSubKeyTree(Places.UninstallKey, false);

                if (removeData)
                {
                    sink.Step(3);
                    try
                    {
                        string moved = Places.MovedDataDir; // 先读：location.json 在 DataDir 里
                        if (moved != null) Directory.Delete(moved, true);
                        if (Directory.Exists(Places.DataDir)) Directory.Delete(Places.DataDir, true);
                    }
                    catch (IOException ex) { sink.Line(L.T("没删干净我的数据：", "Couldn't delete all of my data: ") + ex.Message); }
                    catch (UnauthorizedAccessException ex) { sink.Line(L.T("没删干净我的数据：", "Couldn't delete all of my data: ") + ex.Message); }
                }
                Cleanup();
            }, token);
        }

        /// <summary>安装器自己所在的文件夹：等这个进程退出后再删（正在运行的程序删不掉自己）。</summary>
        public static void RemoveAppDirLater()
        {
            if (!Directory.Exists(Places.AppDir)) return;
            ProcessStartInfo psi = new ProcessStartInfo("cmd.exe",
                "/c ping 127.0.0.1 -n 3 > nul & rmdir /s /q " + Uv.Quote(Places.AppDir));
            psi.CreateNoWindow = true;
            psi.UseShellExecute = false;
            psi.WorkingDirectory = Path.GetTempPath();
            Process.Start(psi);
        }

        public static string InstalledVersion()
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(Places.UninstallKey))
            {
                string version = key != null ? key.GetValue("DisplayVersion") as string : null;
                if (version != null) return version;
            }
            return Directory.Exists(Path.Combine(Uv.ToolDir(null), "super-aide")) ? "" : null; // 用脚本装过、没登记版本
        }

        public static bool AutostartOn()
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(Places.RunKey))
                return key != null && IsOurs(key.GetValue("SuperAide") as string);
        }
    }
}
