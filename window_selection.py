"""Snapshot visible window bounds before showing the capture overlay."""
import math
from PySide6.QtCore import QRect


def logical_bounds(bounds, monitors):
    result = QRect()
    for native, logical in monitors:
        part = bounds.intersected(native)
        if part.isEmpty():
            continue
        sx, sy = logical.width()/native.width(), logical.height()/native.height()
        left = logical.left() + math.floor((part.left()-native.left())*sx)
        top = logical.top() + math.floor((part.top()-native.top())*sy)
        right = logical.left() + math.ceil((part.left()+part.width()-native.left())*sx)
        bottom = logical.top() + math.ceil((part.top()+part.height()-native.top())*sy)
        result = result.united(QRect(left, top, right-left, bottom-top))
    return result


def snapshot_windows(screens):
    import ctypes
    from ctypes import wintypes
    try:
        user = ctypes.WinDLL('user32', use_last_error=True)
        dwm = ctypes.WinDLL('dwmapi')
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD),('device',wintypes.WCHAR*32)]
        monitors = []
        def rect(r):
            return QRect(r.left,r.top,r.right-r.left,r.bottom-r.top)
        monitor_callback = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HANDLE,wintypes.HDC,ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE,ctypes.POINTER(MonitorInfo)]
        @monitor_callback
        def collect_monitor(handle, dc, bounds, data):
            info = MonitorInfo(); info.size = ctypes.sizeof(info)
            if user.GetMonitorInfoW(handle,ctypes.byref(info)):
                for screen in screens:
                    if screen.name().casefold() == info.device.casefold():
                        monitors.append((rect(info.monitor),screen.geometry()))
                        break
            return True
        user.EnumDisplayMonitors(None,None,collect_monitor,0)
        windows = []
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        for name in ('IsWindowVisible','IsIconic','GetWindowTextLengthW'):
            getattr(user,name).argtypes = [wintypes.HWND]
        user.GetWindowRect.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        @callback
        def collect_window(handle, data):
            if not user.IsWindowVisible(handle) or user.IsIconic(handle) or not user.GetWindowTextLengthW(handle):
                return True
            cloaked = wintypes.DWORD()
            if dwm.DwmGetWindowAttribute(handle,14,ctypes.byref(cloaked),ctypes.sizeof(cloaked)) == 0 and cloaked.value:
                return True
            bounds = wintypes.RECT()
            if dwm.DwmGetWindowAttribute(handle,9,ctypes.byref(bounds),ctypes.sizeof(bounds)) != 0:
                if not user.GetWindowRect(handle,ctypes.byref(bounds)):
                    return True
            logical = logical_bounds(rect(bounds),monitors)
            if logical.width() >= 30 and logical.height() >= 30:
                windows.append(logical)
            return True
        user.EnumWindows(collect_window,0)
        return windows
    except (AttributeError,OSError,ctypes.ArgumentError):
        return []
