import os
import sys
from pathlib import Path
import ctypes
from ctypes import wintypes
import time

# Ensure local modules can always be imported regardless of execution working directory
CURRENT_DIR = str(Path(__file__).parent.resolve())
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image

from config_manager import load_config, save_config
from quiz_solver import QuizSolver
from screen_capture import capture_fullscreen, capture_region, capture_from_clipboard, SnipSelector

# Attempt to import pynput for global hotkeys
try:
    from pynput import keyboard as pynput_keyboard
    HAS_PYNPUT = True
except ImportError:
    pynput_keyboard = None
    HAS_PYNPUT = False

# Windows API constants for removing from Taskbar
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

# Color key for 100% ghost transparency on Windows
CHROMA_KEY = "#000001"

def set_windows_clipboard(text: str) -> bool:
    """Set Windows system clipboard directly via Win32 API for rock-solid reliability across all apps."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.CloseClipboard.restype = wintypes.BOOL

        GMEM_MOVEABLE = 0x0002
        CF_UNICODETEXT = 13

        opened = False
        for _ in range(10):
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.01)
        if not opened:
            return False

        try:
            user32.EmptyClipboard()
            encoded = text.encode("utf-16le") + b"\x00\x00"
            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
            if not h_mem:
                return False
            ptr = kernel32.GlobalLock(h_mem)
            if not ptr:
                kernel32.GlobalFree(h_mem)
                return False
            ctypes.memmove(ptr, encoded, len(encoded))
            kernel32.GlobalUnlock(h_mem)
            user32.SetClipboardData(CF_UNICODETEXT, h_mem)
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False

class QuizOverlayApp:
    def __init__(self):
        self.config = load_config()
        provider = self.config.get("provider", "ollama")
        base_url = self.config.get(f"{provider}_base_url", "http://localhost:11434/v1")
        enable_fallback = self.config.get("auto_fallback_ollama", True)
        fallback_model = self.config.get("ollama_model", "llava")
        fallback_base_url = self.config.get("ollama_base_url", "http://localhost:11434/v1")

        self.solver = QuizSolver(
            provider=provider,
            api_key=self.config.get("api_key", ""),
            model=self.config.get("model", "llama3.2-vision"),
            base_url=base_url,
            enable_fallback=enable_fallback,
            fallback_model=fallback_model,
            fallback_base_url=fallback_base_url
        )

        # Asynchronously ensure local Ollama is active if configured or used as fallback
        if provider == "ollama" or enable_fallback:
            threading.Thread(target=self.solver._ensure_ollama_running, daemon=True).start()

        # 1. Root Tkinter window: toolwindow + withdrawn
        self.root = tk.Tk()
        try:
            self.root.wm_attributes("-toolwindow", True)
        except Exception:
            pass
        self.root.withdraw()

        # 2. Main overlay: Borderless Toplevel window
        self.win = tk.Toplevel(self.root)
        self.win.withdraw()  # Withdraw before applying styles to prevent initial taskbar registration
        try:
            self.win.wm_attributes("-toolwindow", True)
        except Exception:
            pass
        self.win.title("QuizLens Overlay")

        # Minimalist Neutral Palette
        self.COLOR_BG = "#0D0D0E"
        self.COLOR_HEADER = "#141416"
        self.COLOR_SURFACE = "#111113"
        self.COLOR_BORDER = "#222225"
        self.COLOR_BTN = "#1A1A1D"
        self.COLOR_BTN_HOVER = "#2A2A2E"
        self.COLOR_TEXT = "#FAFAFA"
        self.COLOR_TEXT_DIM = "#A1A1AA"
        self.COLOR_MUTED = "#66666E"

        # State tracking
        self.is_ghost_mode = self.config.get("glass_mode", False)
        self.is_click_through = self.config.get("click_through", False)
        self.is_visible = True
        self.is_solving = False
        self.last_answer = ""
        self.last_copy_text = ""
        self.last_explanation = ""
        self.last_full_text = ""
        self.history = []
        self.history_index = -1
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Square Geometry (default 200x200)
        x = self.config.get("window_x", 120)
        y = self.config.get("window_y", 120)
        size = max(160, self.config.get("window_width", 200))
        self.win.geometry(f"{size}x{size}+{x}+{y}")
        self.win.overrideredirect(True)  # Borderless, no OS chrome
        self.win.attributes("-topmost", self.config.get("always_on_top", True))

        # Explicitly remove from Windows Taskbar and establish root ownership
        self._hide_from_windows_taskbar()

        # Apply transparency
        self._apply_transparency()

        # Build minimalist square UI
        self._build_ui()
        self._bind_events()
        self._start_global_hotkeys()

        # Deiconify after stealth styles and ownership are established
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", self.config.get("always_on_top", True))
        self._hide_from_windows_taskbar()

        # Check for API key or provider on first run
        if not self.config.get("api_key") and self.config.get("provider") != "ollama":
            self.root.after(700, self._show_first_run_hint)

    def _hide_from_windows_taskbar(self):
        """
        Permanently remove all windows from the Windows Taskbar and Alt+Tab pager.
        Ensures:
        1. Both root and overlay windows carry WS_EX_TOOLWINDOW and lack WS_EX_APPWINDOW.
        2. Root window is set as the Win32 OWNER (GWLP_HWNDPARENT) of the overlay window.
           Windows shell rules dictate that owned windows never receive a taskbar button.
        3. SetWindowPos with SWP_FRAMECHANGED forces Windows Explorer to re-evaluate the window.
        4. Configures SetWindowDisplayAffinity (WDA_EXCLUDEFROMCAPTURE) to hide the window
           completely from screen recording and screenshot tools.
        """
        try:
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            GWLP_HWNDPARENT = -8
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED

            self.root.update_idletasks()
            self.win.update_idletasks()

            root_hwnd = int(self.root.wm_frame(), 16) if hasattr(self.root, "wm_frame") else self.root.winfo_id()
            win_hwnd = int(self.win.wm_frame(), 16) if hasattr(self.win, "wm_frame") else self.win.winfo_id()

            # Set WS_EX_TOOLWINDOW on hidden root window
            if root_hwnd:
                r_style = user32.GetWindowLongW(root_hwnd, GWL_EXSTYLE)
                r_style = (r_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                user32.SetWindowLongW(root_hwnd, GWL_EXSTYLE, r_style)
                user32.SetWindowPos(root_hwnd, 0, 0, 0, 0, 0, flags)

            # Assign root as Win32 OWNER of overlay window (owned windows never appear on taskbar)
            if win_hwnd and root_hwnd:
                user32.SetWindowLongPtrW(win_hwnd, GWLP_HWNDPARENT, root_hwnd)

            # Set WS_EX_TOOLWINDOW on overlay window
            if win_hwnd:
                w_style = user32.GetWindowLongW(win_hwnd, GWL_EXSTYLE)
                w_style = (w_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                user32.SetWindowLongW(win_hwnd, GWL_EXSTYLE, w_style)
                user32.SetWindowPos(win_hwnd, 0, 0, 0, 0, 0, flags)

                # Exclude overlay from screen recordings and screen shares (OBS, Zoom, Discord, Meet)
                try:
                    user32.SetWindowDisplayAffinity(win_hwnd, 0x00000011)  # WDA_EXCLUDEFROMCAPTURE
                except Exception:
                    pass
        except Exception as e:
            print(f"Taskbar removal warning: {e}")

    def _apply_transparency(self):
        """Configure transparency: default 15-20% transparent or 100% ghost mode."""
        alpha = max(0.03, min(1.0, float(self.config.get("opacity", 0.18))))
        if self.is_ghost_mode:
            self.win.configure(bg=CHROMA_KEY)
            try:
                self.win.wm_attributes("-transparentcolor", CHROMA_KEY)
            except Exception:
                pass
            self.win.attributes("-alpha", alpha)
        else:
            try:
                self.win.wm_attributes("-transparentcolor", "")
            except Exception:
                pass
            self.win.configure(bg=self.COLOR_BG)
            self.win.attributes("-alpha", alpha)

    def _build_ui(self):
        """Construct the pure square answer HUD with zero clutter."""
        bg_color = CHROMA_KEY if self.is_ghost_mode else self.COLOR_BG
        header_color = CHROMA_KEY if self.is_ghost_mode else self.COLOR_HEADER
        surface_color = CHROMA_KEY if self.is_ghost_mode else self.COLOR_SURFACE

        # Outer Square Container with hairline border
        self.container = tk.Frame(
            self.win, bg=bg_color,
            highlightbackground=self.COLOR_BORDER,
            highlightthickness=1
        )
        self.container.pack(fill="both", expand=True)

        # Micro Header Strip (Height 18px)
        self.header_frame = tk.Frame(self.container, bg=header_color, height=18)
        self.header_frame.pack(fill="x", side="top")
        self.header_frame.pack_propagate(False)

        # Provider tag / Status on left
        provider_name = self.config.get("provider", "ollama").upper()
        self.lbl_status = tk.Label(
            self.header_frame,
            text=f" ⠇{provider_name}",
            bg=header_color,
            fg=self.COLOR_MUTED,
            font=("Segoe UI", 7),
            cursor="fleur"
        )
        self.lbl_status.pack(side="left", padx=2)

        # Micro Action Icons (Right side)
        # ✕ Close
        self.btn_close = tk.Label(
            self.header_frame, text="✕", bg=header_color, fg=self.COLOR_MUTED,
            font=("Segoe UI", 7), cursor="hand2", padx=4
        )
        self.btn_close.pack(side="right")
        self.btn_close.bind("<Button-1>", lambda e: self.quit())
        self.btn_close.bind("<Enter>", lambda e: self.btn_close.config(fg="#FFFFFF"))
        self.btn_close.bind("<Leave>", lambda e: self.btn_close.config(fg=self.COLOR_MUTED))

        # ⚙ Settings (all preferences live here)
        self.btn_settings = tk.Label(
            self.header_frame, text="⚙", bg=header_color, fg=self.COLOR_MUTED,
            font=("Segoe UI", 8), cursor="hand2", padx=3
        )
        self.btn_settings.pack(side="right")
        self.btn_settings.bind("<Button-1>", lambda e: self._open_settings())

        # 📋 Quick Copy:
        # Left-click: Always copy ENTIRE result (both paragraphs: Answer + Explanation)
        # Right-click: Copy Answer only (1st paragraph)
        # Middle-click: Copy Explanation only (2nd paragraph)
        self.btn_copy = tk.Label(
            self.header_frame, text="📋", bg=header_color, fg=self.COLOR_MUTED,
            font=("Segoe UI", 7), cursor="hand2", padx=3
        )
        self.btn_copy.pack(side="right")
        self.btn_copy.bind("<Button-1>", lambda e: self._copy_entire_output_to_clipboard())
        self.btn_copy.bind("<Button-2>", lambda e: self._copy_explanation_to_clipboard())
        self.btn_copy.bind("<Button-3>", lambda e: self._copy_answer_to_clipboard())
        self.btn_copy.bind("<Enter>", lambda e: self.btn_copy.config(fg="#FFFFFF"))
        self.btn_copy.bind("<Leave>", lambda e: self.btn_copy.config(fg=self.COLOR_MUTED))

        # ✂ Quick Snip
        self.btn_snip = tk.Label(
            self.header_frame, text="✂", bg=header_color, fg=self.COLOR_TEXT_DIM,
            font=("Segoe UI", 8), cursor="hand2", padx=3
        )
        self.btn_snip.pack(side="right")
        self.btn_snip.bind("<Button-1>", lambda e: self._start_snip())
        self.btn_snip.bind("<Enter>", lambda e: self.btn_snip.config(fg="#FFFFFF"))
        self.btn_snip.bind("<Leave>", lambda e: self.btn_snip.config(fg=self.COLOR_TEXT_DIM))

        # PURE ANSWER AREA (Fills the entire rest of the square, fully selectable)
        current_font_size = self.config.get("font_size", 8)
        self.txt_answer = tk.Text(
            self.container,
            wrap="word",
            bg=surface_color,
            fg=self.COLOR_TEXT,
            insertbackground="#FFFFFF",
            selectbackground="#2563EB",
            selectforeground="#FFFFFF",
            font=("Consolas", current_font_size, "bold"),
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=6,
            pady=4,
            cursor="xterm"
        )
        self.txt_answer.pack(fill="both", expand=True)
        self.txt_answer.insert("1.0", f"[{provider_name} Ready]\nPress Alt+S to snip\nor click ✂")

        # Read-only behavior: allow selection, navigation, and all window shortcuts (Ctrl/Alt), but block typing
        def _on_txt_key(event):
            # 1. Let all Control key combinations pass through to trigger window shortcuts
            if event.state & 4:
                k = event.keysym.lower()
                if k == 'a':
                    self.txt_answer.tag_add("sel", "1.0", "end")
                    return "break"
                if k == 'c':
                    self._copy_selection_or_full()
                    return "break"
                # For all other Ctrl shortcuts (Ctrl+[, Ctrl+], Ctrl+G, Ctrl+T, Ctrl++, Ctrl+-, Ctrl+0, etc.)
                return None

            # 2. Let all Alt key combinations (Alt+S) pass through
            if event.state & 8 or event.state & 0x20000 or event.keysym.startswith("Alt"):
                return None

            # 3. Allow navigation keys and Escape
            if event.keysym in ('Left', 'Right', 'Up', 'Down', 'Home', 'End', 'Prior', 'Next', 'Escape', 'Tab'):
                return None

            # 4. Block typing of letters, numbers, spaces, BackSpace, Delete, Return
            return "break"

        self.txt_answer.bind("<Key>", _on_txt_key)
        self.txt_answer.bind("<<Paste>>", lambda e: "break")
        self.txt_answer.bind("<<Clear>>", lambda e: "break")
        self.txt_answer.bind("<<Cut>>", lambda e: (self._copy_selection_or_full(), "break")[1])

        # Micro bottom bar with resize grip (Height 12px)
        self.bottom_bar = tk.Frame(self.container, bg=surface_color, height=12)
        self.bottom_bar.pack(fill="x", side="bottom")
        self.bottom_bar.pack_propagate(False)

        # Bottom Resize Grip (⤡)
        self.grip = tk.Label(
            self.bottom_bar, text="⤡",
            bg=surface_color, fg=self.COLOR_MUTED,
            font=("Segoe UI", 7), cursor="size_nw_se"
        )
        self.grip.pack(side="right", padx=1)
        self.grip.bind("<ButtonPress-1>", self._start_resize)
        self.grip.bind("<B1-Motion>", self._on_resize)

    def _bind_events(self):
        """Bind dragging, shortcuts, and context menu."""
        # Drag on header and grip
        for widget in (self.header_frame, self.lbl_status):
            widget.bind("<ButtonPress-1>", self._start_move)
            widget.bind("<B1-Motion>", self._on_move)

        # Context menu on right click anywhere
        self.context_menu = tk.Menu(self.win, tearoff=0, bg=self.COLOR_SURFACE, fg=self.COLOR_TEXT)
        self.context_menu.add_command(label="✂ Snip Question (Alt+S)", command=self._start_snip)
        self.context_menu.add_command(label="📋 Paste from Clipboard (Ctrl+V)", command=self._solve_from_clipboard)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📑 Copy Entire Text (Ctrl+C / 📋)", command=self._copy_entire_output_to_clipboard)
        self.context_menu.add_command(label="📄 Copy Answer Only (1st Paragraph) (Ctrl+1)", command=self._copy_answer_to_clipboard)
        self.context_menu.add_command(label="📄 Copy Explanation Only (2nd Paragraph) (Ctrl+2)", command=self._copy_explanation_to_clipboard)
        self.context_menu.add_command(label="✂ Copy Selection (if highlighted)", command=self._copy_selection_or_full)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🖥 Solve Fullscreen", command=self._solve_fullscreen)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="◀ Previous Answer (Ctrl+←)", command=self._history_prev)
        self.context_menu.add_command(label="▶ Next Answer (Ctrl+→)", command=self._history_next)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🗚 Increase Font (Ctrl++)", command=lambda: self._adjust_font_size(+1))
        self.context_menu.add_command(label="🗛 Decrease Font (Ctrl+-)", command=lambda: self._adjust_font_size(-1))
        self.context_menu.add_command(label="🖱 Toggle Click-Through (Ctrl+T)", command=self._toggle_click_through)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="👻 Toggle Ghost Mode (Ctrl+G)", command=self._toggle_ghost_mode)
        self.context_menu.add_command(label="➕ More Transparent (Ctrl+[)", command=lambda: self._adjust_opacity(-0.04))
        self.context_menu.add_command(label="➖ Less Transparent (Ctrl+])", command=lambda: self._adjust_opacity(+0.04))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="⚙ Settings (Ollama/Qwen/Gemini)", command=self._open_settings)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="✕ Close Overlay (Esc)", command=self.quit)

        for widget in (self.win, self.container, self.header_frame, self.txt_answer, self.bottom_bar):
            widget.bind("<Button-3>", self._show_context_menu)

        # Ensure clicking anywhere on the overlay immediately focuses the window for instant keyboard shortcut response
        for widget in (self.win, self.container, self.header_frame, self.lbl_status, self.bottom_bar):
            widget.bind("<Button-1>", lambda e: self.win.focus_force(), add="+")

        # Shortcuts helper: execute action and return "break" to halt bubbling so no shortcut runs twice
        def _wrap(fn):
            def handler(e=None):
                fn()
                return "break"
            return handler

        shortcuts = {
            "<Control-v>": _wrap(self._solve_from_clipboard),
            "<Control-V>": _wrap(self._solve_from_clipboard),
            "<Control-c>": _wrap(self._copy_selection_or_full),
            "<Control-C>": _wrap(self._copy_selection_or_full),
            "<Control-Shift-c>": _wrap(self._copy_entire_output_to_clipboard),
            "<Control-Shift-C>": _wrap(self._copy_entire_output_to_clipboard),
            "<Control-Key-1>": _wrap(self._copy_answer_to_clipboard),
            "<Control-Key-2>": _wrap(self._copy_explanation_to_clipboard),
            "<Control-1>": _wrap(self._copy_answer_to_clipboard),
            "<Control-2>": _wrap(self._copy_explanation_to_clipboard),
            "<Control-e>": _wrap(self._copy_explanation_to_clipboard),
            "<Control-E>": _wrap(self._copy_explanation_to_clipboard),
            "<Alt-s>": _wrap(self._start_snip),
            "<Alt-S>": _wrap(self._start_snip),
            "<Escape>": _wrap(self.quit),
            "<Control-bracketleft>": _wrap(lambda: self._adjust_opacity(-0.04)),
            "<Control-bracketright>": _wrap(lambda: self._adjust_opacity(+0.04)),
            "<Control-g>": _wrap(self._toggle_ghost_mode),
            "<Control-G>": _wrap(self._toggle_ghost_mode),
            "<Control-Left>": _wrap(self._history_prev),
            "<Control-Right>": _wrap(self._history_next),
            "<Control-plus>": _wrap(lambda: self._adjust_font_size(+1)),
            "<Control-equal>": _wrap(lambda: self._adjust_font_size(+1)),
            "<Control-minus>": _wrap(lambda: self._adjust_font_size(-1)),
            "<Control-underscore>": _wrap(lambda: self._adjust_font_size(-1)),
            "<Control-0>": _wrap(self._reset_font_size),
            "<Control-Key-0>": _wrap(self._reset_font_size),
            "<Control-t>": _wrap(self._toggle_click_through),
            "<Control-T>": _wrap(self._toggle_click_through),
            "<Control-comma>": _wrap(self._open_settings),
            "<Control-p>": _wrap(self._open_settings),
            "<Control-P>": _wrap(self._open_settings),
        }

        for target in (self.win, self.txt_answer, self.container):
            for seq, handler in shortcuts.items():
                target.bind(seq, handler)

        # Mouse wheel + Ctrl on any widget to adjust transparency on the fly
        for w in (self.win, self.container, self.header_frame, self.txt_answer, self.bottom_bar):
            w.bind("<Control-MouseWheel>", self._on_ctrl_wheel)

    def _adjust_opacity(self, delta: float):
        cur = float(self.config.get("opacity", 0.85))
        new_val = max(0.05, min(0.95, round(cur + delta, 2)))
        self.config["opacity"] = new_val
        self._apply_transparency()
        save_config(self.config)
        self.lbl_status.config(text=f" ⠇{int(new_val * 100)}%")
        p_name = self.config.get("provider", "ollama").upper()
        self.root.after(1200, lambda: self.lbl_status.config(text=f" ⠇{p_name}"))

    def _on_ctrl_wheel(self, event):
        delta = 0.04 if event.delta > 0 else -0.04
        self._adjust_opacity(delta)
        return "break"

    def _toggle_ghost_mode(self):
        self.is_ghost_mode = not self.is_ghost_mode
        self.config["glass_mode"] = self.is_ghost_mode
        save_config(self.config)
        self._apply_transparency()

        bg_color = CHROMA_KEY if self.is_ghost_mode else self.COLOR_BG
        header_color = CHROMA_KEY if self.is_ghost_mode else self.COLOR_HEADER
        surface_color = CHROMA_KEY if self.is_ghost_mode else self.COLOR_SURFACE

        self.container.config(bg=bg_color)
        self.header_frame.config(bg=header_color)
        self.lbl_status.config(bg=header_color)
        self.btn_close.config(bg=header_color)
        self.btn_settings.config(bg=header_color)
        self.btn_copy.config(bg=header_color)
        self.btn_snip.config(bg=header_color)
        self.txt_answer.config(bg=surface_color)
        self.bottom_bar.config(bg=surface_color)
        self.grip.config(bg=surface_color)
        status_txt = "Ghost ON" if self.is_ghost_mode else "Ghost OFF"
        self.lbl_status.config(text=f" ⠇{status_txt}")
        p_name = self.config.get("provider", "ollama").upper()
        self.root.after(1200, lambda: self.lbl_status.config(text=f" ⠇{p_name}"))

    def _flash_status(self, text: str, duration_ms: int = 1200):
        """Briefly display status feedback and revert to provider name."""
        self.lbl_status.config(text=text)
        p_name = self.config.get("provider", "ollama").upper()
        self.root.after(duration_ms, lambda: self.lbl_status.config(text=f" ⠇{p_name}"))

    def _adjust_font_size(self, delta: int):
        """Dynamically adjust text font size on the fly."""
        cur = int(self.config.get("font_size", 8))
        new_size = max(6, min(24, cur + delta))
        if new_size != cur:
            self.config["font_size"] = new_size
            save_config(self.config)
            self.txt_answer.config(font=("Consolas", new_size, "bold"))
            self._flash_status(f" ⠇Font {new_size}pt")

    def _reset_font_size(self):
        """Reset text font size to default 8pt."""
        self.config["font_size"] = 8
        save_config(self.config)
        self.txt_answer.config(font=("Consolas", 8, "bold"))
        self._flash_status(" ⠇Font 8pt")

    def _toggle_click_through(self):
        """Toggle Win32 WS_EX_TRANSPARENT so mouse clicks pass through to background."""
        self.is_click_through = not self.is_click_through
        self.config["click_through"] = self.is_click_through
        save_config(self.config)
        try:
            user32 = ctypes.windll.user32
            win_hwnd = int(self.win.wm_frame(), 16) if hasattr(self.win, "wm_frame") else self.win.winfo_id()
            style = user32.GetWindowLongW(win_hwnd, -20)  # GWL_EXSTYLE
            WS_EX_TRANSPARENT = 0x00000020
            if self.is_click_through:
                style |= WS_EX_TRANSPARENT
                self.lbl_status.config(text=" ⠇Pass-Thru")
            else:
                style &= ~WS_EX_TRANSPARENT
                p_name = self.config.get("provider", "ollama").upper()
                self.lbl_status.config(text=f" ⠇{p_name}")
            user32.SetWindowLongW(win_hwnd, -20, style)
            flags = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # SWP_FRAMECHANGED
            user32.SetWindowPos(win_hwnd, 0, 0, 0, 0, 0, flags)
        except Exception as e:
            print(f"Click-through warning: {e}")

    def _history_prev(self):
        """Step back to previous solved question in the history stack."""
        if not self.history:
            self._flash_status(" ⠇No History")
            return
        if self.history_index <= 0:
            self._flash_status(" ⠇Oldest")
            return
        self.history_index -= 1
        self._display_history_entry(self.history[self.history_index])

    def _history_next(self):
        """Step forward to more recent question in the history stack."""
        if not self.history:
            self._flash_status(" ⠇No History")
            return
        if self.history_index >= len(self.history) - 1:
            self._flash_status(" ⠇Latest")
            return
        self.history_index += 1
        self._display_history_entry(self.history[self.history_index])

    def _display_history_entry(self, entry: dict):
        """Render an answer history entry and auto-copy its text."""
        q_type = entry.get("type", "MCQ")
        correct_ans = entry.get("correct_answer", "")
        copy_txt = entry.get("copy_text", correct_ans)
        explanation = entry.get("explanation", "")

        self.last_answer = correct_ans
        self.last_copy_text = copy_txt
        self.last_explanation = explanation

        display_lines = [f"[{q_type}] {correct_ans}"]
        if explanation:
            display_lines.append(f"\n{explanation}")

        full_output = "\n".join(display_lines).strip()
        self.last_full_text = full_output

        self.txt_answer.delete("1.0", "end")
        self.txt_answer.insert("1.0", "\n".join(display_lines))

        idx_str = f"[{self.history_index + 1}/{len(self.history)}]"
        if entry.get("fallback"):
            idx_str += " (Fallback)"
        self.lbl_status.config(text=f" ⠇{idx_str}")

        if self.config.get("auto_copy", True):
            self._copy_to_system_clipboard(full_output)
            self.btn_copy.config(text="✓")
            self.root.after(1200, lambda: self.btn_copy.config(text="📋"))

    def _show_context_menu(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _start_global_hotkeys(self):
        if not HAS_PYNPUT or pynput_keyboard is None or not self.config.get("global_hotkey_enabled", True):
            return

        def hotkey_snip():
            self.root.after(0, self._start_snip)

        def hotkey_copy():
            self.root.after(0, self._copy_selection_or_full)

        def hotkey_copy_all():
            self.root.after(0, self._copy_entire_output_to_clipboard)

        def hotkey_copy_expl():
            self.root.after(0, self._copy_explanation_to_clipboard)

        def hotkey_clip():
            self.root.after(0, self._solve_from_clipboard)

        def hotkey_toggle_vis():
            self.root.after(0, self._toggle_visibility)

        try:
            def hotkey_prev():
                self.root.after(0, self._history_prev)

            def hotkey_next():
                self.root.after(0, self._history_next)

            def hotkey_clickthru():
                self.root.after(0, self._toggle_click_through)

            def hotkey_ghost():
                self.root.after(0, self._toggle_ghost_mode)

            def hotkey_opacity_down():
                self.root.after(0, lambda: self._adjust_opacity(-0.04))

            def hotkey_opacity_up():
                self.root.after(0, lambda: self._adjust_opacity(+0.04))

            def hotkey_font_up():
                self.root.after(0, lambda: self._adjust_font_size(+1))

            def hotkey_font_down():
                self.root.after(0, lambda: self._adjust_font_size(-1))

            def hotkey_settings():
                self.root.after(0, self._open_settings)

            hotkeys = {
                '<ctrl>+<alt>+s': hotkey_snip,
                '<ctrl>+<alt>+c': hotkey_copy,
                '<ctrl>+<alt>+a': hotkey_copy_all,
                '<ctrl>+<alt>+e': hotkey_copy_expl,
                '<ctrl>+<alt>+v': hotkey_clip,
                '<ctrl>+<alt>+h': hotkey_toggle_vis,
                '<ctrl>+<alt>+<left>': hotkey_prev,
                '<ctrl>+<alt>+<right>': hotkey_next,
                '<ctrl>+<alt>+t': hotkey_clickthru,
                '<ctrl>+<alt>+g': hotkey_ghost,
                '<ctrl>+<alt>+[': hotkey_opacity_down,
                '<ctrl>+<alt>+]': hotkey_opacity_up,
                '<ctrl>+<alt>+=': hotkey_font_up,
                '<ctrl>+<alt>+-': hotkey_font_down,
                '<ctrl>+<alt>+p': hotkey_settings,
            }
            self.hotkey_listener = pynput_keyboard.GlobalHotKeys(hotkeys)
            self.hotkey_listener.daemon = True
            self.hotkey_listener.start()
        except Exception as e:
            print(f"Warning: Global hotkey listener: {e}")

    # --- Drag & Square Resize ---
    def _start_move(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_move(self, event):
        deltax = event.x - self._drag_start_x
        deltay = event.y - self._drag_start_y
        x = self.win.winfo_x() + deltax
        y = self.win.winfo_y() + deltay
        self.win.geometry(f"+{x}+{y}")
        self.config["window_x"] = x
        self.config["window_y"] = y
        save_config(self.config)

    def _start_resize(self, event):
        self._resize_start_x = event.x_root
        self._resize_start_y = event.y_root
        self._resize_start_w = self.win.winfo_width()
        self._resize_start_h = self.win.winfo_height()

    def _on_resize(self, event):
        dx = event.x_root - self._resize_start_x
        dy = event.y_root - self._resize_start_y
        new_size = max(140, max(self._resize_start_w + dx, self._resize_start_h + dy))
        self.win.geometry(f"{new_size}x{new_size}")
        self.config["window_width"] = new_size
        self.config["window_height"] = new_size
        save_config(self.config)

    def _toggle_visibility(self):
        if self.is_visible:
            self.win.withdraw()
            self.is_visible = False
        else:
            self.win.deiconify()
            self.win.lift()
            self.win.attributes("-topmost", True)
            self.is_visible = True

    # --- Screen Capture ---
    def _start_snip(self):
        if self.is_solving:
            self.lbl_status.config(text=" ⠇Busy...")
            self.root.after(800, lambda: self.lbl_status.config(text=" ⠇Thinking..."))
            return
        self.win.withdraw()
        self.root.after(150, lambda: SnipSelector(self._on_snip_done))

    def _on_snip_done(self, pil_image):
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self._hide_from_windows_taskbar()

        if pil_image:
            self.lbl_status.config(text=" ⠇Thinking...")
            self._process_image_async(pil_image)
        else:
            self.is_solving = False
            p_name = self.config.get("provider", "ollama").upper()
            self.lbl_status.config(text=f" ⠇{p_name}")

    def _solve_fullscreen(self):
        if self.is_solving:
            self.lbl_status.config(text=" ⠇Busy...")
            self.root.after(800, lambda: self.lbl_status.config(text=" ⠇Thinking..."))
            return
        self.win.withdraw()
        self.root.after(150, self._do_fullscreen_capture)

    def _do_fullscreen_capture(self):
        img = capture_fullscreen()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self._hide_from_windows_taskbar()
        if img:
            self.lbl_status.config(text=" ⠇Thinking...")
            self._process_image_async(img)
        else:
            self.is_solving = False
            self.lbl_status.config(text=" ⠇Failed")

    def _solve_from_clipboard(self):
        if self.is_solving:
            self.lbl_status.config(text=" ⠇Busy...")
            self.root.after(800, lambda: self.lbl_status.config(text=" ⠇Thinking..."))
            return
        img = capture_from_clipboard()
        if img:
            self.lbl_status.config(text=" ⠇Thinking...")
            self._process_image_async(img)
        else:
            self.is_solving = False
            self._show_error("No image in clipboard.\nPress Win+Shift+S first.")

    # --- Async Solver Execution ---
    def _process_image_async(self, pil_image: Image.Image):
        self.is_solving = True
        def worker():
            try:
                result = self.solver.solve_question(pil_image)
            except Exception as e:
                result = {"success": False, "error": str(e)}
            self.root.after(0, lambda: self._on_solve_complete(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_solve_complete(self, result: dict):
        self.is_solving = False
        if not result.get("success", False):
            self._show_error(result.get("error", "Error"))
            return

        q_type = result.get("type", "MCQ")
        correct_ans = result.get("correct_answer", "")
        copy_txt = result.get("copy_text", correct_ans)
        explanation = result.get("explanation", "")

        self.last_answer = correct_ans
        self.last_copy_text = copy_txt
        self.last_explanation = explanation

        # Add to Answer History stack (up to 20 items)
        history_entry = {
            "type": q_type,
            "correct_answer": correct_ans,
            "copy_text": copy_txt,
            "explanation": explanation,
            "fallback": result.get("fallback", False)
        }
        self.history.append(history_entry)
        if len(self.history) > 20:
            self.history.pop(0)
        self.history_index = len(self.history) - 1

        # Update status tag with indicator
        if result.get("fallback"):
            self.lbl_status.config(text=" ⠇Ollama (Fallback)")
        elif len(self.history) > 1:
            self.lbl_status.config(text=f" ⠇[{self.history_index + 1}/{len(self.history)}]")
        else:
            self.lbl_status.config(text=f" ⠇[{q_type}]")

        # Format pure answer output
        display_lines = [f"[{q_type}] {correct_ans}"]
        if explanation:
            display_lines.append(f"\n{explanation}")

        output_text = "\n".join(display_lines)
        self.last_full_text = output_text.strip()

        self.txt_answer.delete("1.0", "end")
        self.txt_answer.insert("1.0", output_text)

        # Auto-copy if enabled: automatically copy the entire result (both paragraphs) right after finding the answer!
        if self.config.get("auto_copy", True):
            self._copy_to_system_clipboard(self.last_full_text)
            self.btn_copy.config(text="✓")
            self.root.after(1600, lambda: self.btn_copy.config(text="📋"))

    def _get_selected_text(self) -> str:
        """Return text currently selected/highlighted in txt_answer, or empty string."""
        try:
            if self.txt_answer.tag_ranges("sel"):
                return self.txt_answer.get("sel.first", "sel.last").strip()
        except Exception:
            pass
        return ""

    def _copy_selection_or_full(self):
        """If user highlighted text, copy the selection; otherwise copy the ENTIRE result (both paragraphs)."""
        sel = self._get_selected_text()
        if sel:
            self._copy_to_system_clipboard(sel)
            self.btn_copy.config(text="✓")
            self._flash_status(" ⠇Copied Sel!")
            self.root.after(1600, lambda: self.btn_copy.config(text="📋"))
        else:
            self._copy_entire_output_to_clipboard()

    def _copy_answer_to_clipboard(self):
        """Copy the 1st paragraph (Answer only) to clipboard."""
        text_to_copy = self.last_copy_text or self.last_answer
        if not text_to_copy:
            full = self.txt_answer.get("1.0", "end-1c").strip()
            parts = full.split("\n\n", 1)
            text_to_copy = parts[0].strip() if parts else full

        if text_to_copy:
            self._copy_to_system_clipboard(text_to_copy)
            self.btn_copy.config(text="✓")
            self._flash_status(" ⠇Copied Ans!")
            self.root.after(1600, lambda: self.btn_copy.config(text="📋"))
        else:
            self._flash_status(" ⠇Empty")

    def _copy_explanation_to_clipboard(self):
        """Copy the 2nd paragraph (Explanation) to clipboard."""
        expl = getattr(self, "last_explanation", "")
        if not expl:
            full = self.txt_answer.get("1.0", "end-1c").strip()
            parts = full.split("\n\n", 1)
            if len(parts) > 1:
                expl = parts[1].strip()

        if expl:
            self._copy_to_system_clipboard(expl)
            self.btn_copy.config(text="✓")
            self._flash_status(" ⠇Copied Expl!")
            self.root.after(1600, lambda: self.btn_copy.config(text="📋"))
        else:
            self._flash_status(" ⠇No Expl")

    def _copy_entire_output_to_clipboard(self):
        """Copy the entire output (Answer + Explanation) to clipboard."""
        full_text = getattr(self, "last_full_text", "").strip()
        if not full_text:
            full_text = self.txt_answer.get("1.0", "end-1c").strip()
        if full_text:
            self._copy_to_system_clipboard(full_text)
            self.btn_copy.config(text="✓")
            self._flash_status(" ⠇Copied All!")
            self.root.after(1600, lambda: self.btn_copy.config(text="📋"))
        else:
            self._flash_status(" ⠇Empty")

    def _copy_to_system_clipboard(self, text: str):
        # 1. Primary: Direct Win32 OS-level clipboard assignment (instant, universal across all Windows applications)
        set_windows_clipboard(text)
        # 2. Secondary: Tkinter clipboard assignment for internal consistency
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(text)
            self.win.update_idletasks()
        except Exception:
            pass

    def _show_error(self, message: str):
        self.is_solving = False
        self.lbl_status.config(text=" ⠇Error")
        self.txt_answer.delete("1.0", "end")
        self.txt_answer.insert("1.0", message)

    def _show_first_run_hint(self):
        provider = self.config.get("provider", "ollama").capitalize()
        res = messagebox.askyesno(
            f"{provider} Configuration",
            f"Welcome to QuizLens!\n\n"
            f"Would you like to configure your {provider} settings or enter an API key now?"
        )
        if res:
            self._open_settings()

    def _open_settings(self):
        SettingsDialog(self.win, self.config, self._on_settings_saved)

    def _on_settings_saved(self, new_config: dict):
        self.config = new_config
        save_config(self.config)
        self.is_ghost_mode = self.config.get("glass_mode", False)

        prov = self.config.get("provider", "ollama")
        base_url = self.config.get(f"{prov}_base_url", "http://localhost:11434/v1")

        enable_fallback = self.config.get("auto_fallback_ollama", True)
        fallback_model = self.config.get("ollama_model", "llava")
        fallback_base_url = self.config.get("ollama_base_url", "http://localhost:11434/v1")

        self.solver.update_credentials(
            provider=prov,
            api_key=self.config.get("api_key", ""),
            model=self.config.get("model", "llama3.2-vision"),
            base_url=base_url,
            enable_fallback=enable_fallback,
            fallback_model=fallback_model,
            fallback_base_url=fallback_base_url
        )
        self.win.attributes("-topmost", self.config.get("always_on_top", True))
        self._apply_transparency()

        # Update font size
        new_size = self.config.get("font_size", 8)
        self.txt_answer.config(font=("Consolas", new_size, "bold"))

        # Update provider indicator
        p_name = prov.upper()
        self.lbl_status.config(text=f" ⠇{p_name}")

        # Re-apply theme colors if ghost mode toggled
        bg_color = CHROMA_KEY if self.is_ghost_mode else self.COLOR_BG
        header_color = CHROMA_KEY if self.is_ghost_mode else self.COLOR_HEADER
        surface_color = CHROMA_KEY if self.is_ghost_mode else self.COLOR_SURFACE

        self.container.config(bg=bg_color)
        self.header_frame.config(bg=header_color)
        self.lbl_status.config(bg=header_color)
        self.btn_close.config(bg=header_color)
        self.btn_settings.config(bg=header_color)
        self.btn_copy.config(bg=header_color)
        self.btn_snip.config(bg=header_color)
        self.txt_answer.config(bg=surface_color)
        self.bottom_bar.config(bg=surface_color)
        self.grip.config(bg=surface_color)

    def quit(self):
        try:
            if hasattr(self, "hotkey_listener") and self.hotkey_listener:
                self.hotkey_listener.stop()
        except Exception:
            pass
        self.config["window_x"] = self.win.winfo_x()
        self.config["window_y"] = self.win.winfo_y()
        save_config(self.config)
        try:
            self.win.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def run(self):
        self.root.mainloop()


class SettingsDialog:
    """Consolidated Settings modal: Ollama, Qwen, Gemini, transparency, font, and modes."""
    def __init__(self, parent, current_config: dict, on_save_callback):
        self.on_save = on_save_callback
        self.config = current_config.copy()
        self.parent = parent

        self.win = tk.Toplevel(parent)
        self.win.title("QuizLens Settings")
        self.win.geometry("400x540")
        self.win.configure(bg="#18181B")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.grab_set()

        # Title
        tk.Label(
            self.win, text="⚙ Preferences & AI Engine",
            bg="#18181B", fg="#FAFAFA", font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=16, pady=(12, 6))

        # --- Provider Selection (Ollama vs Qwen vs Gemini) ---
        tk.Label(
            self.win, text="AI Engine / Provider:",
            bg="#18181B", fg="#A1A1AA", font=("Segoe UI", 8)
        ).pack(anchor="w", padx=16, pady=(2, 2))

        self.provider_var = tk.StringVar(value=self.config.get("provider", "ollama"))
        prov_frame = tk.Frame(self.win, bg="#18181B")
        prov_frame.pack(fill="x", padx=16, pady=(0, 6))

        rb_ollama = tk.Radiobutton(
            prov_frame, text="Ollama",
            variable=self.provider_var, value="ollama",
            bg="#18181B", fg="#FAFAFA", selectcolor="#101012",
            activebackground="#18181B", activeforeground="#FAFAFA",
            font=("Segoe UI", 8, "bold"), command=self._on_provider_change
        )
        rb_ollama.pack(side="left", padx=(0, 10))

        rb_qwen = tk.Radiobutton(
            prov_frame, text="Qwen",
            variable=self.provider_var, value="qwen",
            bg="#18181B", fg="#FAFAFA", selectcolor="#101012",
            activebackground="#18181B", activeforeground="#FAFAFA",
            font=("Segoe UI", 8), command=self._on_provider_change
        )
        rb_qwen.pack(side="left", padx=(0, 10))

        rb_gemini = tk.Radiobutton(
            prov_frame, text="Gemini",
            variable=self.provider_var, value="gemini",
            bg="#18181B", fg="#FAFAFA", selectcolor="#101012",
            activebackground="#18181B", activeforeground="#FAFAFA",
            font=("Segoe UI", 8), command=self._on_provider_change
        )
        rb_gemini.pack(side="left")

        # --- Base URL Section ---
        self.url_frame = tk.Frame(self.win, bg="#18181B")
        self.url_frame.pack(fill="x", padx=16, pady=(0, 4))

        self.lbl_url = tk.Label(
            self.url_frame, text="Ollama Endpoint URL:",
            bg="#18181B", fg="#A1A1AA", font=("Segoe UI", 7)
        )
        self.lbl_url.pack(anchor="w")

        self.entry_url = tk.Entry(
            self.url_frame, bg="#101012", fg="#FAFAFA",
            insertbackground="#FAFAFA", font=("Segoe UI", 8),
            relief="flat"
        )
        self.entry_url.pack(fill="x", ipady=2)

        # --- API Key Entry ---
        self.lbl_api_key = tk.Label(
            self.win, text="Ollama API Key / Token (optional):",
            bg="#18181B", fg="#A1A1AA", font=("Segoe UI", 8)
        )
        self.lbl_api_key.pack(anchor="w", padx=16, pady=(4, 2))

        key_frame = tk.Frame(self.win, bg="#18181B")
        key_frame.pack(fill="x", padx=16, pady=(0, 4))

        self.entry_key = tk.Entry(
            key_frame, bg="#101012", fg="#FAFAFA",
            insertbackground="#FAFAFA", font=("Segoe UI", 8),
            show="•", relief="flat"
        )
        self.entry_key.pack(side="left", fill="x", expand=True, ipady=3)

        self.btn_show = tk.Button(
            key_frame, text="👁", bg="#27272A", fg="#FAFAFA",
            relief="flat", font=("Segoe UI", 7),
            command=self._toggle_show_key
        )
        self.btn_show.pack(side="right", padx=(4, 0))

        # Test Connection Button
        test_frame = tk.Frame(self.win, bg="#18181B")
        test_frame.pack(fill="x", padx=16, pady=(0, 6))

        self.btn_test = tk.Button(
            test_frame, text="⚡ Test Connection", bg="#27272A", fg="#FAFAFA",
            relief="flat", font=("Segoe UI", 7),
            command=self._test_api_key
        )
        self.btn_test.pack(side="left")

        self.lbl_test_result = tk.Label(
            test_frame, text="", bg="#18181B", fg="#A1A1AA", font=("Segoe UI", 8)
        )
        self.lbl_test_result.pack(side="left", padx=8)

        # --- Model Selector ---
        tk.Label(
            self.win, text="Vision Model (editable):",
            bg="#18181B", fg="#A1A1AA", font=("Segoe UI", 8)
        ).pack(anchor="w", padx=16, pady=(2, 2))

        self.model_frame = tk.Frame(self.win, bg="#18181B")
        self.model_frame.pack(fill="x", padx=16, pady=(0, 6))

        self.entry_model = tk.Entry(
            self.model_frame, bg="#101012", fg="#FAFAFA",
            insertbackground="#FAFAFA", font=("Segoe UI", 8),
            relief="flat"
        )
        self.entry_model.pack(fill="x", ipady=2, pady=(0, 3))

        self.presets_frame = tk.Frame(self.model_frame, bg="#18181B")
        self.presets_frame.pack(fill="x")

        # --- Transparency Slider ---
        tk.Label(
            self.win, text="Window Transparency / Opacity:",
            bg="#18181B", fg="#A1A1AA", font=("Segoe UI", 8)
        ).pack(anchor="w", padx=16, pady=(2, 2))

        self.opacity_var = tk.IntVar(value=int(self.config.get("opacity", 0.18) * 100))
        op_frame = tk.Frame(self.win, bg="#18181B")
        op_frame.pack(fill="x", padx=16, pady=(0, 4))

        self.lbl_opacity = tk.Label(op_frame, text=f"{self.opacity_var.get()}%", bg="#18181B", fg="#FAFAFA", font=("Segoe UI", 8), width=5)
        self.lbl_opacity.pack(side="right")

        self.scale_opacity = tk.Scale(
            op_frame, from_=3, to=85, orient="horizontal",
            variable=self.opacity_var, showvalue=False,
            bg="#18181B", highlightthickness=0, troughcolor="#27272A",
            activebackground="#A1A1AA", sliderrelief="flat",
            command=self._on_opacity_change
        )
        self.scale_opacity.pack(side="left", fill="x", expand=True)

        # --- Font Size Slider ---
        tk.Label(
            self.win, text="Answer Text Size:",
            bg="#18181B", fg="#A1A1AA", font=("Segoe UI", 8)
        ).pack(anchor="w", padx=16, pady=(2, 2))

        self.font_var = tk.IntVar(value=self.config.get("font_size", 8))
        font_frame = tk.Frame(self.win, bg="#18181B")
        font_frame.pack(fill="x", padx=16, pady=(0, 4))

        self.lbl_font = tk.Label(font_frame, text=f"{self.font_var.get()}pt", bg="#18181B", fg="#FAFAFA", font=("Segoe UI", 8), width=5)
        self.lbl_font.pack(side="right")

        self.scale_font = tk.Scale(
            font_frame, from_=6, to=14, orient="horizontal",
            variable=self.font_var, showvalue=False,
            bg="#18181B", highlightthickness=0, troughcolor="#27272A",
            activebackground="#A1A1AA", sliderrelief="flat",
            command=lambda v: self.lbl_font.config(text=f"{v}pt")
        )
        self.scale_font.pack(side="left", fill="x", expand=True)

        # --- Checkboxes ---
        self.var_ghost = tk.BooleanVar(value=self.config.get("glass_mode", False))
        tk.Checkbutton(
            self.win, text="Ghost Mode (100% Invisible Background)",
            variable=self.var_ghost, bg="#18181B", fg="#FAFAFA",
            selectcolor="#101012", activebackground="#18181B",
            font=("Segoe UI", 8)
        ).pack(anchor="w", padx=16, pady=(2, 1))

        self.var_autocopy = tk.BooleanVar(value=self.config.get("auto_copy", True))
        tk.Checkbutton(
            self.win, text="Auto-copy answer to clipboard on solve",
            variable=self.var_autocopy, bg="#18181B", fg="#FAFAFA",
            selectcolor="#101012", activebackground="#18181B",
            font=("Segoe UI", 8)
        ).pack(anchor="w", padx=16, pady=1)

        self.var_topmost = tk.BooleanVar(value=self.config.get("always_on_top", True))
        tk.Checkbutton(
            self.win, text="Always keep overlay on top",
            variable=self.var_topmost, bg="#18181B", fg="#FAFAFA",
            selectcolor="#101012", activebackground="#18181B",
            font=("Segoe UI", 8)
        ).pack(anchor="w", padx=16, pady=1)

        self.var_fallback = tk.BooleanVar(value=self.config.get("auto_fallback_ollama", True))
        tk.Checkbutton(
            self.win, text="Auto-fallback to local Ollama on cloud error",
            variable=self.var_fallback, bg="#18181B", fg="#FAFAFA",
            selectcolor="#101012", activebackground="#18181B",
            font=("Segoe UI", 8)
        ).pack(anchor="w", padx=16, pady=1)

        # Bottom Action Buttons
        btn_frame = tk.Frame(self.win, bg="#18181B")
        btn_frame.pack(side="bottom", fill="x", padx=16, pady=10)

        tk.Button(
            btn_frame, text="Cancel", bg="#27272A", fg="#FAFAFA",
            relief="flat", font=("Segoe UI", 8), command=self.win.destroy
        ).pack(side="right", padx=(6, 0))

        tk.Button(
            btn_frame, text="Save Settings", bg="#3F3F46", fg="#FFFFFF",
            relief="flat", font=("Segoe UI", 8, "bold"), padx=10,
            command=self._save_and_close
        ).pack(side="right")

        # Initial populate
        self._on_provider_change()

    def _build_model_presets(self, models):
        for w in self.presets_frame.winfo_children():
            w.destroy()

        for m_name in models:
            b = tk.Button(
                self.presets_frame, text=m_name, bg="#27272A", fg="#FAFAFA",
                font=("Segoe UI", 7), relief="flat", padx=4, pady=0,
                command=lambda name=m_name: self._set_model_text(name)
            )
            b.pack(side="left", padx=(0, 4))

    def _set_model_text(self, name):
        self.entry_model.delete(0, "end")
        self.entry_model.insert(0, name)

    def _on_provider_change(self):
        prov = self.provider_var.get()
        if prov == "ollama":
            self.lbl_url.config(text="Ollama Endpoint URL:")
            self.url_frame.pack(fill="x", padx=16, pady=(0, 4), before=self.lbl_api_key)
            self.entry_url.delete(0, "end")
            self.entry_url.insert(0, self.config.get("ollama_base_url", "http://localhost:11434/v1"))

            self.lbl_api_key.config(text="Ollama API Key / Bearer Token (optional):")
            self.entry_key.delete(0, "end")
            self.entry_key.insert(0, self.config.get("ollama_api_key", ""))

            cur_m = self.config.get("ollama_model", "llama3.2-vision")
            self._set_model_text(cur_m)
            self._build_model_presets(["llama3.2-vision", "moondream", "llava", "qwen2.5-vl:7b"])

        elif prov == "qwen":
            self.lbl_url.config(text="Qwen DashScope Base URL:")
            self.url_frame.pack(fill="x", padx=16, pady=(0, 4), before=self.lbl_api_key)
            self.entry_url.delete(0, "end")
            self.entry_url.insert(0, self.config.get("qwen_base_url", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"))

            self.lbl_api_key.config(text="Qwen API Key (DashScope sk-...):")
            self.entry_key.delete(0, "end")
            self.entry_key.insert(0, self.config.get("qwen_api_key", ""))

            cur_m = self.config.get("qwen_model", "qwen-vl-max")
            self._set_model_text(cur_m)
            self._build_model_presets(["qwen-vl-max", "qwen-vl-plus", "qwen2.5-vl-72b-instruct"])

        else:  # Gemini
            self.url_frame.pack_forget()
            self.lbl_api_key.config(text="Gemini API Key (Google AI Studio):")
            self.entry_key.delete(0, "end")
            self.entry_key.insert(0, self.config.get("gemini_api_key", ""))

            cur_m = self.config.get("gemini_model", "gemini-3.5-flash-lite")
            self._set_model_text(cur_m)
            self._build_model_presets(["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.5-flash"])

        self.lbl_test_result.config(text="")

    def _on_opacity_change(self, val):
        self.lbl_opacity.config(text=f"{val}%")
        try:
            self.parent.attributes("-alpha", float(val) / 100.0)
        except Exception:
            pass

    def _toggle_show_key(self):
        if self.entry_key.cget("show") == "":
            self.entry_key.config(show="•")
        else:
            self.entry_key.config(show="")

    def _test_api_key(self):
        key = self.entry_key.get().strip()
        prov = self.provider_var.get()
        model = self.entry_model.get().strip()
        base_url = self.entry_url.get().strip()

        self.lbl_test_result.config(text="Testing...", fg="#A1A1AA")
        self.btn_test.config(state="disabled")

        def worker():
            solver = QuizSolver(provider=prov, api_key=key, model=model, base_url=base_url)
            ok, msg = solver.test_connection()
            def update_ui():
                self.btn_test.config(state="normal")
                if ok:
                    self.lbl_test_result.config(text="✓ Connected!", fg="#E0E0E0")
                else:
                    self.lbl_test_result.config(text=f"✕ {msg[:25]}", fg="#EF4444")
            self.win.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _save_and_close(self):
        prov = self.provider_var.get()
        key = self.entry_key.get().strip()
        model = self.entry_model.get().strip()
        base_url = self.entry_url.get().strip()

        self.config["provider"] = prov
        self.config["api_key"] = key
        self.config["model"] = model

        if prov == "ollama":
            self.config["ollama_api_key"] = key
            self.config["ollama_base_url"] = base_url
            self.config["ollama_model"] = model
        elif prov == "qwen":
            self.config["qwen_api_key"] = key
            self.config["qwen_base_url"] = base_url
            self.config["qwen_model"] = model
        else:
            self.config["gemini_api_key"] = key
            self.config["gemini_model"] = model

        self.config["opacity"] = float(self.opacity_var.get()) / 100.0
        self.config["font_size"] = int(self.font_var.get())
        self.config["glass_mode"] = self.var_ghost.get()
        self.config["auto_copy"] = self.var_autocopy.get()
        self.config["always_on_top"] = self.var_topmost.get()
        self.config["auto_fallback_ollama"] = self.var_fallback.get()
        self.on_save(self.config)
        self.win.destroy()


if __name__ == "__main__":
    app = QuizOverlayApp()
    app.run()
