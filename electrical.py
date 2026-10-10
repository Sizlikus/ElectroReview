"""Deterministic, limited checks. No inferred connectivity or AI-generated norms."""
import math
import re

RULESET = 'PUE7-1.7-subset-2026-10-10-v1'
SOURCE_URL = 'https://legalacts.ru/doc/prikaz-minenergo-rf-ot-08072002-n-204/'
SOURCE = 'ПУЭ, изд. 7, гл. 1.7; приказ Минэнерго РФ от 08.07.2002 № 204'
RULES = (
    ('PE_TABLE', '1.7.126, табл. 1.7.5', 'Сечение PE по таблице'),
    ('PE_SEPARATE', '1.7.127', 'Минимум для отдельного PE'),
    ('PEN_SECTION', '1.7.131', 'Сечения при совмещении PE и N в кабеле TN'),
    ('PEN_SINGLE', '1.7.132', 'PEN в однофазной цепи'),
    ('PE_SWITCH', '1.7.145', 'Коммутация PE/PEN'),
    ('N_PE_REJOIN', '1.7.135', 'Повторное объединение N и PE после разделения'),
)
OUTCOMES = {'violation':'Предварительное замечание', 'pass':'Условие выполнено',
            'not_checked':'Не проверено', 'not_applicable':'Не применяется'}

# UI and validation use one schema; unknown is always an explicit choice.
FIELDS = (
    ('name', 'Название / обозначение цепи', 'text', None, 0),
    ('voltage', 'Напряжение цепи, В (220–400)', 'number', None, 0),
    ('current_kind', 'Род тока', 'choice', ('unknown','AC','DC'), 0),
    ('phases', 'Число фаз', 'choice', ('unknown','1','3'), 0),
    ('earthing', 'Система заземления', 'choice', ('unknown','TN-S','TN-C','TN-C-S','TT','IT'), 0),
    ('phase_material', 'Материал фазной жилы', 'choice', ('unknown','Cu','Al'), 0),
    ('phase_mm2', 'Сечение фазной жилы, мм²', 'number', None, 0),
    ('cable', 'Марка кабеля (справочно)', 'text', None, 0),
    ('breaker_a', 'Номинал автомата, А (справочно)', 'number', None, 0),
    ('rcd_ma', 'Дифференциальный ток, мА (справочно)', 'number', None, 0),
    ('protective_type', 'Защитный проводник', 'choice', ('unknown','PE','PEN'), 1),
    ('protective_material', 'Материал PE / PEN', 'choice', ('unknown','Cu','Al'), 1),
    ('protective_mm2', 'Сечение PE / PEN, мм²', 'number', None, 1),
    ('pe_method', 'Метод выбора PE', 'choice', ('unknown','table','calculation'), 1),
    ('pe_route', 'Расположение PE', 'choice', ('unknown','in_cable','common','separate'), 1),
    ('mechanical', 'Механическая защита отдельного PE', 'choice', ('unknown','yes','no'), 1),
    ('fixed_cable', 'Стационарно проложенный кабель', 'choice', ('unknown','yes','no'), 1),
    ('overhead_branch', 'Однофазное ответвление от ВЛ до 1 кВ', 'choice', ('unknown','yes','no'), 1),
    ('switch_protective', 'Аппарат размыкает PE / PEN', 'choice', ('unknown','yes','no'), 2),
    ('switch_exception', 'Исключение для коммутации', 'choice', ('unknown','none','plug','house_overhead'), 2),
    ('rejoin_after_split', 'N и PE объединены после разделения', 'choice', ('unknown','yes','no'), 2),
    ('evidence', 'Где подтверждены данные (лист, надпись, ПЗ)', 'text', None, 2),
)
CHOICES = {'unknown':'Не установлено', '1':'1', '3':'3', 'Cu':'Медь', 'Al':'Алюминий','AC':'Переменный','DC':'Постоянный',
           'yes':'Да', 'no':'Нет', 'table':'По таблице 1.7.5', 'calculation':'По расчёту КЗ',
           'in_cable':'В составе кабеля', 'common':'Отдельно, общая оболочка / труба / короб / лоток',
           'separate':'Отдельно, вне общего маршрута', 'none':'Исключений нет',
           'plug':'Штепсельный соединитель', 'house_overhead':'Ввод индивидуального дома от однофазной ВЛ'}

def validate_data(data):
    result={}
    for key, label, kind, options, tab in FIELDS:
        value=data.get(key)
        if kind=='choice':
            value=value or 'unknown'
            if value not in options:raise ValueError('Неверное значение: '+label)
        elif kind=='number':
            if value is None or str(value).strip()=='':value=None
            else:
                try:value=float(str(value).replace(',','.'))
                except (TypeError,ValueError):raise ValueError('Нужно число: '+label)
                if not math.isfinite(value) or value<=0:raise ValueError('Нужно положительное конечное число: '+label)
                if key=='voltage' and not 220<=value<=400:raise ValueError('Эта версия проверяет цепи только 220–400 В')
        else:value=str(value or '').strip()
        result[key]=value
    if not result['name'] or not result['evidence']:raise ValueError('Укажите название цепи и источник подтверждения данных')
    return result

