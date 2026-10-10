"""Human confirmation is required for electrical facts and their association."""
import tkinter as tk
from tkinter import ttk, messagebox
from electrical import FIELDS, CHOICES, OUTCOMES, SOURCE, SOURCE_URL, RULES, suggested_data, data_description

def readonly_text(parent,text):
    box=tk.Text(parent,wrap='word',font=('Arial',11))
    bar=ttk.Scrollbar(parent,command=box.yview);box.configure(yscrollcommand=bar.set)
    bar.pack(side='right',fill='y');box.pack(fill='both',expand=True)
    box.insert('1.0',text);box.configure(state='disabled');return box

def checks_text(project):
    check=project.state.get('checks')
    if not check:return 'Проверка ещё не запускалась. Создайте и подтвердите карточку цепи.'
    parts=['ОГРАНИЧЕННАЯ ПРОВЕРКА — не заключение о соответствии проекта',
           'Не внесённые в карточки цепи не проверены. «Условие выполнено» относится только к одному тесту.',
           'Не проверяются КЗ, селективность, отключение, допустимый ток кабеля, падение напряжения, УЗО и остальные нормы.',
           'Замечания требуют утверждения. Критичность — индекс, не вероятность; 100% — критичное замечание.',
           check['source'],check['source_url'],'Набор: '+check['ruleset'],
           'Время: '+check['time']+'; проверяющий: '+check['reviewer']]
    if check.get('stale'):parts.insert(0,'РЕЗУЛЬТАТЫ УСТАРЕЛИ. Подтвердите карточки и повторите проверку.')
    for entry in check['circuits']:
        parts.extend(['\nЦЕПЬ: '+entry['name'],data_description(entry['data'])])
        for row in entry['rows']:
            parts.append('ПУЭ '+row['clause']+' — '+OUTCOMES[row['status']]+'\n'+row['message'])
    return '\n\n'.join(parts)

class CircuitDialog:
    def __init__(self,app,source_ids,circuit=None,on_saved=None):
        self.app=app;self.project=app.project;self.circuit=circuit;self.ids=source_ids;self.on_saved=on_saved
        self.win=tk.Toplevel(app.root);self.win.title('Подтверждённые данные цепи');self.win.geometry('950x730');self.win.minsize(850,690)
        self.win.transient(app.root);self.win.grab_set()
        regions={r['id']:r for r in app.project.state['regions']}
        texts=['Стр. '+str(regions[i]['page']+1)+': '+regions[i]['text']+' ['+regions[i]['status']+']' for i in source_ids if i in regions]
        data,candidates=suggested_data(' '.join(regions[i]['text'] for i in source_ids if i in regions))
        if circuit:data=dict(circuit['data'])
        ttk.Label(self.win,text='Связи и параметры подтверждает инженер. Неизвестное оставляйте «Не установлено».',
                  background='#fff3c4',padding=8).pack(fill='x')
        source_box=tk.Text(self.win,height=4,wrap='word');source_box.pack(fill='x',padx=10,pady=6)
        source_box.insert('end','\n'.join(texts));source_box.configure(state='disabled')
        notebook=ttk.Notebook(self.win);notebook.pack(fill='both',expand=True,padx=10)
        tabs=[]
        for name in ('Цепь и обозначения','PE / PEN','Коммутация и источник'):
            frame=ttk.Frame(notebook,padding=10);notebook.add(frame,text=name);frame.columnconfigure(1,weight=1);tabs.append(frame)
        self.vars={};self.reverse={};rows=[0,0,0]
        for key,label,kind,options,tab in FIELDS:
            row=rows[tab];rows[tab]+=1;frame=tabs[tab]
            ttk.Label(frame,text=label,wraplength=330).grid(row=row,column=0,sticky='w',pady=7,padx=6)
            value=data.get(key)
            if kind=='choice':
                values=[CHOICES.get(x,x) for x in options];self.reverse[key]=dict(zip(values,options))
                var=tk.StringVar(value=CHOICES.get(value or 'unknown',value or 'unknown'))
                control=ttk.Combobox(frame,textvariable=var,values=values,state='readonly',width=49)
            else:
                var=tk.StringVar(value='' if value is None else str(value));control=ttk.Entry(frame,textvariable=var,width=50)
            control.grid(row=row,column=1,sticky='ew',pady=7,padx=6);self.vars[key]=var
        ttk.Label(tabs[0],text='Номинал автомата и ток УЗО распознаются справочно. Их соответствие здесь не проверяется.\n'
                  'Число жил не определяет автоматически наличие PE. Материал из марки — только подсказка.',wraplength=820).grid(row=rows[0],column=0,columnspan=2,sticky='w',pady=10)
        ttk.Label(tabs[1],text='Расчёт КЗ, эквивалентность разных материалов и полный выбор PEN не реализованы.\n'
                  'Табличная проверка PE запускается только при явно выбранном методе «По таблице».',wraplength=820).grid(row=rows[1],column=0,columnspan=2,sticky='w',pady=10)
        ttk.Label(tabs[2],text='Штепсельные соединители и вводы домов от ВЛ требуют отдельной проверки исключений.\n'
                  'При их выборе программа не делает автоматический вывод о нарушении.',wraplength=820).grid(row=rows[2],column=0,columnspan=2,sticky='w',pady=10)
        self.confirm=tk.BooleanVar(value=False)
        ttk.Checkbutton(self.win,text='Я проверил значения и принадлежность выбранных надписей одной цепи по схеме / ПЗ.',variable=self.confirm).pack(anchor='w',padx=16,pady=9)
        bar=ttk.Frame(self.win,padding=10);bar.pack(fill='x')
        ttk.Button(bar,text='Подтвердить карточку',command=self.save).pack(side='left')
        ttk.Button(bar,text='Отмена',command=self.win.destroy).pack(side='right')
    def save(self):
        if not self.confirm.get():messagebox.showinfo('Подтверждение','Подтвердите параметры и принадлежность надписей одной цепи.',parent=self.win);return
        try:
            if self.app.project is not self.project:raise ValueError('Проект изменён. Откройте карточку заново.')
            data={key:self.reverse[key].get(var.get(),'unknown') if key in self.reverse else var.get() for key,var in self.vars.items()}
            self.app.project.confirm_circuit(data,self.ids,self.app.actor.get(),self.circuit['id'] if self.circuit else None)
            self.app.refresh()
            if self.on_saved:self.on_saved()
            self.win.destroy()
        except Exception as e:messagebox.showerror('Карточка',str(e),parent=self.win)

