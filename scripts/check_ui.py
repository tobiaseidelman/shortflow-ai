import os,tempfile,json
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
  elif path.startswith('/api/stories/') and request.method=='PUT':state['saved']+=1;payload={'status':'saved'}
  elif path=='/api/videos':payload=[{'id':1,'name':'<script>alert(1)</script>','duration':600,'width':1280,'height':720,'status':'ready','clips':208}]
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
   state['render_parts']=2 if 'generation_id' in request.post_data else 1;payload={'id':'render1','status':'running'}
  elif path=='/api/render-jobs':payload=[]
  elif path=='/api/render-jobs/render1':payload={'id':'render1','status':'ready','message':'Videos listos con voz y subtítulos.','shorts':[{'id':i,'download':f'/api/shorts/{i}/file'} for i in range(1,state['render_parts']+1)]}
  else:return route.fulfill(status=204,body='')
  return route.fulfill(status=200,content_type='application/json',body=json.dumps(payload))
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  page=browser.new_page(viewport={'width':1440,'height':1100})
  page.on('pageerror',lambda err:state['errors'].append(str(err)))
  page.route('**/*',handle);page.goto('http://shortflow.test/')
  page.get_by_role('button',name='Fondos',exact=True).click()
  expect(page.locator('#videos')).to_contain_text('<script>alert(1)</script>')
  assert page.locator('#videos script').count()==0
  page.locator('#url').fill('https://youtu.be/J9dvPQuHz-I');page.locator('#rights').check()
  page.get_by_role('button',name='IMPORTAR VIDEO',exact=True).click()
  expect(page.locator('#urlMsg')).to_contain_text('208 clips')
  page.get_by_role('button',name='Historias',exact=True).click()
  expect(page.locator('#storyPart1')).to_have_value('Yo conté lo que pasó.')
  pair.update(status='needs_review',message='Borrador guardado. Revisá el parentesco <script>alert(1)</script>')
  page.evaluate("watchGeneration('pair')")
  expect(page.locator('#storyReview')).to_contain_text('Revisá el parentesco')
  assert page.locator('#storyReview script').count()==0
  expect(page.locator('#stories')).to_contain_text('BORRADOR PARA REVISAR')
  page.reload()
  page.get_by_role('button',name='Historias',exact=True).click()
  expect(page.locator('#storyReview')).to_contain_text('Revisá el parentesco')
  page.locator('#storyPart1').fill('Yo corregí esta parte antes de grabarla.')
  page.get_by_role('button',name='CREAR LOS DOS VIDEOS',exact=True).click()
  expect(page.locator('#makeDownloads a')).to_have_count(2)
  assert state['saved']==2
  page.locator('#storySelect').select_option('11')
  page.get_by_role('button',name='GENERAR SHORT',exact=True).click()
  expect(page.locator('#makeDownloads a')).to_have_count(1)
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
