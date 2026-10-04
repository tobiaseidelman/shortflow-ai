"""Local Spanish narration and phrase-aligned captions; no paid service."""
from pathlib import Path
import re
import urllib.request
import wave

VOICE = 'es_ES-davefx-medium'
BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/'


def ensure_voice(storage):
    folder = Path(storage) / 'voices' / VOICE
    folder.mkdir(parents=True, exist_ok=True)
    for name in (VOICE + '.onnx', VOICE + '.onnx.json', 'MODEL_CARD'):
        target = folder / name
        if not target.exists():
            temporary = target.with_suffix(target.suffix + '.download')
            try:
                with urllib.request.urlopen(BASE + name, timeout=120) as response, temporary.open('wb') as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    return folder / (VOICE + '.onnx')


def timestamp(seconds):
    centiseconds = round(seconds * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    sec, cs = divmod(remainder, 100)
    return f'{hours}:{minutes:02}:{sec:02}.{cs:02}'


def narrate(text, folder, storage, progress):
    from piper import PiperVoice, SynthesisConfig
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    progress('Preparando la voz en español… La primera vez descarga el modelo.')
    voice = PiperVoice.load(str(ensure_voice(storage)))
    config = SynthesisConfig(length_scale=1.0)
    # Keep natural short phrases together; word timings within each phrase are estimated.
    phrases = []
    for sentence in re.split(r'(?<=[.!?;])\s+|\n+', text.strip()):
        words = sentence.split()
        for start in range(0, len(words), 24):
            phrases.append(' '.join(words[start:start + 24]))
    audio_path = folder / 'voice.wav'
    captions = []
    elapsed = 0.0
    progress('Creando la narración y los subtítulos…')
    with wave.open(str(audio_path), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(voice.config.sample_rate)
        for phrase in phrases:
            chunks = list(voice.synthesize(phrase, syn_config=config))
            raw = b''.join(chunk.audio_int16_bytes for chunk in chunks)
            seconds = len(raw) / (2 * voice.config.sample_rate)
            output.writeframes(raw)
            words = phrase.split()
            groups = [' '.join(words[i:i + 3]) for i in range(0, len(words), 3)]
            weight = sum(len(group) for group in groups) or 1
            for group in groups:
                end = elapsed + seconds * len(group) / weight
                safe = group.replace('\\', '').replace('{', '').replace('}', '').replace('\n', ' ')
                captions.append(f'Dialogue: 0,{timestamp(elapsed)},{timestamp(end)},Default,,0,0,0,,{safe}')
                elapsed = end
    if elapsed < 0.2:
        raise ValueError('No se pudo crear una narración audible.')
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,76,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,80,80,150,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    subtitle_path = folder / 'captions.ass'
    subtitle_path.write_text(header + '\n'.join(captions) + '\n', encoding='utf-8')
    return audio_path, subtitle_path, elapsed


def overlay(background, audio, subtitles, output, duration):
    import subprocess
    import shutil
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='captions-', dir=Path(output).parent) as tmp:
        shutil.copyfile(subtitles, Path(tmp) / 'captions.ass')
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', str(Path(background).resolve()),
                        '-i', str(Path(audio).resolve()), '-vf', 'ass=captions.ass',
                        '-map', '0:v:0', '-map', '1:a:0', '-t', str(duration),
                        '-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
                        '-movflags', '+faststart', str(Path(tmp) / 'final.mp4')],
                       cwd=tmp, check=True, capture_output=True, timeout=1200)
        Path(tmp, 'final.mp4').replace(output)
