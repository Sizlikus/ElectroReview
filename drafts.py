"""Conservative spatial proposals; proximity never establishes connectivity."""
import math
from electrical import parse_labels,suggested_data
from assistant_api import page_regions

def local_drafts(state,page):
    regions=page_regions(state,page);parsed={r['id']:parse_labels(r['text']) for r in regions}
    anchors=[r for r in regions if any(c['kind']=='device' for c in parsed[r['id']])]
    groups={r['id']:[r] for r in anchors}
    warnings={r['id']:['Близость надписей — только подсказка. Проверьте связь по линии схемы.'] for r in anchors}
    def distance(a,b):
        x,y,w,h=a['box'];u,v,m,n=b['box']
        return math.hypot(max(x-m,u-w,0),max(y-n,v-h,0))
    for r in regions:
        if r in anchors or not parsed[r['id']]:continue
        ranked=sorted((distance(r,a),a['id']) for a in anchors)
        if not ranked or ranked[0][0]>.18:continue
        if len(ranked)>1 and ranked[1][0]-ranked[0][0]<.025:
            for _,rid in ranked[:2]:warnings[rid].append('Рядом неоднозначная надпись: '+r['text'][:150]+' — не включена.')
        else:groups[ranked[0][1]].append(r)
    result=[]
    for anchor in anchors:
        group=groups[anchor['id']];data,_=suggested_data(' '.join(r['text'] for r in group))
        if not data.get('name'):data['name']='Уточнить: '+anchor['text'][:80]
        data['evidence']='Лист PDF '+str(page+1)+'; сверено проверяющим'
        result.append({'source_ids':[r['id'] for r in group],'data':data,'warnings':warnings[anchor['id']], 'origin':'Локальный разбор'})
    return result
