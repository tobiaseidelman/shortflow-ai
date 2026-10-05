let selectedStory=0,selectedShort=0;const $=s=>document.querySelector(s);const pages=['dashboard','fondos','historias','crear','editor','historial','config'];
function show(id){pages.forEach(x=>$('#'+x).classList.toggle('active',x===id));document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.page===id));$('#title').textContent=document.querySelector(`button[data-page="${id}"]`).textContent; if(id==='fondos'){loadVideos();resumeImport();resumeUpload();}if(id==='historias'||id==='crear')loadStories();if(['historias','crear','editor'].includes(id))loadBackgroundChoices().catch(()=>{});if(id==='crear')resumeRender();if(id==='historial')loadShorts()}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>show(b.dataset.page));
let activeUpload=false, uploadWatch=null, pendingUpload=null;
function uploadMessage(text,kind='loading') {
  const p=document.createElement('p');p.className=kind;p.textContent=text;
  $('#uploadMsg').replaceChildren(p);
}
function uploadControls(busy) {
  $('#uploadVideo').disabled=busy;$('#file').disabled=busy;
  $('#cancelUpload').disabled=busy;
}
function rememberUpload(value) {
  try {if(value)localStorage.setItem('shortflow-upload',JSON.stringify(value));else localStorage.removeItem('shortflow-upload');}catch(error){}
}
function previousUpload() {
  try {return JSON.parse(localStorage.getItem('shortflow-upload'));}catch(error){return null;}
}
async function sendUploadChunk(id,offset,chunk) {
  for(let attempt=0;attempt<3;attempt++) {
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),120000);
    try {return await storyRequest('/api/uploads/'+id+'/chunks?offset='+offset,
      {method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:chunk,signal:controller.signal});}
    catch(error) {
      if(attempt===2 || (error.status>=400 && error.status<500 && error.status!==408))throw error;
      uploadMessage('La conexión se interrumpió. Reintentando el fragmento…');
      await new Promise(resolve=>setTimeout(resolve,1000*(attempt+1)));
    } finally {clearTimeout(timer);}
  }
}
async function upload() {
  if(activeUpload || uploadWatch)return;
  const file=$('#file').files[0];
  if(!file)return uploadMessage('Elegí un archivo.','err');
  if(file.size>1024**3)return uploadMessage('El límite por archivo es 1 GB. Elegí un archivo más pequeño.','err');
  if(!file.size)return uploadMessage('El archivo está vacío.','err');
  activeUpload=true;uploadControls(true);
  const fingerprint=[file.name,file.size,file.lastModified].join(':');
  try {
    uploadMessage('Preparando la subida por partes…');
    let job, saved=previousUpload();
    if(saved?.fingerprint===fingerprint) {
      try {job=await storyRequest('/api/uploads/'+saved.id);}catch(error){if(error.status!==404)throw error;}
      if(job && job.status!=='uploading')job=null;
    }
    if(!job)job=await storyRequest('/api/uploads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:file.name,size:file.size})});
    pendingUpload=job.id;$('#cancelUpload').hidden=false;
    rememberUpload({id:job.id,fingerprint});
    while(job.received<file.size) {
      const offset=job.received;
      job=await sendUploadChunk(job.id,offset,file.slice(offset,Math.min(offset+job.chunk_size,file.size)));
      uploadMessage('Subiendo: '+Math.floor(job.received/file.size*100)+'% · '+Math.round(job.received/1024**2)+' de '+Math.ceil(file.size/1024**2)+' MB');
    }
    job=await storyRequest('/api/uploads/'+job.id+'/complete',{method:'POST'});
    $('#cancelUpload').hidden=true;rememberUpload(null);
    await watchUpload(job.id);
  } catch(error) {uploadMessage(error.message+' Si la subida quedó a medias, volvé a pulsar SUBIR Y ANALIZAR con el mismo archivo.','err');}
  finally {activeUpload=false;uploadControls(false);}
}
async function watchUpload(id) {
  if(uploadWatch)return;
  uploadWatch=id;uploadControls(true);
  try {
    while(true) {
      const job=await storyRequest('/api/uploads/'+id);
      uploadMessage(job.message,job.status==='ready'?'ok':job.status==='failed'?'err':'loading');
      if(job.status!=='analyzing') {if(job.status==='ready')await loadVideos();break;}
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
  } catch(error) {uploadMessage('No se pudo consultar el análisis. Volvé a Fondos para recuperar el progreso.','err');}
  finally {uploadWatch=null;if(!activeUpload)uploadControls(false);}
}
async function resumeUpload() {
  if(activeUpload || uploadWatch)return;
  try {
    const jobs=await storyRequest('/api/uploads');
    if(activeUpload || uploadWatch)return;
    const analyzing=jobs.find(job=>job.status==='analyzing');
    if(analyzing){$('#cancelUpload').hidden=true;watchUpload(analyzing.id);return;}
    const pending=jobs.find(job=>job.status==='uploading');
    if(pending) {
      pendingUpload=pending.id;$('#cancelUpload').hidden=false;
      uploadMessage('Hay una subida pendiente: '+pending.name+'. Seleccioná el mismo archivo para reanudar desde este navegador, o cancelá la subida para empezar otra.');
    } else if(jobs[0])uploadMessage(jobs[0].message,jobs[0].status==='ready'?'ok':'err');
  } catch(error){uploadMessage(error.message,'err');}
}
async function cancelUpload() {
  if(activeUpload || uploadWatch || !pendingUpload)return;
  try {
    await storyRequest('/api/uploads/'+pendingUpload,{method:'DELETE'});
    pendingUpload=null;rememberUpload(null);$('#cancelUpload').hidden=true;
    uploadMessage('Subida cancelada. Podés elegir otro archivo.','ok');
  } catch(error){uploadMessage(error.message,'err');}
}
let activeImport=null;
function importMessage(text,kind='loading') {
  const p=document.createElement('p');p.className=kind;p.textContent=text;$('#urlMsg').replaceChildren(p);
}
async function importUrl() {
  if(activeImport)return;
  $('#importVideo').disabled=true;
  importMessage('Preparando la importación…');
  const data=new FormData();data.append('url',$('#url').value);data.append('rights',$('#rights').checked);
  try {
    const job=await storyRequest('/api/import-url',{method:'POST',body:data});
    await watchImport(job.id);
  } catch(error){importMessage(error.message,'err');}
  finally {$('#importVideo').disabled=false;}
}
async function watchImport(id) {
  if(activeImport)return;
  activeImport=id;$('#importVideo').disabled=true;
  try {
    while(true) {
      const job=await storyRequest('/api/imports/'+encodeURIComponent(id));
      importMessage(job.message,job.status==='ready'?'ok':job.status==='failed'?'err':'loading');
      if(job.status!=='running'){if(job.status==='ready')await loadVideos();break;}
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
  } catch(error){importMessage('No se pudo consultar el progreso. Volvé a Fondos para recuperarlo.','err');}
  finally {activeImport=null;$('#importVideo').disabled=false;}
}
async function resumeImport() {
  if(activeImport)return;
  try {
    const jobs=await storyRequest('/api/imports');
    const running=jobs.find(job=>job.status==='running');
    if(running)watchImport(running.id);
    else if(jobs[0])importMessage(jobs[0].message,jobs[0].status==='ready'?'ok':'err');
  } catch(error){importMessage('No se pudo consultar la última importación.','err');}
}
async function loadVideos() {
  try {
  const videos=await storyRequest('/api/videos');const container=$('#videos');container.replaceChildren();
  if(!videos.length){const p=document.createElement('p');p.textContent='No hay fondos todavía.';container.append(p);return;}
  const table=document.createElement('table');table.className='table';
  const header=table.insertRow();['Nombre','Duración','Resolución','Estado','Clips','Bordes'].forEach(label=>{const cell=document.createElement('th');cell.textContent=label;header.append(cell);});
  videos.forEach(video=>{const row=table.insertRow();[video.name,video.duration.toFixed(1)+'s',video.width+'×'+video.height,video.status,video.clips].forEach(value=>row.insertCell().textContent=String(value));const b=document.createElement('button');b.textContent='QUITAR FRANJAS';b.onclick=()=>openFraming(video);row.insertCell().append(b);});
  container.append(table);
  } catch(error){$('#videos').textContent=error.message;}
}
let activeGeneration = null, currentPair=null;
function storyMessage(text, kind='loading') {
  const p=document.createElement('p');p.className=kind;p.textContent=text;
  $('#storyMsg').replaceChildren(p);
}
async function storyRequest(url, options) {
  const response=await fetch(url, options);
  let data;
  try {data=await response.json();}
  catch(parseError) {
    const error=new Error(response.status===413?'El servidor rechazó el tamaño de esta solicitud.':
      'El servidor no devolvió una respuesta válida. Puede haberse interrumpido o agotado el tiempo de la solicitud. Revisá Codespaces y volvé a intentar.');
    error.status=response.status;throw error;
  }
  if(!response.ok) {const error=new Error(typeof data.detail==='string'?data.detail:'No se pudo completar la solicitud. Revisá los datos e intentá de nuevo.');error.status=response.status;throw error;}
  return data;
}
function showStoryPair(job) {
  if(!['ready','needs_review'].includes(job.status)||job.parts.length!==2)return;
  currentPair=job;
  $('#storyResult').hidden=false;$('#storyTitle').textContent=job.title;
  $('#storyReview').textContent=job.status==='needs_review'?job.message:'';
  $('#storyReview').hidden=job.status!=='needs_review';
  job.parts.forEach(part=>{
    $('#storyPart'+part.number).value=part.text;
    $('#part'+part.number+'Words').textContent=part.words+' palabras · aprox. '+part.duration+' segundos';
  });
}
async function story() {
  if(activeGeneration)return;
  const button=$('#generateStory');button.disabled=true;
  storyMessage('Preparando la generación de ambas partes…');
  try {
    const data=new FormData();data.append('theme',$('#storyTheme').value);data.append('duration',$('#storyDur').value);
    const job=await storyRequest('/api/stories',{method:'POST',body:data});
    watchGeneration(job.id);
  } catch(error) {storyMessage(error.message,'err');button.disabled=false;}
}
async function watchGeneration(id) {
  if(activeGeneration)return;
  activeGeneration=id;$('#generateStory').disabled=true;
  try {
    while(true) {
      const job=await storyRequest('/api/story-generations/'+encodeURIComponent(id));
      storyMessage(job.message,job.status==='failed'?'err':job.status==='needs_review'?'muted':job.status==='ready'?'ok':'loading');
      if(['ready','needs_review'].includes(job.status)){showStoryPair(job);break;}
      if(job.status==='failed')break;
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
  } catch(error) {storyMessage('No se pudo consultar el progreso. Volvé a entrar en Historias para recuperarlo.','err');}
  finally {activeGeneration=null;$('#generateStory').disabled=false;}
  await loadStories(false);
}
async function copyStoryPart(number) {
  try {await navigator.clipboard.writeText($('#storyPart'+number).value);storyMessage('Parte '+number+' copiada.','ok');}
  catch(error){storyMessage('Seleccioná el texto de la parte y copialo manualmente.','err');}
}
async function loadStories(resume=true) {
  try {
    const [stories,jobs]=await Promise.all([storyRequest('/api/stories'),storyRequest('/api/story-generations')]);
    const select=$('#storySelect'),previous=select.value;
    select.replaceChildren(new Option('Sin historia / solo fondo','0'));
    stories.forEach(story=>select.add(new Option(story.title,String(story.id))));
    if([...select.options].some(option=>option.value===previous))select.value=previous;
    const container=$('#stories');container.replaceChildren();
    jobs.filter(job=>['ready','needs_review'].includes(job.status)).forEach(job=>{
      const card=document.createElement('div');card.className='saved-story';
      const title=document.createElement('strong');title.textContent=job.title;
      const detail=document.createElement('p');detail.className='muted';detail.textContent=(job.status==='needs_review'?'BORRADOR PARA REVISAR · ':'')+'Parte 1 + Parte 2 · '+job.duration+' segundos por parte';
      const button=document.createElement('button');button.textContent='LEER LAS DOS PARTES';button.onclick=()=>showStoryPair(job);
      card.append(title,detail,button);container.append(card);
    });
    const paired=new Set(jobs.flatMap(job=>job.parts.map(part=>part.id)));
    stories.filter(story=>!paired.has(story.id)).forEach(story=>{
      const p=document.createElement('p');p.textContent=story.title+' — '+story.text;container.append(p);
    });
    if(!stories.length){const p=document.createElement('p');p.className='muted';p.textContent='Todavía no hay historias guardadas.';container.append(p);}
    if(resume&&!activeGeneration) {
      const running=jobs.find(job=>job.status==='running');
      if(running)watchGeneration(running.id);
      else if(jobs[0]?.status==='failed')storyMessage(jobs[0].message,'err');
      else if(['ready','needs_review'].includes(jobs[0]?.status)&&$('#storyResult').hidden)showStoryPair(jobs[0]);
    }
  } catch(error) {storyMessage(error.message,'err');}
}
let activeRender=null;
function renderMessage(text,kind='loading') {
  const p=document.createElement('p');p.className=kind;p.textContent=text;$('#makeMsg').replaceChildren(p);
}
async function savePart(number) {
  if(!currentPair)return;
  const part=currentPair.parts.find(p=>p.number===number);
  const fd=new FormData();fd.append('text',$('#storyPart'+number).value);
  await storyRequest('/api/stories/'+part.id,{method:'PUT',body:fd});
  part.text=$('#storyPart'+number).value;
}
async function saveStories() {
  try {await savePart(1);await savePart(2);storyMessage('Cambios guardados.','ok');}
  catch(error){storyMessage(error.message,'err');throw error;}
}
async function makePair() {
  if(!currentPair||activeRender)return;
  try {
    await saveStories();show('crear');
    const fd=new FormData();fd.append('generation_id',currentPair.id);await appendBackgroundSelection(fd);
    const job=await storyRequest('/api/render-jobs',{method:'POST',body:fd});
    await watchRender(job.id);
  } catch(error){renderMessage(error.message,'err');}
}
async function makeShort() {
  if(activeRender)return;
  const fd=new FormData();const id=$('#storySelect').value;
  try {
    await appendBackgroundSelection(fd);
    if(id!=='0') {
      fd.append('story_id',id);
      const job=await storyRequest('/api/render-jobs',{method:'POST',body:fd});await watchRender(job.id);
    } else {
      fd.append('duration',$('#shortDur').value);renderMessage('Generando fondo…');
      const result=await storyRequest('/api/shorts',{method:'POST',body:fd});
      renderLinks([{id:result.id,download:result.download}]);
    }
  } catch(error){renderMessage(error.message,'err');}
}
function renderLinks(shorts) {
  const container=$('#makeDownloads');container.replaceChildren();
  shorts.forEach((short,index)=>{
    const link=document.createElement('a');link.href=short.download;link.textContent='Descargar video '+(index+1)+' · MP4';link.className='download-link';container.append(link);
  });
}
async function watchRender(id) {
  if(activeRender)return;
  activeRender=id;
  try {
    while(true) {
      const job=await storyRequest('/api/render-jobs/'+encodeURIComponent(id));
      renderMessage(job.message,job.status==='ready'?'ok':job.status==='failed'?'err':'loading');renderLinks(job.shorts);
      if(job.status!=='running')break;
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
  } catch(error){renderMessage('No se pudo consultar el progreso. Volvé a Crear Short para recuperarlo.','err');}
  finally{activeRender=null;}
}
async function resumeRender() {
  if(activeRender)return;
  try {
    const jobs=await storyRequest('/api/render-jobs');const running=jobs.find(j=>j.status==='running');
    if(running)watchRender(running.id);
    else if(jobs[0]){renderMessage(jobs[0].message,jobs[0].status==='ready'?'ok':'err');renderLinks(jobs[0].shorts);}
  } catch(error){renderMessage('No se pudo recuperar la última generación.','err');}
}
async function loadShorts(){let a=await fetch('/api/shorts').then(r=>r.json());$('#shorts').innerHTML=a.length?`<table class=table><tr><th>ID</th><th>Fecha</th><th>Duración</th><th>Estado</th><th>Clips</th><th></th></tr>${a.map(x=>`<tr><td>#${x.id}</td><td>${new Date(x.created_at).toLocaleString()}</td><td>${x.duration}s</td><td>${x.status}</td><td>${x.sequence.join(', ')}</td><td><button onclick="editShort(${x.id})">Editar</button> ${x.status==='ready'?`<a href=/api/shorts/${x.id}/file>MP4</a>`:''}</td></tr>`).join('')}</table>`:'<p class=muted>No hay generaciones.</p>'}
function editShort(id){selectedShort=id;show('editor');$('#editorContent').innerHTML=`<h3>Short #${id}</h3><p>Se conserva la historia seleccionada y se genera otra secuencia de fondo. Si este video tiene narración y subtítulos, se conservan sin volver a generarlos.</p><button class=primary onclick="regen(${id})">REGENERAR FONDO</button><div id=regenMsg></div>`}
async function regen(id){msg('#regenMsg','Regenerando únicamente el fondo…','loading');try{const fd=new FormData();await appendBackgroundSelection(fd);let r=await fetch(`/api/shorts/${id}/regenerate-background`,{method:'POST',body:fd}),j=await r.json();if(!r.ok)throw Error(j.detail);msg('#regenMsg',`Listo. <a href="${j.download}">Ver MP4 nuevo</a>`,'ok')}catch(e){msg('#regenMsg',e.message,'err')}}
function msg(sel,t,c){$(sel).innerHTML=`<p class=${c}>${t}</p>`}

let backgroundSelection=null, backgroundChoices=[];
try {const saved=JSON.parse(localStorage.getItem('shortflow-backgrounds'));if(Array.isArray(saved))backgroundSelection=new Set(saved);}catch(error){}
function drawBackgroundChoices() {
  document.querySelectorAll('[data-background-picker]').forEach(container=>{
    container.replaceChildren();
    const title=document.createElement('h3');title.textContent='Fondos que quiero usar';container.append(title);
    const hint=document.createElement('p');hint.className='muted';hint.textContent='Marcá uno para usar solo ese video, o varios para intercalar sus clips.';container.append(hint);
    if(!backgroundChoices.length){const p=document.createElement('p');p.textContent='No hay fondos analizados. Agregalos en Fondos.';container.append(p);}
    backgroundChoices.forEach(v=>{
      const label=document.createElement('label');label.className='background-option';
      const input=document.createElement('input');input.type='checkbox';input.value=v.id;input.checked=backgroundSelection===null||backgroundSelection.has(v.id);
      input.onchange=()=>{if(backgroundSelection===null)backgroundSelection=new Set(backgroundChoices.map(x=>x.id));if(input.checked)backgroundSelection.add(v.id);else backgroundSelection.delete(v.id);try{localStorage.setItem('shortflow-backgrounds',JSON.stringify([...backgroundSelection]));}catch(error){}drawBackgroundChoices();};
      label.append(input,document.createTextNode(v.name));container.append(label);
    });
  });
}
async function loadBackgroundChoices() {
  try{backgroundChoices=(await storyRequest('/api/videos')).filter(v=>v.status==='ready'&&v.clips>0);drawBackgroundChoices();}
  catch(error){document.querySelectorAll('[data-background-picker]').forEach(c=>c.textContent='No se pudieron cargar los fondos. Volvé a entrar en esta sección.');throw error;}
}
async function appendBackgroundSelection(fd) {
  await loadBackgroundChoices();
  const ids=backgroundChoices.filter(v=>backgroundSelection===null||backgroundSelection.has(v.id)).map(v=>v.id);
  if(!ids.length)throw Error('Marcá al menos un fondo analizado.');
  fd.append('background_ids',JSON.stringify(ids));
}
let framingVideo=null;
function openFraming(video) {
  framingVideo=video;$('#framingPanel').hidden=false;$('#framingName').textContent=video.name;
  $('#sideCrop').value=video.side_percent||0;$('#framingSecond').value=1;$('#framingMsg').textContent='';updateFramingPreview();
  $('#framingPanel').scrollIntoView({behavior:'smooth',block:'start'});
}
function updateFramingPreview() {
  if(!framingVideo)return;
  const percent=Number($('#sideCrop').value);$('#cropAmount').textContent=percent+'% de cada lado';
  $('#framingPreview').src='/api/videos/'+framingVideo.id+'/preview?side_percent='+percent+'&second='+Number($('#framingSecond').value||0);
}
async function saveFraming() {
  if(!framingVideo)return;
  const fd=new FormData();fd.append('side_percent',$('#sideCrop').value);
  try{const result=await storyRequest('/api/videos/'+framingVideo.id+'/framing',{method:'PUT',body:fd});framingVideo.side_percent=result.side_percent;$('#framingMsg').textContent='Recorte guardado. Se aplicará al crear videos nuevos o regenerar el fondo.';await loadVideos();}
  catch(error){$('#framingMsg').textContent=error.message;}
}
