/* Source clips are separate from the background library and narrated shorts. */
let clipProject=null, clipBusy=false, clipWatch=null, clipDirty=false, clipPreviewEnd=null;
const clipAPI='/api/clip-projects';
function clipMessage(message,kind='loading') {const p=document.querySelector('#clipsMessage');p.textContent=message;p.className=kind;}
function clipControls() {
  const running=clipBusy||!!clipWatch||['analyzing','exporting'].includes(clipProject?.status);
  document.querySelectorAll('#clips [data-clip-action]').forEach(b=>b.disabled=running);
  document.querySelector('#clipExport').disabled=running||!clipProject?.clips?.length;
  document.querySelector('#clipAnalyze').disabled=running||!clipProject?.source;
  document.querySelector('#clipAdd').disabled=running||!clipProject?.source;
  document.querySelector('#clipSave').disabled=running||!clipProject?.clips?.length;
}
function clipButton(label,action) {const b=document.createElement('button');b.type='button';b.textContent=label;b.dataset.clipAction='';b.onclick=action;return b;}
function clipTime(t) {return Math.floor(t/60)+':'+String(Math.floor(t%60)).padStart(2,'0');}
function clipRequest(path,body,method='POST') {return storyRequest(clipAPI+path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
async function loadClipProjects() {
  try {
    const jobs=await storyRequest(clipAPI);const box=document.querySelector('#clipProjects');box.replaceChildren();
    if(!jobs.length)box.textContent='Todavía no subiste videos a Clips.';
    jobs.forEach(job=>{
      const row=document.createElement('div');row.className='clip-project-row';
      row.append(clipButton(job.name+' · '+({uploading:'Subiendo',uploaded:'Listo para analizar',analyzing:'Analizando',review:'Para revisar',exporting:'Exportando',ready:'Listo',failed:'Interrumpido'}[job.status]||'Guardado'),()=>openClipProject(job.id)));
      box.append(row);
    });
    if(!clipProject&&!clipBusy&&jobs.length)await openClipProject(jobs[0].id);
    clipControls();
  } catch(e) {clipMessage(e.message,'err');}
}
async function openClipProject(id) {
  if(clipBusy||clipWatch)return;
  if(clipDirty&&!confirm('Hay recortes sin guardar. ¿Descartarlos y abrir este video?'))return;
  try {
    clipProject=await storyRequest(clipAPI+'/'+id);clipDirty=false;drawClipProject();
    if(['analyzing','exporting'].includes(clipProject.status))watchClipProject(id);
  } catch(e) {clipMessage(e.message,'err');}
}
function drawClipProject() {
  const job=clipProject;if(!job)return;
  document.querySelector('#clipEditor').hidden=false;
  document.querySelector('#clipName').textContent=job.name+(job.duration?' · '+clipTime(job.duration):'');
  const player=document.querySelector('#clipPlayer');
  if(job.source&&player.getAttribute('src')!==job.source){player.src=job.source;player.load();}
  player.hidden=!job.source;
  clipMessage(job.message,job.status==='ready'?'ok':'');
  const list=document.querySelector('#clipCuts');list.replaceChildren();
  (job.clips||[]).forEach((cut,index)=>{
    const card=document.createElement('article');card.className='clip-cut';
    const heading=document.createElement('h3');heading.textContent='Clip '+(index+1);card.append(heading);
    const label=document.createElement('label');label.textContent='Título';const title=document.createElement('input');title.value=cut.title;title.maxLength=120;title.dataset.clipAction='';title.oninput=()=>{cut.title=title.value;clipDirty=true;};label.append(title);card.append(label);
    const times=document.createElement('div');times.className='two';
    ['start','end'].forEach(key=>{
      const field=document.createElement('label');field.textContent=key==='start'?'Inicio (segundos)':'Final (segundos)';
      const input=document.createElement('input');input.type='number';input.step='.01';input.min='0';input.max=job.duration;input.value=cut[key];input.dataset.clipAction='';
      input.oninput=()=>{cut[key]=Number(input.value);clipDirty=true;};field.append(input);
      field.append(clipButton(key==='start'?'MARCAR INICIO AQUÍ':'MARCAR FINAL AQUÍ',()=>{cut[key]=Math.round(player.currentTime*100)/100;input.value=cut[key];clipDirty=true;}));times.append(field);
    });card.append(times);
    const reason=document.createElement('p');reason.textContent=cut.reason||'Recorte manual. Revisá que el inicio se entienda y el final deje una acción pendiente.';card.append(reason);
    if(cut.last_words){const last=document.createElement('p');last.textContent='Última frase: '+cut.last_words;card.append(last);}
    card.append(clipButton('VER RECORTE',()=>{
      if(!Number.isFinite(cut.start)||!Number.isFinite(cut.end)||cut.end<=cut.start||cut.end>job.duration)return clipMessage('Revisá el inicio y el final.','err');
      clipPreviewEnd=cut.end;player.currentTime=cut.start;player.play().catch(()=>clipMessage('Usá el botón de reproducción del video.'));player.scrollIntoView({block:'center',behavior:'smooth'});
    }),clipButton('AGREGAR CONTINUACIÓN',()=>{
      if(job.clips.length>=12||cut.end>=job.duration-1)return clipMessage('No queda espacio para otra continuación.','err');
      job.clips.push({start:cut.end,end:Math.min(job.duration,cut.end+60),title:cut.title+' · continuación',reason:'Continuación desde el corte anterior. Ajustá su final antes de exportar.'});clipDirty=true;drawClipProject();
    }),clipButton('QUITAR',()=>{job.clips.splice(index,1);clipDirty=true;drawClipProject();}));list.append(card);
  });
  const exports=document.querySelector('#clipDownloads');exports.replaceChildren();
  (job.exports||[]).forEach(item=>{
    const row=document.createElement('article');const label=document.createElement('p');label.textContent=item.title+' · '+clipTime(item.start)+'–'+clipTime(item.end)+(item.revision!==job.revision?' · versión anterior':'');
    const video=document.createElement('video');video.controls=true;video.preload='none';video.src=item.download;video.style='width:100%;max-height:420px';
    const a=document.createElement('a');a.href=item.download;a.textContent='DESCARGAR MP4';a.download='';row.append(label,video,a);exports.append(row);
  });clipControls();
}
async function uploadClipVideo() {
  if(clipBusy||clipWatch)return;
  const file=document.querySelector('#clipFile').files[0];
  if(!file||!file.name.toLowerCase().endsWith('.mp4')||!file.size||file.size>1024**3)return clipMessage('Elegí un MP4 de hasta 1 GB.','err');
  if(clipDirty&&!confirm('Hay recortes sin guardar. ¿Continuar con otra subida?'))return;
  clipBusy=true;clipControls();
  try {
    let saved;try{saved=JSON.parse(localStorage.getItem('shortflow-clip-upload'));}catch(e){}
    let job;
    if(saved?.name===file.name&&saved?.size===file.size&&saved?.modified===file.lastModified){
      try{
        job=await storyRequest(clipAPI+'/'+saved.id);
        if(job.status!=='uploading'&&job.status!=='failed'){
          clipProject=job;clipDirty=false;drawClipProject();
          try{localStorage.removeItem('shortflow-clip-upload');}catch(e){}
          clipBusy=false;
          if(job.status==='uploaded')await analyzeClipVideo();
          else if(['analyzing','exporting'].includes(job.status))await watchClipProject(job.id);
          return;
        }
        if(job.status==='failed')job=null;
      }catch(e){if(e.status!==404)throw e;}
    }
    // A restored server-side pending upload is resumable after browser storage is cleared.
    if(!job&&clipProject?.status==='uploading'&&clipProject.size===file.size&&clipProject.name===file.name){
      job=clipProject;
    }
    if(job?.received){await storyRequest(clipAPI+'/'+job.id+'/chunks?offset=0',{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:file.slice(0,Math.min(job.received,job.chunk_size))});}
    if(!job)job=await clipRequest('',{name:file.name,size:file.size,count:Number(document.querySelector('#clipCount').value),maximum:Number(document.querySelector('#clipMaximum').value)});
    clipProject=job;clipDirty=false;
    try{localStorage.setItem('shortflow-clip-upload',JSON.stringify({id:job.id,name:file.name,size:file.size,modified:file.lastModified}));}catch(e){}
    while(job.received<file.size){
      const offset=job.received;let sent=false;
      for(let attempt=0;attempt<3&&!sent;attempt++){
        try {job=await storyRequest(clipAPI+'/'+job.id+'/chunks?offset='+offset,{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:file.slice(offset,offset+job.chunk_size)});sent=true;}
        catch(e){if(attempt===2||e.status&&e.status<500)throw e;await new Promise(r=>setTimeout(r,1000));}
      }
      clipMessage('Subiendo MP4: '+Math.floor(job.received/file.size*100)+'%');
    }
    clipProject=await clipRequest('/'+job.id+'/complete',{});drawClipProject();
    try{localStorage.removeItem('shortflow-clip-upload');}catch(e){}
    clipBusy=false;await analyzeClipVideo();
  }catch(e){clipMessage(e.message+' Podés seleccionar el mismo archivo y reanudar la subida.','err');}
  finally{clipBusy=false;clipControls();loadClipProjects();}
}
async function analyzeClipVideo() {
  if(!clipProject||clipBusy||clipWatch)return;
  if(clipProject.clips.length&&!confirm('¿Buscar nuevas propuestas? Los recortes actuales se reemplazan solo si el análisis termina bien.'))return;
  clipBusy=true;clipControls();
  try{clipProject=await clipRequest('/'+clipProject.id+'/analyze',{});clipDirty=false;drawClipProject();await watchClipProject(clipProject.id);}
  catch(e){clipMessage(e.message,'err');}
  finally{clipBusy=false;clipControls();}
}
async function watchClipProject(id) {
  if(clipWatch)return;clipWatch=id;clipControls();
  try{
    while(true){
      clipProject=await storyRequest(clipAPI+'/'+id);clipMessage(clipProject.message);
      if(!['analyzing','exporting'].includes(clipProject.status)){clipDirty=false;drawClipProject();break;}
      await new Promise(r=>setTimeout(r,2500));
    }
  }catch(e){clipMessage('No se pudo consultar el progreso. Volvé a Clips para recuperarlo; no hace falta subir de nuevo.','err');}
  finally{clipWatch=null;clipControls();}
}
async function saveClipCuts() {
  if(!clipProject||clipBusy||clipWatch)return false;
  clipBusy=true;clipControls();
  try{
    clipProject=await clipRequest('/'+clipProject.id+'/clips',{revision:clipProject.revision,clips:clipProject.clips.map(c=>({start:c.start,end:c.end,title:c.title,reason:c.reason||''}))},'PUT');
    clipDirty=false;drawClipProject();return true;
  }catch(e){clipMessage(e.message,'err');return false;}
  finally{clipBusy=false;clipControls();}
}
async function exportClipCuts() {
  if(!await saveClipCuts())return;
  clipBusy=true;clipControls();
  try{clipProject=await clipRequest('/'+clipProject.id+'/export',{revision:clipProject.revision,vertical:document.querySelector('#clipFormat').value==='vertical'});drawClipProject();await watchClipProject(clipProject.id);}
  catch(e){clipMessage(e.message,'err');}
  finally{clipBusy=false;clipControls();}
}
function addClipCut() {
  if(!clipProject?.source||clipProject.clips.length>=12)return;
  const start=document.querySelector('#clipPlayer').currentTime||0;
  clipProject.clips.push({start:Math.round(start*100)/100,end:Math.min(clipProject.duration,start+30),title:'Nuevo clip',reason:''});clipDirty=true;drawClipProject();
}
async function deleteClipProject() {
  if(!clipProject||clipBusy||clipWatch||!confirm('¿Eliminar este original y sus clips de la app?'))return;
  try{await storyRequest(clipAPI+'/'+clipProject.id,{method:'DELETE'});clipProject=null;clipDirty=false;document.querySelector('#clipPlayer').pause();document.querySelector('#clipPlayer').removeAttribute('src');document.querySelector('#clipEditor').hidden=true;await loadClipProjects();clipMessage('Video eliminado.');}
  catch(e){clipMessage(e.message,'err');}
}
document.querySelector('#clipPlayer').addEventListener('timeupdate',event=>{if(clipPreviewEnd!==null&&event.target.currentTime>=clipPreviewEnd){event.target.pause();clipPreviewEnd=null;}});
window.addEventListener('beforeunload',event=>{if(clipDirty){event.preventDefault();event.returnValue='';}});
