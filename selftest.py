"""Invoked by the compiled executable on Windows. Fail build on missing OCR/UI/PDF."""
import json, os, sys, tempfile, traceback
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from core import create_demo, export, render, ocr, ocr_binary, bundle, font_path, VERSION

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
        with tempfile.TemporaryDirectory(prefix='electroreview-test-') as temp:
            p=create_demo(Path(temp)/'project');r=p.state['regions'][0]
            p.decide(r['id'],'КАБЕЛЬ C16','Self-test','approved',r['basis'])
            output=export(p,Path(temp)/'result.pdf')
            if 'КАБЕЛЬ' not in PdfReader(output).pages[0].extract_text():raise RuntimeError('Searchable Cyrillic missing')
            render(output,0);checks.append('PDF render, approved searchable Cyrillic and export')
            import tkinter as tk
            from app import App
            root=tk.Tk();root.withdraw();app=App(root);app.replace(p);root.update_idletasks()
            app.actor.set('Self-test');root.destroy();p.close();p=None
            checks.append('Tk application created; PDF displayed')
        report.write_text(json.dumps({'version':VERSION,'status':'passed','checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception:
        if p:p.close()
        report.write_text(json.dumps({'status':'failed','checks':checks,'error':traceback.format_exc()},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
