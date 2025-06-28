from version import __versionMinor__  # type: ignore
__version__ = __versionMinor__  + "30"
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
logging.basicConfig(level=logging.DEBUG)

from huggingface_hub import snapshot_download
# from hf_transfer import HfDownloadConfig


def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

icon_path = os.path.join("icons", "import_video.png")

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
            def update_progress(dl):
                pct = int((dl.bytes_downloaded / dl.bytes_total) * 100)
                self.status_label.config(text=f"Downloading… {pct}%")
                self.progress.config(mode="determinate", value=pct)
                self.update_idletasks()

            path = snapshot_download(
                repo_id=self.model_id,
                cache_dir=self.model_dir,
                local_dir=self.model_dir,
                local_dir_use_symlinks=False,
                progress_callback=update_progress
            )
            if not self.cancelled:
                self.result = path
                self.destroy()
        except Exception as e:
            self.result = e
            self.destroy()

def ensure_model(model_dir="models/whisper-large-v3"):
    if os.path.exists(model_dir):
        return model_dir

    from tkinter import messagebox
    model_size_gb = 2.95
    est_time = "5–20 minutes"

    proceed = messagebox.askyesno(
        title="Whisper Model Required",
        message=(
            f"The Whisper model was not found at:\n{model_dir}\n\n"
            f"⬇ Estimated size: ~{model_size_gb} GB\n"
            f"⏳ Estimated time: {est_time}\n\n"
            "Would you like to download it now?"
        )
    )
    if not proceed:
        messagebox.showinfo("Cancelled", "Model download cancelled.")
        sys.exit()

    # Show download window
    root = tk.Toplevel()  # hidden
    root.withdraw()
    win = ModelDownloader(root, "openai/whisper-large-v3", model_dir)
    root.wait_window(win)

    if win.result is None:
        sys.exit()
    elif isinstance(win.result, Exception):
        messagebox.showerror("Download Failed", str(win.result))
        sys.exit()
    else:
        return model_dir

