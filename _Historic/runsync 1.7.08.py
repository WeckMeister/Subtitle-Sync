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
        self.right_label.config(
        text=f"🧠 ASR Generated: {os.path.basename(path)} (whisper)"
        if "Whisper" in os.path.basename(path)
        else f"🧠 ASR Generated: {os.path.basename(path)}"
    )
        