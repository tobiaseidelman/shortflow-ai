from fastapi import FastAPI,Request,UploadFile,File,Form,HTTPException
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime
import shutil,json,re,os,subprocess
from .db import Base,engine,SessionLocal
from .models import *
from .video_engine import metadata,analyze,optimize,render
from .story_routes import router as story_router, lifespan, set_storage
from .render_routes import router as render_router, set_storage as set_render_storage
from .import_routes import router as import_router, set_storage as set_import_storage
ROOT=Path(__file__).resolve().parents[1]; STORE=Path(os.getenv('SHORTFLOW_STORAGE_DIR', str(ROOT/'storage'))).expanduser().resolve(); UP=STORE/'uploads'; OUT=STORE/'renders'
for p in (UP,OUT,STORE/'temp'):p.mkdir(parents=True,exist_ok=True)
Base.metadata.create_all(engine)
set_storage(STORE)
set_import_storage(STORE)
set_render_storage(STORE)
app=FastAPI(title='ShortFlow AI', lifespan=lifespan); app.include_router(story_router); app.include_router(import_router); app.include_router(render_router); app.mount('/static',StaticFiles(directory=ROOT/'app/static'),name='static'); templates=Jinja2Templates(directory=ROOT/'app/templates')
ALLOWED={'.mp4','.mov','.webm'}; MAX=1024*1024*1024

def db(): return SessionLocal()
def stats(s):
 return {'shorts':s.query(Short).count(),'pending':s.query(Short).filter(Short.status!='ready').count(),'videos':s.query(BackgroundVideo).count(),'clips':s.query(Clip).count(),'stories':s.query(Story).count(),'storage':sum(p.stat().st_size for p in STORE.rglob('*') if p.is_file())}
@app.get('/',response_class=HTMLResponse)
def home(request:Request):
 s=db(); data=stats(s); recent=s.query(Short).order_by(Short.id.desc()).limit(6).all(); s.close(); return templates.TemplateResponse(request,'index.html',{'stats':data,'recent':recent})
@app.get('/api/health')
def health():
 ffmpeg=shutil.which('ffmpeg')
 return {'status':'ok' if ffmpeg else 'degraded','python':os.sys.version.split()[0],'ffmpeg':bool(ffmpeg),'storage_writable':os.access(STORE,os.W_OK)}
@app.get('/api/dashboard')
def dashboard(): s=db(); x=stats(s); s.close(); return x
@app.get('/api/videos')
def videos():
 s=db(); rows=s.query(BackgroundVideo).order_by(BackgroundVideo.id.desc()).all(); out=[{'id':v.id,'name':v.name,'duration':v.duration,'width':v.width,'height':v.height,'size':v.size,'status':v.status,'clips':s.query(Clip).filter_by(source_video_id=v.id).count()} for v in rows];s.close();return out
@app.post('/api/videos/upload')
def upload(file:UploadFile=File(...)):
 ext=Path(file.filename or '').suffix.lower()
 if ext not in ALLOWED: raise HTTPException(400,'Formato no soportado. Usá MP4, MOV o WebM.')
 from uuid import uuid4
 safe=re.sub(r'[^A-Za-z0-9._-]','_',Path(file.filename).name); dest=UP/f'{uuid4().hex}_{safe}'
 size=0
 try:
  with dest.open('wb') as f:
   while chunk:=file.file.read(1024*1024):
    size+=len(chunk)
    if size>MAX:
     raise HTTPException(413,'El archivo supera el límite de 1 GB.')
    f.write(chunk)
 except Exception:
  dest.unlink(missing_ok=True)
  raise
 try:
  m=metadata(dest)
  if m['duration']<1 or m['width']<1 or m['height']<1: raise ValueError('Video inválido')
 except Exception: dest.unlink(missing_ok=True);raise HTTPException(400,'No se pudo decodificar el video.')
 s=db(); v=BackgroundVideo(name=safe,path=str(dest),duration=m['duration'],width=m['width'],height=m['height'],size=dest.stat().st_size,status='analyzing');s.add(v);s.commit()
 try:
  cs=analyze(dest)
  for c in cs:s.add(Clip(source_video_id=v.id,**c))
  v.status='ready';s.commit();res={'id':v.id,'clips':len(cs),'message':'Video analizado correctamente.'}
 except Exception as e:v.status='failed';s.commit();s.close();raise HTTPException(500,f'Falló el análisis: {str(e)[:180]}')
 s.close();return res
