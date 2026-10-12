import os,tempfile,json,subprocess
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright, expect

with tempfile.TemporaryDirectory() as temp:
 os.environ['SHORTFLOW_DB_PATH']=str(Path(temp)/'db.sqlite')
 os.environ['SHORTFLOW_STORAGE_DIR']=str(Path(temp)/'storage')
 from fastapi.testclient import TestClient
 from app.main import app
 with TestClient(app) as client: html=client.get('/').text
 pair={'id':'pair','title':'Prueba de dos partes','duration':90,'status':'ready','message':'Lista','parts':[{'number':1,'id':11,'title':'Parte 1','text':'Yo conté lo que pasó.','words':5,'duration':90},{'number':2,'id':12,'title':'Parte 2','text':'Yo decidí cómo resolverlo.','words':4,'duration':90}]}
 preview=Path(temp)/'preview.webm'
 subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=10','-t','6','-c:v','libvpx-vp9','-deadline','realtime','-crf','40','-b:v','0',str(preview)],check=True)
 manual={'video_id':1,'duration':600,'revision':'','manual':False,'source':'/api/videos/1/source','segments':[]}
 state={'render_parts':2,'saved':0,'imports':0,'errors':[],'chunk_sizes':[],'upload':None}
 def handle(route):
  request=route.request;path=urlsplit(request.url).path
  payload=None
  if path=='/':return route.fulfill(status=200,content_type='text/html',body=html)
  if path.startswith('/static/'):
   file=Path('app')/path.lstrip('/');return route.fulfill(status=200,content_type='text/javascript' if file.suffix=='.js' else 'text/css',body=file.read_text())
  if path=='/api/stories':payload=[{'id':p['id'],'title':p['title'],'text':p['text']} for p in pair['parts']]
  elif path=='/api/story-generations':payload=[pair]
  elif path=='/api/story-generations/pair':payload=pair
  elif path.startswith('/api/stories/') and request.method=='PUT':
   assert 'name="intro"' in request.post_data
   state['saved']+=1;payload={'status':'saved'}
  elif path=='/api/videos':payload=[{'id':1,'name':'<script>alert(1)</script>','duration':600,'width':1280,'height':720,'status':'ready','clips':208},{'id':2,'name':'Segundo fondo','duration':600,'width':1280,'height':720,'status':'ready','clips':208}]
  elif path=='/api/videos/1/source':
   data=preview.read_bytes();range_header=request.headers.get('range')
   if range_header:
    start,end=range_header.removeprefix('bytes=').split('-');start=int(start);end=min(int(end) if end else len(data)-1,len(data)-1)
    return route.fulfill(status=206,content_type='video/webm',headers={'Accept-Ranges':'bytes','Content-Range':f'bytes {start}-{end}/{len(data)}'},body=data[start:end+1])
   return route.fulfill(status=200,content_type='video/webm',headers={'Accept-Ranges':'bytes'},body=data)
  elif path=='/api/videos/1/segments':
   if request.method=='PUT':
    data=request.post_data_json;assert data['revision']==manual['revision']
    manual.update(manual=True,revision=str(int(manual['revision'] or '0')+1),segments=[dict(x,id=41+i) for i,x in enumerate(data['segments'])])
   elif request.method=='DELETE':manual.update(manual=False,revision='',segments=[])
   payload=manual
  elif path.endswith('/framing') and request.method=='PUT':payload={'side_percent':22.5}
  elif path.endswith('/preview'):return route.fulfill(status=200,content_type='image/jpeg',body=b'')
  elif path=='/api/uploads' and request.method=='POST':
   size=request.post_data_json['size'];state['upload']={'id':'upload1','name':'sample.mp4','size':size,'received':0,'status':'uploading','chunk_size':4*1024**2};payload=state['upload']
  elif path=='/api/uploads':payload=[]
  elif path=='/api/uploads/upload1/chunks':
   chunk=request.post_data_buffer
   if len(chunk)>5*1024**2:return route.fulfill(status=413,content_type='text/html',body='<html>Too large</html>')
   assert int(parse_qs(urlsplit(request.url).query)['offset'][0])==state['upload']['received']
   state['chunk_sizes'].append(len(chunk));state['upload']['received']+=len(chunk);payload=state['upload']
  elif path=='/api/uploads/upload1/complete':
   assert state['upload']['received']==state['upload']['size']
   state['upload'].update(status='ready',message='Fondo listo: 10 clips disponibles.');payload=state['upload']
  elif path=='/api/uploads/upload1':payload=state['upload']
  elif path=='/api/imports':payload=[]
  elif path=='/api/import-url':payload={'id':'import1','status':'running'}
  elif path=='/api/imports/import1':state['imports']+=1;payload={'id':'import1','status':'ready','message':'Fondo importado: 208 clips disponibles.'}
  elif path=='/api/render-jobs' and request.method=='POST':
   assert 'background_ids' in request.post_data
   assert '\r\n[1]\r\n' in request.post_data
   state['preview']='name="preview"\r\n\r\ntrue' in request.post_data
   state['render_parts']=1 if state['preview'] else 2 if 'generation_id' in request.post_data else 1;payload={'id':'render1','status':'running'}
  elif path=='/api/shorts' and request.method=='POST':payload={'id':99,'download':'/api/shorts/99/file'}
  elif path=='/api/render-jobs':payload=[{'id':'old','status':'ready','message':'Videos listos con voz y subtítulos.','shorts':[{'id':1,'download':'/api/shorts/1/file'}]}]
  elif path=='/api/render-jobs/render1':payload={'id':'render1','preview':state.get('preview',False),'status':'ready','message':'Videos listos con voz y subtítulos.','shorts':[{'id':i,'download':f'/api/shorts/{i}/file'} for i in range(1,state['render_parts']+1)]}
  else:return route.fulfill(status=204,body='')
  return route.fulfill(status=200,content_type='application/json',body=json.dumps(payload))
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True, **({'executable_path':os.environ['SHORTFLOW_BROWSER']} if os.environ.get('SHORTFLOW_BROWSER') else {}))
  page=browser.new_page(viewport={'width':1440,'height':1100})
  page.on('pageerror',lambda err:state['errors'].append(str(err)))
  page.route('**/*',handle);page.goto('http://shortflow.test/')
  page.get_by_role('button',name='Fondos',exact=True).click()
  expect(page.locator('#videos')).to_contain_text('<script>alert(1)</script>')
  assert page.locator('#videos script').count()==0
  page.get_by_role('button',name='ELEGIR FRAGMENTOS',exact=True).first.click()
  expect(page.locator('#segmentsMsg')).to_contain_text('Agregá los fragmentos')
  page.locator('#segmentStart').fill('2');page.locator('#segmentEnd').fill('4')
  page.get_by_role('button',name='AGREGAR FRAGMENTO',exact=True).click()
  page.locator('#segmentStart').fill('3');page.locator('#segmentEnd').fill('5')
  page.get_by_role('button',name='AGREGAR FRAGMENTO',exact=True).click()
  expect(page.locator('#segmentsMsg')).to_contain_text('superpone')
  page.get_by_role('button',name='GUARDAR FRAGMENTOS',exact=True).click()
  expect(page.locator('#segmentsMsg')).to_contain_text('Fragmentos guardados')
  page.locator('#segmentList').get_by_role('button',name='EDITAR',exact=True).click()
  page.locator('#segmentStart').fill('2.5')
  page.get_by_role('button',name='ACTUALIZAR FRAGMENTO',exact=True).click()
  page.get_by_role('button',name='GUARDAR FRAGMENTOS',exact=True).click()
  expect(page.locator('#segmentsMsg')).to_contain_text('Fragmentos guardados')
  page.get_by_role('button',name='REPRODUCIR SELECCIÓN',exact=True).click()
  try:
   page.wait_for_function("document.querySelector('#segmentPlayer').paused && document.querySelector('#segmentPlayer').currentTime >= 3.99",timeout=10000)
  except Exception:
   print(page.locator('#segmentPlayer').evaluate("v=>({time:v.currentTime,paused:v.paused,ready:v.readyState,error:v.error?.message,playing:segmentPlaying,bounds:segmentBounds(),message:document.querySelector('#segmentPlaybackError').textContent})"),flush=True)
   print(state['errors'],flush=True)
   raise
  assert page.locator('#segmentPlayer').evaluate('(v)=>v.currentTime')<=4.05
  page.get_by_role('button',name='CREAR SHORT CON ESTE FRAGMENTO',exact=True).click()
  expect(page.locator('#makeMsg')).to_contain_text('Fragmento completo listo')
  page.get_by_role('button',name='Fondos',exact=True).click()
  page.get_by_role('button',name='ELEGIR FRAGMENTOS',exact=True).first.click()
  expect(page.locator('#segmentList')).to_contain_text('2.500 s → 4.000 s')
  page.get_by_role('button',name='USAR TOMAS AUTOMÁTICAS',exact=True).click()
  expect(page.locator('#segmentList')).to_contain_text('Todavía no agregaste')
  page.get_by_role('button',name='QUITAR FRANJAS',exact=True).first.click()
  page.locator('#sideCrop').fill('22.5')
  expect(page.locator('#cropAmount')).to_have_text('22.5% de cada lado')
  page.get_by_role('button',name='GUARDAR RECORTE',exact=True).click()
  expect(page.locator('#framingMsg')).to_contain_text('Recorte guardado')
  page.locator('#url').fill('https://youtu.be/J9dvPQuHz-I');page.locator('#rights').check()
  page.get_by_role('button',name='IMPORTAR VIDEO',exact=True).click()
  expect(page.locator('#urlMsg')).to_contain_text('208 clips')
  page.get_by_role('button',name='Historias',exact=True).click()
  expect(page.locator('#storyPart1')).to_have_value('Yo conté lo que pasó.')
  page.locator('#storyIntro1').fill('Mi hermano vendió mi auto sin avisarme.')
  pair.update(status='needs_review',message='Borrador guardado. Revisá el parentesco <script>alert(1)</script>')
  page.evaluate("watchGeneration('pair')")
  expect(page.locator('#storyReview')).to_contain_text('Revisá el parentesco')
  assert page.locator('#storyReview script').count()==0
  expect(page.locator('#stories')).to_contain_text('BORRADOR PARA REVISAR')
  page.reload()
  page.get_by_role('button',name='Historias',exact=True).click()
  expect(page.locator('#storyReview')).to_contain_text('Revisá el parentesco')
  expect(page.locator('#historias [data-background-picker] input')).to_have_count(2)
  page.locator('#historias [data-background-picker] input[value="2"]').uncheck()
  page.reload()
  page.get_by_role('button',name='Historias',exact=True).click()
  expect(page.locator('#historias [data-background-picker] input[value="2"]')).not_to_be_checked()
  page.locator('#storyPart1').fill('Yo corregí esta parte antes de grabarla.')
  page.get_by_role('button',name='CREAR LOS DOS VIDEOS',exact=True).click()
  expect(page.locator('#makeDownloads a')).to_have_count(2)
  assert state['saved']==2
  page.get_by_role('button',name='Historias',exact=True).click()
  page.locator('#historias').get_by_role('button',name='PROBAR VOZ Y FONDO · 12 S',exact=True).click()
  expect(page.locator('#makeDownloads video')).to_have_count(1)
  expect(page.locator('#makeDownloads a')).to_have_count(1)
  page.locator('#storySelect').select_option('11')
  page.get_by_role('button',name='GENERAR SHORT',exact=True).click()
  expect(page.locator('#makeDownloads a')).to_have_count(1)
  page.locator('#storySelect').select_option('0')
  expect(page.locator('#shortPreview')).to_have_text('PROBAR FONDO · 12 S')
  page.get_by_role('button',name='GENERAR SHORT',exact=True).click()
  expect(page.locator('#makeMsg')).to_contain_text('Fondo listo, sin voz ni subtítulos.')
  expect(page.locator('#makeDownloads a')).to_have_attribute('href','/api/shorts/99/file')
  page.evaluate('resumeRender()')
  expect(page.locator('#makeDownloads a')).to_have_attribute('href','/api/shorts/99/file')
  # A delayed restoration response must not overwrite a newly started render.
  page.evaluate('''async () => {
    const original=storyRequest; let release;
    storyRequest=(...args)=>args[0]==='/api/render-jobs'?new Promise(r=>release=r):original(...args);
    const pending=resumeRender(); beginRender();
    renderMessage('Generando fondo…');
    release([{id:'stale',status:'running',message:'Anterior',shorts:[]}]);
    await pending; storyRequest=original; renderStarting=false;
  }''')
  expect(page.locator('#makeMsg')).to_contain_text('Generando fondo…')
  page.get_by_role('button',name='Fondos',exact=True).click()
  page.locator('#file').set_input_files({'name':'sample.mp4','mimeType':'video/mp4','buffer':b'x'*(9*1024**2)})
  page.get_by_role('button',name='SUBIR Y ANALIZAR',exact=True).click()
  expect(page.locator('#uploadMsg')).to_contain_text('Fondo listo: 10 clips',timeout=30000)
  assert state['chunk_sizes']==[4*1024**2,4*1024**2,1024**2]
  page.route('**/api/uploads',lambda route:route.fulfill(status=502,content_type='text/html',body='<html>Bad gateway</html>') if route.request.method=='POST' else route.fulfill(status=200,content_type='application/json',body='[]'))
  page.route('**/api/videos',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'detail':'La base de datos está ocupada.'})))
  page.get_by_role('button',name='Fondos',exact=True).click()
  expect(page.locator('#videos')).to_contain_text('base de datos está ocupada')
  page.locator('#file').set_input_files({'name':'sample.mp4','mimeType':'video/mp4','buffer':b'test'})
  page.get_by_role('button',name='SUBIR Y ANALIZAR',exact=True).click()
  expect(page.locator('#uploadMsg')).to_contain_text('El servidor no devolvió una respuesta válida')
  assert not state['errors'],state['errors']
  page.screenshot(path=str(Path(temp)/'ui.png'),full_page=True)
  browser.close()
 print('Browser checks passed: safe titles, import, edit both parts, pair render, single render, download links. No JavaScript errors.')
