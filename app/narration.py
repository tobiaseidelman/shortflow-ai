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


def caption_groups(phrase):
    groups, words = [], []
    for word in phrase.split():
        if words and (len(words)>=4 or len(' '.join(words+[word]))>28):
            groups.append(' '.join(words));words=[]
        words.append(word)
        if word.endswith((',', ';', ':', '.', '?', '!', '…')):
            groups.append(' '.join(words));words=[]
    if words:groups.append(' '.join(words))
    return groups


def speech_bounds(raw, sample_rate):
    """Exclude leading/trailing silence from estimated captions, preserving the audio."""
    import numpy as np
    samples=np.frombuffer(raw,dtype='<i2').astype(float)
    if not len(samples):return 0.,0.
    step=max(1,round(sample_rate*.01))
    energy=np.array([np.sqrt(np.mean(samples[i:i+step]**2)) for i in range(0,len(samples),step)])
    active=np.flatnonzero(energy>max(20,float(energy.max())*.025))
    if not len(active):return 0.,len(samples)/sample_rate
    return max(0,(active[0]-1)*step/sample_rate),min(len(samples)/sample_rate,(active[-1]+2)*step/sample_rate)


def narrate(text, folder, storage, progress, intro=""):
    from piper import PiperVoice, SynthesisConfig
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    progress('Preparando la voz en español… La primera vez descarga el modelo.')
    voice = PiperVoice.load(str(ensure_voice(storage)))
    config = SynthesisConfig(length_scale=0.93)
    # Keep complete sentences so Piper can carry intonation across clauses.
    # Do not restart the voice every 24 words in the middle of a thought.
    phrases = []
    for paragraph in re.split(r'\n\s*\n', text.strip()):
        sentences = [s.strip() for s in re.split(r'(?<=[.!?;])\s+|\n+', paragraph) if s.strip()]
        for i, sentence in enumerate(sentences):
            phrases.append((sentence, .16 if phrases and i == 0 else 0))
    if intro:
        phrases.insert(0, (intro, 0))
        if len(phrases)>1: phrases[1]=(phrases[1][0], .24)
    audio_path = folder / 'voice.wav'
    captions = []
    elapsed = 0.0
    progress('Creando la narración y los subtítulos…')
    with wave.open(str(audio_path), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(voice.config.sample_rate)
        for phrase_index, (phrase, pause) in enumerate(phrases):
            silence_frames = round(pause * voice.config.sample_rate)
            if silence_frames:
                output.writeframes(b'\0\0' * silence_frames)
                elapsed += silence_frames / voice.config.sample_rate
            chunks = list(voice.synthesize(phrase, syn_config=config))
            raw = b''.join(chunk.audio_int16_bytes for chunk in chunks)
            seconds = len(raw) / (2 * voice.config.sample_rate)
            output.writeframes(raw)
            if intro and phrase_index == 0:
                captions.extend(intro_card(intro, seconds))
                elapsed += seconds
                continue
            groups = caption_groups(phrase)
            start,stop = speech_bounds(raw,voice.config.sample_rate)
            cursor = elapsed+start
            weight = sum(len(group) for group in groups) or 1
            for group in groups:
                end = cursor + (stop-start) * len(group) / weight
                safe = group.replace('\\', '').replace('{', '').replace('}', '').replace('\n', ' ')
                captions.append(f'Dialogue: 0,{timestamp(cursor)},{timestamp(end)},Default,,0,0,0,,{safe}')
                cursor = end
            elapsed += seconds
    if elapsed < 0.2:
        raise ValueError('No se pudo crear una narración audible.')
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Card,DejaVu Sans,54,&H00202020,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,130,130,0,1
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


def intro_card(text, seconds):
    """Post-style opening with vector details, sized to the spoken text."""
    import textwrap
    safe = text.replace('\\', '').replace('{', '').replace('}', '')
    lines = textwrap.wrap(' '.join(safe.split()), width=28)
    height = max(420, len(lines) * 64 + 250)
    top = int(960 - height / 2)
    bottom = top + height
    end = timestamp(seconds)
    events = []

    def shape(path, color, layer=0, extra=''):
        tags = r'{\an7\pos(0,0)\p1\bord0\shad0\c&H' + color + '&' + extra + '}'
        events.append(f'Dialogue: {layer},0:00:00.00,{end},Card,,0,0,0,,{tags}{path}')

    def rounded(x, y, w, h, r):
        return (f'm {x+r} {y} l {x+w-r} {y} '
                f'b {x+w} {y} {x+w} {y} {x+w} {y+r} l {x+w} {y+h-r} '
                f'b {x+w} {y+h} {x+w} {y+h} {x+w-r} {y+h} l {x+r} {y+h} '
                f'b {x} {y+h} {x} {y+h} {x} {y+h-r} l {x} {y+r} '
                f'b {x} {y} {x} {y} {x+r} {y}')

    shape(rounded(85, top+14, 910, height, 32), '000000', extra=r'\alpha&H70&\blur12')
    shape(rounded(85, top, 910, height, 32), 'FCFAFA')
    # A conversation icon and short accent rule replace the brand label.
    shape(rounded(130, top+35, 72, 72, 22), 'EFE4F3', 1)
    shape(rounded(145, top+53, 42, 29, 9) + f' m 153 {top+78} l 153 {top+91} 168 {top+78}', '965EE5', 2)
    shape(rounded(220, top+60, 100, 8, 4), '965EE5', 1)
    shape(rounded(220, top+78, 62, 6, 3), 'DAD0DF', 1)
    for x in (913, 931, 949):
        shape(rounded(x, top+65, 7, 7, 3), 'A79BAE', 1)
    body = (r'{\an5\pos(540,' + str(top+135+len(lines)*32) + r')\fs52\c&H262020&}'
            + r'\N'.join(lines))
    events.append(f'Dialogue: 2,0:00:00.00,{end},Card,,0,0,0,,{body}')
    shape(f'm 130 {bottom-75} l 950 {bottom-75} 950 {bottom-73} 130 {bottom-73}', 'E9E3ED', 1)
    # Quiet footer details: conversation and bookmark, without invented counters.
    shape(rounded(135, bottom-53, 34, 24, 7) + f' m 140 {bottom-33} l 140 {bottom-24} 151 {bottom-33}', 'C9BBCE', 1)
    shape(rounded(184, bottom-46, 75, 7, 3), 'E5DCE9', 1)
    shape(f'm 923 {bottom-54} l 945 {bottom-54} 945 {bottom-25} 934 {bottom-33} 923 {bottom-25}', '965EE5', 1)
    return events
