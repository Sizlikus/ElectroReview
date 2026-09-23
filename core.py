"""Local review, no network requests. Coordinates are normalized display-page coordinates."""
import csv, hashlib, io, json, math, os, shutil, subprocess, sys, tempfile, uuid
from pathlib import Path
from datetime import datetime, timezone
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.annotations import Rectangle
from pypdf.generic import RectangleObject, NameObject, ArrayObject, FloatObject, TextStringObject, NumberObject

VERSION='0.2.0'
MAX_BYTES=100_000_000
LABELS={'pending':'Ожидает подтверждения','approved':'Утверждено','excluded':'Исключено'}
def now(): return datetime.now(timezone.utc).isoformat()
def bundle(): return Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent

def home():
    p=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'ElectroReview'
    p.mkdir(parents=True,exist_ok=True); return p

def box_valid(b):
    if len(b)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in b): raise ValueError('Неверная область')
    if not (0<=b[0]<b[2]<=1 and 0<=b[1]<b[3]<=1): raise ValueError('Область за пределами листа')
    return list(b)

def read_pdf(path):
    r=PdfReader(str(path))
    if r.is_encrypted and not r.decrypt(''): raise ValueError('PDF требует пароль. Сохраните доступную копию без пароля.')
    if not r.pages: raise ValueError('В PDF нет страниц')
    return r

def render(path,page,scale=1.5):
    with pdfium.PdfDocument(str(path)) as d:
        p=d[page];w,h=p.get_size();scale=min(scale,(24_000_000/max(w*h,1))**.5)
        bitmap=p.render(scale=scale)
        try: return bitmap.to_pil().copy().convert('RGB')
        finally: bitmap.close();p.close()

