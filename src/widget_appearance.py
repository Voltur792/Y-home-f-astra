"""Windows identity and a cached image fitted to the desktop canvas."""
import ctypes
from pathlib import Path


def set_application_identity():
    shell = ctypes.WinDLL('shell32')
    shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
    shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    shell.SetCurrentProcessExplicitAppUserModelID('Voltur.YandexSmartHome.DesktopWidgets')


def set_window_icon(root):
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user.LoadImageW.restype = wintypes.HANDLE
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.restype = ctypes.c_ssize_t
    path = str(Path(__file__).resolve().parent.parent / 'ui/desktop-widget.ico')
    root.iconbitmap(default=path)
    root.iconbitmap(path)
    hwnd = user.GetParent(root.winfo_id()) or root.winfo_id()
    handles = []
    for kind, size in ((0, 16), (1, 32)):
        icon = user.LoadImageW(None, path, 1, size, size, 0x10)
        if not icon:
            raise ctypes.WinError(ctypes.get_last_error())
        user.SendMessageW(hwnd, 0x80, kind, icon)  # WM_SETICON
        handles.append(icon)
    return handles


class BackgroundImage:
    def __init__(self):
        self.key = None
        self.photo = None

    def get(self, master, path, size, color):
        if not path:
            self.key, self.photo = None, None
            return None
        from PIL import Image, ImageOps, ImageTk
        file = Path(path)
        key = (path, file.stat().st_mtime_ns, size, color)
        if key != self.key:
            with Image.open(file) as image:
                fitted = ImageOps.fit(image.convert('RGBA'), size, method=Image.Resampling.LANCZOS)
            background = Image.new('RGBA', size, color)
            background.alpha_composite(fitted)
            self.photo = ImageTk.PhotoImage(background.convert('RGB'), master=master)
            self.key = key
        return self.photo