def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def load_icon(name, mode="light"):
    fname = f"{name}{'_dark' if mode == 'dark' else ''}.png"
    return tk.PhotoImage(file=os.path.join("icons", fname))

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
        self.video_path = tk.StringVar()
        self.subtitle_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.export_filename = tk.StringVar(value="—")
        self.flush_lines = tk.IntVar(value=10)
        self.beam_size = tk.IntVar(value=5)

        self.match_threshold = tk.DoubleVar(value=10.0)  # default threshold in seconds        

        self.preview_buffer = []
        self.whisper_buffer = []
        self.word_level_asr = tk.BooleanVar(value=True)

        self.pause_flag = threading.Event()
        self.stop_flag = threading.Event()
        self.auto_scroll_right = True

        self.chunk_size = tk.IntVar(value=8)
        self.chunk_step = tk.IntVar(value=2)        

        self.beam_size.trace_add("write", lambda *args: self.update_beam_status())

        self.icons = {
    "import_video": tk.PhotoImage(file=resource_path("icons/import_video.png")),
    "import_subtitle": tk.PhotoImage(file=resource_path("icons/import_subtitle.png")),
    "export": tk.PhotoImage(file=resource_path("icons/export.png")),
    "sync": tk.PhotoImage(file=resource_path("icons/syncred.png")),
    "sync_only": tk.PhotoImage(file=resource_path("icons/syncred.png")),    
    "pause": tk.PhotoImage(file=resource_path("icons/pause.png")),
    "stop": tk.PhotoImage(file=resource_path("icons/stop.png")),
    "change_left": tk.PhotoImage(file=resource_path("icons/left_arrow.png")),
    "change_right": tk.PhotoImage(file=resource_path("icons/right_arrow.png")),
    "syncred": tk.PhotoImage(file=resource_path("icons/syncred.png")),     # for NOT ready states
    "sync": tk.PhotoImage(file=resource_path("icons/sync.png")),           # for ready states
    "syncgreen": tk.PhotoImage(file=resource_path("icons/syncgreen.png")),
    "sync_only": tk.PhotoImage(file=resource_path("icons/sync.png")),  # ✅ Always this,
    "live_scroll": tk.PhotoImage(file=resource_path("icons/live_scroll.png")),
    "asr_only": tk.PhotoImage(file=resource_path("icons/asr_only.png")),    
    "reset": tk.PhotoImage(file=resource_path("icons/broom.png")),
}
        self.merge_comments = tk.BooleanVar(value=True)

        # ─── Menu Bar ────────────────────────────────────────────
        self.create_menu_bar()

        # ─── Ribbon Toolbar ──────────────────────────────────────
        self.create_ribbon()

        # ─── Feedback Panel ──────────────────────────────────────
        self.create_feedback_panel()   # 👈 this sets up self.export_label

        # ─── Subtitle Viewer Panes and Controls ──────────────────
        self.create_widgets()       
    
    def load_icon(path, master):
        try:
            return tk.PhotoImage(file=path, master=master)
        except tk.TclError as e:
            print(f"⚠ Couldn’t load icon: {path}")
            return None

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
            ("Pause", self.toggle_pause, "pause"),
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

            if icon_key == "syncred":
                if "Full ASR" in label:
                    self.full_sync_btn = btn
                elif "Sync Only" in label:
                    self.sync_only_btn = btn   
                #if "Reset" in label:
                #    ToolTip(btn, "Clear all files and start over")        
                 
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
            self.summarize_srt(path)  # uses default "Original"
        
            # If output path is empty, suggest a default export name
        if not self.output_path.get():
            base = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(os.path.dirname(path), f"{base}.merged.srt")
            self.output_path.set(out_path)
            self.feedback_label.config(text=f"📁 Export path auto-set: {os.path.basename(out_path)}")

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

        # Left Subtitle Viewer
        left_frame = tk.Frame(pane_frame)
        left_frame.grid(row=0, column=0, sticky="nsew")
        left_frame.grid_rowconfigure(1, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        # Right Subtitle Viewer
        right_frame = tk.Frame(pane_frame)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        # Left subtitle label
        self.left_label = tk.Label(left_frame, text="🎞 Original Subtitle: —", font=("Segoe UI", 9, "bold"))
        self.left_label.grid(row=0, column=0, sticky="w", padx=(2, 2), pady=(2, 0))
        left_frame.grid_rowconfigure(0, weight=0)  # 👈 Prevent vertical expansion

        # Right subtitle label
        self.right_label = tk.Label(right_frame, text="🧠 ASR Generated: —", font=("Segoe UI", 9, "bold"))
        self.right_label.grid(row=0, column=0, sticky="w", padx=(2, 2), pady=(2, 0))
        right_frame.grid_rowconfigure(0, weight=0)  # 👈 Prevent vertical expansion      

        columns = ("index", "timestamp", "text")

        # Left TreeView
        self.left_tree_scroll = ttk.Scrollbar(left_frame, orient="vertical")
        self.left_tree = ttk.Treeview(
            left_frame,
            columns=columns,
            show="headings",
            yscrollcommand=self.left_tree_scroll.set
        )
        self.left_tree_scroll.config(command=self.left_tree.yview)
        self.left_tree.grid(row=1, column=0, sticky="nsew")
        self.left_tree_scroll.grid(row=1, column=1, sticky="ns")  # changed from row=0 ➜ row=1
        self.left_tree.heading("index", text="#")
        self.left_tree.heading("timestamp", text="Timestamp")
        self.left_tree.heading("text", text="Text")
        self.left_tree.column("index", width=40, anchor="center")
        self.left_tree.column("timestamp", width=180, anchor="center")
        self.left_tree.column("text", width=500, anchor="w")

        # Right TreeView
        self.right_tree_scroll = ttk.Scrollbar(right_frame, orient="vertical")
        self.right_tree = ttk.Treeview(
            right_frame,
            columns=columns,
            show="headings",
            yscrollcommand=self.right_tree_scroll.set
        )
        self.right_tree_scroll.config(command=self.right_tree.yview)
        self.right_tree.grid(row=1, column=0, sticky="nsew")
        self.right_tree_scroll.grid(row=1, column=1, sticky="ns")  # changed from row=0 ➜ row=1
        self.right_tree.heading("index", text="#")
        self.right_tree.heading("timestamp", text="Timestamp")
        self.right_tree.heading("text", text="Text")
        self.right_tree.column("index", width=40, anchor="center")
        self.right_tree.column("timestamp", width=180, anchor="center")
        self.right_tree.column("text", width=500, anchor="w")
        self.right_tree.bind("<MouseWheel>", self.on_right_tree_scroll)

        self.left_tree.bind("<Button-1>", lambda e: self.on_subtitle_click("left"))
        self.right_tree.bind("<Button-1>", lambda e: self.on_subtitle_click("right"))        

        self.feedback_console = tk.Text(right_frame, height=6, bg="#fdfdfd", fg="#333333", wrap="word", font=("Consolas", 9))
        self.feedback_console.pack(fill="x", padx=8, pady=(6, 0))
        self.feedback_console.config(state="disabled")

                # ─── Feedback Console Tag Configs ─────────────────────────────
        self.feedback_console.tag_config("debug", foreground="#555555")       # muted gray
        self.feedback_console.tag_config("warn", foreground="#c28a00")        # amber
        self.feedback_console.tag_config("error", foreground="#d00000")       # red
        self.feedback_console.tag_config("info", foreground="#1e60a2")        # blue
        self.feedback_console.tag_config("success", foreground="#007f5f")     # green

        # Timestamp below right pane
        self.preview_timestamp = tk.Label(pane_frame, text="Last updated: —", font=("Segoe UI", 8), anchor="e")
        self.preview_timestamp.grid(row=1, column=1, sticky="e", padx=(0, 4), pady=(2, 4))

        # Grid weights for main layout
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_columnconfigure(2, weight=1)

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

        # ─── Progress + Status Label ─────────────────────────────
        #### self.progress = ttk.Progressbar(self.root, orient="horizontal", length=400, mode="determinate")
        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=100)
        self.progress.grid(row=3, column=0, columnspan=3, pady=(8, 0))

        self.status_label = tk.Label(self.root, text="Ready", font=("Segoe UI", 9))
        self.status_label.grid(row=4, column=0, columnspan=3, pady=(2, 6))

        self.update_status_bar()

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
        self.update_status_bar()

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
        if not self.video_path.get() or not self.subtitle_path.get() or not self.output_path.get():
            messagebox.showwarning("Missing Info", "Please select all files and paths.")
            return
        threading.Thread(target=self.run_sync).start()
        if self.full_sync_btn:
            self.full_sync_btn.config(bg=self.root.cget("bg"))

        self.feedback_label.config(text="🟢 Synchronization started...")

    def run_sync(self):
        import time
        t0 = time.time()

        ffmpeg_path = resource_path(os.path.join("bin", "ffmpeg.exe"))
        if not os.path.exists(ffmpeg_path):
            raise FileNotFoundError(f"ffmpeg.exe not found at: {ffmpeg_path}")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
            audio_path = temp_audio.name

        ffmpeg.input(self.video_path.get()).output(
            audio_path,
            format='wav',
            acodec='pcm_s16le',
            ac=1,
            ar='16000'
        ).run(cmd=ffmpeg_path, overwrite_output=True)

        t1 = time.time()
        self.debug("[DEBUG] Audio extracted in {:.2f}s", t1 - t0)

        self.feedback_label.config(text="💬 Running Faster-Whisper transcription...")
        self.status_label.config(text="Transcribing with Faster-Whisper...")
        self.progress["value"] = 30

        model_path = ensure_model()
        model = WhisperModel(model_path, compute_type="int8")

        self.debug("[DEBUG] Starting transcription...")
        self.debug("Calling model.transcribe")

        t4 = time.time()
        segments_gen, _ = model.transcribe(
            audio_path,
            beam_size=self.beam_size.get(),
            word_timestamps=self.word_level_asr.get()
        )
        segments = list(segments_gen)

        t5 = time.time()
        self.debug("[DEBUG] Transcription completed in {:.2f}s", t5 - t4)
        self.debug("[DEBUG] Transcription duration: {:.2f}s", time.time() - t4)

        for s in segments[:5]:
            snippet = s.text.strip()[:80]
            print(f"▶ Segment: {self.format_timestamp(s.start)} → {self.format_timestamp(s.end)} | {snippet}", flush=True)

        if not segments:
            self.feedback_label.config(text="⚠️ No speech detected by Whisper.")
            self.status_label.config(text="Empty result — check audio input", fg="red")
            return

        transcription_path = self.output_path.get()
        total_duration = self.get_audio_duration(audio_path)
        self.asr_path = transcription_path

        base_name = os.path.splitext(os.path.basename(self.video_path.get()))[0]
        beam = self.beam_size.get()
        tag = f"ASR{beam:02}"
        if self.word_level_asr.get():
            tag += "1W"

        preview_path = os.path.join(os.path.dirname(transcription_path), f"{base_name}.preview.srt")
        whisper_path = os.path.join(os.path.dirname(transcription_path), f"{base_name}.{tag}.srt")

        self.preview_buffer = []
        self.whisper_buffer = []

        with open(transcription_path, "w", encoding="utf-8") as final_file, \
            open(preview_path, "w", encoding="utf-8") as preview_file, \
            open(whisper_path, "w", encoding="utf-8") as whisper_file:

            for i, segment in enumerate(segments):
                if self.stop_flag.is_set():
                    self.feedback_label.config(text="⛔️ Transcription stopped by user.")
                    break
                while self.pause_flag.is_set():
                    self.feedback_label.config(text="⏸ Paused…")
                    time.sleep(0.2)

                text = segment.text.strip()
                if not text and hasattr(segment, "words") and segment.words:
                    text = " ".join([w.word for w in segment.words])
                if not text:
                    self.debug("[WARN] Empty segment {} — skipping or writing placeholder.", i + 1)

                entry = (
                    f"{i+1}\n"
                    f"{self.format_timestamp(segment.start)} --> {self.format_timestamp(segment.end)}\n"
                    f"{text}\n\n"
                )

                final_file.write(entry)
                self.whisper_buffer.append(entry)
                self.preview_buffer.append(entry)

                if len(self.whisper_buffer) >= self.flush_lines.get():
                    whisper_file.writelines(self.whisper_buffer)
                    whisper_file.flush()
                    self.whisper_buffer.clear()

                if len(self.preview_buffer) >= self.flush_lines.get():
                    preview_file.writelines(self.preview_buffer)
                    preview_file.flush()
                    self.preview_buffer.clear()
                    now = time.strftime("%H:%M:%S")
                    self.preview_timestamp.config(text=f"Last updated: {now}")
                    self.load_subtitle_to_right_pane(preview_path)

                percent = min((segment.end / total_duration) * 100, 100)
                self.progress["value"] = percent
                self.status_label.config(text=f"Transcribing… {percent:.1f}%")
                self.feedback_label.config(text=f"💬 Whisper processing: {percent:.1f}%")
                self.root.update_idletasks()

        t6 = time.time()
        self.debug("[DEBUG] Subtitle writing complete in {:.2f}s", t6 - t5)

        if os.path.exists(audio_path):
            os.remove(audio_path)

        if os.path.exists(preview_path):
            try:
                os.remove(preview_path)
            except Exception as e:
                self.debug("[WARN] Could not delete preview file: {}", e)

        self.status_label.config(
            text="✔ Transcription complete.",
            fg="#2e7d32",
            font=("Segoe UI", 9, "bold")
        )
        self.feedback_label.config(text="✅ Transcription complete. Output written.")
        self.flash_status_success()
        self.progress["value"] = 100
        self.load_subtitle_to_right_pane(transcription_path)

        tag_label = "Word-Level" if self.word_level_asr.get() else "Sentence-Level"
        self.right_label.config(
            text=f"🧠 ASR Generated: {os.path.basename(transcription_path)} [{tag_label}]"
        )

        self.debug("[DEBUG] Total sync process time: {:.2f}s", time.time() - t0)

    def debug(self, msg, *args):
        formatted = msg.format(*args)
        print(formatted, flush=True)
        self.log_feedback(formatted)

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

        def to_seconds(ts):
            try:
                t = datetime.strptime(ts.strip(), "%H:%M:%S,%f")
                return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1_000_000
            except:
                return None

        def is_comment(text):
            return text.strip().startswith("[") and text.strip().endswith("]")

        original_blocks = self.parse_srt_blocks(original_lines)
        asr_blocks = self.parse_srt_blocks(asr_lines)
        chunks = self.chunk_asr_blocks(asr_blocks, self.chunk_size.get(), self.chunk_step.get())
        threshold = self.match_threshold.get()
        confidence_threshold = 0.5  # 🔧 Optional: expose in UI later

        result = []
        index = 1
        matched = 0

        for orig in original_blocks:
            orig_text = orig["text"].strip()
            orig_time = to_seconds(orig["start"])
            if not orig_text:
                continue

            if is_comment(orig_text):
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
                result.extend([
                    f"{index}",
                    f"{best_chunk['start']} --> {best_chunk['end']}",
                    orig_text,
                    ""
                ])
                matched += 1
            else:
                # fallback to original timestamps
                result.extend([
                    f"{index}",
                    f"{orig['start']} --> {orig['end']}",
                    orig_text,
                    ""
                ])

            index += 1

        self.feedback_label.config(
            text=f"🔗 Realignment complete: {matched}/{len(original_blocks)} lines retimed (chunked match)"
        )
        return [line + "\n" for line in result]
    
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
        self.stop_flag.set()
        self.status_label.config(text="Stopping...")
        self.feedback_label.config(text="🛑 Stopping process…")

    def enable_auto_scroll(self):
        self.auto_scroll_right = True
        self.live_scroll_btn.config(state="disabled")

    def on_right_tree_scroll(self, event):
        self.auto_scroll_right = False
        self.live_scroll_btn.config(state="normal")

    def toggle_pause(self):
        if not self.pause_flag.is_set():
            self.pause_flag.set()
            self.status_label.config(text="Paused")
            self.feedback_label.config(text="⏸ Paused.")
        else:
            self.pause_flag.clear()
            self.status_label.config(text="Resuming...")
            self.feedback_label.config(text="▶️ Resuming…")

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
        if not original or not candidate:
            return 0.0
        a_words = set(original.lower().split())
        b_words = set(candidate.lower().split())
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
            
    def run_asr_only(self):
        import tempfile
        import os
        import time
        from faster_whisper import WhisperModel
        ffmpeg_path = resource_path("ffmpeg.exe")
        if not os.path.exists(ffmpeg_path):
            raise FileNotFoundError(f"ffmpeg.exe not found at: {ffmpeg_path}")
        
        model_path = ensure_model()  # ✅ Check or download model at runtime

        self.status_label.config(text="Running ASR only...")
        self.status_frame.config(bg="#ffe4e1")
        self.feedback_label.config(text="🎙️ Starting Whisper transcription (ASR only)...")
        self.progress["value"] = 10
        self.root.update_idletasks()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
            audio_path = temp_audio.name

        ffmpeg.input(self.video_path.get()).output(
            audio_path,
            format='wav',
            acodec='pcm_s16le',
            ac=1,
            ar='16000'
        ).run(cmd=ffmpeg_path, overwrite_output=True)

        self.feedback_label.config(text="💬 Transcribing with Faster-Whisper...")
        self.status_label.config(text="Transcribing...")
        self.progress["value"] = 30
        self.root.update_idletasks()

        model = WhisperModel(model_path, compute_type="int8")  # 👈 uses downloaded model path
        segments_gen, _ = model.transcribe(
            audio_path,
            beam_size=self.beam_size.get(),
            word_timestamps=self.word_level_asr.get()
        )
        segments = list(segments_gen)
        print(f"[DEBUG] Segments returned: {len(segments)}")

        if not segments:
            self.feedback_label.config(text="⚠️ No speech detected by Whisper.")
            self.status_label.config(text="Empty result — check audio input", fg="red")
            return

        total_duration = self.get_audio_duration(audio_path)
        start_time = time.time()

        base_name = os.path.splitext(os.path.basename(self.video_path.get()))[0]
        tag = "WORD" if self.word_level_asr.get() else "SENTENCE"
        asr_path = os.path.join(os.path.dirname(self.video_path.get()), f"{base_name}.{tag}.srt")
        self.asr_path = asr_path

        with open(asr_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments):
                text = segment.text.strip()
                if not text and hasattr(segment, "words") and segment.words:
                    text = " ".join([w.word for w in segment.words])
                if not text:
                    print(f"[WARN] Empty segment {i+1} — skipping or writing placeholder.")

                f.write(f"{i+1}\n")
                f.write(f"{self.format_timestamp(segment.start)} --> {self.format_timestamp(segment.end)}\n")
                f.write(f"{text}\n\n")

                percent = min((segment.end / total_duration) * 100, 100)
                elapsed = time.time() - start_time
                est_total = elapsed / (percent / 100) if percent > 0 else 0
                remaining = est_total - elapsed

                elapsed_str = time.strftime("%M:%S", time.gmtime(elapsed))
                remaining_str = time.strftime("%M:%S", time.gmtime(remaining))

                self.progress["value"] = percent
                self.status_label.config(
                    text=f"Transcribing… {percent:.1f}% | ⏱ Elapsed: {elapsed_str} | ⌛ Remaining: {remaining_str}"
                )
                self.feedback_label.config(text=f"💬 Whisper processing: {percent:.1f}%")
                self.root.update_idletasks()

        if os.path.exists(audio_path):
            os.remove(audio_path)

        if os.path.exists(asr_path) and os.path.getsize(asr_path) > 0:
            self.load_subtitle_to_right_pane(asr_path)
            with open(asr_path, encoding="utf-8") as f:
                line_count = len(f.readlines())
            ToolTip(self.right_label, f"{line_count} lines generated")
        else:
            line_count = 0
            self.feedback_label.config(text="⚠️ File exists but appears empty — check segment text fallback?")

        self.feedback_label.config(
            text=f"✅ ASR-only complete. File: {os.path.basename(asr_path)} ({line_count} lines)"
        )
        self.output_path.set(asr_path)
        self.export_filename.set(f"Export: {os.path.basename(asr_path)}")
        self.update_status_bar()

        tag_label = "[Word-Level]" if self.word_level_asr.get() else "[Sentence-Level]"
        self.right_label.config(text=f"🧠 ASR Generated: {os.path.basename(asr_path)} {tag_label}")
        self.root.update_idletasks()
        
    def transcribe_whisper(self, audio_path):
        model = WhisperModel("large-v3", compute_type="int8")
        return model.transcribe(
            audio_path,
            beam_size=self.beam_size.get(),
            word_timestamps=self.word_level_asr.get()
        )

if __name__ == "__main__":
    root = tk.Tk()
    #test = tk.Toplevel(root)
    #img = tk.PhotoImage(file="icons/import_video.png")
    #tk.Label(test, image=img).pack()
    #test.mainloop()
    app_icon = load_icon("my_icon", root)
    app = SubtitleSyncApp(root)
    root.mainloop()                