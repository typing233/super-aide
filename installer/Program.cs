// Super Aide 安装器（SuperAideSetup.exe）：一个很小的程序，打开后下载、检查、安装，装好打开 Super Aide。
// 也负责更新（Super Aide 设置里点"更新"时以 /update 启动）和卸载（系统"设置 → 应用"里卸载时以 /uninstall 启动）。
//
// 用 Windows 自带的 .NET Framework 4.8 编译（scripts\build_installer.ps1），不需要另装运行库。
// 只能用 C# 5 的写法（自带的编译器只到 C# 5）：没有 $"" 字符串、?. 这些。
//
//   SuperAideSetup.exe                 安装（或者更新已经装好的）
//   SuperAideSetup.exe /update [/pid N] 更新：先等进程 N（正在运行的 Super Aide）退出
//   SuperAideSetup.exe /uninstall      卸载
//   SuperAideSetup.exe /wheel <路径>    用本地的安装包（离线安装、测试）
//   SuperAideSetup.exe /auto           不用点按钮：直接装（或 /uninstall /auto 直接卸载、不删数据），做完自己关
//   SuperAideSetup.exe /render <目录>   把每个页面画成图片（检查界面用）

using System;
using System.Globalization;
using System.Threading;
using System.Windows.Forms;

namespace SuperAideSetup
{
    enum Mode { Install, Update, Uninstall }

    /// <summary>中英文：跟着 Windows 的显示语言（中文系统用中文，其它用英文）。应用名：超级助手 / Super Aide。</summary>
    static class L
    {
        /// <summary>环境变量 SUPER_AIDE_LANG=zh / en 可以指定（测试界面用），否则看系统。</summary>
        public static readonly bool Zh = Environment.GetEnvironmentVariable("SUPER_AIDE_LANG") == "zh" ||
            (Environment.GetEnvironmentVariable("SUPER_AIDE_LANG") != "en" && CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "zh");

        public static string T(string zh, string en) { return Zh ? zh : en; }

        public static string AppName { get { return Zh ? "超级助手" : "Super Aide"; } }
    }

    class Options
    {
        public Mode Mode = Mode.Install;
        public int Pid;
        public string Wheel;
        public string RenderDir;
        public bool Auto;   // 不等点按钮，直接装（或卸载，不删数据），做完自己关，退出码 0 = 成功

        public static Options Parse(string[] args)
        {
            Options o = new Options();
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i].ToLowerInvariant().TrimStart('-', '/');
                string next = i + 1 < args.Length ? args[i + 1] : null;
                if (a == "update") o.Mode = Mode.Update;
                else if (a == "uninstall") o.Mode = Mode.Uninstall;
                else if (a == "pid" && next != null) { int.TryParse(next, out o.Pid); i++; }
                else if (a == "wheel" && next != null) { o.Wheel = next; i++; }
                else if (a == "render" && next != null) { o.RenderDir = next; i++; }
                else if (a == "auto") o.Auto = true;
            }
            return o;
        }
    }

    static class Program
    {
        static bool quiet; // 画图检查界面时：出错只记下来，不弹框

        [STAThread]
        static int Main(string[] args)
        {
            Options options = Options.Parse(args);
            quiet = options.RenderDir != null;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += delegate(object sender, ThreadExceptionEventArgs e) { Crash(e.Exception); };
            AppDomain.CurrentDomain.UnhandledException += delegate(object sender, UnhandledExceptionEventArgs e) { Crash(e.ExceptionObject as Exception); };
            try
            {
                if (options.RenderDir != null)
                {
                    SetupForm.RenderPages(options.RenderDir);
                    return 0;
                }
                bool created;
                using (Mutex mutex = new Mutex(true, "Local\\SuperAideSetup", out created))
                {
                    if (!created) return 1; // 已经开着一个安装器
                    Log.Start(options);
                    Application.Run(new SetupForm(options));
                }
                return 0;
            }
            catch (Exception ex)
            {
                Crash(ex);
                return 2;
            }
        }

        /// <summary>意外出错：记下来（%TEMP%\SuperAideSetup-crash.log），告诉用户，不弹系统的崩溃框。</summary>
        static void Crash(Exception ex)
        {
            string path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "SuperAideSetup-crash.log");
            try { System.IO.File.AppendAllText(path, DateTime.Now + " " + ex + "\r\n\r\n"); }
            catch (Exception) { }
            if (!quiet) MessageBox.Show("安装器出了意外：" + (ex != null ? ex.Message : "原因不明") + "\n\n详细记录在 " + path,
                "Super Aide", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Environment.Exit(2);
        }
    }
}