class CircuitManager:
    def __init__(self,app):
        self.app=app;self.project=app.project;self.win=tk.Toplevel(app.root);self.win.title('Цепи и правила');self.win.geometry('920x570')
        self.win.transient(app.root);self.win.grab_set()
        ttk.Label(self.win,text='Сначала утвердите надписи на схеме. Выделите одну или несколько строк (Ctrl) и создайте карточку цепи.\n'
                  'Каждая карточка проверяется отдельно. Соединения по геометрии автоматически не восстанавливаются.',padding=10).pack(fill='x')
        self.tree=ttk.Treeview(self.win,columns=('name','status','reviewer'),show='headings',height=7)
        for key,label in [('name','Цепь'),('status','Данные'),('reviewer','Подтвердил')]:self.tree.heading(key,text=label)
        self.tree.pack(fill='both',expand=True,padx=10)
        bar=ttk.Frame(self.win,padding=10);bar.pack(fill='x')
        ttk.Button(bar,text='Открыть / подтвердить заново',command=self.edit).pack(side='left')
        ttk.Button(bar,text='Результаты проверки',command=self.results).pack(side='left',padx=5)
        ttk.Button(bar,text='Закрыть',command=self.win.destroy).pack(side='right')
        ttk.Label(self.win,text='Включены 6 условных проверок ПУЭ гл. 1.7:\n'+', '.join(r[1] for r in RULES)+'\n'+SOURCE+'\n'+SOURCE_URL,wraplength=880,padding=10).pack(fill='x')
        self.refresh()
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for c in self.app.project.state['circuits']:
            self.tree.insert('','end',iid=c['id'],values=(c['data']['name'],'Подтверждено' if c['status']=='confirmed' else 'Требует подтверждения',c['reviewer']))
    def edit(self):
        if self.app.project is not self.project:self.win.destroy();return
        ids=self.tree.selection()
        if ids:
            c=next(c for c in self.app.project.state['circuits'] if c['id']==ids[0]);CircuitDialog(self.app,c['source_ids'],c,self.refresh)
    def results(self):
        if self.app.project is not self.project:self.win.destroy();return
        win=tk.Toplevel(self.win);win.title('Проверено / не проверено');win.geometry('920x720');readonly_text(win,checks_text(self.app.project))
