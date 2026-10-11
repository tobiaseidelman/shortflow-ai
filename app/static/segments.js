let segmentState=null, segmentEditing=-1, segmentDirty=false, segmentPlaying=false, segmentBusy=false, segmentEpoch=0;
const segmentPlayer=$('#segmentPlayer');
function segmentMessage(text,error=false){const el=$('#segmentsMsg');el.textContent=text;el.className=error?'err':'ok';}
function segmentBounds(){return {start:Number($('#segmentStart').value),end:Number($('#segmentEnd').value)};}
function segmentValid({start,end}){return segmentState&&Number.isFinite(start)&&Number.isFinite(end)&&start>=0&&end<=segmentState.duration&&end-start>=.25&&end-start<=300;}
function segmentControls(){
 const valid=segmentValid(segmentBounds());
 $('#segmentDuration').textContent=valid?'Duración: '+(segmentBounds().end-segmentBounds().start).toFixed(3)+' segundos':'Elegí un intervalo de 0,25 a 300 segundos dentro del video.';
 $('#playSegment').disabled=!valid||segmentPlayer.readyState<1;
 $('#addSegment').disabled=segmentBusy||!valid;$('#saveSegments').disabled=segmentBusy||!segmentDirty||!segmentState?.segments.length;
 $('#resetSegments').disabled=segmentBusy||!segmentState?.manual;
}
function setSegmentBounds(start,end){
 segmentPlaying=false;segmentPlayer.pause();
 $('#segmentStart').value=start;$('#segmentEnd').value=end;
 $('#segmentStartRange').value=start;$('#segmentEndRange').value=end;segmentControls();
}
async function openSegments(video){
 if(segmentBusy)return;
 const epoch=++segmentEpoch;segmentPlayer.pause();segmentState=null;$('#segmentsPanel').hidden=false;$('#segmentsName').textContent=video.name;
 $('#segmentList').replaceChildren();segmentMessage('Cargando fragmentos…');$('#segmentPlaybackError').textContent='';segmentControls();
 try{
  const result=await storyRequest('/api/videos/'+video.id+'/segments');if(epoch!==segmentEpoch)return;
  segmentState=result;segmentDirty=false;segmentEditing=-1;
  for(const id of ['segmentStart','segmentEnd','segmentStartRange','segmentEndRange'])$('#'+id).max=result.duration;
  segmentPlayer.src=result.source;segmentPlayer.load();setSegmentBounds(0,Math.min(20,result.duration));renderSegments();
  segmentMessage(result.manual?'Fragmentos guardados cargados.':'Agregá los fragmentos que querés conservar y guardá la lista.');
  $('#segmentsPanel').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(error){if(epoch===segmentEpoch)segmentMessage(error.message,true);}
}
function markSegment(which){if(!segmentState)return;const bounds=segmentBounds();bounds[which]=Math.round(segmentPlayer.currentTime*1000)/1000;setSegmentBounds(bounds.start,bounds.end);}
function newSegment(){if(!segmentState||segmentBusy)return;segmentEditing=-1;$('#addSegment').textContent='AGREGAR FRAGMENTO';const start=Math.min(segmentPlayer.currentTime,Math.max(0,segmentState.duration-.25));setSegmentBounds(start,Math.min(start+20,segmentState.duration));}
async function playSegment(){
 if(!segmentValid(segmentBounds())||segmentPlayer.readyState<1)return;
 segmentPlayer.currentTime=segmentBounds().start;segmentPlaying=true;
 try{await segmentPlayer.play();}catch(error){segmentPlaying=false;$('#segmentPlaybackError').textContent='No se pudo reproducir este formato. Podés marcar los tiempos manualmente o usar un MP4 compatible con el navegador.';}
}
function checkSegmentEnd(){if(segmentPlaying&&segmentPlayer.currentTime>=segmentBounds().end){segmentPlayer.pause();segmentPlayer.currentTime=segmentBounds().end;segmentPlaying=false;}}
function watchSegmentFrame(){checkSegmentEnd();if(!segmentPlayer.paused)requestAnimationFrame(watchSegmentFrame);}
segmentPlayer.addEventListener('loadedmetadata',segmentControls);
segmentPlayer.addEventListener('play',watchSegmentFrame);segmentPlayer.addEventListener('timeupdate',checkSegmentEnd);
segmentPlayer.addEventListener('pause',()=>{segmentPlaying=false;});
segmentPlayer.addEventListener('error',()=>{$('#segmentPlaybackError').textContent='El navegador no puede reproducir este archivo. Probá un MP4 con video H.264. Los tiempos se pueden editar igualmente.';});
for(const which of ['Start','End']){
 const number=$('#segment'+which),range=$('#segment'+which+'Range');
 number.oninput=()=>{segmentPlaying=false;segmentPlayer.pause();range.value=number.value;segmentControls();};
 range.oninput=()=>{segmentPlaying=false;segmentPlayer.pause();number.value=range.value;segmentControls();};
}
function addSegment(){
 if(segmentBusy||!segmentValid(segmentBounds()))return;
 const value=segmentBounds();
 if(segmentState.segments.some((s,i)=>i!==segmentEditing&&value.start<s.end&&value.end>s.start)){segmentMessage('Ese fragmento se superpone con otro de la lista.',true);return;}
 if(segmentEditing<0){if(segmentState.segments.length>=200){segmentMessage('Podés guardar hasta 200 fragmentos por fondo.',true);return;}segmentState.segments.push(value);}
 else segmentState.segments[segmentEditing]=value;
 segmentState.segments.sort((a,b)=>a.start-b.start);segmentDirty=true;segmentEditing=-1;$('#addSegment').textContent='AGREGAR FRAGMENTO';renderSegments();segmentMessage('Cambios sin guardar. Tocá GUARDAR FRAGMENTOS para usarlos.');
}
function renderSegments(){
 const list=$('#segmentList');list.replaceChildren();
 if(!segmentState?.segments.length){list.textContent='Todavía no agregaste fragmentos.';segmentControls();return;}
 segmentState.segments.forEach((s,i)=>{
  const row=document.createElement('div');row.className='saved-story';
  const label=document.createElement('p');label.textContent=`${i+1}. ${s.start.toFixed(3)} s → ${s.end.toFixed(3)} s · ${(s.end-s.start).toFixed(3)} s`;row.append(label);
  const button=(text,action)=>{const b=document.createElement('button');b.textContent=text;b.disabled=segmentBusy;b.onclick=action;row.append(b);return b;};
  button('EDITAR',()=>{segmentEditing=i;setSegmentBounds(s.start,s.end);segmentPlayer.currentTime=s.start;$('#addSegment').textContent='ACTUALIZAR FRAGMENTO';});
  button('VER',()=>{setSegmentBounds(s.start,s.end);playSegment();});
  button('QUITAR',()=>{segmentState.segments.splice(i,1);segmentDirty=true;segmentEditing=-1;$('#addSegment').textContent='AGREGAR FRAGMENTO';renderSegments();segmentMessage('Cambios sin guardar.');});
  button('CREAR SHORT CON ESTE FRAGMENTO',()=>makeManualShort(s.id)).disabled=segmentBusy||segmentDirty||!s.id;
  list.append(row);
 });segmentControls();
}
async function storeSegments(method){
 if(!segmentState||segmentBusy)return;
 segmentBusy=true;renderSegments();
 try{
  const body={revision:segmentState.revision};if(method==='PUT')body.segments=segmentState.segments.map(({start,end})=>({start,end}));
  segmentState=await storyRequest('/api/videos/'+segmentState.video_id+'/segments',{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  segmentDirty=false;segmentEditing=-1;$('#addSegment').textContent='AGREGAR FRAGMENTO';
  segmentMessage(method==='PUT'?'Fragmentos guardados. Se usarán en los próximos shorts.':'Tomas automáticas restauradas.');await loadVideos();
 }catch(error){segmentMessage(error.message,true);}
 finally{segmentBusy=false;renderSegments();}
}
function saveSegments(){return storeSegments('PUT');}
function resetSegments(){return storeSegments('DELETE');}
async function makeManualShort(id){
 if(segmentDirty||segmentBusy||activeRender||renderStarting)return;
 segmentPlayer.pause();beginRender();show('crear');renderMessage('Creando el fragmento completo…');
 try{
  const fd=new FormData();fd.append('clip_id',id);fd.append('background_ids',JSON.stringify([segmentState.video_id]));
  const result=await storyRequest('/api/shorts',{method:'POST',body:fd});renderLinks([{id:result.id,download:result.download}],true);$('#makeDownloads a').textContent='Descargar fragmento · MP4';renderMessage('Fragmento completo listo, sin voz ni subtítulos.','ok');
 }catch(error){renderMessage(error.message,'err');}finally{renderStarting=false;}
}
