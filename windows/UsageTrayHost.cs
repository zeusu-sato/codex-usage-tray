using System;
using System.Drawing;
using System.Threading;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal sealed class UsageTrayHost : Form
{
    readonly TabControl tabs = new TabControl();
    readonly UsageToggleForm[] views = new UsageToggleForm[2];
    readonly EventWaitHandle[] childEvents = new EventWaitHandle[2];
    readonly EventWaitHandle wake;
    RegisteredWaitHandle wakeWait;
    bool showRequested;
    bool exiting;

    public UsageTrayHost(string python, string backend, string data, bool tray, EventWaitHandle show)
    {
        wake = show;
        showRequested = !tray;
        Text = "Codex + Claude Usage";
        Name = "UsageTrayHost";
        Font = new Font("Yu Gothic UI", 10.5F);
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96,96);
        ClientSize = new Size(480, Math.Min(790, Screen.PrimaryScreen.WorkingArea.Height - 90));
        MinimumSize = new Size(440, 420);
        StartPosition = FormStartPosition.CenterScreen;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        tabs.Dock = DockStyle.Fill;
        tabs.Name = "ProviderTabs";
        Controls.Add(tabs);
        for (int i=0;i<views.Length;i++)
        {
            int index=i;
            string provider=i==0?"codex":"claude";
            var page = new TabPage(i==0?"Codex / GPT":"Claude Code");
            page.BackColor = Color.FromArgb(247,249,250);
            tabs.TabPages.Add(page);
            childEvents[i] = new EventWaitHandle(false,EventResetMode.AutoReset);
            var view=new UsageToggleForm(python,backend,data,false,childEvents[i],provider);
            views[i]=view;
            view.TopLevel=false;
            view.FormBorderStyle=FormBorderStyle.None;
            view.Dock=DockStyle.Fill;
            view.HostOpen=delegate { OpenProvider(index); };
            view.HostExit=delegate { exiting=true; Close(); };
            page.Controls.Add(view);
            view.Show();
        }
        Activated += delegate { RefreshSelectedPolicy(); };
        tabs.SelectedIndexChanged += delegate { RefreshSelectedPolicy(); };
        FormClosing+=delegate(object sender,FormClosingEventArgs e) {
            if(e.CloseReason==CloseReason.UserClosing&&!exiting){e.Cancel=true;showRequested=false;Hide();}
        };
    }
    public void Prepare()
    {
        var handle=Handle;
        foreach(var view in views) view.Prepare();
        wakeWait=ThreadPool.RegisterWaitForSingleObject(wake,delegate {
            try { BeginInvoke(new Action(delegate { OpenProvider(tabs.SelectedIndex); })); }
            catch(InvalidOperationException){}
        },null,Timeout.Infinite,false);
    }
    protected override void SetVisibleCore(bool value){base.SetVisibleCore(value&&showRequested);}
    void RefreshSelectedPolicy()
    {
        if(exiting || IsDisposed || Disposing) return;
        int index = tabs.SelectedIndex;
        if(index >= 0 && index < views.Length && views[index] != null) views[index].RefreshPolicy();
    }
    void OpenProvider(int index)
    {
        if(IsDisposed||exiting)return;
        showRequested=true;
        tabs.SelectedIndex=index;
        Show();
        WindowState=FormWindowState.Normal;
        ShowWindow(Handle,9);
        SetForegroundWindow(Handle);
        Activate();BringToFront();
        RefreshSelectedPolicy();
    }
    protected override void Dispose(bool disposing)
    {
        if(disposing){exiting=true;if(wakeWait!=null)wakeWait.Unregister(null);
            foreach(var view in views)if(view!=null)view.Dispose();
            foreach(var item in childEvents)if(item!=null)item.Dispose();}
        base.Dispose(disposing);
    }
    [DllImport("user32.dll")]static extern bool ShowWindow(IntPtr handle,int command);
    [DllImport("user32.dll")]static extern bool SetForegroundWindow(IntPtr handle);
}
