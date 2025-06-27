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

__version__ = __versionMinor__  + "06"

# ─── ToolTip ────────────────────────────────────────────────────────────────
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tipwindow or not self.text:
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
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None

class SubtitleSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Subtitle Synchroniser v{__version__}")

        # ─── Initialize paths and flags ─────────────────────────
        self.video_path = tk.StringVar()
        self.subtitle_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.flush_lines = tk.IntVar(value=10)
        self.beam_size = tk.IntVar(value=5)

        self.preview_buffer = []
        self.whisper_buffer = []

        self.pause_flag = threading.Event()
        self.stop_flag = threading.Event()
        self.auto_scroll_right = True

        self.beam_size.trace_add("write", lambda *args: self.update_beam_status())

        # ─── Menu Bar ────────────────────────────────────────────
        self.create_menu_bar()

        # ─── Ribbon Toolbar ──────────────────────────────────────
        self.create_ribbon()

        # ─── Subtitle Viewer Panes and Controls ──────────────────
        self.create_widgets()

        # ─── Feedback Panel ──────────────────────────────────────
        self.create_feedback_panel()

        self.icons = {
    "import_video": tk.PhotoImage(file="icons/import_video.png"),
    "import_subtitle": tk.PhotoImage(file="icons/import_subtitle.png"),
    "export": tk.PhotoImage(file="icons/export.png"),
    "sync": tk.PhotoImage(file="icons/sync.png"),
    "pause": tk.PhotoImage(file="icons/pause.png"),
    "stop": tk.PhotoImage(file="icons/stop.png"),
    "change_left": tk.PhotoImage(file="icons/left_arrow.png"),
    "change_right": tk.PhotoImage(file="icons/right_arrow.png")
}

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

        # Help menu
        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="Application Overview", command=self.show_app_overview)
        help_menu.add_command(label="Developer Reference", command=self.show_dev_reference)
        menu_bar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menu_bar)

    def create_ribbon(self):
        ribbon = tk.Frame(self.root, bg="#e6e6e6", relief="raised", bd=1)
        ribbon.grid(row=0, column=0, columnspan=3, sticky="we", padx=2, pady=2)

        btns = [
            ("Import Video", self.select_video, "import_video"),
            ("Import Subtitle", self.select_subtitle, "import_subtitle"),
            ("Export", self.select_output, "export"),
            ("Sync", self.start_process, "sync"),
            ("Pause", self.toggle_pause, "pause"),
            ("Stop", self.trigger_stop, "stop"),
            ("Left Subtitle", self.select_subtitle, "change_left"),
            ("Right Subtitle", lambda: self.load_subtitle_to_right_pane(self.output_path.get()), "change_right")
        ]

        for label, command, icon_key in btns:
            icon = self.icons.get(icon_key)
            tk.Button(
                ribbon,
                text=label,
                image=icon,
                command=command,
                **RIBBON_BUTTON_STYLE
            ).pack(side="left", padx=2, pady=2)

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
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        # Right Subtitle Viewer
        right_frame = tk.Frame(pane_frame)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

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
        self.left_tree.grid(row=0, column=0, sticky="nsew")
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
        self.right_tree.grid(row=0, column=0, sticky="nsew")
        self.right_tree_scroll.grid(row=0, column=1, sticky="ns")

        self.right_tree.heading("index", text="#")
        self.right_tree.heading("timestamp", text="Timestamp")
        self.right_tree.heading("text", text="Text")

        self.right_tree.column("index", width=40, anchor="center")
        self.right_tree.column("timestamp", width=180, anchor="center")
        self.right_tree.column("text", width=500, anchor="w")

        self.right_tree.bind("<MouseWheel>", self.on_right_tree_scroll)

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


    def select_video(self):
        path = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.mkv *.avi")])
        if path:
            self.video_path.set(path)
        self.update_status_bar()

    def select_subtitle(self):
        path = filedialog.askopenfilename(filetypes=[("Subtitle files", "*.srt")])
        if path:
            self.subtitle_path.set(path)
            self.load_subtitle_to_left_pane(path)
        self.update_status_bar()

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
        suggested_name = "output.SYNCED.srt"
        video_path = self.video_path.get()

        if video_path:
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            suggested_name = f"{base_name}.SYNCED.srt"

        path = filedialog.asksaveasfilename(
            defaultextension=".srt",
            filetypes=[("Subtitle files", "*.srt")],
            initialfile=suggested_name
        )
        if path:
            self.output_path.set(path)
        self.update_status_bar()

    def update_status_bar(self):
        paths = {
            "video": self.video_path.get(),
            "subtitle": self.subtitle_path.get(),
            "export": self.output_path.get()
        }

        def label_status(p): return "[✓]" if p else "[✗]"

        self.video_status.config(text=f"{label_status(paths['video'])} Video")
        self.subtitle_status.config(text=f"{label_status(paths['subtitle'])} Subtitle")
        self.output_status.config(text=f"{label_status(paths['export'])} Export")

        ToolTip(self.video_status, paths["video"] or "No video selected")
        ToolTip(self.subtitle_status, paths["subtitle"] or "No subtitle selected")
        ToolTip(self.output_status, paths["export"] or "No export path selected")

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

        base_name = os.path.splitext(os.path.basename(self.video_path.get()))[0]
        preview_path = os.path.join(os.path.dirname(transcription_path), f"{base_name}.preview.srt")
        whisper_path = os.path.join(os.path.dirname(transcription_path), f"{base_name}.Whisper.srt")

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

if __name__ == "__main__":
    root = tk.Tk()
    app = SubtitleSyncApp(root)
    root.mainloop()                