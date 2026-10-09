// 安装器的界面：和 Super Aide 同一套视觉规范（深浅色跟随系统、蓝紫渐变的光点和主按钮、圆角、留白）。
// 一个窗口，几页：欢迎（选项）→ 进度（步骤、进度条、详情）→ 完成 / 没装好；卸载有确认页。
// 全部自己画（WinForms 自带的控件太老气），按系统 DPI 缩放。

using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace SuperAideSetup
{
    class Theme
    {
        public bool Dark;
        public Color Back, Text, Text2, Text3, Line, Control, Hover, LogBack;
        public static readonly Color A = Color.FromArgb(0x5B, 0x8C, 0xFF);
        public static readonly Color B = Color.FromArgb(0x9B, 0x6B, 0xFF);
        public static readonly Color Ok = Color.FromArgb(0x3C, 0xCB, 0x7F);
        public static readonly Color Err = Color.FromArgb(0xFF, 0x5D, 0x5D);

        public static Theme Load(bool? dark)
        {
            bool isDark = dark ?? SystemIsDark();
            Theme t = new Theme { Dark = isDark };
            if (isDark)
            {
                t.Back = Color.FromArgb(32, 32, 35); t.Text = Color.FromArgb(235, 235, 237);
                t.Text2 = Color.FromArgb(152, 152, 158); t.Text3 = Color.FromArgb(108, 108, 115);
                t.Line = Color.FromArgb(50, 50, 55); t.Control = Color.FromArgb(46, 46, 51);
                t.Hover = Color.FromArgb(57, 57, 63); t.LogBack = Color.FromArgb(25, 25, 28);
            }
            else
            {
                t.Back = Color.White; t.Text = Color.FromArgb(30, 30, 32);
                t.Text2 = Color.FromArgb(110, 110, 116); t.Text3 = Color.FromArgb(158, 158, 165);
                t.Line = Color.FromArgb(232, 232, 236); t.Control = Color.FromArgb(240, 240, 243);
                t.Hover = Color.FromArgb(231, 231, 236); t.LogBack = Color.FromArgb(246, 246, 248);
            }
            return t;
        }

        static bool SystemIsDark()
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"))
            {
                object value = key != null ? key.GetValue("AppsUseLightTheme") : null;
                return value is int && (int)value == 0;
            }
        }
    }

    static class Draw
    {
        public static GraphicsPath Round(RectangleF r, float radius)
        {
            float d = Math.Min(radius * 2, Math.Min(r.Width, r.Height));
            GraphicsPath path = new GraphicsPath();
            if (d <= 0.5f)
            {
                if (r.Width > 0 && r.Height > 0) path.AddRectangle(r);
                return path;
            }
            path.AddArc(r.X, r.Y, d, d, 180, 90);
            path.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            path.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }

        public static void Gradient(Graphics g, GraphicsPath path, RectangleF bounds, Color a, Color b)
        {
            using (LinearGradientBrush brush = new LinearGradientBrush(bounds, a, b, 45f))
                g.FillPath(brush, path);
        }

        public static void Orb(Graphics g, float cx, float cy, float s)
        {
            float r = 5 * s;
            using (SolidBrush glow = new SolidBrush(Color.FromArgb(46, Theme.A)))
                g.FillEllipse(glow, cx - r * 1.9f, cy - r * 1.9f, r * 3.8f, r * 3.8f);
            RectangleF dot = new RectangleF(cx - r, cy - r, r * 2, r * 2);
            using (GraphicsPath path = new GraphicsPath())
            {
                path.AddEllipse(dot);
                Gradient(g, path, dot, Theme.A, Theme.B);
            }
        }

        public static void Check(Graphics g, RectangleF box, Color color, float width)
        {
            using (Pen pen = new Pen(color, width) { StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round })
                g.DrawLines(pen, new[] {
                    new PointF(box.X + box.Width * 0.27f, box.Y + box.Height * 0.53f),
                    new PointF(box.X + box.Width * 0.44f, box.Y + box.Height * 0.69f),
                    new PointF(box.X + box.Width * 0.74f, box.Y + box.Height * 0.36f) });
        }

        /// <summary>步骤前面的小圆：done 打勾，failed 感叹号，running 转圈，否则空心圆。</summary>
        public static void StepIcon(Graphics g, RectangleF box, Theme t, string state, float phase, float s)
        {
            if (state == "done" || state == "failed")
            {
                using (SolidBrush brush = new SolidBrush(state == "done" ? Theme.Ok : Theme.Err))
                    g.FillEllipse(brush, box);
                if (state == "done") Check(g, box, Color.White, 1.7f * s);
                else Bang(g, box, s);
            }
            else if (state == "running")
            {
                using (Pen track = new Pen(t.Line, 1.6f * s))
                    g.DrawEllipse(track, Inset(box, 0.8f * s));
                using (Pen arc = new Pen(Theme.A, 1.8f * s) { StartCap = LineCap.Round, EndCap = LineCap.Round })
                    g.DrawArc(arc, Inset(box, 0.8f * s), phase * 360f, 110f);
            }
            else
            {
                using (Pen ring = new Pen(t.Text3, 1.3f * s))
                    g.DrawEllipse(ring, Inset(box, 1.2f * s));
            }
        }

        public static void Bang(Graphics g, RectangleF box, float s)
        {
            using (Pen pen = new Pen(Color.White, Math.Max(1.6f * s, box.Width * 0.11f)) { StartCap = LineCap.Round, EndCap = LineCap.Round })
            {
                float x = box.X + box.Width / 2;
                g.DrawLine(pen, x, box.Y + box.Height * 0.27f, x, box.Y + box.Height * 0.56f);
                g.DrawLine(pen, x, box.Y + box.Height * 0.73f, x, box.Y + box.Height * 0.74f);
            }
        }

        public static RectangleF Inset(RectangleF r, float d)
        {
            return new RectangleF(r.X + d, r.Y + d, r.Width - 2 * d, r.Height - 2 * d);
        }
    }

    class FlatButton : Control
    {
        public bool Primary, Danger, Link, Glyph;
        readonly Theme t;
        readonly float s;
        bool hover;

        public FlatButton(Theme theme, float scale, string text)
        {
            t = theme;
            s = scale;
            Text = text;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
            Cursor = Cursors.Hand;
            TabStop = true;
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Enter || e.KeyCode == Keys.Space) OnClick(EventArgs.Empty);
            base.OnKeyDown(e);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(t.Back);
            if (Width < 4 || Height < 4) return;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            RectangleF r = new RectangleF(0.5f, 0.5f, Width - 1.5f, Height - 1.5f);
            using (GraphicsPath path = Draw.Round(r, 9 * s))
            {
                if (Primary && Enabled)
                    Draw.Gradient(g, path, r, Danger ? Theme.Err : Theme.A, Danger ? Color.FromArgb(0xE8, 0x4A, 0x6A) : Theme.B);
                else if (Primary)
                    using (SolidBrush brush = new SolidBrush(t.Control)) g.FillPath(brush, path);
                else if (hover && !Link)
                    using (SolidBrush brush = new SolidBrush(t.Hover)) g.FillPath(brush, path);
                if (Primary && Enabled && hover)
                    using (SolidBrush shine = new SolidBrush(Color.FromArgb(22, Color.White))) g.FillPath(shine, path);
            }
            if (Glyph)
            {
                float c = Width / 2f, d = 4.6f * s;
                using (Pen pen = new Pen(hover ? t.Text : t.Text2, 1.4f * s) { StartCap = LineCap.Round, EndCap = LineCap.Round })
                {
                    g.DrawLine(pen, c - d, Height / 2f - d, c + d, Height / 2f + d);
                    g.DrawLine(pen, c + d, Height / 2f - d, c - d, Height / 2f + d);
                }
                return;
            }
            Color fg = Primary ? (Enabled ? Color.White : t.Text3) : (!Enabled ? t.Text3 : hover ? t.Text : t.Text2);
            TextRenderer.DrawText(g, Text, Font, ClientRectangle, fg,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
        }

        public int Preferred()
        {
            return Math.Max((int)(88 * s), TextRenderer.MeasureText(Text, Font).Width + (int)(30 * s));
        }
    }

    class CheckOption : Control
    {
        public bool Checked;
        readonly Theme t;
        readonly float s;

        public CheckOption(Theme theme, float scale, string text, bool on)
        {
            t = theme;
            s = scale;
            Text = text;
            Checked = on;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            Cursor = Cursors.Hand;
        }

        protected override void OnClick(EventArgs e)
        {
            Checked = !Checked;
            Invalidate();
            base.OnClick(e);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(t.Back);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float size = 17 * s;
            RectangleF box = new RectangleF(0.5f, (Height - size) / 2, size, size);
            using (GraphicsPath path = Draw.Round(box, 4.5f * s))
            {
                if (Checked)
                {
                    Draw.Gradient(g, path, box, Theme.A, Theme.B);
                    Draw.Check(g, box, Color.White, 1.7f * s);
                }
                else
                    using (Pen pen = new Pen(t.Text3, 1.3f * s)) g.DrawPath(pen, path);
            }
            Rectangle text = new Rectangle((int)(size + 10 * s), 0, Width - (int)(size + 10 * s), Height);
            TextRenderer.DrawText(g, Text, Font, text, t.Text,
                TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
        }
    }

    enum Page { Welcome, Progress, Done, Failed, ConfirmUninstall }

    class SetupForm : Form, ISink
    {
        const int BaseW = 480, BaseH = 400, LogH = 176, Pad = 28;
        readonly Options options;
        readonly Theme t;
        readonly float s;
        readonly Font brandFont, titleFont, bodyFont, smallFont, buttonFont;
        readonly FlatButton primary, secondary, details, close;
        readonly CheckOption option1, option2;
        readonly TextBox log;
        readonly System.Windows.Forms.Timer timer;

        Page page;
        string title = "", body = "";
        string[] steps = new string[0];
        int current = -1;
        bool stepFailed, running, showLog, closeWhenDone;
        string detail = "";
        double progress = -1;
        float phase;
        DateTime stepStarted = DateTime.Now;
        CancellationTokenSource cts;
        Action retry;

        [DllImport("user32.dll")] static extern bool ReleaseCapture();
        [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);
        [DllImport("user32.dll")] static extern uint GetDpiForSystem();
        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

        public SetupForm(Options options) : this(options, null) { }

        SetupForm(Options options, bool? dark)
        {
            this.options = options;
            t = Theme.Load(dark);
            float dpi = 96;
            try { dpi = GetDpiForSystem(); } catch (EntryPointNotFoundException) { }
            s = dpi / 96f;
            string family = L.Zh ? "Microsoft YaHei UI" : "Segoe UI";
            brandFont = MakeFont(family, 14, FontStyle.Bold);
            titleFont = MakeFont(family, 20, FontStyle.Bold);
            bodyFont = MakeFont(family, 13.5f, FontStyle.Regular);
            smallFont = MakeFont(family, 12, FontStyle.Regular);
            buttonFont = MakeFont(family, 13, FontStyle.Regular);

            AutoScaleMode = AutoScaleMode.None;
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = t.Back;
            DoubleBuffered = true;
            KeyPreview = true;
            Text = options.Mode == Mode.Uninstall ? L.T("卸载超级助手", "Uninstall Super Aide") : L.T("安装超级助手", "Install Super Aide");
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch (Exception) { }
            ClientSize = new Size(S(BaseW), S(BaseH));

            primary = Button("", true);
            secondary = Button("", false);
            details = Button(L.T("查看详情", "Details"), false);
            details.Link = true;
            close = Button("", false);
            close.Glyph = true;
            close.TabStop = false;
            option1 = new CheckOption(t, s, AutostartText(), true) { Font = bodyFont };
            option2 = new CheckOption(t, s, L.T("在桌面放一个快捷方式", "Add a desktop shortcut"), true) { Font = bodyFont };
            log = new TextBox
            {
                Multiline = true, ReadOnly = true, BorderStyle = BorderStyle.None, ScrollBars = ScrollBars.Vertical,
                BackColor = t.LogBack, ForeColor = t.Text2, Font = MakeFont("Consolas", 11.5f, FontStyle.Regular), WordWrap = true,
            };
            Controls.AddRange(new Control[] { primary, secondary, details, close, option1, option2, log });
            close.Click += delegate { Close(); };
            details.Click += delegate { ToggleLog(); };
            primary.Click += delegate { OnPrimary(); };
            secondary.Click += delegate { OnSecondary(); };

            timer = new System.Windows.Forms.Timer { Interval = 33 };
            timer.Tick += delegate
            {
                phase = (phase + 0.028f) % 1f;
                if (running && page == Page.Progress) Invalidate();
            };
            timer.Start();
            Start();
        }

        Font MakeFont(string family, float px, FontStyle style)
        {
            return new Font(family, px * s, style, GraphicsUnit.Pixel);
        }

        int S(float v) { return (int)Math.Round(v * s); }

        FlatButton Button(string text, bool isPrimary)
        {
            return new FlatButton(t, s, text) { Primary = isPrimary, Font = buttonFont };
        }

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams cp = base.CreateParams;
                cp.ClassStyle |= 0x00020000; // CS_DROPSHADOW
                return cp;
            }
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            int round = 2; // Windows 11：圆角
            try { DwmSetWindowAttribute(Handle, 33, ref round, sizeof(int)); } catch (DllNotFoundException) { }
            int dark = t.Dark ? 1 : 0;
            try { DwmSetWindowAttribute(Handle, 20, ref dark, sizeof(int)); } catch (DllNotFoundException) { }
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button != MouseButtons.Left) return;
            ReleaseCapture();
            SendMessage(Handle, 0xA1, (IntPtr)2, IntPtr.Zero); // 按住空白处拖动窗口
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Escape) Close();
            base.OnKeyDown(e);
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (running)
            {
                // 正在装：先停下来（结束 uv），停好再关
                e.Cancel = true;
                closeWhenDone = true;
                if (cts != null) cts.Cancel();
                return;
            }
            base.OnFormClosing(e);
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            timer.Stop();
            base.OnFormClosed(e);
        }

        // ---------- 页面 ----------

        void Start()
        {
            if (options.Mode == Mode.Uninstall)
            {
                ShowConfirmUninstall();
                if (options.Auto) Shown += delegate { RunUninstall(false); };
            }
            else if (options.Mode == Mode.Update || options.Auto) Shown += delegate { RunInstall(options.Mode == Mode.Update); };
            else ShowWelcome();
        }

        /// <summary>/auto：做完自己关，退出码告诉调用的人成没成。</summary>
        void AutoFinish(bool ok)
        {
            if (!options.Auto) return;
            Environment.ExitCode = ok ? 0 : 1;
            System.Windows.Forms.Timer bye = new System.Windows.Forms.Timer { Interval = 800 };
            bye.Tick += delegate { bye.Stop(); Close(); };
            bye.Start();
        }

        void ShowWelcome()
        {
            string installed = Setup.InstalledVersion();
            page = Page.Welcome;
            if (installed != null)
            {
                title = L.T("更新超级助手", "Update Super Aide");
                body = (installed.Length > 0 ? L.T("已经装了 " + installed + "。", "Version " + installed + " is installed. ")
                                             : L.T("已经装过了。", "It's already installed. ")) +
                       L.T("这会下载最新版本装上，你的设置和记录都会保留。",
                           "This downloads and installs the latest version. Your settings and history are kept.");
                primary.Text = L.T("更新", "Update");
                option1.Checked = Setup.AutostartOn();
                option2.Checked = Places.HasDesktopLink();
            }
            else
            {
                title = L.T("安装超级助手", "Install Super Aide");
                body = WelcomeBody();
                primary.Text = L.T("安装", "Install");
            }
            secondary.Text = L.T("取消", "Cancel");
            option1.Text = AutostartText();
            Relayout();
        }

        static string WelcomeBody()
        {
            return L.T("按一下快捷键，问它问题，或者让它直接动手。\n接下来会下载并安装运行环境（约 600MB，要几分钟）。" +
                       "装好后第一次打开，会帮你检查 Claude Code 和 Codex。",
                       "Press a hotkey to ask a question, or let it do the work for you.\nNext, the runtime is downloaded and " +
                       "installed (about 600 MB, takes a few minutes). On first launch it checks Claude Code and Codex for you.");
        }

        static string AutostartText()
        {
            return L.T("开机自动启动（推荐：随时按快捷键就能用）", "Start with Windows (recommended: the hotkeys always work)");
        }

        void ShowConfirmUninstall()
        {
            page = Page.ConfirmUninstall;
            title = L.T("卸载超级助手", "Uninstall Super Aide");
            body = L.T("会删除超级助手本身、快捷方式和开机自启。\nClaude Code、Codex 是独立的工具，不会删。",
                       "This removes Super Aide, its shortcuts and autostart.\nClaude Code and Codex are separate tools and stay installed.");
            option1.Text = L.T("同时删除我的数据（设置、历史记录、经验）", "Also delete my data (settings, history, lessons)");
            option1.Checked = false;
            primary.Text = L.T("卸载", "Uninstall");
            primary.Danger = true;
            secondary.Text = L.T("取消", "Cancel");
            Relayout();
        }

        void ShowProgress(string heading, string[] list)
        {
            page = Page.Progress;
            title = heading;
            steps = list;
            current = -1;
            stepFailed = false;
            detail = "";
            progress = -1;
            running = true;
            secondary.Text = L.T("取消", "Cancel");
            Relayout();
        }

        void ShowDone(string heading, string text)
        {
            running = false;
            current = steps.Length;
            page = Page.Done;
            title = heading;
            body = text;
            primary.Text = L.T("完成", "Done");
            primary.Danger = false;
            Relayout();
        }

        void ShowFailed(string heading, string text, Action again)
        {
            running = false;
            stepFailed = true;
            page = Page.Failed;
            title = heading;
            body = text;
            retry = again;
            primary.Text = L.T("重试", "Retry");
            primary.Danger = false;
            secondary.Text = L.T("关闭", "Close");
            Relayout();
        }

        void OnPrimary()
        {
            if (page == Page.Welcome) RunInstall(false);
            else if (page == Page.ConfirmUninstall) RunUninstall(option1.Checked);
            else if (page == Page.Failed && retry != null) retry();
            else if (page == Page.Done) Close();
        }

        void OnSecondary()
        {
            if (page == Page.Progress) { if (cts != null) cts.Cancel(); }
            else Close();
        }

        async void RunInstall(bool update)
        {
            bool autostart = option1.Checked, desktop = option2.Checked;
            ShowProgress(update ? L.T("正在更新超级助手", "Updating Super Aide") : L.T("正在安装超级助手", "Installing Super Aide"),
                         Setup.InstallSteps);
            cts = new CancellationTokenSource();
            Setup setup = new Setup(this, cts.Token, options);
            Action again = delegate { RunInstall(update); };
            try
            {
                string version = await Task.Run(() => setup.Install(autostart, desktop, update));
                if (update)
                {
                    ShowDone(L.T("已更新到 ", "Updated to ") + version, L.T("超级助手已经重新打开。", "Super Aide is running again."));
                    System.Windows.Forms.Timer bye = new System.Windows.Forms.Timer { Interval = 2500 };
                    bye.Tick += delegate { bye.Stop(); Close(); };
                    bye.Start();
                }
                else
                    ShowDone(L.T("安装完成", "Installed"), DoneBody());
                AutoFinish(true);
            }
            catch (OperationCanceledException) { ShowFailed(L.T("已经停下了", "Stopped"), L.T("随时可以重新安装。", "You can install again any time."), again); }
            catch (SetupException ex) { ShowFailed(FailedTitle(update), ex.Message, again); }
            catch (Exception ex)
            {
                Log.Write(ex.ToString());
                ShowFailed(FailedTitle(update), ex.Message + L.T("\n详情里有完整记录。", "\nThe details have the full log."), again);
            }
            finally
            {
                running = false;
                if (page == Page.Failed) AutoFinish(false);
                if (closeWhenDone) Close();
            }
        }

        static string DoneBody()
        {
            return L.T("超级助手已经打开，第一次会先检查 Claude Code 和 Codex。\n以后从开始菜单打开；按 Alt+Q 问答，Alt+W 操作。",
                       "Super Aide is open and will first check Claude Code and Codex.\nLater, open it from the Start menu. " +
                       "Press Alt+Q to ask, Alt+W to act.");
        }

        static string FailedTitle(bool update)
        {
            return update ? L.T("没有更新好", "Update didn't finish") : L.T("没有装好", "Install didn't finish");
        }

        async void RunUninstall(bool removeData)
        {
            string[] list = removeData ? Setup.UninstallSteps : new[] { Setup.UninstallSteps[0], Setup.UninstallSteps[1], Setup.UninstallSteps[2] };
            ShowProgress(L.T("正在卸载超级助手", "Uninstalling Super Aide"), list);
            cts = new CancellationTokenSource();
            Setup setup = new Setup(this, cts.Token, options);
            try
            {
                await setup.Uninstall(removeData);
                ShowDone(L.T("已卸载超级助手", "Super Aide is uninstalled"),
                         L.T("Claude Code、Codex 是独立的工具，没有动。", "Claude Code and Codex are separate tools and were left alone.") +
                         (removeData ? "" : L.T("\n你的数据还在 " + Places.DataDir + "，不要了可以直接删掉。",
                                                "\nYour data is still in " + Places.DataDir + "; delete it if you don't need it.")));
                FormClosed += delegate { Setup.RemoveAppDirLater(); };
                AutoFinish(true);
            }
            catch (OperationCanceledException) { ShowFailed(L.T("已经停下了", "Stopped"), L.T("可以重新卸载。", "You can uninstall again."), delegate { RunUninstall(removeData); }); }
            catch (Exception ex)
            {
                Log.Write(ex.ToString());
                ShowFailed(L.T("没有卸载干净", "Uninstall didn't finish"), ex.Message, delegate { RunUninstall(removeData); });
            }
            finally
            {
                running = false;
                if (page == Page.Failed) AutoFinish(false);
                if (closeWhenDone) Close();
            }
        }

        // ---------- ISink（从后台线程调用） ----------

        void Ui(MethodInvoker action)
        {
            if (IsDisposed || !IsHandleCreated) return;
            try { BeginInvoke(action); } catch (InvalidOperationException) { }
        }

        public void Step(int index)
        {
            Log.Write(L.T("步骤：", "Step: ") + (index < steps.Length ? steps[index] : index.ToString()));
            Ui(delegate { current = index; detail = ""; progress = -1; stepStarted = DateTime.Now; Invalidate(); });
        }

        public void Detail(string text) { Ui(delegate { detail = text; Invalidate(); }); }

        public void Progress(double value) { Ui(delegate { progress = value; Invalidate(); }); }

        public void Line(string text)
        {
            Log.Write(text);
            Ui(delegate
            {
                if (log.TextLength > 200000) log.Text = log.Text.Substring(log.TextLength - 100000);
                log.AppendText(text + "\r\n");
            });
        }

        // ---------- 布局和绘制 ----------

        void ToggleLog()
        {
            showLog = !showLog;
            details.Text = showLog ? L.T("收起详情", "Hide details") : L.T("查看详情", "Details");
            ClientSize = new Size(S(BaseW), S(BaseH + (showLog ? LogH : 0)));
            Relayout();
        }

        void Relayout()
        {
            int w = ClientSize.Width, h = ClientSize.Height;
            close.Bounds = new Rectangle(w - S(14 + 28), S(12), S(28), S(28));
            int footer = h - S(24 + 34);
            // 窗口还没显示时，子控件的 Visible 读出来都是 false：按算出来的值摆，不要回读
            bool twoButtons = page == Page.Welcome || page == Page.ConfirmUninstall || page == Page.Failed;
            bool showPrimary = page != Page.Progress, showSecondary = page == Page.Progress || twoButtons;
            primary.Visible = showPrimary;
            secondary.Visible = showSecondary;
            int right = w - S(Pad);
            if (showPrimary)
            {
                int pw = primary.Preferred();
                primary.Bounds = new Rectangle(right - pw, footer, pw, S(34));
                right -= pw + S(8);
            }
            if (showSecondary)
            {
                int sw = secondary.Preferred();
                secondary.Bounds = new Rectangle(right - sw, footer, sw, S(34));
            }
            details.Visible = page == Page.Progress || page == Page.Failed;
            int dw = details.Preferred() - S(10);
            details.Bounds = new Rectangle(S(Pad - 10), footer, dw, S(34));
            bool showOptions = page == Page.Welcome || page == Page.ConfirmUninstall;
            int optionTop = S(102) + BodyHeight() + S(22);
            option1.Visible = showOptions;
            option2.Visible = page == Page.Welcome;
            option1.Bounds = new Rectangle(S(Pad), optionTop, w - S(2 * Pad), S(26));
            option2.Bounds = new Rectangle(S(Pad), optionTop + S(34), w - S(2 * Pad), S(26));
            log.Visible = showLog;
            log.Bounds = new Rectangle(S(Pad), S(BaseH - 66), w - S(2 * Pad), S(LogH - 16));
            if (page == Page.Done) primary.Focus();
            Invalidate();
        }

        int BodyHeight()
        {
            if (string.IsNullOrEmpty(body) || page == Page.Progress) return 0;
            return TextRenderer.MeasureText(body, bodyFont, new Size(ClientSize.Width - S(2 * Pad), 10000),
                TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix).Height;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            int w = ClientSize.Width;
            if (Native.WindowsBuild > 0 && Native.WindowsBuild < 22000)
                using (Pen border = new Pen(t.Line)) g.DrawRectangle(border, 0, 0, w - 1, ClientSize.Height - 1); // Windows 10 没有系统画的边

            Draw.Orb(g, S(Pad) + 5 * s, S(31), s);
            TextRenderer.DrawText(g, L.AppName, brandFont, new Point(S(Pad + 18), S(21)), t.Text, TextFormatFlags.NoPrefix);

            int titleX = S(Pad);
            if (page == Page.Done || page == Page.Failed)
            {
                RectangleF icon = new RectangleF(S(Pad), S(68), 24 * s, 24 * s);
                Draw.StepIcon(g, icon, t, page == Page.Done ? "done" : "failed", 0, s);
                titleX += S(34);
            }
            TextRenderer.DrawText(g, title, titleFont, new Point(titleX, S(62)), t.Text, TextFormatFlags.NoPrefix);

            if (page == Page.Progress) PaintSteps(g, w);
            else if (!string.IsNullOrEmpty(body))
                TextRenderer.DrawText(g, body, bodyFont, new Rectangle(S(Pad), S(102), w - S(2 * Pad), S(240)), t.Text2,
                    TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix);
        }

        void PaintSteps(Graphics g, int w)
        {
            int y = S(108);
            for (int i = 0; i < steps.Length; i++)
            {
                string state = i < current ? "done" : i == current ? (stepFailed ? "failed" : running ? "running" : "done") : "pending";
                RectangleF icon = new RectangleF(S(Pad), y + 3 * s, 16 * s, 16 * s);
                Draw.StepIcon(g, icon, t, state, phase, s);
                Color color = i == current ? t.Text : i < current ? t.Text2 : t.Text3;
                TextRenderer.DrawText(g, steps[i], bodyFont, new Point(S(Pad + 28), y), color, TextFormatFlags.NoPrefix);
                y += S(32);
                if (i == current && running)
                {
                    string line = detail;
                    double seconds = (DateTime.Now - stepStarted).TotalSeconds;
                    if (seconds >= 5) line += (line.Length > 0 ? "  ·  " : "") + L.T("已用 ", "elapsed ") + ((int)seconds / 60) + ":" + ((int)seconds % 60).ToString("00");
                    TextRenderer.DrawText(g, line, smallFont, new Rectangle(S(Pad + 28), y - S(9), w - S(2 * Pad + 28), S(20)), t.Text3,
                        TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine);
                    y += S(16);
                }
            }
            if (!running) return;
            // 进度条：知道进度就按进度画；不知道就一段渐变来回走
            RectangleF track = new RectangleF(S(Pad), S(BaseH - 92), w - S(2 * Pad), 3 * s);
            using (GraphicsPath path = Draw.Round(track, 1.5f * s))
            using (SolidBrush brush = new SolidBrush(t.Control))
                g.FillPath(brush, path);
            RectangleF fill;
            if (progress >= 0)
                fill = new RectangleF(track.X, track.Y, Math.Max(track.Height, (float)(track.Width * Math.Min(1, progress))), track.Height);
            else
            {
                float seg = track.Width * 0.32f;
                float x = track.X - seg + (track.Width + seg) * phase;
                fill = RectangleF.Intersect(new RectangleF(x, track.Y, seg, track.Height), track);
            }
            if (fill.Width > 0)
                using (GraphicsPath path = Draw.Round(fill, 1.5f * s))
                    Draw.Gradient(g, path, new RectangleF(fill.X - 1, fill.Y, fill.Width + 2, fill.Height), Theme.A, Theme.B);
        }

        // ---------- 检查界面用：把每个页面画成图片 ----------

        public static void RenderPages(string dir)
        {
            Directory.CreateDirectory(dir);
            foreach (bool dark in new[] { true, false })
            {
                foreach (string name in new[] { "welcome", "progress", "progress-log", "done", "failed", "uninstall" })
                {
                    using (SetupForm form = new SetupForm(new Options { Mode = name == "uninstall" ? Mode.Uninstall : Mode.Install }, dark))
                    {
                        form.Preview(name);
                        form.StartPosition = FormStartPosition.Manual;
                        form.Location = new Point(-20000, -20000);
                        form.ShowInTaskbar = false;
                        form.Show();
                        Application.DoEvents();
                        using (Bitmap bitmap = new Bitmap(form.Width, form.Height))
                        {
                            form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, form.Size));
                            bitmap.Save(Path.Combine(dir, (dark ? "dark-" : "light-") + name + ".png"), ImageFormat.Png);
                        }
                        form.Close();
                    }
                }
            }
        }

        void Preview(string name)
        {
            if (name == "welcome")
            {
                title = L.T("安装超级助手", "Install Super Aide");
                body = WelcomeBody();
                page = Page.Welcome;
                primary.Text = L.T("安装", "Install");
                secondary.Text = L.T("取消", "Cancel");
                option2.Checked = true;
            }
            else if (name.StartsWith("progress"))
            {
                ShowProgress(L.T("正在安装超级助手", "Installing Super Aide"), Setup.InstallSteps);
                current = 3;
                detail = L.T("国内镜像 mirrors.aliyun.com：", "mirror mirrors.aliyun.com: ") + "Prepared 41 packages in 1m 12s";
                stepStarted = DateTime.Now.AddSeconds(-151);
                phase = 0.45f;
                if (name == "progress-log")
                {
                    foreach (string line in new[] { L.T("能连上：GitHub 否，PyPI 是", "Reachable: GitHub no, PyPI yes"),
                                                    L.T("uv 0.12.23 下载好了（mirrors.aliyun.com）", "Got uv 0.12.23 (mirrors.aliyun.com)"),
                                                    L.T("下载好了超级助手 0.2.0（PyPI）", "Downloaded Super Aide 0.2.0 (PyPI)"),
                                                    L.T("---- 安装运行环境：官方源", "---- Installing the runtime: official index"),
                                                    "Resolved 57 packages in 3.79s", "Downloading pyside6-addons (160.4MiB)" })
                        log.AppendText(line + "\r\n");
                    ToggleLog();
                }
                timer.Stop();
            }
            else if (name == "done")
            {
                steps = Setup.InstallSteps;
                ShowDone(L.T("安装完成", "Installed"), DoneBody());
            }
            else if (name == "failed")
                ShowFailed(FailedTitle(false), L.T("运行环境没装上：", "The runtime didn't install: ") +
                           "error: Failed to fetch: `https://pypi.org/simple/pyside6/`" +
                           L.T("。检查网络（或代理）后点重试。", ". Check your network (or proxy) and click Retry."), null);
            else if (name == "uninstall")
                ShowConfirmUninstall();
            Relayout();
        }
    }
}
