from faster_whisper import WhisperModel
import time

start = time.time()
model = WhisperModel("models/whisper-large-v3", compute_type="int8", device="auto")
print("⏳ Model loaded in", time.time() - start, "seconds")

# start = time.time()
# segments, _ = model.transcribe("C:/Users/heiko/Documentation Heiko/Programing Code/Python code/Subtitle-Sync/_Testsubs/Ring05.wav", beam_size=5, word_timestamps=False)
# print("🧠 Transcription done in", time.time() - start, "seconds")

start = time.time()
segments, _ = model.transcribe(r"C:/Users/heiko/Documentation Heiko/Programing Code/Python code/Subtitle-Sync/_Testsubs/Ring05.wav", beam_size=5, word_timestamps=False)
print("🧠 Transcription done in", time.time() - start, "seconds")