class Project:
    def __init__(self,folder):
        self.folder=Path(folder);self.source=self.folder/'source.pdf';self.path=self.folder/'project.json';self.lock=None
        self.state=json.loads(self.path.read_text(encoding='utf-8'))
        if self.state.get('schema')!=2: raise ValueError('Неподдерживаемый формат проекта')
        if hashlib.sha256(self.source.read_bytes()).hexdigest()!=self.state['sha256']: raise ValueError('Исходный PDF изменён')
        for r in self.state['regions']:box_valid(r['box'])
        self.lock=open(self.folder/'.lock','a+b');self.lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                if self.lock.read(1)==b'': self.lock.write(b'0');self.lock.flush()
                self.lock.seek(0);msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.lock.close();self.lock=None;raise ValueError('Проект уже открыт в другом окне')
    def close(self):
        if self.lock:
            self.lock.close();self.lock=None
    def __del__(self): self.close()
    @classmethod
    def create(cls,source,folder):
        source=Path(source);folder=Path(folder)
        if source.stat().st_size>MAX_BYTES:raise ValueError('Лимит файла: 100 МБ')
        reader=read_pdf(source);pages=[]
        for p in reader.pages:
            try:has_text=bool((p.extract_text() or '').strip())
            except Exception:has_text=False
            pages.append({'has_text':has_text,'ocr':'not_run'})
        folder.mkdir(parents=True,exist_ok=True)
        if any(folder.iterdir()):raise ValueError('Для нового проекта нужна пустая папка')
        data=source.read_bytes();(folder/'source.pdf').write_bytes(data)
        state={'schema':2,'version':VERSION,'name':source.name,'sha256':hashlib.sha256(data).hexdigest(),
               'created':now(),'pages':pages,'regions':[],'audit':[],'normative_status':'not_run'}
        (folder/'project.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        return cls(folder)
    def save(self):
        fd,name=tempfile.mkstemp(dir=self.folder,suffix='.tmp')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump(self.state,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
            shutil.copyfile(self.path,self.folder/'project.backup.json')
            os.replace(name,self.path)
        finally:
            if os.path.exists(name):os.unlink(name)
    def event(self,r,actor,before=None):
        self.state['audit'].append({'time':now(),'actor':actor,'id':r['id'],'before':before,'after':dict(r)})
    def add(self,page,box,text='',kind='reading',severity=None,basis='',confidence=None,engine='manual',persist=True):
        if not isinstance(page,int) or not 0<=page<len(self.state['pages']):raise ValueError('Неверная страница')
        box=box_valid(box)
        if kind not in ('reading','finding'):raise ValueError('Неверный тип области')
        if kind=='finding' and (not isinstance(severity,int) or not 1<=severity<=100):raise ValueError('Критичность: 1–100')
        r={'id':uuid.uuid4().hex,'page':page,'box':box,'original':text,'text':text,'kind':kind,'severity':severity if kind=='finding' else None,
           'basis':basis,'confidence':confidence,'engine':engine,'status':'pending','reviewer':'','reviewed_at':None}
        self.state['regions'].append(r);self.event(r,'system' if engine!='manual' else 'manual')
        if persist:self.save()
        return r
    def decide(self,rid,text,reviewer,status,basis=''):
        if not reviewer.strip():raise ValueError('Укажите имя проверяющего')
        if status not in LABELS:raise ValueError('Неизвестный статус')
        r=next(r for r in self.state['regions'] if r['id']==rid)
        if status=='approved' and not text.strip():raise ValueError('Введите подтверждённый текст')
        if status=='approved' and r['kind']=='finding' and not basis.strip():raise ValueError('Укажите основание замечания')
        before=dict(r);r.update(text=text.strip(),reviewer=reviewer.strip(),status=status,basis=basis.strip(),reviewed_at=now())
        self.event(r,reviewer.strip(),before);self.save()
    def ingest(self,page,words):
        if self.state['pages'][page]['ocr']=='done':raise ValueError('OCR уже выполнен')
        # Validate all data before mutating the project.
        for w in words:box_valid(w['box'])
        for w in words:self.add(page,w['box'],w['text'],confidence=w['confidence'],engine='Tesseract rus+eng',persist=False)
        if not words:self.add(page,[.01,.01,.99,.99],basis='OCR не обнаружил текст. Проверьте лист вручную.',engine='Tesseract rus+eng')
        self.state['pages'][page]['ocr']='done';self.save()


def ocr_binary():
    paths=[bundle()/'ocr/tesseract.exe',Path(os.environ.get('TESSERACT_CMD','/not-found'))]
    system=shutil.which('tesseract')
    if system:paths.append(Path(system))
    paths.append(Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe'))
    for p in paths:
        if p.is_file():return p
    raise RuntimeError('Не найден OCR. В Windows-сборке должна быть папка ocr рядом с EXE.')

def ocr_command():
    p=ocr_binary();cmd=[str(p)]
    data=p.parent/'tessdata'
    return cmd,(['--tessdata-dir',str(data)] if data.is_dir() else [])

def run_process(cmd,timeout=240):
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    env=os.environ.copy();env.pop('TESSDATA_PREFIX',None)
    result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,env=env,**flags)
    if result.returncode:raise RuntimeError(result.stderr[-1500:] or 'Ошибка OCR')
    return result.stdout

def languages():
    cmd,data=ocr_command();return run_process(cmd+data+['--list-langs'],30)

def parse_tsv(s,width,height):
    words=[]
    for r in csv.DictReader(io.StringIO(s),delimiter='\t',quoting=csv.QUOTE_NONE):
        text=(r.get('text') or '').strip()
        if r.get('level')!='5' or not text:continue
        x,y,w,h=[int(r[k]) for k in ('left','top','width','height')]
        b=[max(0,x/width),max(0,y/height),min(1,(x+w)/width),min(1,(y+h)/height)]
        try:box_valid(b)
        except ValueError:continue
        words.append({'text':text,'box':b,'confidence':max(0,min(100,float(r['conf'])))})
    return words

def ocr(image,lang='rus+eng'):
    available=languages().splitlines()
    if not set(lang.split('+')).issubset(set(available)):raise RuntimeError('В комплекте OCR нет требуемых языков: '+lang)
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)/'page.png';image.save(p);cmd,data=ocr_command()
        result=run_process(cmd+[str(p),'stdout']+data+['-l',lang,'--psm','11','tsv'])
        return parse_tsv(result,image.width,image.height)

def font_path():
    paths=[os.environ.get('ELECTROREVIEW_FONT',''),r'C:\Windows\Fonts\arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for s in paths:
        if s and Path(s).is_file():return s
    raise RuntimeError('Не найден шрифт с кириллицей')

def register_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont('ReviewFont',font_path()))

def export(project,dest):
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from xml.sax.saxutils import escape
    dest=Path(dest)
    if dest.resolve()==project.source.resolve():raise ValueError('Нельзя перезаписать исходный PDF')
    register_font();writer=PdfWriter()
    for p in read_pdf(project.source).pages:
        p.transfer_rotation_to_content();l,b,r,t=map(float,p.cropbox)
        p.add_transformation(Transformation().translate(-l,-b));p.mediabox=RectangleObject([0,0,r-l,t-b]);p.cropbox=p.mediabox
        writer.add_page(p)
    for index,p in enumerate(writer.pages):
        width,height=float(p.mediabox.width),float(p.mediabox.height)
        stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=(width,height))
        for r in project.state['regions']:
            if r['page']!=index or r['status']=='excluded':continue
            a,b,d,e=r['box'];x=a*width;y=(1-e)*height;w=(d-a)*width;h=(e-b)*height
            if r['kind']=='reading' and r['status']=='approved':
                if not project.state['pages'][index]['has_text']:
                    text=c.beginText();size=max(2,min(24,h*.8));text.setFont('ReviewFont',size);text.setTextRenderMode(3)
                    text.setTextOrigin(x,y+h*.15);measure=pdfmetrics.stringWidth(r['text'],'ReviewFont',size)
                    text.setHorizScale(max(1,min(300,100*w/max(measure,1))));text.textOut(r['text']);c.drawText(text)
            else:
                color=(1,.75,0) if r['status']=='pending' else (.85,.1,.1)
                details=f"{LABELS[r['status']]}\n{r['text'] or 'Текст не распознан'}\n{r['basis']}\nПроверяющий: {r['reviewer']}"
                if r['kind']=='finding':details+=f"\nКритичность: {r['severity']}% (экспертный индекс)"
                writer.add_annotation(index,Rectangle(rect=(x,y,x+w,y+h)))
                ann=p['/Annots'][-1].get_object();ann[NameObject('/C')]=ArrayObject([FloatObject(v) for v in color])
                ann[NameObject('/Contents')]=TextStringObject(details);ann[NameObject('/F')]=NumberObject(4)
                c.setStrokeColorRGB(*color);c.setLineWidth(1);c.rect(x,y,w,h)
        c.showPage();c.save();p.merge_page(PdfReader(stream).pages[0])
    stream=io.BytesIO();styles=getSampleStyleSheet()
    for s in styles.byName.values():s.fontName='ReviewFont'
    styles['Normal'].fontSize=9;styles['Normal'].leading=13
    story=[]
    def paragraph(t,style='Normal'):
        story.extend([Paragraph(escape(t).replace('\n','<br/>'),styles[style]),Spacer(1,8)])
    paragraph('ЭлектроКонтроль • ведомость','Title');paragraph(project.state['name'])
    paragraph('Демо '+VERSION+'. Автоматическая нормативная проверка НЕ выполнена. Отсутствие замечаний не означает соответствия нормам. Жёлтый — подтвердить; красный — утверждённое замечание.')
    paragraph('Новый поисковый слой содержит только подтверждённые чтения на страницах без исходного текста. На смешанных страницах чтения приведены в ведомости. Номера ниже — страницы PDF. Критичность — экспертный индекс, не вероятность аварии.')
    for n,r in enumerate(project.state['regions'],1):
        paragraph(f"{n}. Страница {r['page']+1} • {LABELS[r['status']]}",'Heading3')
        paragraph(f"Текст: {r['text'] or '(не распознан)'}\nИсходное чтение: {r['original'] or '(нет)'}\nОснование: {r['basis'] or '(нет)'}\nПроверяющий: {r['reviewer'] or '(нет)'}\nКритичность: {str(r['severity'])+'%' if r['kind']=='finding' else 'не назначается для чтения'}")
    SimpleDocTemplate(stream,rightMargin=40,leftMargin=40,topMargin=40,bottomMargin=40).build(story)
    for p in PdfReader(stream).pages:writer.add_page(p)
    fd,temp=tempfile.mkstemp(dir=dest.parent,suffix='.pdf')
    try:
        with os.fdopen(fd,'wb') as f:writer.write(f)
        os.replace(temp,dest)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return dest

