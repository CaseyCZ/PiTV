using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class PiTVNativeDisk
{
    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint OPEN_EXISTING = 3;

    private const uint FSCTL_LOCK_VOLUME = 0x00090018;
    private const uint FSCTL_UNLOCK_VOLUME = 0x0009001C;
    private const uint FSCTL_DISMOUNT_VOLUME = 0x00090020;

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern SafeFileHandle CreateFile(
        string lpFileName,
        uint dwDesiredAccess,
        uint dwShareMode,
        IntPtr lpSecurityAttributes,
        uint dwCreationDisposition,
        uint dwFlagsAndAttributes,
        IntPtr hTemplateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool DeviceIoControl(
        SafeFileHandle hDevice,
        uint dwIoControlCode,
        IntPtr lpInBuffer,
        uint nInBufferSize,
        IntPtr lpOutBuffer,
        uint nOutBufferSize,
        out uint lpBytesReturned,
        IntPtr lpOverlapped);

    private static SafeFileHandle OpenHandle(string path, uint access)
    {
        SafeFileHandle handle = CreateFile(
            path,
            access,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            IntPtr.Zero,
            OPEN_EXISTING,
            0,
            IntPtr.Zero);

        if (handle.IsInvalid)
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error);
        }

        return handle;
    }

    public static FileStream Open(string path, bool writable)
    {
        uint access = GENERIC_READ | (writable ? GENERIC_WRITE : 0);
        SafeFileHandle handle = OpenHandle(path, access);

        return new FileStream(
            handle,
            writable ? FileAccess.ReadWrite : FileAccess.Read,
            1024 * 1024,
            false);
    }

    private static string NormalizeVolumePath(string path)
    {
        if (String.IsNullOrWhiteSpace(path))
            throw new ArgumentException("Volume path is empty.", "path");

        string p = path.Trim();

        // Drive-letter access path from Get-Partition, e.g. "E:\".
        if (p.Length >= 2 && Char.IsLetter(p[0]) && p[1] == ':')
            return @"\\.\" + Char.ToUpperInvariant(p[0]) + ":";

        // Volume GUID access path from Get-Partition/Get-Volume,
        // e.g. "\\?\Volume{GUID}\". CreateFile requires no trailing slash.
        if (p.StartsWith(@"\\?\Volume{", StringComparison.OrdinalIgnoreCase))
            return p.TrimEnd('\\');

        return p.TrimEnd('\\');
    }

    public static PiTVVolumeLock LockAndDismount(string volumePath)
    {
        string normalized = NormalizeVolumePath(volumePath);
        SafeFileHandle handle = OpenHandle(normalized, GENERIC_READ | GENERIC_WRITE);
        uint returned;

        if (!DeviceIoControl(handle, FSCTL_LOCK_VOLUME, IntPtr.Zero, 0, IntPtr.Zero, 0, out returned, IntPtr.Zero))
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, "FSCTL_LOCK_VOLUME failed for " + normalized);
        }

        if (!DeviceIoControl(handle, FSCTL_DISMOUNT_VOLUME, IntPtr.Zero, 0, IntPtr.Zero, 0, out returned, IntPtr.Zero))
        {
            int error = Marshal.GetLastWin32Error();
            DeviceIoControl(handle, FSCTL_UNLOCK_VOLUME, IntPtr.Zero, 0, IntPtr.Zero, 0, out returned, IntPtr.Zero);
            handle.Dispose();
            throw new Win32Exception(error, "FSCTL_DISMOUNT_VOLUME failed for " + normalized);
        }

        return new PiTVVolumeLock(handle, normalized);
    }

    public sealed class PiTVVolumeLock : IDisposable
    {
        private SafeFileHandle handle;
        private bool disposed;

        internal PiTVVolumeLock(SafeFileHandle handle, string path)
        {
            this.handle = handle;
            this.Path = path;
        }

        public string Path { get; private set; }

        public void Dispose()
        {
            if (disposed)
                return;

            disposed = true;
            try
            {
                if (handle != null && !handle.IsInvalid && !handle.IsClosed)
                {
                    uint returned;
                    DeviceIoControl(handle, FSCTL_UNLOCK_VOLUME, IntPtr.Zero, 0, IntPtr.Zero, 0, out returned, IntPtr.Zero);
                }
            }
            finally
            {
                if (handle != null)
                    handle.Dispose();
                handle = null;
            }
        }
    }
}
