"""Opt-in real-model smoke check using a synthetic reveal, never user footage."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
from app.narration import narrate
from app.clips_engine import propose, transcribe
from app.video_engine import metadata

with TemporaryDirectory(prefix='shortflow-clips-ai-') as temp:
    root=Path(temp)
    before=('Hoy tenemos un reto para vos. Detrás de esta pantalla hay una fotografía de un animal. '
            'Tenés que adivinar qué animal es antes de que mostremos la foto. '
            'Si acertás sin verla ganás el desafío. Voy a darte una pista. '
            'Es un animal que muchas personas tienen en su casa. '
            'Puede ser pequeño o grande y le gusta jugar. Pensá bien tu respuesta. '
            'No la cambies después de ver la imagen. Ya elegiste tu respuesta. '
            'Ahora vamos a descubrir qué animal está escondido detrás de la pantalla.')
    after='Es un perro. La fotografía muestra un perro blanco sentado. Si dijiste perro, acertaste. Ese era el resultado del desafío.'
    a,_,d1=narrate(before,root/'before',root,print)
    b,_,d2=narrate(after,root/'after',root,print)
    asset=Path('app/assets/channel-avatar.jpg').resolve()
    source=root/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'color=c=purple:s=640x360:r=15:d={d1}',
                    '-i',str(a),'-t',str(d1),'-c:v','libx264','-c:a','aac',str(root/'before.mp4')],check=True)
    subprocess.run(['ffmpeg','-v','error','-loop','1','-i',str(asset),'-i',str(b),'-t',str(d2),
                    '-vf','scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1',
                    '-r','15','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(root/'after.mp4')],check=True)
    (root/'list.txt').write_text("file 'before.mp4'\nfile 'after.mp4'\n")
    subprocess.run(['ffmpeg','-v','error','-f','concat','-safe','0','-i',str(root/'list.txt'),'-c','copy',str(source)],check=True)
    analysis=root/'clip-projects'/'smoke';analysis.mkdir(parents=True)
    progress=lambda message: print(message,flush=True)
    print('Reveal starts at',d1,flush=True)
    print('TRANSCRIPT:',json.dumps(transcribe(source,analysis,progress),ensure_ascii=False),flush=True)
    try:
        result=propose(source,analysis,metadata(source)['duration'],1,90,root,progress)
    finally:
        for evidence in sorted(analysis.glob('*-*.json')):
            print(evidence.name, evidence.read_text(), flush=True)
    print('REAL CLIPS PROPOSALS:',json.dumps(result,ensure_ascii=False),flush=True)
    assert result, 'No usable suspense proposal in controlled reveal'
    assert result[0]['end']<=d1+.5, 'The cut already includes the revealed image'
    assert result[0]['start']<d1-12
    print('Real local speech, text and visual models completed the controlled-reveal smoke test.',flush=True)
