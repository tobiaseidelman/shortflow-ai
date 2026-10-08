"""Actual local voice + captions + video check, without an external paid API."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import subprocess
from app.narration import narrate, overlay
from app.video_engine import render, metadata

with TemporaryDirectory(prefix='shortflow-media-') as directory:
    folder=Path(directory)
    audio, captions, duration=narrate('Mi hermana me dijo que nadie iba a notar mi ausencia. Dejé las llaves sobre la mesa.',folder/'voice',folder,print)
    source=folder/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=15','-t',str(duration+.1),'-c:v','libx264',str(source)],check=True)
    clip=SimpleNamespace(duration=duration+.1,start_time=0,source_video_id=1)
    render([clip],{1:str(source)},folder/'background.mp4',duration)
    overlay(folder/'background.mp4',audio,captions,folder/'final.mp4',duration)
    actual=metadata(folder/'final.mp4')
    assert actual['width']==1080 and actual['height']==1920
    assert abs(actual['duration']-duration)<0.15
    subprocess.run(['ffmpeg','-v','error','-i',str(folder/'final.mp4'),'-map','0:a:0','-f','null','-'],check=True,capture_output=True)
    assert 'Dialogue:' in captions.read_text()
    print('Verified real narration, captions and vertical video:',actual,flush=True)
