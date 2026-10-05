"""Draggable desktop canvas. The parent owns settings and telemetry."""
import ctypes
import queue
import sys
import threading
import tkinter as tk
from .timer_integration import integration_call
from .widget_appearance import BackgroundImage, set_application_identity, set_window_icon


def run_window(ident, session):
    set_application_identity()
    root = tk.Tk()
    root.withdraw()
    root.title('Умный дом · Виджет')
    root.overrideredirect(True)
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    close_button = tk.Button(root, text='×', relief='flat', borderwidth=0, takefocus=True)
    stopping = threading.Event()
    messages, requests = queue.Queue(), queue.Queue()
    background = BackgroundImage()
    appearance, positioned, last_snapshot = None, False, None
    icon_handles, drag = [], {}

    def call(method, **params):
        return integration_call('home', method, id=ident, session=session, **params)

    def worker():
        while not stopping.is_set():
            try:
                while True:
                    try:
                        params = requests.get_nowait()
                    except queue.Empty:
                        break
                    call('widget_report', **params)
                    if params.get('closed'):
                        messages.put({'closed': True})
                        return
                messages.put(call('widget_snapshot'))
            except Exception:
                messages.put({'error': 'Нет связи с Astra · показания устарели'})
            stopping.wait(.5)

    def close():
        close_button.configure(state='disabled')
        requests.put({'closed': True})

    def begin(event):
        drag.update(x=event.x_root-root.winfo_x(), y=event.y_root-root.winfo_y())

    def position(x, y):
        # Native coordinates support monitors to the left of the primary screen.
        from ctypes import wintypes
        user = ctypes.WinDLL('user32')
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        hwnd = user.GetParent(root.winfo_id()) or root.winfo_id()
        user.SetWindowPos(hwnd, None, x, y, 0, 0, 0x15)

    def move(event):
        if drag:
            position(event.x_root-drag['x'], event.y_root-drag['y'])

    def end(event):
        requests.put({'x': root.winfo_x(), 'y': root.winfo_y()})
        drag.clear()

    canvas.bind('<ButtonPress-1>', begin)
    canvas.bind('<B1-Motion>', move)
    canvas.bind('<ButtonRelease-1>', end)
    root.protocol('WM_DELETE_WINDOW', close)
    close_button.configure(command=close)

    def rounded(settings):
        from ctypes import wintypes
        user = ctypes.WinDLL('user32')
        gdi = ctypes.WinDLL('gdi32')
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
        gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        gdi.CreateRoundRectRgn.restype = wintypes.HANDLE
        gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        hwnd = user.GetParent(root.winfo_id()) or root.winfo_id()
        region = gdi.CreateRoundRectRgn(0, 0, root.winfo_width()+1, root.winfo_height()+1, 24, 24) if settings['rounded'] else None
        if not user.SetWindowRgn(hwnd, region, True) and region:
            gdi.DeleteObject(region)

    def apply(snapshot):
        nonlocal appearance, positioned, last_snapshot, icon_handles
        settings = snapshot['settings']
        if not settings['enabled']:
            stopping.set()
            root.destroy()
            return
        if snapshot == last_snapshot:
            return
        last_snapshot = snapshot
        bg, fg, accent, font = (settings[k] for k in ('background', 'foreground', 'accent', 'font_size'))
        width = settings['width']
        root.title('Умный дом · ' + settings['title'])
        canvas.configure(bg=bg)
        close_button.configure(bg=bg, fg=fg, activebackground=bg, activeforeground=accent, font=('Segoe UI', font))
        canvas.delete('all')
        title = canvas.create_text(12, 10, anchor='nw', width=width-60, text=settings['title'], fill=fg, font=('Segoe UI', font, 'bold'))
        canvas.create_window(width-25, 20, window=close_button, width=26, height=26)
        y = max(42, canvas.bbox(title)[3]+12)
        label_width = int((width-34)*.55)
        for row in snapshot['rows']:
            label = canvas.create_text(12, y, anchor='nw', width=label_width, text=row['label'], fill=fg, font=('Segoe UI', font))
            value = canvas.create_text(width-12, y, anchor='ne', justify='right', width=width-34-label_width,
                text=row['text'] + (' *' if row.get('stale') else ''), fill=fg, font=('Segoe UI', font, 'bold'))
            y = max(canvas.bbox(label)[3], canvas.bbox(value)[3])+5
            if settings['bars'] and row.get('progress') is not None:
                canvas.create_rectangle(12, y, width-12, y+4, fill=bg, outline=accent)
                canvas.create_rectangle(12, y, 12+(width-24)*row['progress']/100, y+4, fill=accent, outline='')
                y += 8
            y += 9
        status = canvas.create_text(12, y, anchor='nw', width=width-24, fill=fg, font=('Segoe UI', max(9, font-3)), tags='status', text=(
            'Нет связи с Яндексом · показания устарели' if snapshot.get('device_error') else
            'Обновлено ' + snapshot['updated'] if snapshot.get('updated') else 'Показатели компьютера'))
        height = max(100, canvas.bbox(status)[3]+10)
        try:
            photo = background.get(root, settings.get('background_path', ''), (width, height), bg)
            if photo:
                canvas.create_image(0, 0, anchor='nw', image=photo, tags='background')
                canvas.tag_lower('background')
        except (OSError, ValueError):
            canvas.itemconfigure('status', text='Картинка недоступна · показания обновляются')
        current = (width, height, settings['rounded'], settings['transparency'], settings['on_top'])
        if current != appearance:
            root.geometry(f'{width}x{height}')
            root.attributes('-alpha', 1-settings['transparency']/100)
            root.attributes('-topmost', settings['on_top'])
            root.update_idletasks()
            rounded(settings)
            appearance = current
        if not positioned:
            user = ctypes.windll.user32
            left, top = user.GetSystemMetrics(76), user.GetSystemMetrics(77)
            screen_width, screen_height = user.GetSystemMetrics(78), user.GetSystemMetrics(79)
            x, y = settings.get('x'), settings.get('y')
            if x is None or y is None or not (left <= x <= left+screen_width-80 and top <= y <= top+screen_height-40):
                x, y = max(left, root.winfo_screenwidth()-width-24), max(top, 40)
            root.deiconify()
            root.update_idletasks()
            icon_handles = set_window_icon(root)
            position(x, y)
            rounded(settings)
            positioned = True

    def tick():
        nonlocal last_snapshot
        latest = None
        while True:
            try:
                latest = messages.get_nowait()
            except queue.Empty:
                break
        if latest:
            if latest.get('closed'):
                stopping.set(); root.destroy(); return
            if latest.get('error'):
                last_snapshot = None
                canvas.itemconfigure('status', text=latest['error'])
                if str(close_button['state']) == 'disabled':
                    stopping.set(); root.destroy(); return
            else:
                apply(latest)
                if stopping.is_set():
                    return
        root.after(100, tick)

    threading.Thread(target=worker, daemon=True).start()
    root.after(100, tick)
    root.mainloop()
    stopping.set()
    from ctypes import wintypes
    user = ctypes.WinDLL('user32')
    user.DestroyIcon.argtypes = [wintypes.HICON]
    for handle in icon_handles:
        user.DestroyIcon(handle)


if __name__ == '__main__':
    run_window(sys.argv[1], sys.argv[2])
