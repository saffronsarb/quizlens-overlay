import os
import sys
import ctypes
from PIL import Image, ImageGrab
import tkinter as tk

# Enable per-monitor DPI awareness on Windows for pixel-perfect coordinates
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

try:
    import mss
    import mss.tools
    HAS_MSS = True
except ImportError:
    mss = None
    HAS_MSS = False

def capture_fullscreen() -> Image.Image | None:
    """Capture the full active screen."""
    # Attempt mss first
    if HAS_MSS and mss is not None:
        try:
            with mss.MSS() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(monitor)
                return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception:
            pass

    # Fallback to PIL ImageGrab
    try:
        return ImageGrab.grab(all_screens=True)
    except Exception:
        try:
            return ImageGrab.grab()
        except Exception as e:
            print(f"Fullscreen grab failed: {e}")
            return None

def capture_region(bbox: tuple[int, int, int, int]) -> Image.Image | None:
    """
    Capture a specific region (left, top, right, bottom).
    """
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    height = y2 - y1

    if width < 5 or height < 5:
        return None

    if HAS_MSS and mss is not None:
        try:
            with mss.MSS() as sct:
                region = {"left": int(x1), "top": int(y1), "width": int(width), "height": int(height)}
                sct_img = sct.grab(region)
                return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception:
            pass

    # Fallback to ImageGrab
    try:
        return ImageGrab.grab(bbox=(x1, y1, x2, y2))
    except Exception as e:
        print(f"Region grab failed: {e}")
        return None

def capture_from_clipboard() -> Image.Image | None:
    """
    Fetch an image directly from the Windows clipboard.
    Useful with Windows' native Snipping Tool (Win+Shift+S).
    """
    try:
        content = ImageGrab.grabclipboard()
        if isinstance(content, Image.Image):
            return content
        elif isinstance(content, list) and len(content) > 0:
            # Clipboard might contain a list of file paths
            file_path = content[0]
            if os.path.exists(file_path) and file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                return Image.open(file_path)
    except Exception as e:
        print(f"Clipboard grab error: {e}")
    return None


class SnipSelector:
    """
    A full-screen semi-transparent overlay that lets the user
    click and drag a selection rectangle to snip a region of the screen.
    """
    def __init__(self, on_snip_complete):
        self.on_snip_complete = on_snip_complete
        self.start_x: int = 0
        self.start_y: int = 0
        self.current_x: int = 0
        self.current_y: int = 0
        self.rect_id = None

        self.root = tk.Toplevel()
        self.root.attributes("-alpha", 0.3)
        self.root.attributes("-topmost", True)
        self.root.attributes("-fullscreen", True)
        self.root.config(cursor="cross")

        # Capture total virtual screen width & height
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        self.canvas = tk.Canvas(self.root, cursor="cross", bg="#111111", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Instructions banner at top center
        self.canvas.create_text(
            screen_w // 2, 40,
            text="✂️ Drag mouse to select quiz question | ESC to cancel",
            fill="#FFFFFF",
            font=("Segoe UI", 14, "bold")
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", lambda e: self._cancel())

        self.root.focus_force()

    def _on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#00E5FF", width=2, fill="#00E5FF", stipple="gray25"
        )

    def _on_drag(self, event):
        self.current_x = event.x
        self.current_y = event.y
        if self.rect_id:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, self.current_x, self.current_y)

    def _on_release(self, event):
        self.current_x = event.x
        self.current_y = event.y

        x1 = min(self.start_x, self.current_x)
        y1 = min(self.start_y, self.current_y)
        x2 = max(self.start_x, self.current_x)
        y2 = max(self.start_y, self.current_y)

        # Close the snip overlay window
        self.root.destroy()

        if (x2 - x1) > 10 and (y2 - y1) > 10:
            # Capture the selected region
            img = capture_region((x1, y1, x2, y2))
            self.on_snip_complete(img)
        else:
            self.on_snip_complete(None)

    def _cancel(self):
        self.root.destroy()
        self.on_snip_complete(None)

