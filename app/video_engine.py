import cv2, json, math, subprocess, hashlib
import numpy as np
from pathlib import Path

def metadata(path):
 cap=cv2.VideoCapture(str(path)); fps=cap.get(cv2.CAP_PROP_FPS) or 30; frames=cap.get(cv2.CAP_PROP_FRAME_COUNT); w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)); cap.release(); return {'fps':fps,'duration':frames/fps if fps else 0,'width':w,'height':h}

def _sample(path, step=.35):
 cap=cv2.VideoCapture(str(path)); fps=cap.get(cv2.CAP_PROP_FPS) or 30; dur=(cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps); out=[]; prev=None; t=0.0
 while t<dur:
  cap.set(cv2.CAP_PROP_POS_MSEC,t*1000); ok,f=cap.read()
  if not ok: break
  g=cv2.resize(cv2.cvtColor(f,cv2.COLOR_BGR2GRAY),(160,90)); lap=cv2.Laplacian(g,cv2.CV_64F).var();
  if prev is None: motion=change=0
  else:
   diff=cv2.absdiff(g,prev); change=float(diff.mean()); flow=cv2.calcOpticalFlowFarneback(prev,g,None,.5,2,12,2,5,1.1,0); motion=float(np.linalg.norm(flow,axis=2).mean())
  out.append((t,motion,change,float(lap))); prev=g; t+=step
 cap.release(); return out

def analyze(path):
 m=metadata(path); samples=_sample(path); dur=m['duration'];
 if dur<1 or len(samples)<2: return []
 changes=np.array([x[2] for x in samples]); threshold=max(12,float(np.percentile(changes,82)))
 cuts=[0.0]+[samples[i][0] for i in range(1,len(samples)) if changes[i]>threshold]+[dur]
 # build 4-8s candidates around real visual changes, then fill long spans adaptively
 anchors=sorted(set(round(x,2) for x in cuts)); candidates=[]
 for a in anchors[:-1]:
  for L in (4.5,6.0,7.5):
   b=min(dur,a+L)
   if b-a>=4: candidates.append((a,b))
 # adaptive coverage for videos with few scene cuts
 t=0
 while t+4<=dur:
  local=[x for x in samples if t<=x[0]<=min(dur,t+8)]
  if local:
   peak=max(local,key=lambda x:x[1]+x[2]/10)[0]; start=max(0,min(peak-.6,dur-4)); end=min(dur,start+6)
   if end-start>=4:candidates.append((start,end))
  t+=5.5
 # de-dupe near timestamps
 uniq=[]
 for a,b in sorted(candidates):
  if not uniq or abs(a-uniq[-1][0])>.8: uniq.append((a,b))
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
 slots=max(1,math.ceil(required/min(c.duration for c in clips))); beam=[([],0.0,0.0)]
 for pos in range(slots):
  if all(total >= required for _,_,total in beam): break
  nxt=[]
  for seq,score,total in beam:
   recent=seq[-3:]; groups={c.similarity_group for c in recent}; sources={c.source_video_id for c in recent}
   candidates=[c for c in clips if c not in recent] or [c for c in clips if not recent or c != recent[-1]] or clips
   if total >= required:
    nxt.append((seq,score,total)); continue
   for c in candidates:
    novelty=max(0,100-c.times_used*12); position=c.hook_score if pos==0 else (c.motion_score if pos%3 else c.visual_change_score)
    penalty=(35 if c.similarity_group in groups else 0)+(18 if c.source_video_id in sources else 0)+(50 if c.cooldown_until>generation_no else 0)
    s=weights['hook']*(c.hook_score if pos==0 else c.hook_score*.35)+weights['motion']*c.motion_score+weights['change']*c.visual_change_score+weights['quality']*c.quality_score+weights['novelty']*novelty+weights['position']*position-penalty
    nxt.append((seq+[c],score+s,total+c.duration))
  beam=sorted(nxt,key=lambda x:x[1],reverse=True)[:40]
 best=max(beam,key=lambda x:x[1]+min(x[2],required)*2); return best[0]

def render(sequence, video_paths, output, duration, subtitles=None):
 from tempfile import TemporaryDirectory
 from itertools import cycle
 if not sequence or duration <= 0 or duration > 600: raise ValueError('Secuencia o duración inválida')
 output=Path(output).resolve()
 with TemporaryDirectory(prefix='render-',dir=output.parent) as folder:
  tmp=Path(folder); pieces=[]; remaining=duration
  for i,c in enumerate(cycle(sequence)):
   if c.duration <= 0: raise ValueError('Clip vacío')
   take=min(c.duration,remaining); p=tmp/f'p{i}.mp4'
   vf='scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30'
   subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-ss',str(c.start_time),'-i',str(video_paths[c.source_video_id]),'-t',str(take),'-an','-vf',vf,'-c:v','libx264','-preset','veryfast','-threads','2','-pix_fmt','yuv420p',str(p)],capture_output=True,check=True,timeout=600)
   pieces.append(p); remaining-=take
   if remaining<=.001: break
  lst=tmp/'concat.txt'; lst.write_text('\n'.join("file '"+p.name+"'" for p in pieces))
  result=tmp/'joined.mp4'
  subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-f','concat','-safe','0','-i',str(lst),'-t',str(duration),'-c','copy','-movflags','+faststart',str(result)],capture_output=True,check=True,timeout=600)
  result.replace(output)
 return output
