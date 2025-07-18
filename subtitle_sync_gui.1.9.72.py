from version import __versionMinor__  # type: ignore
__version__ = __versionMinor__  + "72"
import os
import sys
import time
import wave
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import ffmpeg  # type: ignore
from faster_whisper import WhisperModel  # type: ignore
from theme import RIBBON_BUTTON_STYLE
import logging
import io
import contextlib
import re
import traceback
import os, json

# run_asr_only
# run_sync

CONFIG_PATH = os.path.expanduser("~/.subtitle_sync_config.json")
logging.basicConfig(level=logging.DEBUG)

from huggingface_hub import snapshot_download

def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

icon_path = os.path.join("icons", "import_video.png")

from shutil import which
from tkinter import messagebox, filedialog

def load_config():
    """Return a dict of saved settings, or {} if none exist."""
    try:
        return json.load(open(CONFIG_PATH, 'r', encoding='utf-8'))
    except Exception:
        return {}

def save_config(cfg: dict):
    """Persist config dict to disk."""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print("⚠️ Could not save config:", e)

def find_ffmpeg() -> str:
    # 1) Try your bundled ffmpeg
    bundled = resource_path(os.path.join("bin", "ffmpeg.exe"))
    if os.path.isfile(bundled):
        return bundled

    # 2) Try system-wide on PATH
    system_ff = which("ffmpeg") or which("ffmpeg.exe")
    if system_ff:
        return system_ff

    # 3) Prompt user to locate it manually
    msg = (
        "Could not find ffmpeg.exe in your bundle or on PATH.\n\n"
        "You can:\n"
        " • Download & place ffmpeg.exe in the 'bin' folder next to the app, or\n"
        " • Locate an existing ffmpeg.exe on your PC now."
    )
    if messagebox.askyesno("ffmpeg Not Found", msg):
        chosen = filedialog.askopenfilename(
            title="Select ffmpeg.exe",
            filetypes=[("Executable", "*.exe")]
        )
        if chosen and os.path.isfile(chosen):
            return chosen
        messagebox.showerror("Invalid Selection", "That file wasn’t found or isn’t an .exe.")
    # If we get here, bail out
    sys.exit("ffmpeg.exe is required but was not found.")


class ModelDownloader(tk.Toplevel):
    def __init__(self, parent, model_id, model_dir, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.title("Downloading Whisper Model")
        self.geometry("400x120")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.model_id = model_id
        self.model_dir = model_dir
        self.cancelled = False
        self.result = None

        tk.Label(self, text="Downloading Whisper model…", font=("Segoe UI", 10)).pack(pady=(15, 5))
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=20, pady=5)
        self.status_label = tk.Label(self, text="Estimated ~3GB", font=("Segoe UI", 9), fg="gray")
        self.status_label.pack()
        self.cancel_button = ttk.Button(self, text="Cancel", command=self.cancel)
        self.cancel_button.pack(pady=8)

        self.thread = threading.Thread(target=self.download)
        self.thread.start()
        self.progress.start(8)

    def cancel(self):
        self.cancelled = True
        self.result = None
        self.destroy()    

    def download(self):
        try:
            from huggingface_hub import __version__ as hf_version
            from packaging import version
            import tkinter.messagebox as messagebox

            # Notify if version is too old
            if version.parse(hf_version) < version.parse("0.20.0"):
                messagebox.showwarning(
                    "Update Required",
                    "Your installed version of 'huggingface_hub' is outdated and may cause errors.\n\n"
                    "Please upgrade it by running:\n\npip install --upgrade huggingface_hub"
                )

            def update_progress(dl):
                pct = int((dl.bytes_downloaded / dl.bytes_total) * 100)
                self.status_label.config(text=f"Downloading… {pct}%")
                self.progress.config(mode="determinate", value=pct)
                self.update_idletasks()

            kwargs = {}
            if version.parse(hf_version) >= version.parse("0.20.0"):
                kwargs["progress_callback"] = update_progress

            path = snapshot_download(
                repo_id=self.model_id,
                cache_dir=self.model_dir,
                local_dir=self.model_dir,
                local_dir_use_symlinks=False,
                **kwargs
            )

            if not self.cancelled:
                self.result = path
                self.destroy()

        except Exception as e:
            self.result = e
            self.destroy()

    @staticmethod
    def ensure_model(repo_id: str, model_dir: str = "models/whisper-large-v3") -> str:
        import os, sys
        from tkinter import messagebox, filedialog

        # 1) Already bundled?
        if os.path.isdir(model_dir):
            return model_dir

        # 2) Ask user: locate or download?
        choice = messagebox.askyesnocancel(
            "Whisper Model Missing",
            f"The model folder was not found at:\n{model_dir}\n\n"
            "Yes: Locate manually\n"
            "No: Download now (~3 GB)\n"
            "Cancel: Exit application"
        )
        if choice is None:
            sys.exit()  # user clicked Cancel
        if choice:  # Yes → browse
            folder = filedialog.askdirectory(title="Select Whisper Model Folder")
            if folder and os.path.isdir(folder):
                return folder
            messagebox.showerror("Invalid Folder", "No model found in that location.")
            sys.exit()

        # 3) No → kick off download
        parent = tk._default_root or tk.Tk()
        downloader = ModelDownloader(parent, repo_id, model_dir)
        downloader.master.withdraw()
        downloader.master.wait_window(downloader)

        if downloader.result is None or isinstance(downloader.result, Exception):
            messagebox.showerror("Download Failed", str(downloader.result))
            sys.exit()

        return model_dir

def load_icon(name, master=None):
    try:
        return tk.PhotoImage(file=os.path.join("icons", f"{name}.png"), master=master)
    except tk.TclError:
        print(f"[WARN] Could not load icon: {name}")
        return None

# ─── ToolTip ────────────────────────────────────────────────────────────────
class ToolTip:    
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self._tip_active = False
        self.match_threshold = tk.DoubleVar(value=10.0)  # default to 10.0 seconds
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)
        self.merge_comments = tk.BooleanVar(value=True)

    def show_tip(self, event=None):
        if self._tip_active or not self.text:
            return
        self._tip_active = True
        self.widget.after(300, self._actually_show_tip)

    def _actually_show_tip(self):
        if self.tipwindow or not self.text:
            self._tip_active = False
            return

        x, y, _, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 20
        y += self.widget.winfo_rooty() + cy + 10

        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            justify='left',
            background="#ffffe0",
            relief='solid',
            borderwidth=1,
            font=("Segoe UI", 8)
        )
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        self._tip_active = False
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None

class SubtitleSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Subtitle Synchroniser v{__version__}")
        self.asr_path = ""

        # ─── Initialize paths and flags ─────────────────────────
        self.video_path      = tk.StringVar()
        self.subtitle_path   = tk.StringVar()
        self.output_path     = tk.StringVar()
        self.export_filename = tk.StringVar(value="—")
        self.flush_lines     = tk.IntVar(value=10)
        self.beam_size       = tk.IntVar(value=5)
        self.match_threshold = tk.DoubleVar(value=10.0)

        self.preview_buffer   = []
        self.whisper_buffer   = []
        self.word_level_asr   = tk.BooleanVar(value=True)
        self.stop_flag        = threading.Event()
        self.auto_scroll_right= True
        self.chunk_size       = tk.IntVar(value=8)
        self.chunk_step       = tk.IntVar(value=2)

        # Update beam display when beam_size changes
        self.beam_size.trace_add("write", lambda *args: self.update_beam_status())

        # ─── Load last‐used file paths ───────────────────────────
        cfg = load_config()
        if cfg.get("video_path"):
            self.video_path.set(cfg["video_path"])
        if cfg.get("subtitle_path"):
            self.subtitle_path.set(cfg["subtitle_path"])
        if cfg.get("output_path"):
            self.output_path.set(cfg["output_path"])

        # ─── Load icons (your existing dictionary) ──────────────
        self.icons = {
            # … your icon setup here …
        }

        # Handle window close (to save config)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # ─── Build UI ───────────────────────────────────────────
        self.create_menu_bar()
        self.create_ribbon()
        self.create_feedback_panel()
        self.create_widgets()

        # Reflect loaded paths in status bar
        self.update_status_bar()
        self.debug("[INFO] READY - all logs will be recorded here.")
  
      
    def on_close(self):
        self.stop_flag.set()        
        self.root.destroy()

    def create_menu_bar(self):
        menu_bar = tk.Menu(self.root)

        # File selection menu
        components_menu = tk.Menu(menu_bar, tearoff=0)
        components_menu.add_command(label="Video File...", command=self.select_video)
        components_menu.add_command(label="Subtitle File...", command=self.select_subtitle)
        components_menu.add_command(label="Export Location...", command=self.select_output)
        menu_bar.add_cascade(label="Select Components", menu=components_menu)

        # Settings menu (flush and beam size)
        settings_menu = tk.Menu(menu_bar, tearoff=0)
        flush_values = [1, 5, 10, 20, 50]
        for val in flush_values:
            settings_menu.add_radiobutton(
                label=f"Flush preview every {val} lines",
                variable=self.flush_lines,
                value=val
            )

        beam_menu = tk.Menu(settings_menu, tearoff=0)
        for val in range(1, 6):
            beam_menu.add_radiobutton(
                label=f"{val}",
                variable=self.beam_size,
                value=val
            )
        settings_menu.add_cascade(label="Beam Size", menu=beam_menu)
        menu_bar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_checkbutton(
            label="Merge [comments] into ASR blocks",
            variable=self.merge_comments,
            onvalue=True,
            offvalue=False
        )        
        settings_menu.add_command(label="Set Sync Tolerance", command=self.set_threshold_dialog)
        chunk_menu = tk.Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label="ASR Chunking", menu=chunk_menu)

        chunk_menu.add_command(
            label="Set Chunk Size...",
            command=self.prompt_chunk_size
        )

        chunk_menu.add_command(
            label="Set Chunk Step...",
            command=self.prompt_chunk_step
        )

        settings_menu.add_checkbutton(
            label="Enable Word-Level ASR Timestamps",
            variable=self.word_level_asr,
            onvalue=True,
            offvalue=False
        )


        # Help menu
        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="Application Overview", command=self.show_app_overview)
        help_menu.add_command(label="Developer Reference", command=self.show_dev_reference)
        menu_bar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menu_bar)

    def set_threshold_dialog(self):
        from tkinter.simpledialog import askfloat

        value = askfloat(
            "Set Sync Tolerance",
            f"Current tolerance: {self.match_threshold.get():.2f} seconds\n\nEnter new max timestamp gap:",
            initialvalue=self.match_threshold.get(),
            minvalue=0.0,
            maxvalue=10.0
        )
        
        if value is not None:
            self.match_threshold.set(value) 
            self.feedback_label.config(text=f"⚙️ Sync tolerance set to {value:.2f} seconds")       

    def create_ribbon(self):
        self.full_sync_btn = None
        self.sync_only_btn = None        
        if self.full_sync_btn:
            self.full_sync_btn.config(state="disabled", bg=self.root.cget("bg"))
       
        ribbon = tk.Frame(self.root, bg="#e6e6e6", relief="raised", bd=1)
        ribbon.grid(row=0, column=0, columnspan=3, sticky="we", padx=2, pady=2)

        btns = [
            ("Import Video", self.select_video, "import_video"),                    
            ("Original Subtitle", self.select_subtitle, "change_left"),
            ("ASR (Whisper) Subtitle", self.select_right_subtitle, "change_right"),
            ("Select Export File", self.select_output, "export"),
            ("ASR (Whisper Only)", self.start_asr_only, "asr_only"),
            ("Full ASR and Sync", self.start_process, "syncred"),
            ("Sync Only", self.sync_only_mode, "syncred"),  # 👈 both start red by default                       
            ("Stop", self.trigger_stop, "stop"), 
            ("Live Scroll", self.enable_auto_scroll, "live_scroll"),          
            ("Reset", self.reset_app, "reset"),
        ]        

        for label, command, icon_key in btns:
            icon = self.icons.get(icon_key)
            btn = tk.Button(ribbon, text=label, image=icon, command=command, **RIBBON_BUTTON_STYLE)
            btn.pack(side="left", padx=2, pady=2)

            if label == "Reset":
                ToolTip(btn, "Clear all files and start over")

            if label == "Live Scroll":
                self.live_scroll_btn = btn
                ToolTip(btn, "Enable auto-scroll to follow ASR output")

            if label == "ASR (Whisper Only)":
                ToolTip(btn, "Run Whisper transcription only — no syncing")

            if label == "Stop":
                self.btn_stop = btn
                self.btn_stop.config(state="disabled")  # Start disabled

            if icon_key == "syncred":
                if "Full ASR" in label:
                    self.full_sync_btn = btn
                elif "Sync Only" in label:
                    self.sync_only_btn = btn
                
                 
    def start_asr_only(self):
        threading.Thread(target=self.run_asr_only).start()                                  

    def create_feedback_panel(self):
        self.feedback_frame = tk.Frame(self.root, bg="#f8f8f8", bd=1, relief="sunken")
        self.feedback_frame.grid(row=99, column=0, columnspan=3, sticky="we")
        self.feedback_label = tk.Label(
            self.feedback_frame,
            text="Ready. Load your files to begin.",
            anchor="w",
            font=("Segoe UI", 9)
        )
        self.feedback_label.pack(side="left", padx=8, pady=4)

        self.export_label = tk.Label(
            self.feedback_frame,
            textvariable=self.export_filename,
            anchor="e",
            font=("Segoe UI", 9, "italic"),
            fg="#666666"
        )
        self.export_label.pack(side="right", padx=8)

    def sync_only_mode(self):
        if not self.subtitle_path.get() or not self.asr_path:
            messagebox.showwarning("Missing Files", "Please load both Original and ASR subtitle files.")
            return

        self.feedback_label.config(text="🔗 Syncing subtitles without Whisper...")
        # Call your sync logic here:
        self.run_sync_only(self.subtitle_path.get(), self.asr_path, self.output_path.get())
        self.export_filename.set(f"Exported: {os.path.basename(self.output_path.get())}")

    def select_right_subtitle(self):
        path = filedialog.askopenfilename(filetypes=[("Subtitle files", "*.srt")])
        if path:
            self.load_subtitle_to_right_pane(path)   
            self.right_label.config(text=f"⭢ Synced Subtitle: {os.path.basename(path)}")  
            self.summarize_srt(path, role="ASR")                  
        self.update_status_bar()
        self.asr_path = path

    def select_subtitle(self):
        path = filedialog.askopenfilename(filetypes=[("Subtitle files", "*.srt")])
        
        if path:
            self.subtitle_path.set(path)
            self.load_subtitle_to_left_pane(path)
            self.left_label.config(text=f"⭠ Original Subtitle: {os.path.basename(path)}")
            self.summarize_srt(path)
            self.debug("[INFO] Subtitle loaded: {}", os.path.basename(path))

            # Only suggest if output path is blank or still a fallback
            if not self.output_path.get() or self.output_path.get().endswith(".merged.srt") or ".MERGE" in self.output_path.get().upper():
                out_path = self.suggest_output_path()
                if out_path:
                    self.output_path.set(out_path)
                    self.export_filename.set(f"Export: {os.path.basename(out_path)}")
                    self.feedback_label.config(text=f"📁 Export path auto-suggested: {os.path.basename(out_path)}")
                    self.debug("[INFO] Suggested export path: {}", os.path.basename(out_path))

            self.update_status_bar()

    def summarize_srt(self, path, role="Original"):
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()

            # Count meaningful (non-blank) lines
            line_count = len([l for l in lines if l.strip()])

            # Extract timestamps only
            timestamps = [
                l.strip().split("-->")[1].strip()
                for l in lines
                if "-->" in l
            ]
            last_time = timestamps[-1] if timestamps else "—"

            self.feedback_label.config(
                text=f"📄 {role} subtitle: {line_count} lines (last timestamp: {last_time})"
            )

        except Exception as e:
            self.feedback_label.config(
                text=f"⚠ Failed to read {role.lower()} subtitle: {e}"
            )

    def show_app_overview(self):
        overview_text = (
            f"Subtitle Synchroniser v{__version__}\n\n"
            "• Synchronize video and subtitle files using Whisper transcription.\n"
            "• View original and generated subtitles side by side.\n"
            "• Edit paths, pause/resume, and control preview flush frequency.\n\n"
            "Ready to roll subtitles into sync!"
        )
        messagebox.showinfo("Application Overview", overview_text)

    def show_dev_reference(self):
        path = "developer_reference.txt"
        if not os.path.exists(path):
            messagebox.showerror("Missing File", "Couldn't find developer_reference.txt in the app folder.")
            return

        with open(path, "r", encoding="utf-8") as f:
            doc = f.read()

        doc_window = tk.Toplevel(self.root)
        doc_window.title("Developer Reference")
        doc_window.geometry("800x500")

        text_widget = tk.Text(doc_window, wrap="word", font=("Segoe UI", 9))
        text_widget.insert("1.0", doc)
        text_widget.config(state="disabled")
        text_widget.pack(expand=True, fill="both")

        scrollbar = ttk.Scrollbar(doc_window, command=text_widget.yview)
        text_widget.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    def create_widgets(self):
        # ─── Subtitle Viewer Frames ───────────────────────────────
        pane_frame = tk.Frame(self.root)
        pane_frame.grid(row=1, column=0, columnspan=3, padx=10, pady=5, sticky="nsew")
        pane_frame.grid_rowconfigure(0, weight=1)
        pane_frame.grid_columnconfigure(0, weight=1)
        pane_frame.grid_columnconfigure(1, weight=1)

        # Left and Right Viewer Frames
        left_frame = tk.Frame(pane_frame)
        left_frame.grid(row=0, column=0, sticky="nsew")
        left_frame.grid_rowconfigure(1, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        right_frame = tk.Frame(pane_frame)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        # Labels
        self.left_label = tk.Label(left_frame, text="🎞 Original Subtitle: —", font=("Segoe UI", 9, "bold"))
        self.left_label.grid(row=0, column=0, sticky="w", padx=(2, 2), pady=(2, 0))

        self.right_label = tk.Label(right_frame, text="🧠 ASR Generated: —", font=("Segoe UI", 9, "bold"))
        self.right_label.grid(row=0, column=0, sticky="w", padx=(2, 2), pady=(2, 0))

        columns = ("index", "timestamp", "text")

        # Left TreeView
        self.left_tree_scroll = ttk.Scrollbar(left_frame, orient="vertical")
        self.left_tree = ttk.Treeview(left_frame, columns=columns, show="headings", yscrollcommand=self.left_tree_scroll.set)
        self.left_tree_scroll.config(command=self.left_tree.yview)
        self.left_tree.grid(row=1, column=0, sticky="nsew")
        self.left_tree_scroll.grid(row=1, column=1, sticky="ns")
        self.left_tree.heading("index", text="#")
        self.left_tree.heading("timestamp", text="Timestamp")
        self.left_tree.heading("text", text="Text")
        self.left_tree.column("index", width=40, anchor="center")
        self.left_tree.column("timestamp", width=180, anchor="center")
        self.left_tree.column("text", width=500, anchor="w")

        # Right TreeView
        self.right_tree_scroll = ttk.Scrollbar(right_frame, orient="vertical")
        self.right_tree = ttk.Treeview(right_frame, columns=columns, show="headings", yscrollcommand=self.right_tree_scroll.set)
        self.right_tree_scroll.config(command=self.right_tree.yview)
        self.right_tree.grid(row=1, column=0, sticky="nsew")
        self.right_tree_scroll.grid(row=1, column=1, sticky="ns")
        self.right_tree.heading("index", text="#")
        self.right_tree.heading("timestamp", text="Timestamp")
        self.right_tree.heading("text", text="Text")
        self.right_tree.column("index", width=40, anchor="center")
        self.right_tree.column("timestamp", width=180, anchor="center")
        self.right_tree.column("text", width=500, anchor="w")
        self.right_tree.bind("<MouseWheel>", self.on_right_tree_scroll)

        # Click Bindings
        self.left_tree.bind("<Button-1>", lambda e: self.on_subtitle_click("left"))
        self.right_tree.bind("<Button-1>", lambda e: self.on_subtitle_click("right"))

        # Timestamp label under right pane
        self.preview_timestamp = tk.Label(pane_frame, text="Last updated: —", font=("Segoe UI", 8), anchor="e")
        self.preview_timestamp.grid(row=1, column=1, sticky="e", padx=(0, 4), pady=(2, 4))

        # ─── Status Strip ─────────────────────────────────────────
        self.status_frame = tk.Frame(self.root, bg="#ffe4e1", relief="sunken", bd=1)
        self.status_frame.grid(row=98, column=0, columnspan=3, sticky="we")

        self.beam_status = tk.Label(self.status_frame, text=f"[{self.beam_size.get()}] Beam", anchor="w", padx=5, font=("Segoe UI", 9))
        self.beam_status.pack(side="left")

        self.video_status = tk.Label(self.status_frame, text="[✗] Video", anchor="w", padx=5, font=("Segoe UI", 9))
        self.video_status.pack(side="left")

        self.subtitle_status = tk.Label(self.status_frame, text="[✗] Subtitle", anchor="w", padx=5, font=("Segoe UI", 9))
        self.subtitle_status.pack(side="left")

        self.output_status = tk.Label(self.status_frame, text="[✗] Export", anchor="w", padx=5, font=("Segoe UI", 9))
        self.output_status.pack(side="left")

        # ─── Progress Bar + Status Label ─────────────────────────
        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=100)
        self.progress.grid(row=3, column=0, columnspan=3, pady=(8, 0))

        self.status_label = tk.Label(self.root, text="Ready", font=("Segoe UI", 9))
        self.status_label.grid(row=4, column=0, columnspan=3, pady=(2, 4))

        # ─── Feedback Console (Moved Below Everything) ────────────
        self.feedback_console = tk.Text(self.root, height=6, bg="#fdfdfd", fg="#333333", wrap="word", font=("Consolas", 9))
        self.feedback_console.grid(row=100, column=0, columnspan=3, sticky="nsew", padx=10, pady=(4, 0))
        self.feedback_console.config(state="disabled")

        # Tag configs
        self.feedback_console.tag_config("debug", foreground="#555555")
        self.feedback_console.tag_config("warn", foreground="#c28a00")
        self.feedback_console.tag_config("error", foreground="#d00000")
        self.feedback_console.tag_config("info", foreground="#1e60a2")
        self.feedback_console.tag_config("success", foreground="#007f5f")

        # Log controls
        log_controls = tk.Frame(self.root)
        log_controls.grid(row=101, column=0, columnspan=3, sticky="e", padx=10, pady=(2, 8))

        clear_btn = tk.Button(log_controls, text="🧹 Clear Log", command=self.clear_feedback_console)
        clear_btn.pack(side="left", padx=(0, 5))

        save_btn = tk.Button(log_controls, text="💾 Save Log", command=self.save_feedback_console)
        save_btn.pack(side="left")

        # Final layout weights
        self.root.grid_rowconfigure(1, weight=1)  # center pane
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_columnconfigure(2, weight=1)

        self.debug("[INFO] READY - all logs will be recorded here.")


    def log_feedback(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}\n"

        if "[ERROR]" in msg:
            tag = "error"
        elif "[WARN]" in msg:
            tag = "warn"
        elif "[INFO]" in msg:
            tag = "info"
        elif "[SUCCESS]" in msg or "✅" in msg:
            tag = "success"
        else:
            tag = "debug"

        self.feedback_console.config(state="normal")
        self.feedback_console.insert("end", line, (tag,))
        self.feedback_console.see("end")
        self.feedback_console.config(state="disabled")

    def reset_app(self):
        self.video_path.set("")
        self.subtitle_path.set("")
        self.output_path.set("")
        self.asr_path = ""
        self.export_filename.set("—")

        self.left_label.config(text="🎞 Original Subtitle: —")
        self.right_label.config(text="🧠 ASR Generated: —")
        self.preview_timestamp.config(text="Last updated: —")

        self.left_tree.delete(*self.left_tree.get_children())
        self.right_tree.delete(*self.right_tree.get_children())

        self.feedback_label.config(text="🧹 Reset complete. Ready to go again!")
        self.status_label.config(text="Ready", fg="black", font=("Segoe UI", 9))
        self.status_frame.config(bg="#ffe4e1")
        self.progress["value"] = 0
        if self.full_sync_btn:
            self.full_sync_btn.config(state="disabled", bg=self.root.cget("bg"))

        self.update_status_bar()
        
    def select_video(self):
        path = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.mkv *.avi")])
        if path:
            self.video_path.set(path)
            self.check_file_pairing_status()

            self.debug("[INFO] Video loaded: {}", os.path.basename(path))
            if self.output_path.get():
                self.debug("[INFO] Export file already selected: {}", os.path.basename(self.output_path.get()))
                self.update_status_bar()

            # Only suggest if user hasn't set it manually
            if not self.output_path.get() or self.output_path.get().endswith(".merged.srt") or ".MERGE" in self.output_path.get().upper():
                out_path = self.suggest_output_path()
                if out_path:
                    self.output_path.set(out_path)
                    self.export_filename.set(f"Export: {os.path.basename(out_path)}")
                    self.feedback_label.config(text=f"📁 Export path auto-suggested: {os.path.basename(out_path)}")
                    self.debug("[INFO] Suggested export path: {}", os.path.basename(out_path))           

    def on_subtitle_click(self, pane):
        if pane == "left":
            path = self.subtitle_path.get()
            label = "Original"
        else:
            path = self.asr_path
            label = "ASR"

        if os.path.exists(path):
            self.summarize_srt(path, label)
        else:
            self.feedback_label.config(text=f"⚠ No {label.lower()} file loaded.")

    def check_file_pairing_status(self):
        if self.video_path.get() and self.output_path.get():
            self.debug(
                "[INFO] Video loaded: {} and export file selected: {}",
                os.path.basename(self.video_path.get()),
                os.path.basename(self.output_path.get())
            )

    def load_subtitle_to_left_pane(self, path):
        import re
        self.left_tree.delete(*self.left_tree.get_children())

        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load subtitle:\n{e}")
            return

        i = 0
        while i < len(lines):
            if lines[i].isdigit():
                index = lines[i]
                timestamp = lines[i + 1] if i + 1 < len(lines) else ""
                text_lines = []
                j = i + 2
                while j < len(lines) and lines[j].strip():
                    text_lines.append(lines[j])
                    j += 1
                self.left_tree.insert("", "end", values=(index, timestamp, " ".join(text_lines)))
                i = j + 1
            else:
                i += 1

    def load_subtitle_to_right_pane(self, path):
        self.right_tree.delete(*self.right_tree.get_children())
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            self.status_label.config(text="Error reading Whisper output")
            return

        i = 0
        while i < len(lines):
            if lines[i].isdigit():
                index = lines[i]
                timestamp = lines[i + 1] if i + 1 < len(lines) else ""
                text_lines = []
                j = i + 2
                while j < len(lines) and lines[j].strip():
                    text_lines.append(lines[j])
                    j += 1
                self.right_tree.insert("", "end", values=(index, timestamp, " ".join(text_lines)))
                if self.auto_scroll_right:
                    self.right_tree.yview_moveto(1.0)
                i = j + 1
            else:
                i += 1


    def select_output(self):
        # Pick base name from video if available, otherwise subtitle
        if self.video_path.get():
            base_name = os.path.splitext(os.path.basename(self.video_path.get()))[0]
            beam = self.beam_size.get()
            suggested_name = f"{base_name}.SYNC{beam:02}.srt"
        elif self.subtitle_path.get():
            base_name = os.path.splitext(os.path.basename(self.subtitle_path.get()))[0]
            suggested_name = f"{base_name}.merged.srt"
        else:
            suggested_name = "output.srt"

        path = filedialog.asksaveasfilename(
            defaultextension=".srt",
            filetypes=[("Subtitle files", "*.srt")],
            initialfile=suggested_name
        )
        
        if path:
            self.output_path.set(path)
            self.check_file_pairing_status()

            if self.video_path.get():
                self.debug("[INFO] Export file selected: {} (video already loaded: {})", os.path.basename(path), os.path.basename(self.video_path.get()))
            self.export_filename.set(f"Export: {os.path.basename(path)}")
            self.feedback_label.config(
                text=f"📁 Export path set: {os.path.basename(path)}"
            )
            self.update_status_bar()
        else:
            self.feedback_label.config(text="📁 No export file was selected.")
            self.export_filename.set("—")

            try:
                if path:
                    self.output_path.set(path)
                    self.export_filename.set(f"Export: {os.path.basename(path)}")
                    self.feedback_label.config(text=f"📁 Export path set: {os.path.basename(path)}")
                    self.update_status_bar()
                else:
                    print("⚠️ No export file selected.")
            except Exception as e:
                print(f"Export path selection error: {e}")
                self.feedback_label.config(text=f"❌ Failed to set export path: {e}")

    def update_status_bar(self):
        paths = {
            "video": self.video_path.get(),
            "subtitle": self.subtitle_path.get(),
            "export": self.output_path.get()
        }     

        # Update [Full ASR and Sync] button icon
        if self.full_sync_btn:
            ready = self.video_path.get() and self.subtitle_path.get() and self.output_path.get()
            icon = self.icons["syncgreen"] if ready else self.icons["syncred"]
            self.full_sync_btn.config(image=icon)

        # Update [Sync Only] button icon
        if self.sync_only_btn:
            ready = self.subtitle_path.get() and self.asr_path and self.output_path.get()
            icon = self.icons["sync"] if ready else self.icons["syncred"]
            self.sync_only_btn.config(image=icon)

        def label_status(p): return "[✓]" if p else "[✗]"   #what is this - not called anywhere

        self.video_status.config(text=f"{label_status(paths['video'])} Video")
        self.subtitle_status.config(text=f"{label_status(paths['subtitle'])} Subtitle")
        self.output_status.config(text=f"{label_status(paths['export'])} Export")

        ToolTip(self.video_status, paths["video"] or "No video selected")
        ToolTip(self.subtitle_status, paths["subtitle"] or "No subtitle selected")
        ToolTip(self.output_status, paths["export"] or "No export path selected")
        ToolTip(self.export_label, self.output_path.get())

        all_ok = all(paths.values())
        self.status_frame.config(bg="#d0ffd0" if all_ok else "#ffe4e1")
        
    def update_beam_status(self):
        beam = self.beam_size.get()
        self.beam_status.config(text=f"[{beam}] Beam")

    def start_process(self):
        # Validate required input paths
        if not (self.video_path.get() and self.subtitle_path.get() and self.output_path.get()):
            messagebox.showwarning("Missing Info", "Please select all files and paths.")
            return

        # Launch synchronization in a separate thread
        threading.Thread(target=self.run_sync, daemon=True).start()

        # Disable sync buttons to prevent overlap
        if self.full_sync_btn:
            self.full_sync_btn.config(state="disabled", bg=self.root.cget("bg"))
        if self.sync_only_btn:
            self.sync_only_btn.config(state="disabled")

        # Update feedback UI
        self.feedback_label.config(text="🟢 Synchronization started...")

    def run_asr_only(self):
        """
        Extract audio → run Whisper ASR → dump an .srt
        """
        # enable Stop button
        self.set_stop_enabled(True)

        try:
            self.debug("[INFO] run_asr_only() starting…")

            # 1) Ensure model & ffmpeg
            repo_id, model_dir = "openai/whisper-large-v3", "models/whisper-large-v3"
            model_path = ModelDownloader.ensure_model(repo_id, model_dir)
            self.debug("[INFO] Whisper model at {}", model_path)

            ffmpeg_path = find_ffmpeg()
            self.debug("[INFO] Using ffmpeg at {}", ffmpeg_path)

            # 2) Extract audio
            self.status_label.config(text="🎙️ Extracting audio…")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name
            ffmpeg.input(self.video_path.get()) \
                .output(wav_path, format="wav", acodec="pcm_s16le", ac=1, ar="16000") \
                .run(cmd=ffmpeg_path, overwrite_output=True)

            # 3) Transcribe streaming into UI
            self.attach_whisper_logger()
            model = WhisperModel(model_path, compute_type="int8")
            segments = self.capture_transcribe_output(model, wav_path)
            self.detach_whisper_logger()

            # 4) Write out .srt
            out_path = self.output_path.get()
            with open(out_path, "w", encoding="utf-8", newline="\r\n") as f:
                for i, seg in enumerate(segments, start=1):
                    s, e = self.format_timestamp(seg.start), self.format_timestamp(seg.end)
                    f.write(f"{i}\r\n{s} --> {e}\r\n{seg.text.strip()}\r\n\r\n")

            # Done
            self.feedback_label.config(text=f"✅ ASR-only complete → {os.path.basename(out_path)}")
            self.status_label.config(text="✔ ASR complete", fg="#2e7d32")
            self.progress["value"] = 100
            self.debug("[INFO] run_asr_only() finished successfully")

        except Exception:
            tb = traceback.format_exc()
            self.debug("[ERROR] run_asr_only() crashed:\n{}", tb)
            self.feedback_label.config(text="❌ ASR-only failed — see log")

        finally:
            # always disable Stop when done
            self.set_stop_enabled(False)


    def run_sync(self):
        """
        Full pipeline: extract audio, run ASR, then merge with original subtitles
        """
        self.set_stop_enabled(True)

        try:
            self.debug("[INFO] run_sync() starting…")

            # 1) Ensure model & ffmpeg
            repo_id, model_dir = "openai/whisper-large-v3", "models/whisper-large-v3"
            model_path = ModelDownloader.ensure_model(repo_id, model_dir)
            self.debug("[INFO] Whisper model at {}", model_path)

            ffmpeg_path = find_ffmpeg()
            self.debug("[INFO] Using ffmpeg at {}", ffmpeg_path)

            # 2) Extract audio
            self.status_label.config(text="🔁 Extracting audio…")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name
            ffmpeg.input(self.video_path.get()) \
                .output(wav_path, format="wav", acodec="pcm_s16le", ac=1, ar="16000") \
                .run(cmd=ffmpeg_path, overwrite_output=True)

            # 3) Transcribe streaming into UI
            self.attach_whisper_logger()
            model = WhisperModel(model_path, compute_type="int8")
            segments = self.capture_transcribe_output(model, wav_path)
            self.detach_whisper_logger()

            # 4) Write temporary ASR .srt
            temp_asr = tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w", encoding="utf-8", newline="\r\n")
            for idx, seg in enumerate(segments, start=1):
                s, e = self.format_timestamp(seg.start), self.format_timestamp(seg.end)
                temp_asr.write(f"{idx}\r\n{s} --> {e}\r\n{seg.text.strip()}\r\n\r\n")
            temp_asr.close()

            # 5) Merge with original
            self.status_label.config(text="🔗 Synchronizing subtitles…")
            with open(self.subtitle_path.get(), encoding="utf-8") as orig_f:
                orig_lines = orig_f.readlines()
            with open(temp_asr.name, encoding="utf-8") as asr_f:
                asr_lines = asr_f.readlines()

            merged = self.merge_subtitles(orig_lines, asr_lines)
            with open(self.output_path.get(), "w", encoding="utf-8", newline="\r\n") as out:
                out.writelines(merged)

            # Done
            self.feedback_label.config(text="✅ Full sync complete.")
            self.status_label.config(text="✔ Sync complete", fg="#2e7d32")
            self.progress["value"] = 100
            self.debug("[INFO] run_sync() finished successfully")

        except Exception:
            tb = traceback.format_exc()
            self.debug("[ERROR] run_sync() crashed:\n{}", tb)
            self.feedback_label.config(text="❌ Sync failed — see log")

        finally:
            self.set_stop_enabled(False)

            
    def debug(self, msg, *args):
        formatted = msg.format(*args)
        print(formatted, flush=True)
        # Schedule log_feedback safely in the main thread
        self.root.after(0, lambda text=formatted: self.log_feedback(text))

    def run_sync_only(self, original_path, asr_path, output_path):
        self.status_label.config(text="Syncing existing subtitle files...")
        self.status_frame.config(bg="#ffe4e1")
        self.feedback_label.config(text="🔁 Comparing and synchronizing subtitles…")
        self.progress["value"] = 15
        self.root.update_idletasks()

        try:
            with open(original_path, encoding="utf-8") as orig_file:
                original_lines = orig_file.readlines()
            with open(asr_path, encoding="utf-8") as asr_file:
                asr_lines = asr_file.readlines()

            # ✨ TODO: Replace this with actual sync logic (e.g. match timestamps, align text, etc.)
            synced_lines = self.merge_subtitles(original_lines, asr_lines)

            with open(output_path, "w", encoding="utf-8") as out_file:
                out_file.writelines(synced_lines)

            self.feedback_label.config(text="✅ Sync-only completed successfully.")
            self.status_label.config(text="✔ Sync complete.", fg="#2e7d32", font=("Segoe UI", 9, "bold"))
            self.progress["value"] = 100
            self.flash_status_success()

            self.load_subtitle_to_right_pane(output_path)
            self.right_label.config(text=f"🧠 ASR Generated: {os.path.basename(asr_path)}")
            
            self.update_status_bar()

            if os.path.exists(asr_path) and os.path.getsize(asr_path) > 0:
                self.load_subtitle_to_right_pane(asr_path)
                with open(asr_path, encoding="utf-8") as f:
                    line_count = len(f.readlines())
                ToolTip(self.right_label, f"{line_count} lines generated")
            else:
                self.feedback_label.config(text="⚠️ ASR complete, but no data written — check audio content?")



        except Exception as e:
            self.feedback_label.config(text=f"❌ Sync-only failed: {str(e)}")
            self.status_label.config(text="⚠ Error during sync", fg="red")
            self.progress["value"] = 0  

    def merge_subtitles(self, original_lines, asr_lines):
        from datetime import datetime

        original_blocks = self.parse_srt_blocks(original_lines)
        asr_blocks = self.parse_srt_blocks(asr_lines)
        chunks = self.chunk_asr_blocks(asr_blocks, self.chunk_size.get(), self.chunk_step.get())
        threshold = self.match_threshold.get()
        confidence_threshold = 0.5  # 🔧 Adjustable later

        result = []
        index = 1
        matched_map = set()  # zero-based indexes of original_blocks that were matched

        for i, orig in enumerate(original_blocks):
            orig_text = orig["text"].strip()
            if not orig_text:
                continue

            # Preserve comments unmodified
            if orig_text.startswith("[") and orig_text.endswith("]") and self.merge_comments.get():
                result.extend([
                    f"{index}",
                    f"{orig['start']} --> {orig['end']}",
                    orig_text,
                    ""
                ])
                index += 1
                continue

            best_chunk = None
            best_score = 0.0

            for chunk in chunks:
                score = self.token_match_score(orig_text, chunk["text"])
                if score > best_score and score >= confidence_threshold:
                    best_score = score
                    best_chunk = chunk

            if best_chunk:
                result.append({
                    "index": index,
                    "start": best_chunk["start"],
                    "end": best_chunk["end"],
                    "text": orig_text
                })
                matched_map.add(i)
            else:
                # Temporarily store with original timing, to be adjusted
                result.append({
                    "index": index,
                    "start": orig["start"],
                    "end": orig["end"],
                    "text": orig_text
                })

            index += 1

        # 🔁 Adjust unmatched blocks based on neighbors
        adjusted_blocks = self.adjust_unmatched_timing(result, matched_map)

        # 🔄 Format as final SRT-ready lines
        srt_lines = []
        for block in adjusted_blocks:
            srt_lines.extend([
                str(block["index"]),
                f"{block['start']} --> {block['end']}",
                block["text"],
                ""
            ])

        self.feedback_label.config(
            text=f"🔗 Realignment complete: {len(matched_map)}/{len(original_blocks)} lines retimed"
        )
        return [line + "\n" for line in srt_lines]
    
    def parse_srt_blocks(self, lines):
        blocks = []
        block = {"index": "", "start": "", "end": "", "text": ""}
        state = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if block["text"]:
                    blocks.append(block)
                    block = {"index": "", "start": "", "end": "", "text": ""}
                state = 0
            elif state == 0:
                block["index"] = stripped
                state = 1
            elif state == 1:
                try:
                    block["start"], block["end"] = [t.strip() for t in stripped.split("-->")]
                    state = 2
                except:
                    continue
            else:
                block["text"] += stripped + " "

        if block["text"]:
            blocks.append(block)

        return blocks                    

    def trigger_stop(self):
        if not self.status_label.cget("text").lower().startswith(("transcribing", "running", "synchronizing", "syncing")):
            self.feedback_label.config(text="⚠️ Nothing is currently running.")
            return

        self.stop_flag.set()
        self.status_label.config(text="Stopping...")
        self.feedback_label.config(text="🛑 Stopping process…")
        # Disable active buttons to prevent race conditions
        self.set_ribbon_enabled(False)


    def enable_auto_scroll(self):
        self.auto_scroll_right = True
        self.live_scroll_btn.config(state="disabled")

    def on_right_tree_scroll(self, event):
        self.auto_scroll_right = False
        self.live_scroll_btn.config(state="normal")

    def pulse_start_button(self, count=0):
        if not hasattr(self, "start_button"):
            return
        colors = ["#d0ffd0", "#b0f0b0"]
        self.start_button.config(bg=colors[count % 2])
        if self.start_button["state"] == "normal":
            self.root.after(500, lambda: self.pulse_start_button(count + 1))
        else:
            self.start_button.config(bg=self.root.cget("bg"))

    def format_timestamp(self, seconds):
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hrs:02}:{mins:02}:{secs:02},{millis:03}"

    def get_audio_duration(self, path):
        with wave.open(path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / float(rate)

    def flash_status_success(self):
        self.status_label.config(bg="#d0f0c0")
        self.root.after(800, lambda: self.status_label.config(bg=self.root.cget("bg")))

    def safe_icon(path):
        try:
            return tk.PhotoImage(file=path)
        except tk.TclError:
            print(f"⚠️ Warning: could not load {path}")
            return None   
        
    def token_match_score(self, original, candidate):
        def clean_token(token):
            # Remove punctuation but preserve contractions (e.g., "don't")
            return re.sub(r"[^\w']+", "", token).lower()

        if not original or not candidate:
            return 0.0

        a_words = set(clean_token(w) for w in original.split() if w.strip())
        b_words = set(clean_token(w) for w in candidate.split() if w.strip())

        shared = a_words & b_words
        return len(shared) / max(len(a_words), 1)

 
    def chunk_asr_blocks(self, asr_blocks, chunk_size=8, step=2):
        chunks = []
        for block in asr_blocks:
            words = block["text"].split()
            for i in range(0, len(words) - chunk_size + 1, step):
                chunk = " ".join(words[i:i + chunk_size])
                chunks.append({
                    "text": chunk,
                    "start": block["start"],
                    "end": block["end"]
                })
        return chunks    
    
    def prompt_chunk_size(self):
        value = simpledialog.askinteger(
            "Set Chunk Size",
            f"Current value: {self.chunk_size.get()}\n\nEnter number of words per ASR chunk:",
            initialvalue=self.chunk_size.get(),
            minvalue=1, maxvalue=30
        )
        if value:
            self.chunk_size.set(value)

    def prompt_chunk_step(self):
        value = simpledialog.askinteger(
            "Set Chunk Step",
            f"Current value: {self.chunk_step.get()}\n\nEnter overlap step size (lower = more precision):",
            initialvalue=self.chunk_step.get(),
            minvalue=1, maxvalue=self.chunk_size.get()
        )
        if value:
                self.chunk_step.set(value)    
                            
      
    def transcribe_whisper(self, audio_path):
        model = WhisperModel("large-v3", compute_type="int8")
        return model.transcribe(
            audio_path,
            beam_size=self.beam_size.get(),
            word_timestamps=self.word_level_asr.get()
        )
        
    def clear_feedback_console(self):
        self.feedback_console.config(state="normal")
        self.feedback_console.delete("1.0", "end")
        self.feedback_console.config(state="disabled")

    def save_feedback_console(self):
        from tkinter import filedialog
        log_text = self.feedback_console.get("1.0", "end").strip()
        if not log_text:
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            title="Save Feedback Log"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(log_text)
                self.log_feedback(f"[SUCCESS] Log saved to {os.path.basename(file_path)}")
            except Exception as e:
                    self.log_feedback(f"[ERROR] Could not save log: {e}")  

    def attach_whisper_logger(self, tag="[WHISPER]"):
        import logging

        class GuiLogHandler(logging.Handler):
            def __init__(self, app): super().__init__(); self.app = app
            def emit(self, record):
                msg = self.format(record)
                self.app.root.after(0, lambda: self.app.log_feedback(f"{tag} {msg}"))

        whisper_logger = logging.getLogger("faster_whisper")
        whisper_logger.setLevel(logging.DEBUG)
        whisper_logger.propagate = False

        gui_handler = GuiLogHandler(self)
        gui_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        whisper_logger.addHandler(gui_handler)
        self._whisper_log_handler = gui_handler  # Save for cleanup later
    
    def detach_whisper_logger(self):
        import logging
        whisper_logger = logging.getLogger("faster_whisper")
        if hasattr(self, "_whisper_log_handler"):
            whisper_logger.removeHandler(self._whisper_log_handler)
            del self._whisper_log_handler

    def suggest_output_path(self):
        video = self.video_path.get()
        sub = self.subtitle_path.get()

        if video:
            base = os.path.splitext(os.path.basename(video))[0]
            beam = self.beam_size.get()
            granularity = "W" if self.word_level_asr.get() else "S"
            tag = f"ASR{beam:02}{granularity}"
            return os.path.join(os.path.dirname(video), f"{base}.{tag}.srt")
        elif sub:
            base = os.path.splitext(os.path.basename(sub))[0]
            return os.path.join(os.path.dirname(sub), f"{base}.merged.srt")
        return ""           
    
    def capture_transcribe_output(self, model, audio_path):
        segments = []
        total_duration = self.get_audio_duration(audio_path)
        start_time = time.time()

        def update_ui(segment):
            if not hasattr(segment, "text") or not segment.text.strip():
                return
            timestamp = f"{self.format_timestamp(segment.start)} --> {self.format_timestamp(segment.end)}"
            text = segment.text.strip()[:80]  # Truncate for preview
            index = len(segments) + 1
            self.root.after(0, lambda: self.right_tree.insert("", "end", values=(index, timestamp, text)))
            percent = min((segment.end / total_duration) * 100, 100)
            elapsed = time.time() - start_time
            self.root.after(0, lambda: self.progress.config(value=percent))
            self.root.after(0, lambda: self.status_label.config(text=f"Transcribing… {percent:.1f}%"))
            self.root.after(0, lambda: self.feedback_label.config(text=f"💬 Whisper preview: {percent:.1f}%"))

        for segment in self.interruptible_transcribe(model, audio_path, on_segment=update_ui):
            segments.append(segment)
            if self.stop_flag.is_set():
                self.debug("[INFO] capture_transcribe_output() interrupted at segment {}", len(segments))
                break

        return segments

    def set_stop_enabled(self, enabled):
        if hasattr(self, "btn_stop") and self.btn_stop:
            self.btn_stop.config(state="normal" if enabled else "disabled")    
    
    def is_transcribing(self):
        return "transcrib" in self.status_label.cget("text").lower() or "sync" in self.status_label.cget("text").lower()

    def set_ribbon_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        if hasattr(self, "full_sync_btn") and self.full_sync_btn:
            self.full_sync_btn.config(state=state)
        if hasattr(self, "sync_only_btn") and self.sync_only_btn:
            self.sync_only_btn.config(state=state)
        if hasattr(self, "btn_stop") and self.btn_stop:
            self.btn_stop.config(state=state)    

    def clean_word(self, text):
        # Removes punctuation but preserves contractions (e.g., "don't")
        return re.sub(r"[^\w']+", "", text).strip()    
    
    def interruptible_transcribe(self, model, audio_path, on_segment=None):
        try:
            segment_gen, _ = model.transcribe(
                audio_path,
                beam_size=self.beam_size.get(),
                word_timestamps=True
            )
            for segment in segment_gen:
                if self.stop_flag.is_set():
                    self.debug("[INFO] Transcription interrupted by user flag.")
                    break
                if on_segment:
                    on_segment(segment)
                yield segment
        except Exception as e:
            self.debug("[ERROR] Transcription error: {}", e)    

    def adjust_unmatched_timing(self, original_blocks, matched_map):
        adjusted = []

        for i, block in enumerate(original_blocks):
            if i not in matched_map:
                # Try to find nearby matched neighbors
                prev = next((j for j in range(i - 1, -1, -1) if j in matched_map), None)
                next_ = next((j for j in range(i + 1, len(original_blocks)) if j in matched_map), None)

                if prev is not None and next_ is not None:
                    prev_end = self.parse_srt_time(original_blocks[prev]["end"])
                    next_start = self.parse_srt_time(original_blocks[next_]["start"])
                    duration = self.parse_srt_time(block["end"]) - self.parse_srt_time(block["start"])

                    # Choose midpoint or best-fit within gap
                    mid = prev_end + ((next_start - prev_end - duration) / 2)
                    new_start = max(prev_end + 0.1, mid)
                    new_end = min(new_start + duration, next_start - 0.1)

                    block["start"] = self.format_timestamp(new_start)
                    block["end"] = self.format_timestamp(new_end)
                    block["adjusted"] = True  # Optional: for tagging in UI
                else:
                    block["adjusted"] = False  # No safe neighbors, leave as-is

            adjusted.append(block)

        return adjusted   

    def create_menu_bar(self):
        menu_bar = tk.Menu(self.root)
        # … existing menus …
        pref_menu = tk.Menu(menu_bar, tearoff=0)
        pref_menu.add_command(label="Clear Saved Paths", command=self.clear_saved_paths)
        menu_bar.add_cascade(label="Preferences", menu=pref_menu)
        self.root.config(menu=menu_bar)

    def clear_saved_paths(self):
        if messagebox.askyesno("Clear Defaults", "Remove saved file paths?"):
            try:
                os.remove(CONFIG_PATH)
            except:
                pass
            self.video_path.set(""); self.subtitle_path.set(""); self.output_path.set("")
            self.update_status_bar()
            self.feedback_label.config(text="⚙️ Saved paths cleared.")        

    def parse_srt_time(self, ts):
        from datetime import datetime
        t = datetime.strptime(ts.strip(), "%H:%M:%S,%f")
        return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1_000_000                


if __name__ == "__main__":
    root = tk.Tk()  
    app = SubtitleSyncApp(root)
    root.mainloop()                