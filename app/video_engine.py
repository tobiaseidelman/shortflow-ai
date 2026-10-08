import cv2, json, math, subprocess, hashlib
import numpy as np
from pathlib import Path

def metadata(path):
 cap=cv2.VideoCapture(str(path)); fps=cap.get(cv2.CAP_PROP_FPS) or 30; frames=cap.get(cv2.CAP_PROP_FRAME_COUNT); w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)); cap.release(); return {'fps':fps,'duration':frames/fps if fps else 0,'width':w,'height':h}

def _sample(path, step=.35):
 cap=cv2.VideoCapture(str(path)); fps=cap.get(cv2.CAP_PROP_FPS) or 30; out=[]; prev=None
 stride=max(1,round(fps*step)); frame=-1
 while cap.grab():
  frame+=1
  if frame%stride: continue
  ok,f=cap.retrieve()
  if not ok: continue
  t=frame/fps
  g=cv2.resize(cv2.cvtColor(f,cv2.COLOR_BGR2GRAY),(160,90)); lap=cv2.Laplacian(g,cv2.CV_64F).var();
  if prev is None: motion=change=0
  else:
   diff=cv2.absdiff(g,prev); change=float(diff.mean()); flow=cv2.calcOpticalFlowFarneback(prev,g,None,.5,2,12,2,5,1.1,0); motion=float(np.linalg.norm(flow,axis=2).mean())
  out.append((t,motion,change,float(lap))); prev=g
 cap.release(); return out

def analyze(path):
 m=metadata(path); samples=_sample(path); dur=m['duration'];
 if dur<1 or len(samples)<2: return []
 changes=np.array([x[2] for x in samples]); threshold=max(12,float(np.percentile(changes,82)))
 # Keep complete detected shots; never manufacture overlapping 4-8 second windows.
 # A large, isolated visual jump is safer than a percentile alone (which cuts motion).
 boundaries=[0.0]
 for i in range(2,len(samples)-2):
  neighbors=[changes[j] for j in (i-2,i-1,i+1,i+2)]
  if changes[i] > max(30, float(np.median(neighbors))*3) and samples[i][0]-boundaries[-1]>=2:
   boundaries.append(samples[i][0])
 if dur-boundaries[-1]<1: boundaries.pop()
 boundaries.append(dur)
 uniq=list(zip(boundaries,boundaries[1:]))
 def norm(v,scale): return max(0,min(100,v/scale*100))
 result=[]
 for a,b in uniq:
  ss=[x for x in samples if a<=x[0]<=b]
  if len(ss)<2: continue
  mot=np.array([x[1] for x in ss]); ch=np.array([x[2] for x in ss]); q=np.array([x[3] for x in ss]); early=[x for x in ss if x[0]<=a+2] or ss[:3]
  base=np.median(mot)+.15; onset=next((x[0]-a for x in ss if x[1]>base*1.35 or x[2]>threshold*.75),2.5)
  motion=norm(float(mot.mean()),2.4); visual=norm(float(ch.mean()),20); quality=norm(float(np.median(q)),700)
  em=norm(float(np.mean([x[1] for x in early])),2.0); ec=norm(float(np.mean([x[2] for x in early])),18); onset_score=max(0,100-onset*35)
  hook=.42*em+.28*ec+.2*onset_score+.1*quality
  att=[]
  for sec in range(max(1,math.ceil(b-a))):
   z=[x for x in ss if a+sec<=x[0]<a+sec+1]; att.append(round(.65*norm(float(np.mean([x[1] for x in z])) if z else 0,2.0)+.35*norm(float(np.mean([x[2] for x in z])) if z else 0,18),1))
  loop=max(0,100-abs(att[0]-att[-1]) if att else 0); group=hashlib.sha1(f'{round(motion/15)}:{round(visual/15)}'.encode()).hexdigest()[:8]
  result.append(dict(start_time=round(a,2),end_time=round(b,2),duration=round(b-a,2),motion_score=round(motion,1),visual_change_score=round(visual,1),action_onset=round(onset,2),quality_score=round(quality,1),hook_score=round(hook,1),loop_score=round(loop,1),similarity_group=group,attention_curve=json.dumps(att)))
 return result

