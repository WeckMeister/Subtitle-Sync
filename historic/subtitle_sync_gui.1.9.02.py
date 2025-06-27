import os
import time
import wave
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import ffmpeg  # type: ignore
from faster_whisper import WhisperModel  # type: ignore
from version import __versionMinor__   # type: ignore
from theme import RIBBON_BUTTON_STYLE
import os
icon_path = os.path.join("icons", "import_video.png")

__version__ = __versionMinor__  + "02"

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
        self.match_threshold = tk.DoubleVar(value=1.0)  # default to 1.0 seconds
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

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

        self.match_threshold = tk.DoubleVar(value=1.0)  # default threshold in seconds        

        self.preview_buffer = []
        self.whisper_buffer = []

        self.pause_flag = threading.Event()
        self.stop_flag = threading.Event()
        self.auto_scroll_right = True

        self.beam_size.trace_add("write", lambda *args: self.update_beam_status())

        self.icons = {
    "import_video": tk.PhotoImage(file="icons/import_video.png"),
    "import_subtitle": tk.PhotoImage(file="icons/import_subtitle.png"),
    "export": tk.PhotoImage(file="icons/export.png"),
    "sync": tk.PhotoImage(file="icons/syncred.png"),
    "sync_only": tk.PhotoImage(file="icons/syncred.png"),    
    "pause": tk.PhotoImage(file="icons/pause.png"),
    "stop": tk.PhotoImage(file="icons/stop.png"),
    "change_left": tk.PhotoImage(file="icons/left_arrow.png"),
    "change_right": tk.PhotoImage(file="icons/right_arrow.png"),
    "syncred": tk.PhotoImage(file="icons/syncred.png"),     # for NOT ready states
    "sync": tk.PhotoImage(file="icons/sync.png"),           # for ready states
    "syncgreen": tk.PhotoImage(file="icons/syncgreen.png"),
    "sync_only": tk.PhotoImage(file="icons/sync.png"),  # ✅ Always this,
    "reset": tk.PhotoImage(file="icons/broom.png"),
}

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
        settings_menu.add_command(label="Set Sync Tolerance", command=self.set_threshold_dialog)


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
            "Enter max timestamp gap (in seconds):",
            initialvalue=self.match_threshold.get(),
            minvalue=0.0,
            maxvalue=10.0
        )
        if value is not None:
            self.match_threshold.set(value) 
            self.feedback_label.config(text=f"⚙️ Sync tolerance set to {value:.2f} seconds")       

    def create_ribbon(self):
        ribbon = tk.Frame(self.root, bg="#e6e6e6", relief="raised", bd=1)
        ribbon.grid(row=0, column=0, columnspan=3, sticky="we", padx=2, pady=2)

        btns = [
            ("Import Video", self.select_video, "import_video"),
            ("Import Subtitle", self.select_subtitle, "import_subtitle"),            
            ("Full ASR and Sync", self.start_process, "syncred"),
            ("Sync Only", self.sync_only_mode, "syncred"),  # 👈 both start red by default
            ("Pause", self.toggle_pause, "pause"),
            ("Stop", self.trigger_stop, "stop"),
            ("Original Subtitle", self.select_subtitle, "change_left"),
            ("ASR (Whisper) Subtitle", self.select_right_subtitle, "change_right"),
            ("Select Export File", self.select_output, "export"),
            ("Reset", self.reset_app, "reset"),
        ]

        self.full_sync_btn = None
        self.sync_only_btn = None

        for label, command, icon_key in btns:
            icon = self.icons.get(icon_key)
            btn = tk.Button(ribbon, text=label, image=icon, command=command, **RIBBON_BUTTON_STYLE)
            btn.pack(side="left", padx=2, pady=2)

            if label == "Reset":
                ToolTip(btn, "Clear all files and start over")

            if icon_key == "syncred":
                if "Full ASR" in label:
                    self.full_sync_btn = btn
                elif "Sync Only" in label:
                    self.sync_only_btn = btn   
                #if "Reset" in label:
                #    ToolTip(btn, "Clear all files and start over")  

                       

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
        self.left_tree_scroll.grid(row=0, column=1, sticky="ns")
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
        self.right_tree_scroll.grid(row=0, column=1, sticky="ns")
        self.right_tree.heading("index", text="#")
        self.right_tree.heading("timestamp", text="Timestamp")
        self.right_tree.heading("text", text="Text")
        self.right_tree.column("index", width=40, anchor="center")
        self.right_tree.column("timestamp", width=180, anchor="center")
        self.right_tree.column("text", width=500, anchor="w")
        self.right_tree.bind("<MouseWheel>", self.on_right_tree_scroll)

        self.left_tree.bind("<Button-1>", lambda e: self.on_subtitle_click("left"))
        self.right_tree.bind("<Button-1>", lambda e: self.on_subtitle_click("right"))        

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
        self.status_frame.grid(row=2, column=0, columnspan=3, sticky="we")

        self.beam_status = tk.Label(self.status_frame, text=f"[{self.beam_size.get()}] Beam", anchor="w", padx=5, font=("Segoe UI", 9))
        self.beam_status.pack(side="left")

        self.video_status = tk.Label(self.status_frame, text="[✗] Video", anchor="w", padx=5, font=("Segoe UI", 9))
        self.video_status.pack(side="left")

        self.subtitle_status = tk.Label(self.status_frame, text="[✗] Subtitle", anchor="w", padx=5, font=("Segoe UI", 9))
        self.subtitle_status.pack(side="left")

        self.output_status = tk.Label(self.status_frame, text="[✗] Export", anchor="w", padx=5, font=("Segoe UI", 9))
        self.output_status.pack(side="left")

        # ─── Progress + Status Label ─────────────────────────────
        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=400, mode="determinate")
        self.progress.grid(row=3, column=0, columnspan=3, pady=(8, 0))

        self.status_label = tk.Label(self.root, text="Ready", font=("Segoe UI", 9))
        self.status_label.grid(row=4, column=0, columnspan=3, pady=(2, 6))

        # ─── Start Button + Control Row ──────────────────────────
        self.start_button = tk.Button(self.root, text="Start Sync", command=self.start_process, state="disabled")
        self.start_button.grid(row=5, column=0, columnspan=3, pady=(0, 12))

        control_frame = tk.Frame(self.root)
        control_frame.grid(row=6, column=0, columnspan=3, pady=10)
        pause_btn = tk.Button(control_frame, text="Pause", command=self.toggle_pause)
        pause_btn.pack(side="left", padx=(0, 10))

        self.live_scroll_btn = tk.Button(control_frame, text="📡 Live", font=("Segoe UI", 8), command=self.enable_auto_scroll)
        self.live_scroll_btn.pack(side="left", padx=(0, 10))

        stop_btn = tk.Button(control_frame, text="Stop", command=self.trigger_stop)
        stop_btn.pack(side="left")

        self.update_status_bar()

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
        self.start_button.config(state="disabled", bg=self.root.cget("bg"))

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
        self.start_button.config(state="normal" if all_ok else "disabled")
        if all_ok:
            self.pulse_start_button()

    def update_beam_status(self):
        beam = self.beam_size.get()
        self.beam_status.config(text=f"[{beam}] Beam")

    def start_process(self):
        if not self.video_path.get() or not self.subtitle_path.get() or not self.output_path.get():
            messagebox.showwarning("Missing Info", "Please select all files and paths.")
            return
        threading.Thread(target=self.run_sync).start()
        self.start_button.config(bg=self.root.cget("bg"))
        self.feedback_label.config(text="🟢 Synchronization started...")

    def run_sync(self):
        self.status_label.config(text="Extracting audio...")
        self.status_frame.config(bg="#ffe4e1")  # indicate "working"
        self.progress["value"] = 10
        self.feedback_label.config(text="🔉 Extracting audio track from video...")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
            audio_path = temp_audio.name

        ffmpeg.input(self.video_path.get()).output(
            audio_path,
            format='wav',
            acodec='pcm_s16le',
            ac=1,
            ar='16000'
        ).run(overwrite_output=True)

        self.feedback_label.config(text="💬 Running Faster-Whisper transcription...")
        self.status_label.config(text="Transcribing with Faster-Whisper...")
        self.progress["value"] = 30

        model = WhisperModel("large-v3", compute_type="int8")
        segments, _ = model.transcribe(audio_path, beam_size=self.beam_size.get())

        transcription_path = self.output_path.get()
        total_duration = self.get_audio_duration(audio_path)

        self.asr_path = transcription_path

        base_name = os.path.splitext(os.path.basename(self.video_path.get()))[0]
        beam = self.beam_size.get()
        tag = f"ASR{beam:02}"

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

                entry = (
                    f"{i+1}\n"
                    f"{self.format_timestamp(segment.start)} --> {self.format_timestamp(segment.end)}\n"
                    f"{segment.text.strip()}\n\n"
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
                    self.root.after(0, lambda: self.load_subtitle_to_right_pane(preview_path))

                percent = min((segment.end / total_duration) * 100, 100)
                self.progress["value"] = percent
                self.status_label.config(text=f"Transcribing… {percent:.1f}%")
                self.feedback_label.config(text=f"💬 Whisper processing: {percent:.1f}%")
                self.root.update_idletasks()

        if os.path.exists(audio_path):
            os.remove(audio_path)

        if os.path.exists(preview_path):
            try:
                os.remove(preview_path)
            except Exception as e:
                print(f"Could not delete preview file: {e}")

        self.status_label.config(
            text="✔ Transcription complete.",
            fg="#2e7d32",
            font=("Segoe UI", 9, "bold")
        )
        self.feedback_label.config(text="✅ Transcription complete. Output written.")
        self.flash_status_success()
        self.progress["value"] = 100
        self.load_subtitle_to_right_pane(transcription_path)
        self.right_label.config(
        text=f"🧠 ASR Generated: {os.path.basename(path)} (whisper)"
        if "Whisper" in os.path.basename(path)
        else f"🧠 ASR Generated: {os.path.basename(path)}"
    )
        
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

        except Exception as e:
            self.feedback_label.config(text=f"❌ Sync-only failed: {str(e)}")
            self.status_label.config(text="⚠ Error during sync", fg="red")
            self.progress["value"] = 0  

    def merge_subtitles(self, original_lines, asr_lines, max_gap_seconds=1.0):
        from datetime import datetime

        def to_seconds(timestamp):
            parts = datetime.strptime(timestamp.strip(), "%H:%M:%S,%f")
            return parts.hour * 3600 + parts.minute * 60 + parts.second + parts.microsecond / 1_000_000

        original_blocks = parse_srt_blocks(original_lines)
        asr_blocks = parse_srt_blocks(asr_lines)

        result_lines = []
        index = 1

        for orig in original_blocks:
            orig_start = to_seconds(orig["start"])
            matched = None

            for asr in asr_blocks:
                asr_start = to_seconds(asr["start"])
                if abs(orig_start - asr_start) <= max_gap_seconds:
                    matched = asr
                    break

            if matched:
                result_lines.extend([
                    f"{index}",
                    f"{orig['start']} --> {orig['end']}",
                    matched["text"].strip(),
                    ""
                ])
            else:
                result_lines.extend([
                    f"{index}",
                    f"{orig['start']} --> {orig['end']}",
                    "(No matching ASR line)",
                    ""
                ])

            index += 1

        return [line + "\n" for line in result_lines]   

    def parse_srt_blocks(lines):
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
                    continue  # skip malformed line
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

 
         
  

if __name__ == "__main__":
    root = tk.Tk()
    #test = tk.Toplevel(root)
    #img = tk.PhotoImage(file="icons/import_video.png")
    #tk.Label(test, image=img).pack()
    #test.mainloop()
    app_icon = load_icon("my_icon", root)
    app = SubtitleSyncApp(root)
    root.mainloop()                