def create_demo(folder):
    """Synthetic scan, never represented as the user's engineering project."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    register_font()
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'vector.pdf';c=canvas.Canvas(str(path),pagesize=(842,595));c.setFont('ReviewFont',19)
        c.drawString(45,550,'ЭлектроКонтроль • учебная схема')
        c.setFont('ReviewFont',10);c.drawString(45,528,'Синтетический пример интерфейса, не рабочий проект и не проверка ПУЭ.')
        c.setLineWidth(2);c.line(100,420,740,420);c.drawString(105,440,'Ввод 230 В')
        for x,label,wire in [(200,'QF1 C16','ВВГнг 3×2,5'),(420,'QF2 C10','ВВГнг 3×1,5'),(640,'QF3 C16','ВВГнг 3×2,5')]:
            c.line(x,420,x,350);c.rect(x-12,320,24,30);c.line(x,320,x,210)
            c.drawString(x+25,330,label);c.drawString(x+15,260,wire);c.circle(x,200,10)
        c.drawString(45,90,'Выделите надпись мышью, прочитайте её и подтвердите справа.')
        c.drawString(45,70,'Заранее добавленная жёлтая область демонстрирует согласование чтения.')
        c.save();im=render(path,0,2);scan=Path(temp)/'Учебный пример.pdf'
        c=canvas.Canvas(str(scan),pagesize=(842,595));c.drawImage(ImageReader(im),0,0,842,595);c.save()
        p=Project.create(scan,folder);p.add(0,[.265,.42,.385,.46],basis='Демонстрационная область. Не установленная ошибка или размытость.')
        return p
