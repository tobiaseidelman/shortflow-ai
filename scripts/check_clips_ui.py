"""Browser contract checks for uploads, suggestions, editing and downloads."""
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright, expect

with tempfile.TemporaryDirectory() as temp:
    os.environ['SHORTFLOW_DB_PATH']=str(Path(temp)/'db.sqlite')
    os.environ['SHORTFLOW_STORAGE_DIR']=str(Path(temp)/'storage')
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        html=client.get('/').text
    state={'job':None,'chunks':[],'errors':[]}
    def handle(route):
        req=route.request;path=urlsplit(req.url).path;job=state['job'];data=[]
        if path=='/':return route.fulfill(status=200,content_type='text/html',body=html)
        if path.startswith('/static/'):
            file=Path('app')/path.lstrip('/')
            return route.fulfill(status=200,content_type='text/javascript' if file.suffix=='.js' else 'text/css',body=file.read_text())
        if path=='/api/clip-projects':
            if req.method=='POST':
                body=req.post_data_json
                job={'id':'example','name':body['name'],'size':body['size'],'received':0,'status':'uploading','message':'Subiendo',
                     'duration':0,'source':None,'clips':[],'exports':[],'revision':0,'chunk_size':4*1024**2}
                state['job']=job;data=job
            else:data=[job] if job else []
        elif path.endswith('/chunks'):
            offset=int(parse_qs(urlsplit(req.url).query)['offset'][0]);assert offset==job['received']
            state['chunks'].append(len(req.post_data_buffer));job['received']+=len(req.post_data_buffer);data=job
        elif path.endswith('/complete'):
            assert job['received']==job['size']
            job.update(status='uploaded',duration=200,source='/api/clip-projects/example/source');data=job
        elif path.endswith('/analyze'):
            job.update(status='review',message='Propuestas listas',revision=1,clips=[{'start':10,'end':40,'title':'<img src=x onerror=alert(1)>','reason':'El resultado todavía no aparece.'}]);data=job
        elif path.endswith('/clips') and req.method=='PUT':
            body=req.post_data_json;assert body['revision']==job['revision']
            job.update(clips=body['clips'],revision=job['revision']+1,message='Recortes guardados.');data=job
        elif path.endswith('/export'):
            assert req.post_data_json['revision']==job['revision']
            job.update(status='ready',message='Clips exportados.',exports=[{'title':c['title'],'start':c['start'],'end':c['end'],'revision':job['revision'],'name':f'{i}.mp4','download':f'/api/clip-projects/example/files/{i}.mp4'} for i,c in enumerate(job['clips'])]);data=job
        elif path=='/api/clip-projects/example':data=job
        elif path.endswith('/source') or '/files/' in path:return route.fulfill(status=404)
        return route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, **({'executable_path':os.environ['SHORTFLOW_BROWSER']} if os.environ.get('SHORTFLOW_BROWSER') else {}))
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:state['errors'].append(str(e)))
        page.on('dialog',lambda d:d.accept())
        page.route('**/*',handle);page.goto('http://shortflow.test/')
        page.get_by_role('button',name='Clips',exact=True).click()
        expect(page.locator('#clips')).to_be_visible()
        page.locator('#clipFile').set_input_files({'name':'challenge.mp4','mimeType':'video/mp4','buffer':b'x'*(9*1024**2)})
        page.get_by_role('button',name='SUBIR Y BUSCAR CLIPS',exact=True).click()
        expect(page.locator('#clipsMessage')).to_contain_text('Propuestas listas',timeout=15000)
        assert state['chunks']==[4*1024**2,4*1024**2,1024**2]
        assert page.locator('#clipCuts img').count()==0
        expect(page.locator('#clipCuts input').first).to_have_value('<img src=x onerror=alert(1)>')
        page.locator('#clipCuts input[type=number]').nth(1).fill('45')
        page.get_by_role('button',name='AGREGAR CONTINUACIÓN',exact=True).click()
        assert page.locator('#clipCuts article').count()==2
        page.get_by_role('button',name='GUARDAR RECORTES',exact=True).click()
        expect(page.locator('#clipsMessage')).to_contain_text('Recortes guardados')
        assert state['job']['clips'][1]['start']==45
        page.get_by_role('button',name='EXPORTAR LOS CLIPS',exact=True).click()
        expect(page.locator('#clipDownloads a')).to_have_count(2)
        expect(page.locator('#clipsMessage')).to_contain_text('Clips exportados')
        page.reload();page.get_by_role('button',name='Clips',exact=True).click()
        expect(page.locator('#clipDownloads a')).to_have_count(2)
        assert not state['errors'],state['errors']
        screenshot=os.getenv('CLIPS_SCREENSHOT')
        if screenshot:page.screenshot(path=screenshot,full_page=True)
        browser.close()
        print('Clips browser workflow passed: chunk upload, proposal, continuation, edit, export and recovery.')
