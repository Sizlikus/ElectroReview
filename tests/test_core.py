import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Project,box_valid,parse_tsv,export,render,create_demo
from pypdf import PdfReader,PdfWriter
from pypdf.generic import RectangleObject
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);w=PdfWriter();w.add_blank_page(width=600,height=800)
        self.src=self.root/'input.pdf'
        with self.src.open('wb') as f:w.write(f)
        self.p=Project.create(self.src,self.root/'project')
    def tearDown(self):self.p.close();self.tmp.cleanup()
    def test_review_history(self):
        r=self.p.add(0,[.1,.1,.3,.2],'C1O');self.p.decide(r['id'],'C10','Инженер','approved')
        self.assertEqual(r['original'],'C1O');self.assertEqual(len(self.p.state['audit']),2)
        self.p.close();self.p=Project(self.root/'project');self.assertEqual(self.p.state['regions'][0]['text'],'C10')
    def test_no_reviewer(self):
        r=self.p.add(0,[.1,.1,.3,.2])
        with self.assertRaises(ValueError):self.p.decide(r['id'],'C10','','approved')
    def test_finding_basis(self):
        r=self.p.add(0,[.1,.1,.3,.2],kind='finding',severity=100)
        with self.assertRaises(ValueError):self.p.decide(r['id'],'Ошибка','Инженер','approved')
    def test_lock(self):
        with self.assertRaises(ValueError):Project(self.p.folder)
    def test_source_hash(self):
        self.p.close();self.p.source.write_bytes(b'changed')
        with self.assertRaises(ValueError):Project(self.p.folder)
    def test_empty_password(self):
        w=PdfWriter();w.add_blank_page(width=600,height=800);w.encrypt('','owner')
        src=self.root/'encrypted.pdf'
        with src.open('wb') as f:w.write(f)
        p=Project.create(src,self.root/'encrypted');export(p,self.root/'export.pdf');p.close()
    def test_required_password(self):
        w=PdfWriter();w.add_blank_page(width=600,height=800);w.encrypt('password')
        src=self.root/'locked.pdf'
        with src.open('wb') as f:w.write(f)
        with self.assertRaises(ValueError):Project.create(src,self.root/'locked')
    def test_invalid_boxes(self):
        for b in [[0,0,2,1],[0,0,float('nan'),1],[.3,.1,.1,.2]]:
            with self.assertRaises(ValueError):box_valid(b)
    def test_ocr_pending_and_duplicate(self):
        self.p.ingest(0,[{'text':'C16','box':[.1,.1,.2,.2],'confidence':99}]);self.assertEqual(self.p.state['regions'][0]['status'],'pending')
        with self.assertRaises(ValueError):self.p.ingest(0,[])
    def test_empty_ocr(self):
        self.p.ingest(0,[]);self.assertEqual(len(self.p.state['regions']),1)
    def test_tsv(self):
        s='level\tleft\ttop\twidth\theight\tconf\ttext\n5\t10\t20\t20\t10\t85\tC16\n'
        self.assertEqual(parse_tsv(s,100,100)[0]['box'],[.1,.2,.3,.3])
    def test_export_searchable_only_approved(self):
        r=self.p.add(0,[.1,.1,.3,.2]);self.p.decide(r['id'],'КАБЕЛЬ','Инженер','approved')
        self.p.add(0,[.4,.1,.6,.2],'UNAPPROVED')
        out=export(self.p,self.root/'out.pdf');reader=PdfReader(out)
        self.assertIn('КАБЕЛЬ',reader.pages[0].extract_text());self.assertNotIn('UNAPPROVED',reader.pages[0].extract_text())
        self.assertIn('НЕ выполнена',reader.pages[1].extract_text());self.assertEqual(len(reader.pages[0]['/Annots']),1)
    def test_rotation_crop(self):
        w=PdfWriter();p=w.add_blank_page(width=600,height=800);p.cropbox=RectangleObject([50,100,550,700]);p.rotate(90)
        src=self.root/'rot.pdf'
        with src.open('wb') as f:w.write(f)
        p=Project.create(src,self.root/'rot');p.add(0,[.1,.1,.2,.2]);out=export(p,self.root/'rot-out.pdf')
        page=PdfReader(out).pages[0];self.assertEqual(list(map(float,page['/Annots'][0].get_object()['/Rect'])),[60,400,120,450])
        self.assertEqual(render(src,0).size,render(out,0).size);p.close()
    def test_source_export_protected(self):
        with self.assertRaises(ValueError):export(self.p,self.p.source)
    def test_ocr_relative_data_and_stdin(self):
        from unittest.mock import patch
        import core
        from PIL import Image
        calls=[]
        def fake_run(cmd,timeout=240,input_bytes=None):
            calls.append((cmd,input_bytes))
            if '--list-langs' in cmd:return 'List of available languages (2):\nrus\neng\n'
            return 'level\tleft\ttop\twidth\theight\tconf\ttext\n5\t0\t0\t10\t10\t90\tC16\n'
        with patch('core.ocr_command',return_value=(['C:/Проверка программы/ocr/tesseract.exe'],['--tessdata-dir','tessdata'])), patch('core.run_process',side_effect=fake_run):
            words=core.ocr(Image.new('RGB',(20,20),'white'))
        self.assertEqual(words[0]['text'],'C16')
        self.assertIn('stdin',calls[1][0]);self.assertIn('tessdata',calls[1][0])
        self.assertTrue(calls[1][1].startswith(b'\x89PNG'))
    def test_demo(self):
        p=create_demo(self.root/'demo');self.assertFalse(p.state['pages'][0]['has_text']);self.assertEqual(len(p.state['regions']),1);p.close()
if __name__=='__main__':unittest.main()
