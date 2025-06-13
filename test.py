import whisper
import torch
import sounddevice as sd
from scipy.io.wavfile import write
import tempfile

# Configuration
duration = 5  # seconds to record
sample_rate = 16000  # Whisper expects 16000 Hz

# Check device
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")

# Load Whisper model
model = whisper.load_model("large", device=device)

# Record audio
print("🎤 Speak now...")
recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='int16')
sd.wait()
print("✅ Recording finished.")

# Save to temporary file
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    write(f.name, sample_rate, recording)
    audio_path = f.name

# Transcribe
result = model.transcribe(audio_path, language="ar", verbose=True)
print("\n📝 Transcription:\n", result["text"])


