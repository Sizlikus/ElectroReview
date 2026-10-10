"""Guided page review and optional API configuration. Secrets are session-only."""
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk,messagebox
from core import home,render
from drafts import local_drafts
from assistant_api import endpoint,page_regions,request_drafts
from circuit_ui import CircuitDialog,readonly_text,checks_text

def load_settings():
    default={'endpoint':'http://localhost:11434/v1','model':'','send_image':False}
    try:
        data=json.loads((home()/'assistant-settings.json').read_text(encoding='utf-8'))
        for key in ('endpoint','model'):
            if isinstance(data.get(key),str):default[key]=data[key]
        if isinstance(data.get('send_image'),bool):default['send_image']=data['send_image']
    except (OSError,ValueError,TypeError,AttributeError):pass
    return default

class AssistantSettings:
    def __init__(self,app):
        self.app=app;self.win=tk.Toplevel(app.root);self.win.title('ИИ-помощник — необязательно');self.win.geometry('760x490')
        self.win.transient(app.root);self.win.grab_set()
        frame=ttk.Frame(self.win,padding=16);frame.pack(fill='both',expand=True);frame.columnconfigure(1,weight=1)
        self.vars={}
        for row,(key,label,value) in enumerate([('endpoint','Базовый адрес API',app.ai_settings['endpoint']),
                    ('model','Имя модели',app.ai_settings['model']),('key','API-ключ (до закрытия)',app.ai_key)]):
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=8)
            self.vars[key]=tk.StringVar(value=value)
            ttk.Entry(frame,textvariable=self.vars[key],show='•' if key=='key' else '',width=50).grid(row=row,column=1,sticky='ew',pady=8)
        self.vision=tk.BooleanVar(value=app.ai_settings['send_image'])
        ttk.Checkbutton(frame,text='Также передавать изображение листа (нужна модель с поддержкой изображений)',variable=self.vision).grid(row=3,column=0,columnspan=2,sticky='w',pady=8)
        presets=ttk.Frame(frame);presets.grid(row=4,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Button(presets,text='Локально: Ollama',command=lambda:self.preset('http://localhost:11434/v1','qwen3-vl:8b',True)).pack(side='left')
        ttk.Button(presets,text='Облако: DeepSeek',command=lambda:self.preset('https://api.deepseek.com','deepseek-flash',False)).pack(side='left',padx=5)
        ttk.Label(frame,text='Ollama устанавливается отдельно; выбранную модель нужно загрузить в Ollama.\n'
                  'Облачный API может быть платным; регистрация в чате не даёт API-квоту.\n\n'
                  'Запрос выполняется только кнопкой «Отправить лист ИИ». Передаются надписи\n'
                  'текущего листа и, при включённой опции, его уменьшенное изображение.\n'
                  'Ключ не сохраняется в проекте или настройках. ИИ предлагает черновики;\n'
                  'каждый из них необходимо сверить с оригиналом и подтвердить.',wraplength=710).grid(row=5,column=0,columnspan=2,sticky='w',pady=12)
        ttk.Button(frame,text='Сохранить настройки',command=self.save).grid(row=6,column=0,columnspan=2,sticky='w')
    def preset(self,url,model,vision):
        self.vars['endpoint'].set(url);self.vars['model'].set(model);self.vision.set(vision);self.vars['key'].set('')
    def save(self):
        try:
            settings={k:self.vars[k].get().strip() for k in ('endpoint','model')};endpoint(settings['endpoint'])
            if not settings['model']:raise ValueError('Укажите модель')
            settings['send_image']=self.vision.get()
            path=home()/'assistant-settings.json';temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)
            self.app.ai_settings=settings;self.app.ai_key=self.vars['key'].get().strip();self.win.destroy()
        except Exception as e:messagebox.showerror('ИИ-помощник',str(e),parent=self.win)

