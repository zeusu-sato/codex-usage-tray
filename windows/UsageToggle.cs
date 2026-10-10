using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string backend = Path.Combine(Application.StartupPath, "backend", "CodexUsageBackend.exe");
        string python = null;
        string dataDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CodexUsageTray");
        bool startInTray = false;
        try
        {
            for (int i = 0; i < args.Length; i++)
            {
                if ((args[i] == "--backend" || args[i] == "--python" || args[i] == "--data-dir") && i + 1 < args.Length)
                {
                    string option = args[i];
                    string path = Path.GetFullPath(args[++i]);
                    if (option == "--backend") backend = path;
                    else if (option == "--python") python = path;
                    else dataDirectory = path;
                }
                else if (args[i] == "--tray") startInTray = true;
                else throw new ArgumentException("起動オプションを確認してください。");
            }
            // Different extracted versions share one resident instance for the same user data.
            dataDirectory = CanonicalPaths.DataDirectory(dataDirectory);
            string instanceName;
            using (SHA256 hash = SHA256.Create())
                instanceName = "Local\\CodexUsageTray." + BitConverter.ToString(hash.ComputeHash(
                    Encoding.UTF8.GetBytes(Path.GetFullPath(dataDirectory).TrimEnd(Path.DirectorySeparatorChar).ToUpperInvariant()))).Replace("-", "");
            bool firstInstance;
            using (Mutex instance = new Mutex(true, instanceName, out firstInstance))
            using (EventWaitHandle showWindow = new EventWaitHandle(false, EventResetMode.AutoReset, instanceName + ".Show"))
            {
                if (!firstInstance)
                {
                    if (!startInTray) showWindow.Set();
                    return;
                }
                try
                {
                    using (UsageTrayHost form = new UsageTrayHost(python, backend, dataDirectory, startInTray, showWindow))
                    {
                        form.Prepare();
                        Application.Run(form);
                    }
                }
                finally { instance.ReleaseMutex(); }
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Codex Usage Tray", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}

internal static class CanonicalPaths
{
    public static string DataDirectory(string path)
    {
        path = Path.GetFullPath(path);
        Directory.CreateDirectory(path);
        return Existing(path);
    }

    public static string Existing(string path)
    {
        path = Path.GetFullPath(path);
        // Open with no data access, sharing reads/writes/deletion. BACKUP_SEMANTICS
        // allows directory handles; following links gives the same target as Python resolve().
        using (Microsoft.Win32.SafeHandles.SafeFileHandle handle = CreateFile(path, 0, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero))
        {
            if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            StringBuilder buffer = new StringBuilder(512);
            for (int attempt = 0; attempt < 3; attempt++)
            {
                uint length = GetFinalPathNameByHandle(handle, buffer, (uint)buffer.Capacity, 0);
                if (length == 0) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                if (length >= buffer.Capacity)
                {
                    buffer = new StringBuilder(checked((int)length + 1));
                    continue;
                }
                string final = buffer.ToString();
                if (final.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) final = @"\\" + final.Substring(8);
                else if (final.StartsWith(@"\\?\", StringComparison.Ordinal)) final = final.Substring(4);
                return Path.GetFullPath(final);
            }
            throw new IOException("保存先の実体パスを確認できませんでした。");
        }
    }

    [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern Microsoft.Win32.SafeHandles.SafeFileHandle CreateFile(string name, uint access, uint share,
        IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", EntryPoint = "GetFinalPathNameByHandleW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(Microsoft.Win32.SafeHandles.SafeFileHandle handle,
        StringBuilder path, uint length, uint flags);
}

internal static class StartupShortcuts
{
    public static bool Matches(string path, string target, string arguments, string description)
    {
        object instance = new ShellLink();
        try
        {
            ((System.Runtime.InteropServices.ComTypes.IPersistFile)instance).Load(path, 0);
            IShellLinkW link = (IShellLinkW)instance;
            StringBuilder actualTarget = new StringBuilder(32768);
            StringBuilder actualArguments = new StringBuilder(32768);
            StringBuilder actualDescription = new StringBuilder(1024);
            link.GetPath(actualTarget, actualTarget.Capacity, IntPtr.Zero, 4);
            link.GetArguments(actualArguments, actualArguments.Capacity);
            link.GetDescription(actualDescription, actualDescription.Capacity);
            return String.Equals(actualDescription.ToString(), description, StringComparison.Ordinal)
                && String.Equals(Path.GetFileName(actualTarget.ToString()), Path.GetFileName(target), StringComparison.OrdinalIgnoreCase)
                && String.Equals(actualArguments.ToString(), arguments, StringComparison.OrdinalIgnoreCase);
        }
        finally { Marshal.FinalReleaseComObject(instance); }
    }

    public static void Save(string path, string target, string arguments, string workingDirectory, string description)
    {
        object instance = new ShellLink();
        try
        {
            IShellLinkW link = (IShellLinkW)instance;
            link.SetPath(target);
            link.SetArguments(arguments);
            link.SetWorkingDirectory(workingDirectory);
            link.SetDescription(description);
            link.SetIconLocation(target, 0);
            link.SetShowCmd(7);
            ((System.Runtime.InteropServices.ComTypes.IPersistFile)instance).Save(path, true);
        }
        finally { Marshal.FinalReleaseComObject(instance); }
    }

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    private class ShellLink { }

    // Vtable order follows the Unicode Shell Link interface; no ANSI path conversion.
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellLinkW
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int length, IntPtr findData, uint flags);
        void GetIDList(out IntPtr itemList);
        void SetIDList(IntPtr itemList);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder description, int length);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string description);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder directory, int length);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string directory);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder arguments, int length);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);
        void GetHotkey(out short hotkey);
        void SetHotkey(short hotkey);
        void GetShowCmd(out int command);
        void SetShowCmd(int command);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int length, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        void Resolve(IntPtr owner, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }
}