def optimize(clips, required, generation_no=0, weights=None):
 weights=weights or {'hook':.28,'motion':.20,'change':.14,'quality':.10,'novelty':.16,'position':.12}
 if not clips: raise ValueError('No hay clips disponibles')
 clips=[c for c in clips if c.duration > 0]
 if not clips: raise ValueError('No hay clips válidos')
 source_ids=sorted({c.source_video_id for c in clips})
 first_source=source_ids[generation_no % len(source_ids)]
 slots=max(1,math.ceil(required/min(c.duration for c in clips))); beam=[([],0.0,0.0)]
 for pos in range(slots):
  if all(total >= required for _,_,total in beam): break
  nxt=[]
  for seq,score,total in beam:
   recent=seq[-3:]; groups={c.similarity_group for c in recent}; sources={c.source_video_id for c in recent}
   # Alternate source videos before ranking individual clips. A soft score alone
   # lets a high-scoring source monopolize every short.
   allowed_sources=set(source_ids)
   if len(source_ids)>1:
    if not seq:
     allowed_sources={first_source}
    else:
     allowed_sources.discard(seq[-1].source_video_id)
     counts={sid:sum(c.source_video_id==sid for c in seq) for sid in allowed_sources}
     least=min(counts.values())
     allowed_sources={sid for sid in allowed_sources if counts[sid]==least}
   def overlaps(a,b):
    if a.source_video_id != b.source_video_id: return False
    start_a=getattr(a,'start_time',0); start_b=getattr(b,'start_time',0)
    return min(start_a+a.duration,start_b+b.duration)-max(start_a,start_b) > .001
   unused=[c for c in clips if not any(overlaps(c,old) for old in seq)]
   candidates=[c for c in unused if c.source_video_id in allowed_sources] or unused
   if total >= required:
    nxt.append((seq,score,total)); continue
   if not candidates: continue
   least_used=min(c.times_used for c in candidates)
   candidates=[c for c in candidates if c.times_used==least_used]
   for c in candidates:
    novelty=max(0,100-c.times_used*12); position=c.hook_score if pos==0 else (c.motion_score if pos%3 else c.visual_change_score)
    penalty=(35 if c.similarity_group in groups else 0)+(18 if c.source_video_id in sources else 0)+(50 if c.cooldown_until>generation_no else 0)
    s=weights['hook']*(c.hook_score if pos==0 else c.hook_score*.35)+weights['motion']*c.motion_score+weights['change']*c.visual_change_score+weights['quality']*c.quality_score+weights['novelty']*novelty+weights['position']*position-penalty
    nxt.append((seq+[c],score+s,total+c.duration))
  if not nxt: break
  beam=sorted(nxt,key=lambda x:x[1],reverse=True)[:40]
 complete=[item for item in beam if item[2]>=required]
 if not complete: raise ValueError('No alcanza el fondo sin repetir fragmentos. Elegí más fondos o una historia más corta.')
 return max(complete,key=lambda x:x[1])[0]

def render(sequence, video_paths, output, duration, subtitles=None, crops=None):
 from tempfile import TemporaryDirectory
 if not sequence or duration <= 0 or duration > 600: raise ValueError('Secuencia o duración inválida')
 if sum(c.duration for c in sequence)+.001 < duration: raise ValueError('El fondo no alcanza para completar el video sin repetir.')
 output=Path(output).resolve()
 with TemporaryDirectory(prefix='render-',dir=output.parent) as folder:
  tmp=Path(folder); pieces=[]; remaining=duration
  for i,c in enumerate(sequence):
   if c.duration <= 0: raise ValueError('Clip vacío')
   take=min(c.duration,remaining); p=tmp/f'p{i}.mp4'
   percent=(crops or {}).get(c.source_video_id, 0)
   if not 0 <= percent <= 40: raise ValueError('Recorte lateral inválido')
   crop=f'crop=iw-2*trunc(iw*{percent}/100/2)*2:ih:trunc(iw*{percent}/100/2)*2:0,' if percent else ''
   # Normalize display aspect ratio; only the blurred duplicate may be cropped.
   vf=(crop+'scale=trunc(iw*sar/2)*2:ih,setsar=1,split=2[back][front];'
       '[back]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,'
       'boxblur=12:2,scale=1080:1920[blur];'
       '[front]scale=1080:1920:force_original_aspect_ratio=decrease:'
       'force_divisible_by=2[fit];'
       '[blur][fit]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[out]')
   subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-ss',str(c.start_time),'-i',str(video_paths[c.source_video_id]),'-t',str(take),'-an','-filter_complex_threads','1','-filter_complex',vf,'-map','[out]','-c:v','libx264','-preset','veryfast','-threads','2','-pix_fmt','yuv420p',str(p)],capture_output=True,check=True,timeout=600)
   pieces.append(p); remaining-=take
   if remaining<=.001: break
  lst=tmp/'concat.txt'; lst.write_text('\n'.join("file '"+p.name+"'" for p in pieces))
  result=tmp/'joined.mp4'
  subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-f','concat','-safe','0','-i',str(lst),'-t',str(duration),'-c','copy','-movflags','+faststart',str(result)],capture_output=True,check=True,timeout=600)
  result.replace(output)
 return output