class QuickReview:
    def __init__(self,app):
        self.app=app;self.project=app.project;self.page=app.page;self.busy=False;self.jobs=queue.Queue();self.alive=True
        self.win=tk.Toplevel(app.root);self.win.title('Проверка листа — шаг за шагом');self.win.geometry('1050x720');self.win.minsize(900,630)
        self.win.transient(app.root);self.win.grab_set();self.win.protocol('WM_DELETE_WINDOW',self.close)
        ttk.Label(self.win,text='1. Выберите черновик → 2. Сверьте надписи и параметры → 3. Утвердите и получите результат',font=('Arial',12,'bold'),padding=10).pack(fill='x')
        ttk.Label(self.win,text='Можно подтвердить надписи одной цепи вместе. Все остальные чтения сохранят жёлтые отметки.\n'
                  'Предложения по близости надписей и предложения ИИ не устанавливают электрические соединения.',padding=10).pack(fill='x')
        top=ttk.Frame(self.win);top.pack(fill='both',expand=True,padx=10)
        self.tree=ttk.Treeview(top,columns=('name','source','count'),show='headings',height=8,selectmode='browse')
        for key,label,width in [('name','Черновик цепи',400),('source','Помощник',180),('count','Надписей',100)]:
            self.tree.heading(key,text=label);self.tree.column(key,width=width)
        scroll=ttk.Scrollbar(top,command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self.select);self.tree.bind('<Double-1>',lambda e:self.review())
        self.details=tk.StringVar();ttk.Label(self.win,textvariable=self.details,wraplength=980,padding=10).pack(fill='x')
        bar=ttk.Frame(self.win,padding=10);bar.pack(fill='x')
        self.review_button=ttk.Button(bar,text='Сверить выбранную цепь',command=self.review);self.review_button.pack(side='left')
        ttk.Button(bar,text='Добавить цепь вручную',command=self.manual).pack(side='left',padx=5)
        ttk.Button(bar,text='Результаты проверки',command=self.results).pack(side='left',padx=5)
        ttk.Button(bar,text='Закрыть',command=self.close).pack(side='right')
        ai=ttk.LabelFrame(self.win,text='Необязательный ИИ-помощник',padding=10);ai.pack(fill='x',padx=10,pady=5)
        self.ai_label=ttk.Label(ai,wraplength=980);self.ai_label.pack(anchor='w')
        self.ai_button=ttk.Button(ai,text='Отправить лист ИИ',command=self.request);self.ai_button.pack(side='left',pady=5)
        ttk.Button(ai,text='Настроить ИИ',command=lambda:AssistantSettings(app)).pack(side='left',padx=5)
        ttk.Button(ai,text='Вернуть локальный разбор',command=self.local).pack(side='left',padx=5)
        self.status=tk.StringVar();ttk.Label(self.win,textvariable=self.status,padding=10,wraplength=980).pack(fill='x')
        self.local();self.win.after(200,self.poll)
    def current(self):
        if self.app.project is not self.project:raise ValueError('Проект изменён. Откройте проверку листа заново.')
    def set_drafts(self,drafts):
        self.drafts=drafts;self.tree.delete(*self.tree.get_children())
        used=[set(c['source_ids']) for c in self.project.state['circuits'] if c['status']=='confirmed']
        self.drafts=[d for d in drafts if not any(set(d['source_ids'])<=ids for ids in used)]
        for i,d in enumerate(self.drafts):self.tree.insert('','end',iid=str(i),values=(d['data']['name'],d['origin'],len(d['source_ids'])))
        self.details.set('Выберите черновик и сверьте оригинал. Если аппарат не распознан, добавьте цепь вручную.')
        if self.drafts:self.tree.selection_set('0');self.select()
        count=len(page_regions(self.project.state,self.page));self.status.set(f'Лист {self.page+1}: чтений {count}, новых черновиков {len(self.drafts)}. Уже подтверждённые источники повторно не предлагаются.')
    def local(self):
        if self.busy:return
        self.current();self.set_drafts(local_drafts(self.project.state,self.page))
    def select(self,event=None):
        ids=self.tree.selection()
        if ids:
            d=self.drafts[int(ids[0])];self.details.set('\n'.join(d['warnings'])[:1500])
    def review(self):
        if self.busy:return
        self.current();ids=self.tree.selection()
        if not ids:return
        draft=self.drafts[int(ids[0])]
        CircuitDialog(self.app,draft['source_ids'],on_saved=self.saved,draft=draft,page=self.page)
    def manual(self):
        if self.busy:return
        self.current()
        CircuitDialog(self.app,[],on_saved=self.saved,page=self.page,draft={'data':{'name':'Новая цепь','evidence':'Лист PDF '+str(self.page+1)},'source_ids':[],'origin':'Вручную'})
    def saved(self):
        self.set_drafts(self.drafts)
        check=self.project.state.get('checks')
        if check:
            rows=[r for c in check['circuits'] for r in c['rows']]
            self.status.set('Сохранено и проверено. Предварительных замечаний: '+str(sum(r['status']=='violation' for r in rows))+
                            '; условий без достаточных данных: '+str(sum(r['status']=='not_checked' for r in rows))+'. Откройте результаты; замечания требуют решения.')
    def results(self):
        self.current();win=tk.Toplevel(self.win);win.title('Результаты и покрытие');win.geometry('920x720');readonly_text(win,checks_text(self.project))
    def request(self):
        if self.busy:return
        try:
            self.current();settings=dict(self.app.ai_settings);key=self.app.ai_key
            endpoint(settings['endpoint'])
            if not settings['model']:raise ValueError('Сначала нажмите «Настроить ИИ» и укажите модель')
            regions=page_regions(self.project.state,self.page)
            image=render(self.project.source,self.page,1.8) if settings['send_image'] else None
            self.busy=True;self.started=time.monotonic();self.ai_button.configure(state='disabled');self.review_button.configure(state='disabled')
            def worker():
                try:self.jobs.put(('ok',request_drafts(settings,key,regions,self.page,image)))
                except Exception as e:self.jobs.put(('error',str(e)))
            threading.Thread(target=worker,daemon=True).start()
        except Exception as e:messagebox.showinfo('ИИ-помощник',str(e),parent=self.win)
    def poll(self):
        if not self.alive:return
        self.ai_label.configure(text='Кнопка отправит OCR текущего листа'+(' и его изображение' if self.app.ai_settings['send_image'] else '')+
                                ' по адресу: '+self.app.ai_settings['endpoint']+' • Модель: '+(self.app.ai_settings['model'] or 'не настроена'))
        if self.busy:self.status.set(f'ИИ готовит черновики… {int(time.monotonic()-self.started)} с. Окно продолжает работать; запрос может занять до 120 с.')
        try:
            kind,value=self.jobs.get_nowait();self.busy=False;self.ai_button.configure(state='normal');self.review_button.configure(state='normal')
            if kind=='ok':self.set_drafts(value)
            else:self.status.set('ИИ не выполнил запрос. Локальные черновики сохранены.');messagebox.showerror('ИИ-помощник',value,parent=self.win)
        except queue.Empty:pass
        self.win.after(200,self.poll)
    def close(self):
        self.alive=False;self.win.destroy()