def parse_labels(text):
    """Label candidates only. Do not silently fix O/0 or guess protective conductor."""
    text=re.sub(r'\s+',' ',text).strip()
    candidates=[]
    # Only known model families with complete equal-size core notation. Mixed sizes
    # are retained as a candidate but never turned into a phase/PE size automatically.
    pattern=r'(?<![\w])(?:А?ВВГ[\w()\-]*|NYM[\w()\-]*|КГ[\w()\-]*|ПВС|СИП[\w()\-]*)\s*[-–]?\s*\d+\s*[xх×*]\s*\d+(?:[.,]\d+)?(?:\s*\+\s*\d+\s*[xх×*]\s*\d+(?:[.,]\d+)?)?'
    pattern+=r'(?![\w.,+])'
    for match in re.finditer(pattern,text,re.I):
        raw=match.group();parts=re.search(r'(\d+)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)',raw)
        model=raw[:parts.start()].strip(' -–');mixed='+' in raw
        material='Al' if model.upper().startswith(('АВВГ','СИП')) else 'Cu'
        candidates.append({'kind':'cable','raw':raw,'model':model,'cores':int(parts[1]),
                           'phase_mm2':None if mixed else float(parts[2].replace(',','.')), 'material':material,
                           'note':'Сечение PE/PEN и принадлежность цепи подтвердите по схеме.'})
    for match in re.finditer(r'(?<![\w])Q[FDS]\s*\d+(?:[.\-/]\d+)*',text,re.I):
        candidates.append({'kind':'device','raw':match.group(),'designation':match.group().replace(' ','').upper()})
    for match in re.finditer(r'(?<![\w])([BCDВСД])\s*(\d{1,4})(?:\s*[AaАа])?(?![\w.,])',text):
        candidates.append({'kind':'breaker','raw':match.group(),'curve':match[1].translate(str.maketrans('ВСД','BCD')),'amps':float(match[2]),
                           'note':'Только обозначение характеристики и тока; тип аппарата подтвердите.'})
    for match in re.finditer(r'(?<![\d])([0-9]+(?:[.,][0-9]+)?)\s*(?:mA|мА)(?![\w])',text,re.I):
        candidates.append({'kind':'rcd','raw':match.group(),'ma':float(match[1].replace(',','.'))})
    for match in re.finditer(r'(?<![\w])(?:PEN|PE|TN-C-S|TN-S|TN-C|TT|IT)(?![\w])',text,re.I):
        candidates.append({'kind':'system','raw':match.group().upper()})
    return candidates

def suggested_data(text):
    candidates=parse_labels(text);data={}
    cables=[x for x in candidates if x['kind']=='cable']
    devices=[x for x in candidates if x['kind']=='device']
    breakers=[x for x in candidates if x['kind']=='breaker']
    rcds=[x for x in candidates if x['kind']=='rcd']
    if len(cables)==1:
        data.update(cable=cables[0]['raw'],phase_mm2=cables[0]['phase_mm2'],phase_material=cables[0]['material'])
    if len(devices)==1:data['name']=devices[0]['designation']
    if len(breakers)==1:data['breaker_a']=breakers[0]['amps']
    if len(rcds)==1:data['rcd_ma']=rcds[0]['ma']
    # PE/PEN, system, voltage and connections deliberately require a human choice.
    return data,candidates

