"""Invoked by the compiled executable on Windows. Fail build on missing OCR/UI/PDF."""
import json, os, sys, tempfile, traceback
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from core import Project, read_pdf, create_demo, export, render, ocr, ocr_directions, ocr_binary, bundle, font_path, VERSION

def check_vertical_ocr(checks):
    from electrical import parse_labels
    page=Image.new('RGB',(900,800),'white')
    for angle,x,text in [(90,50,'NYM 5x6'),(270,450,'NYM 3x2.5')]:
        strip=Image.new('RGB',(500,120),'white');ImageDraw.Draw(strip).text((20,25),text,font=ImageFont.truetype(font_path(),50),fill='black')
        page.paste(strip.rotate(angle,expand=True),(x,80))
    found=ocr_directions(page)
    for size,x in [(6,50),(2.5,450)]:
        matches=[w for w in found if any(c.get('phase_mm2')==size for c in parse_labels(w['text']))]
        if not matches:raise RuntimeError('Vertical OCR failed: '+str(found))
        if not any(x<=900*(w['box'][0]+w['box'][2])/2<=x+120 and 80<=800*(w['box'][1]+w['box'][3])/2<=580 for w in matches):
            raise RuntimeError('Vertical OCR coordinate mapping failed')
    checks.append('Real vertical cable labels in both directions; boxes mapped to original page')

def check_rules(project,temp,checks):
    from electrical import suggested_data
    r=project.add(0,[.3,.3,.5,.4],'QF9 C16 ВВГ 3х2,5 PE 1,5')
    project.decide(r['id'],r['text'],'Self-test','approved')
    d,candidates=suggested_data(r['text'])
    d.update(evidence='Synthetic self-test, not an engineering project',voltage=230,current_kind='AC',phases='1',earthing='TN-S',
             protective_type='PE',protective_material='Cu',protective_mm2=1.5,pe_method='table',pe_route='in_cable')
    circuit=project.confirm_circuit(d,[r['id']],'Self-test');project.check_circuits('Self-test')
    findings=[f for f in project.state['regions'] if f.get('circuit_id')==circuit['id']]
    if len(findings)!=1 or findings[0]['status']!='pending':raise RuntimeError('Expected a pending PE table finding')
    output=export(project,temp/'rules-result.pdf');reader=PdfReader(output)
    text='\n'.join(p.extract_text() for p in reader.pages)
    if '1.7.126' not in text or 'Не проверено' not in text or not reader.pages[0].get('/Annots'):
        raise RuntimeError('Rule report/annotations missing')
    render(output,0);checks.append('Label parsing, confirmed circuit, PE rule, pending annotation and coverage PDF')
    return circuit

def check_aes(temp, scan, checks):
    """Exercise encrypted scanned input using the same import/render/export as the UI."""
    for algorithm in ('AES-128', 'AES-256'):
        source=temp/(algorithm+'.pdf')
        writer=PdfWriter(clone_from=scan)
        writer.encrypt('', owner_password='self-test-owner', algorithm=algorithm)
        writer.write(source)
        if not PdfReader(source).is_encrypted:raise RuntimeError('Fixture is not encrypted')
        project=Project.create(source,temp/algorithm)
        try:
            if render(project.source,0).size!=render(scan,0).size:raise RuntimeError('AES page dimensions changed')
            r=project.add(0,[.1,.1,.3,.2],'КАБЕЛЬ C16')
            project.decide(r['id'],'КАБЕЛЬ C16','Self-test','approved')
            output=export(project,temp/(algorithm+'-result.pdf'))
            reader=PdfReader(output)
            if reader.is_encrypted or 'КАБЕЛЬ' not in reader.pages[0].extract_text():
                raise RuntimeError('AES export/searchable Cyrillic failed')
            render(output,0)
        finally:project.close()
        checks.append(algorithm+' scanned PDF: import, render, approved Cyrillic and export')
        writer.encrypt('required-password', owner_password='self-test-owner', algorithm=algorithm)
        locked=temp/(algorithm+'-locked.pdf');writer.write(locked)
        try:read_pdf(locked)
        except ValueError:pass
        else:raise RuntimeError('PDF requiring a password was accepted')
        checks.append(algorithm+' password-required PDF: rejected with a clear error')

