let selectedStory=0,selectedShort=0;const $=s=>document.querySelector(s);const pages=['dashboard','fondos','historias','crear','editor','historial','config'];
function show(id){pages.forEach(x=>$('#'+x).classList.toggle('active',x===id));document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.page===id));$('#title').textContent=document.querySelector(`button[data-page="${id}"]`).textContent; if(id==='fondos'){loadVideos();resumeImport();}if(id==='historias'||id==='crear')loadStories();if(id==='historial')loadShorts()}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>show(b.dataset.page));
async function upload(){let f=$('#file').files[0];if(!f)return msg('#uploadMsg','Elegí un archivo.','err');let fd=new FormData();fd.append('file',f);msg('#uploadMsg','Subiendo y analizando frames… puede tardar según el video.','loading');try{let r=await fetch('/api/videos/upload',{method:'POST',body:fd}),j=await r.json();if(!r.ok)throw Error(j.detail);msg('#uploadMsg',`Listo: ${j.clips} clips detectados y puntuados.`,'ok');loadVideos()}catch(e){msg('#uploadMsg',e.message,'err')}}
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
  const videos=await storyRequest('/api/videos');const container=$('#videos');container.replaceChildren();
  if(!videos.length){const p=document.createElement('p');p.textContent='No hay fondos todavía.';container.append(p);return;}
  const table=document.createElement('table');table.className='table';
  const header=table.insertRow();['Nombre','Duración','Resolución','Estado','Clips'].forEach(label=>{const cell=document.createElement('th');cell.textContent=label;header.append(cell);});
  videos.forEach(video=>{const row=table.insertRow();[video.name,video.duration.toFixed(1)+'s',video.width+'×'+video.height,video.status,video.clips].forEach(value=>row.insertCell().textContent=String(value));});
  container.append(table);
}
let activeGeneration = null;
function storyMessage(text, kind='loading') {
  const p=document.createElement('p');p.className=kind;p.textContent=text;
  $('#storyMsg').replaceChildren(p);
}
async function storyRequest(url, options) {
  const response=await fetch(url, options);
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Revisá el tema y la duración e intentá de nuevo.');
  return data;
}
function showStoryPair(job) {
  if(job.status!=='ready'||job.parts.length!==2)return;
  $('#storyResult').hidden=false;$('#storyTitle').textContent=job.title;
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
      storyMessage(job.message,job.status==='failed'?'err':job.status==='ready'?'ok':'loading');
      if(job.status==='ready'){showStoryPair(job);break;}
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
    jobs.filter(job=>job.status==='ready').forEach(job=>{
      const card=document.createElement('div');card.className='saved-story';
      const title=document.createElement('strong');title.textContent=job.title;
      const detail=document.createElement('p');detail.className='muted';detail.textContent='Parte 1 + Parte 2 · '+job.duration+' segundos por parte';
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
      else if(jobs[0]?.status==='ready'&&$('#storyResult').hidden)showStoryPair(jobs[0]);
    }
  } catch(error) {storyMessage('No se pudieron cargar las historias. Volvé a intentarlo.','err');}
}
async function makeShort(){let fd=new FormData();fd.append('story_id',$('#storySelect').value);fd.append('duration',$('#shortDur').value);msg('#makeMsg','Optimizando la secuencia y renderizando 1080×1920…','loading');try{let r=await fetch('/api/shorts',{method:'POST',body:fd}),j=await r.json();if(!r.ok)throw Error(j.detail);selectedShort=j.id;msg('#makeMsg',`Short #${j.id} listo. <a href="${j.download}">Descargar MP4</a>`,'ok')}catch(e){msg('#makeMsg',e.message,'err')}}
async function loadShorts(){let a=await fetch('/api/shorts').then(r=>r.json());$('#shorts').innerHTML=a.length?`<table class=table><tr><th>ID</th><th>Fecha</th><th>Duración</th><th>Estado</th><th>Clips</th><th></th></tr>${a.map(x=>`<tr><td>#${x.id}</td><td>${new Date(x.created_at).toLocaleString()}</td><td>${x.duration}s</td><td>${x.status}</td><td>${x.sequence.join(', ')}</td><td><button onclick="editShort(${x.id})">Editar</button> ${x.status==='ready'?`<a href=/api/shorts/${x.id}/file>MP4</a>`:''}</td></tr>`).join('')}</table>`:'<p class=muted>No hay generaciones.</p>'}
function editShort(id){selectedShort=id;show('editor');$('#editorContent').innerHTML=`<h3>Short #${id}</h3><p>Se conserva la historia seleccionada y se genera otra secuencia de fondo. El video aún no incluye voz ni subtítulos.</p><button class=primary onclick="regen(${id})">REGENERAR FONDO</button><div id=regenMsg></div>`}
async function regen(id){msg('#regenMsg','Regenerando únicamente el fondo…','loading');try{let r=await fetch(`/api/shorts/${id}/regenerate-background`,{method:'POST'}),j=await r.json();if(!r.ok)throw Error(j.detail);msg('#regenMsg',`Listo. <a href="${j.download}">Ver MP4 nuevo</a>`,'ok')}catch(e){msg('#regenMsg',e.message,'err')}}
function msg(sel,t,c){$(sel).innerHTML=`<p class=${c}>${t}</p>`}
