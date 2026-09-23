import json, queue, sys, threading, traceback, uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from PIL import ImageTk
from core import Project, render, ocr, export, create_demo, home, LABELS, VERSION

class App:
    def __init__(self,root):
        self.root=root;root.title('ЭлектроКонтроль '+VERSION+' | 220–400 В');root.geometry('1400x900');root.minsize(1050,700)
        self.project=None;self.page=0;self.scale=1.3;self.selected=None;self.drag=None;self.busy=False;self.mode='reading';self.jobs=queue.Queue()
        style=ttk.Style();style.theme_use('clam');style.configure('TButton',padding=7)
        bar=ttk.Frame(root,padding=8);bar.pack(fill='x')
        for label,fn in [('Открыть PDF',self.new),('Открыть проект',self.open),('Учебный пример',self.demo),('Экспорт PDF',self.export)]:
            ttk.Button(bar,text=label,command=fn).pack(side='left',padx=3)
        self.actor=tk.StringVar();ttk.Label(bar,text=' Проверяющий:').pack(side='left');ttk.Entry(bar,textvariable=self.actor,width=22).pack(side='left')
        ttk.Label(root,text='ДЕМО • Автоматическая проверка норм пока не выполняется. Жёлтый — требуется подтверждение чтения.',
                  background='#fff3c4',foreground='#75500c',padding=8).pack(fill='x')
        bar=ttk.Frame(root,padding=5);bar.pack(fill='x')
        for label,fn in [('◀',lambda:self.navigate(-1)),('▶',lambda:self.navigate(1)),('−',lambda:self.zoom(-.2)),('+',lambda:self.zoom(.2)),
                         ('OCR листа',self.read),('Жёлтая область',lambda:self.mode_set('reading')),('Замечание',lambda:self.mode_set('finding'))]:
            ttk.Button(bar,text=label,command=fn).pack(side='left',padx=2)
        self.page_label=ttk.Label(bar);self.page_label.pack(side='left',padx=10)
        pane=ttk.Panedwindow(root,orient='horizontal');pane.pack(fill='both',expand=True)
        left=ttk.Frame(pane);right=ttk.Frame(pane,padding=8);pane.add(left,weight=4);pane.add(right,weight=1)
        self.canvas=tk.Canvas(left,background='#dae1e9',highlightthickness=0)
        sy=ttk.Scrollbar(left,orient='vertical',command=self.canvas.yview);sx=ttk.Scrollbar(left,orient='horizontal',command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set);self.canvas.grid(row=0,column=0,sticky='nsew')
        sy.grid(row=0,column=1,sticky='ns');sx.grid(row=1,column=0,sticky='ew');left.rowconfigure(0,weight=1);left.columnconfigure(0,weight=1)
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        ttk.Label(right,text='Области и решения',font=('Arial',13,'bold')).pack(anchor='w')
        self.tree=ttk.Treeview(right,columns=('status','text'),show='headings',height=8)
        self.tree.heading('status',text='Статус');self.tree.heading('text',text='Текст');self.tree.column('status',width=110);self.tree.column('text',width=230)
        self.tree.pack(fill='x',pady=8);self.tree.bind('<<TreeviewSelect>>',self.select)
        self.info=ttk.Label(right,text='Откройте PDF или учебный пример',wraplength=340);self.info.pack(anchor='w')
        self.crop=ttk.Label(right);self.crop.pack(pady=8)
        ttk.Label(right,text='Подтверждённый текст / описание').pack(anchor='w');self.text=tk.Text(right,width=42,height=4,wrap='word');self.text.pack(fill='x',pady=4)
        ttk.Label(right,text='Основание замечания / примечание').pack(anchor='w');self.basis=tk.Text(right,width=42,height=3,wrap='word');self.basis.pack(fill='x',pady=4)
        for label,status in [('Утвердить','approved'),('Исключить','excluded'),('Вернуть на проверку','pending')]:
            ttk.Button(right,text=label,command=lambda s=status:self.decide(s)).pack(fill='x',pady=2)
        ttk.Button(right,text='Журнал решений',command=self.history).pack(fill='x',pady=8)
        self.status=tk.StringVar(value='Проекты сохраняются локально. Начните с учебного примера.')
        ttk.Label(root,textvariable=self.status,padding=7).pack(fill='x')
        root.after(150,self.poll);root.protocol('WM_DELETE_WINDOW',self.close)
    def available(self):
        if self.busy:messagebox.showinfo('Обработка','Дождитесь завершения операции.');return False
        return True
    def unsaved_ok(self):
        if self.project and self.selected:
            r=next(x for x in self.project.state['regions'] if x['id']==self.selected)
            if self.text.get('1.0','end').strip()!=r['text'] or self.basis.get('1.0','end').strip()!=r['basis']:
                return messagebox.askyesno('Несохранённый текст','Текст ещё не утверждён. Отбросить изменения?')
        return True
    def replace(self,p):
        if self.project:self.project.close()
        self.project=p;self.page=0;self.show()
    def new(self):
        if not self.available() or not self.unsaved_ok():return
        src=filedialog.askopenfilename(filetypes=[('PDF','*.pdf')])
        if not src:return
        dest=home()/'projects'/uuid.uuid4().hex
        self.start(lambda:Project.create(src,dest),'project','Чтение PDF…')
    def open(self):
        if not self.available() or not self.unsaved_ok():return
        path=filedialog.askopenfilename(initialdir=home()/'projects',filetypes=[('Проект','project.json')])
        if not path:return
        self.start(lambda:Project(Path(path).parent),'project','Открытие проекта…')
    def demo(self):
        if not self.available() or not self.unsaved_ok():return
        self.start(lambda:create_demo(home()/'projects'/('demo-'+uuid.uuid4().hex)),'project','Создание учебного примера…')
    def show(self):
        if not self.project:return
        self.im=render(self.project.source,self.page,self.scale);self.photo=ImageTk.PhotoImage(self.im)
        self.canvas.delete('all');self.canvas.create_image(0,0,image=self.photo,anchor='nw');self.canvas.configure(scrollregion=(0,0,self.im.width,self.im.height))
        self.selected=None;self.text.delete('1.0','end');self.basis.delete('1.0','end');self.crop.configure(image='')
        self.page_label.configure(text=f'Страница PDF {self.page+1} / {len(self.project.state["pages"])}');self.refresh()
    def refresh(self):
        self.canvas.delete('region');self.tree.delete(*self.tree.get_children())
        for r in self.project.state['regions']:
            if r['page']!=self.page:continue
            self.tree.insert('', 'end',iid=r['id'],values=(LABELS[r['status']],r['text'] or '(не распознано)'))
            if r['status']=='excluded':continue
            color='#e5af00' if r['status']=='pending' else ('#ce293f' if r['kind']=='finding' else '#258663')
            x,y,a,b=r['box'];self.canvas.create_rectangle(x*self.im.width,y*self.im.height,a*self.im.width,b*self.im.height,
                outline=color,width=2,fill=color if r['status']=='pending' else '',stipple='gray12',tags='region')
        count=sum(r['status']=='pending' for r in self.project.state['regions'])
        self.status.set(f'Ожидают решения: {count} | Проект: {self.project.folder}')
    def navigate(self,d):
        if self.available() and self.project and self.unsaved_ok():self.page=max(0,min(len(self.project.state['pages'])-1,self.page+d));self.show()
    def zoom(self,d):
        if self.available() and self.project and self.unsaved_ok():self.scale=max(.5,min(4,self.scale+d));self.show()
    def mode_set(self,mode):self.mode=mode;self.status.set('Выделите прямоугольник мышью на листе')
    def point(self,e):return max(0,min(self.im.width,self.canvas.canvasx(e.x))),max(0,min(self.im.height,self.canvas.canvasy(e.y)))
    def press(self,e):
        if self.project and not self.busy:self.drag=self.point(e)
    def motion(self,e):
        if self.drag:self.canvas.delete('drag');self.canvas.create_rectangle(*self.drag,*self.point(e),outline='#e5af00',width=2,tags='drag')
    def release(self,e):
        if not self.drag:return
        start=self.drag;end=self.point(e);self.drag=None;self.canvas.delete('drag');x,a=sorted([start[0],end[0]]);y,b=sorted([start[1],end[1]])
        if a-x<6 or b-y<6:
            hits=[r for r in self.project.state['regions'] if r['page']==self.page and r['status']!='excluded' and r['box'][0]<=end[0]/self.im.width<=r['box'][2] and r['box'][1]<=end[1]/self.im.height<=r['box'][3]]
            if hits:self.tree.selection_set(hits[-1]['id'])
            return
        if not self.unsaved_ok():return
        severity=None
        if self.mode=='finding':
            severity=simpledialog.askinteger('Критичность','Экспертный индекс 1–100%:',minvalue=1,maxvalue=100)
            if severity is None:return
        try:
            r=self.project.add(self.page,[x/self.im.width,y/self.im.height,a/self.im.width,b/self.im.height],kind=self.mode,severity=severity)
            self.selected=None;self.refresh();self.tree.selection_set(r['id'])
        except Exception as e:messagebox.showerror('Ошибка',str(e))
    def select(self,event=None):
        ids=self.tree.selection()
        if not ids:return
        if ids[0]!=self.selected and not self.unsaved_ok():
            if self.selected:self.tree.selection_set(self.selected)
            return
        self.selected=ids[0];r=next(r for r in self.project.state['regions'] if r['id']==self.selected)
        self.text.delete('1.0','end');self.text.insert('1.0',r['text']);self.basis.delete('1.0','end');self.basis.insert('1.0',r['basis'])
        self.info.configure(text=f"Исходное чтение: {r['original'] or '(нет)'}. " + (f"Оценка OCR: {r['confidence']:.0f}/100; не вероятность." if r['confidence'] is not None else 'Ручная область.'))
        x,y,a,b=r['box'];im=self.im.crop((int(x*self.im.width),int(y*self.im.height),int(a*self.im.width),int(b*self.im.height)))
        k=min(3,340/max(1,im.width),130/max(1,im.height));im=im.resize((max(1,int(im.width*k)),max(1,int(im.height*k))))
        self.crop_photo=ImageTk.PhotoImage(im);self.crop.configure(image=self.crop_photo)
    def decide(self,status):
        if not self.available() or not self.selected:return
        try:
            rid=self.selected;self.project.decide(rid,self.text.get('1.0','end').strip(),self.actor.get(),status,self.basis.get('1.0','end').strip())
            self.refresh();self.tree.selection_set(rid)
        except Exception as e:messagebox.showerror('Подтверждение',str(e))
    def start(self,fn,kind,label):
        self.busy=True;self.status.set(label)
        def worker():
            try:self.jobs.put((kind,fn()))
            except Exception as e:self.jobs.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        try:
            kind,value=self.jobs.get_nowait();self.busy=False
            if kind=='error':messagebox.showerror('Ошибка',value);self.status.set('Операция не выполнена: '+value)
            elif kind=='project':self.replace(value)
            elif kind=='ocr':self.project.ingest(self.page,value);self.refresh()
            elif kind=='export':self.status.set('Сохранено: '+str(value));messagebox.showinfo('Готово','PDF сохранён: '+str(value))
        except queue.Empty:pass
        except Exception as e:messagebox.showerror('Ошибка',str(e))
        self.root.after(150,self.poll)
    def read(self):
        if not self.available() or not self.project or not self.unsaved_ok():return
        if self.project.state['pages'][self.page]['ocr']=='done':messagebox.showinfo('OCR','Этот лист уже распознан.');return
        self.start(lambda:ocr(render(self.project.source,self.page,300/72)),'ocr','Распознавание rus+eng… Все чтения потребуют подтверждения.')
    def export(self):
        if not self.available() or not self.project or not self.unsaved_ok():return
        dest=filedialog.asksaveasfilename(defaultextension='.pdf',initialfile='Результат-проверки.pdf',filetypes=[('PDF','*.pdf')])
        if dest:self.start(lambda:export(self.project,dest),'export','Экспорт PDF…')
    def history(self):
        if not self.project:return
        win=tk.Toplevel(self.root);win.title('Журнал решений');win.geometry('850x600');text=tk.Text(win,wrap='word');text.pack(fill='both',expand=True)
        for e in self.project.state['audit']:
            if not self.selected or e['id']==self.selected:text.insert('end',json.dumps(e,ensure_ascii=False,indent=2)+'\n')
        text.configure(state='disabled')
    def close(self):
        if self.available() and self.unsaved_ok():
            if self.project:self.project.close()
            self.root.destroy()

def main():
    if '--self-test' in sys.argv:
        from selftest import run
        run(Path(sys.argv[sys.argv.index('--self-test')+1]));return
    root=tk.Tk();App(root);root.mainloop()

if __name__=='__main__':
    try:main()
    except Exception:
        log=home()/'startup-error.txt';log.write_text(traceback.format_exc(),encoding='utf-8')
        if '--self-test' not in sys.argv:
            try:messagebox.showerror('Ошибка запуска','Подробности: '+str(log))
            except Exception:pass
        sys.exit(1)