@app.get('/api/stories')
def stories():s=db();r=s.query(Story).order_by(Story.id.desc()).all();o=[{'id':x.id,'title':x.title,'genre':x.genre,'duration':x.duration_target,'text':x.text} for x in r];s.close();return o
@app.post('/api/shorts')
def create_short(story_id:int=Form(0),duration:float=Form(45,ge=1,le=300)):
 s=db();
 if story_id: s.close();raise HTTPException(400,'Usá la generación con voz para una historia.')
 clips=s.query(Clip).all()
 if not clips:s.close();raise HTTPException(400,'Primero agregá y analizá al menos un video de fondo.')
 gen=s.query(Short).count(); seq=optimize(clips,duration,gen); sh=Short(story_id=story_id or None,duration=duration,status='rendering',sequence_json=json.dumps([c.id for c in seq]));s.add(sh);s.commit(); out=OUT/f'short_{sh.id:04d}.mp4'; paths={v.id:v.path for v in s.query(BackgroundVideo).all()}
 try:
  render(seq,paths,out,duration)
  sh.status='ready';sh.output_path=str(out)
  for i,c in enumerate(seq): c.times_used+=1;c.last_used=datetime.utcnow();c.cooldown_until=gen+10;s.add(UsedClip(clip_id=c.id,short_id=sh.id,position=i))
  s.commit(); result={'id':sh.id,'status':'ready','download':f'/api/shorts/{sh.id}/file','sequence':[{'clip':c.id,'source':c.source_video_id,'start':c.start_time,'end':c.end_time,'hook':c.hook_score} for c in seq]}
 except Exception as e:sh.status='failed';s.commit();s.close();raise HTTPException(500,f'Falló el render: {str(e)[:180]}')
 s.close();return result
@app.post('/api/shorts/{sid}/regenerate-background')
def regen(sid:int):
 from tempfile import TemporaryDirectory
 from .render_routes import _lock
 from .narration import overlay
 if not _lock.acquire(blocking=False):raise HTTPException(409,'Ya hay un video generándose. Esperá a que termine.')
 try:
  with SessionLocal() as s:
   sh=s.get(Short,sid)
   if not sh or sh.status!='ready':raise HTTPException(404,'Short listo no encontrado')
   clips=s.query(Clip).all()
   if not clips:raise HTTPException(400,'No hay fondos disponibles')
   seq=optimize(clips,sh.duration,s.query(Short).count()+1)
   paths={v.id:v.path for v in s.query(BackgroundVideo).all()}
   with TemporaryDirectory(prefix='regen-',dir=OUT) as folder:
    background=Path(folder)/'background.mp4';render(seq,paths,background,sh.duration)
    asset=s.get(NarrationAsset,sid)
    result=background
    if asset:
     result=Path(folder)/'final.mp4';overlay(background,asset.audio_path,asset.subtitle_path,result,sh.duration)
    out=OUT/f'short_{sid:04d}_regen.mp4';result.replace(out)
   sh.output_path=str(out);sh.sequence_json=json.dumps([c.id for c in seq]);s.commit()
   return {'status':'ready','download':f'/api/shorts/{sid}/file'}
 except HTTPException:raise
 except Exception as exc:raise HTTPException(500,'No se pudo regenerar el fondo. El video anterior se conserva.') from exc
 finally:_lock.release()
@app.get('/api/shorts')
def shorts():s=db();r=s.query(Short).order_by(Short.id.desc()).all();o=[{'id':x.id,'duration':x.duration,'status':x.status,'created_at':x.created_at.isoformat(),'sequence':json.loads(x.sequence_json)} for x in r];s.close();return o
@app.get('/api/shorts/{sid}/file')
def short_file(sid:int):
 s=db();x=s.get(Short,sid);s.close()
 if not x or not x.output_path or not Path(x.output_path).exists():raise HTTPException(404,'Archivo no disponible')
 return FileResponse(x.output_path,media_type='video/mp4',filename=Path(x.output_path).name)
