"""Audio capture, synthetic generation, and DSP analysis pipeline."""

from ferrowidget.audio.analysis import AudioAnalyzer, Features
from ferrowidget.audio.capture import AudioCaptureThread
from ferrowidget.audio.synthetic import generate_synthetic_audio

__all__ = ["AudioAnalyzer", "Features", "AudioCaptureThread", "generate_synthetic_audio"]
