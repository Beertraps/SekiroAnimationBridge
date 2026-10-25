using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace AnimationBridge {
    // Loaded by a dedicated STA PowerShell process, separately from Blender and Python.
    public static class NativePicker {
        const int Cancelled = unchecked((int)0x800704C7);
        const string EventPrefix = "Local\\SekiroAnimationBridge-PickerCancel-";
        delegate bool EnumWindowCallback(IntPtr window, IntPtr data);
        [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowCallback callback, IntPtr data);
        [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr window, StringBuilder text, int count);
        [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32.dll")] static extern IntPtr GetLastActivePopup(IntPtr owner);
        [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
        [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
        [DllImport("user32.dll")] static extern bool IsIconic(IntPtr window);
        [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window, int command);

        sealed class WindowOwner : IWin32Window {
            public IntPtr Handle { get; private set; }
            public WindowOwner(IntPtr handle) { Handle = handle; }
        }

        static bool IsBridgeWindow(IntPtr window) {
            if (window == IntPtr.Zero || !IsWindowVisible(window)) return false;
            var title = new StringBuilder(512);
            GetWindowText(window, title, title.Capacity);
            return title.ToString().IndexOf("Animation Bridge", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        static IntPtr FindOwner() {
            IntPtr active = GetForegroundWindow();
            if (IsBridgeWindow(active)) return active;
            IntPtr found = IntPtr.Zero;
            EnumWindows(delegate(IntPtr window, IntPtr data) {
                if (!IsBridgeWindow(window)) return true;
                found = window;
                return false;
            }, IntPtr.Zero);
            return found;
        }

        static string EventName(string requestId) {
            return EventPrefix + Guid.Parse(requestId).ToString("N");
        }

        public static bool Cancel(string requestId) {
            string name = EventName(requestId);
            // The initial picker may still be compiling or creating its window.
            for (int i = 0; i < 100; i++) {
                try {
                    using (var signal = EventWaitHandle.OpenExisting(name)) { signal.Set(); return true; }
                } catch (WaitHandleCannotBeOpenedException) { Thread.Sleep(25); }
            }
            return false;
        }

        static string ExistingFolder(string current) {
            if (String.IsNullOrWhiteSpace(current)) return "";
            try {
                string path = Path.GetFullPath(current);
                while (!String.IsNullOrEmpty(path)) {
                    if (Directory.Exists(path)) return path;
                    path = Path.GetDirectoryName(path);
                }
            } catch (ArgumentException) { } catch (NotSupportedException) { } catch (PathTooLongException) { }
            return "";
        }

        public static string[] Show(string kind, string current, string title, string filter, bool multiple, string requestId) {
            using (var mutex = new Mutex(false, "Local\\SekiroAnimationBridge-NativePicker")) {
                bool acquired;
                try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) throw new InvalidOperationException("A Browse window is already open. Finish or cancel that selection first.");
                try {
                    return ShowOwned(kind, current, title, filter, multiple, requestId);
                } finally { mutex.ReleaseMutex(); }
            }
        }

        static string[] ShowOwned(string kind, string current, string title, string filter, bool multiple, string requestId) {
            using (var signal = new EventWaitHandle(false, EventResetMode.ManualReset, EventName(requestId)))
            using (var proxy = new Form())
            using (var timer = new System.Windows.Forms.Timer()) {
                // Own the proxy by the real bridge window. Only the proxy is modal, so
                // the page's Cancel button remains usable. Native dialogs inherit its
                // topmost position and cannot disappear behind the browser.
                IntPtr browser = FindOwner();
                proxy.ShowInTaskbar = false;
                proxy.FormBorderStyle = FormBorderStyle.None;
                proxy.StartPosition = FormStartPosition.CenterScreen;
                proxy.Size = new Size(1, 1);
                proxy.Opacity = 0;
                proxy.TopMost = true;
                if (browser != IntPtr.Zero) {
                    if (IsIconic(browser)) ShowWindow(browser, 9);
                    proxy.Show(new WindowOwner(browser));
                } else { proxy.Show(); }
                proxy.Activate();
                SetForegroundWindow(proxy.Handle);

                IFileOpenDialog folderDialog = null;
                bool timedOut = false;
                DateTime deadline = DateTime.UtcNow.AddMinutes(5);
                timer.Interval = 100;
                timer.Tick += delegate {
                    bool expired = DateTime.UtcNow >= deadline;
                    if (!expired && !signal.WaitOne(0)) return;
                    timedOut = expired;
                    if (folderDialog != null) { folderDialog.Close(Cancelled); }
                    else {
                        IntPtr popup = GetLastActivePopup(proxy.Handle);
                        if (popup != IntPtr.Zero && popup != proxy.Handle) PostMessage(popup, 0x0010, IntPtr.Zero, IntPtr.Zero);
                    }
                };
                timer.Start();
                try {
                    string folder = ExistingFolder(current);
                    string[] result;
                    if (kind == "folder") {
                        // Modern Explorer folder picker; avoids the legacy shell tree
                        // used by .NET Framework's FolderBrowserDialog.
                        folderDialog = (IFileOpenDialog)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")));
                        folderDialog.SetOptions(0x20 | 0x40 | 0x800 | 0x8 | 0x2000000);
                        folderDialog.SetTitle(title);
                        if (!String.IsNullOrEmpty(folder)) {
                            IShellItem initial;
                            Guid iid = typeof(IShellItem).GUID;
                            int hr = SHCreateItemFromParsingName(folder, IntPtr.Zero, ref iid, out initial);
                            if (hr >= 0) {
                                try { folderDialog.SetFolder(initial); } finally { Marshal.ReleaseComObject(initial); }
                            }
                        }
                        int status = folderDialog.Show(proxy.Handle);
                        if (status == Cancelled) result = new string[0];
                        else {
                            Marshal.ThrowExceptionForHR(status);
                            IShellItem selected;
                            folderDialog.GetResult(out selected);
                            try {
                                IntPtr text;
                                selected.GetDisplayName(0x80058000, out text);
                                try { result = new[] { Marshal.PtrToStringUni(text) }; }
                                finally { Marshal.FreeCoTaskMem(text); }
                            } finally { Marshal.ReleaseComObject(selected); }
                        }
                    } else {
                        using (FileDialog dialog = kind == "save" ? (FileDialog)new SaveFileDialog() : new OpenFileDialog()) {
                            dialog.Title = title;
                            dialog.Filter = String.IsNullOrEmpty(filter) ? "All files (*.*)|*.*" : filter;
                            dialog.AutoUpgradeEnabled = true;
                            dialog.RestoreDirectory = true;
                            if (!String.IsNullOrEmpty(folder)) dialog.InitialDirectory = folder;
                            if (!String.IsNullOrEmpty(current) && !Directory.Exists(current)) dialog.FileName = Path.GetFileName(current);
                            var open = dialog as OpenFileDialog;
                            if (open != null) { open.Multiselect = multiple; open.CheckFileExists = true; }
                            var save = dialog as SaveFileDialog;
                            if (save != null) { save.AddExtension = true; save.OverwritePrompt = true; }
                            result = dialog.ShowDialog(proxy) == DialogResult.OK ? dialog.FileNames : new string[0];
                        }
                    }
                    if (timedOut) throw new TimeoutException("Browse timed out after five minutes. Open Browse again to retry.");
                    return result;
                } finally {
                    timer.Stop();
                    if (folderDialog != null) Marshal.ReleaseComObject(folderDialog);
                    // Hand the foreground back to the bridge before the proxy goes. The proxy is
                    // not a popup, so closing it while active can let Windows activate the next
                    // window in the Z order rather than its owner, and put another application
                    // over the bridge. Without the foreground, as after Cancel
                    // Browse in the page, the call changes nothing.
                    if (IsBridgeWindow(browser)) SetForegroundWindow(browser);
                    proxy.Close();
                }
            }
        }

        [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=true)]
        static extern int SHCreateItemFromParsingName(string path, IntPtr binding, ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out IShellItem item);

        [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IShellItem {
            void BindToHandler(IntPtr binding, ref Guid handler, ref Guid iid, out IntPtr result);
            void GetParent(out IShellItem parent);
            void GetDisplayName(uint kind, out IntPtr name);
            void GetAttributes(uint mask, out uint attributes);
            void Compare(IShellItem other, uint hint, out int order);
        }

        // Native vtable order is significant, including the unused methods.
        [ComImport, Guid("D57C7288-D4AD-4768-BE02-9D969532D960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IFileOpenDialog {
            [PreserveSig] int Show(IntPtr parent);
            void SetFileTypes(uint count, IntPtr filters);
            void SetFileTypeIndex(uint index);
            void GetFileTypeIndex(out uint index);
            void Advise(IntPtr events, out uint cookie);
            void Unadvise(uint cookie);
            void SetOptions(uint options);
            void GetOptions(out uint options);
            void SetDefaultFolder(IShellItem folder);
            void SetFolder(IShellItem folder);
            void GetFolder(out IShellItem folder);
            void GetCurrentSelection(out IShellItem item);
            void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
            void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
            void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
            void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
            void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
            void GetResult(out IShellItem item);
            void AddPlace(IShellItem folder, uint placement);
            void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
            void Close([MarshalAs(UnmanagedType.Error)] int result);
            void SetClientGuid(ref Guid guid);
            void ClearClientData();
            void SetFilter(IntPtr filter);
            void GetResults(out IntPtr items);
            void GetSelectedItems(out IntPtr items);
        }
    }
}