def check_assistant(project,checks):
    from http.server import BaseHTTPRequestHandler,HTTPServer
    import threading
    from assistant_api import request_drafts,page_regions
    r=project.add(0,[.65,.35,.8,.45],'QF88 C20 NYM 3x4')
    captured=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            draft={'drafts':[{'source_ids':[r['id']],'data':{'name':'QF88','breaker_a':20},
                    'field_sources':{'name':[r['id']],'breaker_a':[r['id']]},'warnings':['Synthetic draft only']}]}
            body=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(draft)}}]}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.handle_request,daemon=True);thread.start()
    try:
        drafts=request_drafts({'endpoint':f'http://127.0.0.1:{server.server_port}/v1','model':'synthetic-selftest'},'',
                              page_regions(project.state,0),0,render(project.source,0))
    finally:thread.join(5);server.server_close()
    image=captured[0]['messages'][1]['content'][1]['image_url']['url']
    if not image.startswith('data:image/jpeg;base64,') or r['status']!='pending':raise RuntimeError('Vision payload or draft status invalid')
    checks.append('Optional API: real local HTTP, synthetic OCR+JPEG request, validated draft; no external model called')
    return drafts[0]

def run(report):
    checks=[];p=None
    try:
        if getattr(sys,'frozen',False):
            if ocr_binary().resolve().parent != (bundle()/'ocr').resolve():raise RuntimeError('OCR must be bundled')
            system=Path(os.environ['SystemRoot']);os.environ['PATH']=str(system/'System32')+os.pathsep+str(system)
            checks.append('Bundled OCR selected; external PATH removed')
        im=Image.new('RGB',(1300,240),'white');d=ImageDraw.Draw(im)
        d.text((30,60),'КАБЕЛЬ QF1 C16 230V',font=ImageFont.truetype(font_path(),60),fill='black')
        words=ocr(im);text=' '.join(w['text'] for w in words).upper()
        if 'КАБЕЛЬ' not in text or 'C16' not in text:raise RuntimeError('Russian/English OCR failed: '+text)
        checks.append('Real rus+eng OCR: '+text)
        check_vertical_ocr(checks)
        with tempfile.TemporaryDirectory(prefix='electroreview-test-') as temp:
            p=create_demo(Path(temp)/'project');r=p.state['regions'][0]
            p.decide(r['id'],'КАБЕЛЬ C16','Self-test','approved',r['basis'])
            output=export(p,Path(temp)/'result.pdf')
            if 'КАБЕЛЬ' not in PdfReader(output).pages[0].extract_text():raise RuntimeError('Searchable Cyrillic missing')
            render(output,0);checks.append('PDF render, approved searchable Cyrillic and export')
            check_aes(Path(temp),p.source,checks)
            circuit=check_rules(p,Path(temp),checks)
            draft=check_assistant(p,checks)
            import tkinter as tk
            from app import App
            root=tk.Tk();root.withdraw();app=App(root);app.replace(p);root.update_idletasks()
            app.actor.set('Self-test')
            from circuit_ui import CircuitDialog,CircuitManager
            dialog=CircuitDialog(app,circuit['source_ids'],circuit);root.update_idletasks();dialog.win.destroy()
            manager=CircuitManager(app);root.update_idletasks();manager.win.destroy()
            from quick_ui import QuickReview,AssistantSettings
            quick=QuickReview(app);root.update_idletasks()
            dialog=CircuitDialog(app,draft['source_ids'],draft=draft,page=0);root.update_idletasks()
            if dialog.confirm.get():raise RuntimeError('Human confirmation must default to false')
            dialog.confirm.set(True);dialog.save();root.update_idletasks()
            if not any(c['data']['name']=='QF88' for c in p.state['circuits']):raise RuntimeError('Guided batch approval failed')
            quick.close();settings=AssistantSettings(app);root.update_idletasks();settings.win.destroy()
            app.advanced.set(True);app.toggle_tools();root.update_idletasks()
            root.destroy();p.close();p=None
            checks.append('Tk application, guided review, original crop, batch approval/check, API settings, advanced tools and circuit manager')
        report.write_text(json.dumps({'version':VERSION,'status':'passed','checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception:
        if p:p.close()
        report.write_text(json.dumps({'status':'failed','checks':checks,'error':traceback.format_exc()},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