def evaluate(data):
    """Six conditional checks; 'pass' always refers to a single stated condition."""
    d=validate_data(data);results=[]
    def add(rule,status,message,severity=None):
        spec=next(x for x in RULES if x[0]==rule)
        results.append({'rule':rule,'clause':spec[1],'title':spec[2],'status':status,'message':message,
                        'severity':severity,'source_url':SOURCE_URL,'ruleset':RULESET})
    def done(rule,ok,detail,severity):add(rule,'pass' if ok else 'violation',detail,None if ok else severity)
    # Do not assume 230 V simply because the project focus is LV.
    if d['voltage'] is None or d['current_kind']!='AC':
        for key,_,_ in RULES:add(key,'not_checked','Этот набор проверяет только подтверждённые цепи переменного тока 220–400 В.')
        return results
    p=d['protective_type'];s=d['phase_mm2'];sp=d['protective_mm2'];mat=d['protective_material']
    if p=='PEN':add('PE_TABLE','not_checked','Для PEN нужна дополнительная проверка по 1.7.134 и гл. 2.1; она не реализована.')
    elif p=='unknown':add('PE_TABLE','not_checked','Не установлен тип защитного проводника.')
    elif d['pe_method']!='table':add('PE_TABLE','not_checked','Подтвердите табличный метод; расчёт КЗ и его применимость эта версия не проверяет.')
    elif not s or not sp or mat=='unknown' or d['phase_material']=='unknown':add('PE_TABLE','not_checked','Нужны сечения и материалы фазной жилы и PE.')
    elif mat!=d['phase_material']:add('PE_TABLE','not_checked','Разные материалы: нужна проверка эквивалентной проводимости.')
    else:
        minimum=s if s<=16 else (16 if s<=35 else s/2)
        done('PE_TABLE',sp>=minimum,f'Sф={s:g} мм²; SPE={sp:g} мм²; табличный минимум={minimum:g} мм². Материал одинаковый; метод — таблица.',90)
    if p=='PEN':add('PE_SEPARATE','not_applicable','В этой карточке указан PEN, а не отдельный PE.')
    elif p=='unknown' or d['pe_route']=='unknown':add('PE_SEPARATE','not_checked','Не установлены тип или расположение PE.')
    elif mat=='unknown' or not sp:add('PE_SEPARATE','not_checked','Нужны материал и сечение PE.')
    elif mat=='Cu' and d['pe_route']=='in_cable':add('PE_SEPARATE','not_applicable','PE входит в кабель; проверяйте выбор сечения отдельно.')
    elif mat=='Cu' and d['mechanical']=='unknown':add('PE_SEPARATE','not_checked','Нужно подтвердить механическую защиту отдельного медного PE.')
    elif mat=='Al' and d['pe_route']=='in_cable':add('PE_SEPARATE','not_applicable','Алюминиевый PE входит в кабель.')
    else:
        minimum=16 if mat=='Al' else (2.5 if d['mechanical']=='yes' else 4)
        done('PE_SEPARATE',sp>=minimum,f'SPE={sp:g} мм²; минимум для указанных условий={minimum:g} мм².',90)
    if p=='PE':add('PEN_SECTION','not_applicable','PEN не используется в указанной цепи.')
    elif p=='unknown':add('PEN_SECTION','not_checked','Не установлен тип защитного проводника.')
    elif d['phases']!='3' or not d['earthing'].startswith('TN') or d['fixed_cable']!='yes':
        add('PEN_SECTION','not_checked','Для этого теста нужны многофазная цепь TN и стационарный кабель; другие случаи не оценены.')
    elif not sp or not s or mat=='unknown' or d['phase_material']=='unknown':add('PEN_SECTION','not_checked','Нужны материалы и сечения фазной жилы и PEN.')
    elif mat!=d['phase_material']:add('PEN_SECTION','not_checked','Разные материалы фазной жилы и PEN: условия совмещения требуют отдельной проверки.')
    else:
        minimum=10 if mat=='Cu' else 16
        done('PEN_SECTION',sp>=minimum and s>=minimum,f'Sф={s:g} мм²; SPEN={sp:g} мм²; минимум для жил кабеля при совмещении={minimum:g} мм²; {mat}, многофазная TN, стационарный кабель.',100)
    if p=='PE' or d['phases']=='3':add('PEN_SINGLE','not_applicable','Однофазный PEN не указан.')
    elif p=='unknown' or d['phases']=='unknown':add('PEN_SINGLE','not_checked','Нужны тип проводника и число фаз.')
    elif d['overhead_branch']=='unknown':add('PEN_SINGLE','not_checked','Не установлено, действует ли исключение для однофазного ответвления от ВЛ.')
    elif d['overhead_branch']=='yes':add('PEN_SINGLE','not_applicable','Указано ответвление от ВЛ до 1 кВ; исключение. Его условия и остальные требования не проверены.')
    else:done('PEN_SINGLE',False,'В однофазной цепи указан PEN; исключение для ответвления от ВЛ исключено проверяющим.',100)
    if p=='unknown' or d['switch_protective']=='unknown':add('PE_SWITCH','not_checked','Не установлены тип защитного проводника или его коммутация.')
    elif d['switch_protective']=='no':add('PE_SWITCH','pass','По подтверждённым данным аппарат не размыкает PE/PEN.')
    elif d['switch_exception']=='unknown':add('PE_SWITCH','not_checked','Проверьте исключения пункта 1.7.145.')
    elif d['switch_exception']=='plug':add('PE_SWITCH','not_checked','Штепсельный соединитель: исключение требует проверки по 1.7.146, не реализованной здесь.')
    elif d['switch_exception']=='house_overhead':add('PE_SWITCH','not_checked','Исключение для ввода дома от ВЛ требует отдельной проверки всех условий; автоматического решения нет.')
    else:done('PE_SWITCH',False,'Подтверждено размыкание PE/PEN аппаратом; исключения не применяются.',100)
    if d['rejoin_after_split']=='unknown':add('N_PE_REJOIN','not_checked','Подтвердите наличие / отсутствие повторного объединения N и PE после разделения.')
    else:done('N_PE_REJOIN',d['rejoin_after_split']=='no','Повторное объединение после разделения: '+CHOICES[d['rejoin_after_split']]+'.',100)
    return results

def data_description(data):
    d=validate_data(data)
    return '\n'.join(label+': '+('не установлено' if d[key] is None else CHOICES.get(str(d[key]),str(d[key])))
                     for key,label,_,_,_ in FIELDS)
