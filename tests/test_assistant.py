import copy
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from unittest.mock import patch
from core import create_demo
from drafts import local_drafts
from assistant_api import endpoint,page_regions,request_drafts,validate_drafts

def answer(rid):
    return {'drafts':[{'source_ids':[rid],'data':{'name':'QF1','breaker_a':16},
                      'field_sources':{'name':[rid],'breaker_a':[rid]},'warnings':['Сверьте связь']} ]}

class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.project=create_demo(Path(self.temp.name)/'project')
        self.r=self.project.add(0,[.1,.1,.2,.2],'QF1 C16')
        self.regions=page_regions(self.project.state,0)
    def tearDown(self):self.project.close();self.temp.cleanup()
    def test_endpoint_validation(self):
        for base in ('http://localhost:11434/v1','http://127.0.0.1:9999','http://[::1]:8000/v1'):
            self.assertTrue(endpoint(base)[1]);self.assertTrue(endpoint(base)[0].endswith('/chat/completions'))
        self.assertFalse(endpoint('https://api.deepseek.com')[1])
        for base in ('http://example.com','http://127.0.0.1.evil.test','https://key@host/v1','https://host?key=x',
                     'https://host/#x','file:///tmp/a','https://host:bad','https://host/chat/completions',''):
            with self.subTest(base=base),self.assertRaises(ValueError):endpoint(base)
    def test_drafts_are_not_approved(self):
        before=copy.deepcopy(self.project.state)
        drafts=validate_drafts(answer(self.r['id']),self.regions,0)
        self.assertEqual(drafts[0]['data']['voltage'],None)
        self.assertEqual(drafts[0]['data']['protective_type'],'unknown')
        self.assertEqual(self.project.state,before)
    def test_unknown_reference_rejected(self):
        data=answer('absent')
        with self.assertRaises(ValueError):validate_drafts(data,self.regions,0)
    def test_unsubstantiated_fields_rejected(self):
        data=answer(self.r['id']);data['drafts'][0]['data']['protective_mm2']=2.5
        with self.assertRaises(ValueError):validate_drafts(data,self.regions,0)
    def test_unknown_field_and_invalid_types_rejected(self):
        for key,value in [('risk',100),('voltage',11000),('breaker_a',float('nan')),('breaker_a',True),('earthing','typical')]:
            data=answer(self.r['id']);data['drafts'][0]['data'][key]=value;data['drafts'][0]['field_sources'][key]=[self.r['id']]
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_drafts(data,self.regions,0)
    def test_foreign_field_source_rejected(self):
        data=answer(self.r['id']);data['drafts'][0]['field_sources']['name']=['absent']
        with self.assertRaises(ValueError):validate_drafts(data,self.regions,0)
    def test_duplicate_and_extra_verdict_rejected(self):
        data=answer(self.r['id']);data['drafts']*=2
        with self.assertRaises(ValueError):validate_drafts(data,self.regions,0)
        data=answer(self.r['id']);data['verdict']='соответствует'
        with self.assertRaises(ValueError):validate_drafts(data,self.regions,0)
    def test_only_current_page_nonexcluded_readings(self):
        self.project.add(0,[.2,.2,.3,.3],'Ошибка',kind='finding',severity=90)
        r=self.project.add(0,[.3,.3,.4,.4],'Скрыто');self.project.decide(r['id'],r['text'],'Engineer','excluded')
        self.assertNotIn('Скрыто',[r['text'] for r in page_regions(self.project.state,0)])
        self.assertNotIn('Ошибка',[r['text'] for r in page_regions(self.project.state,0)])
    def test_real_local_http_request_and_no_key_persistence(self):
        captured=[];rid=self.r['id']
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append((self.path,dict(self.headers),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                body=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer(rid))}}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.handle_request);thread.start()
        try:
            drafts=request_drafts({'endpoint':f'http://127.0.0.1:{server.server_port}/v1','model':'test'},'synthetic-secret',self.regions,0)
            self.assertEqual(drafts[0]['data']['name'],'QF1')
        finally:thread.join(5);server.server_close()
        path,headers,payload=captured[0];self.assertEqual(path,'/v1/chat/completions')
        self.assertEqual(headers['Authorization'],'Bearer synthetic-secret')
        self.assertNotIn('synthetic-secret',json.dumps(payload))
        self.assertNotIn('synthetic-secret',self.project.path.read_text(encoding='utf-8'))
    def test_redirect_does_not_forward_credentials(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302);self.send_header('Location','http://127.0.0.1:1/stolen');self.end_headers()
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.handle_request);thread.start()
        try:
            with self.assertRaisesRegex(ValueError,'HTTP 302'):
                request_drafts({'endpoint':f'http://127.0.0.1:{server.server_port}','model':'test'},'synthetic-secret',self.regions,0)
        finally:thread.join(5);server.server_close()

class DraftWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.p=create_demo(Path(self.temp.name)/'project')
        self.q=self.p.add(0,[.10,.10,.14,.13],'QF1 C16')
        self.c=self.p.add(0,[.10,.15,.18,.18],'NYM 3x2.5')
        self.other=self.p.add(0,[.70,.70,.80,.74],'Пояснение')
        self.data={'name':'QF1','evidence':'Проверено по учебному листу'}
    def tearDown(self):self.p.close();self.temp.cleanup()
    def test_local_draft_is_proposal_not_final_topology(self):
        drafts=local_drafts(self.p.state,0)
        self.assertEqual(len(drafts),1);self.assertEqual(set(drafts[0]['source_ids']),{self.q['id'],self.c['id']})
        self.assertEqual(drafts[0]['data']['phase_mm2'],2.5)
        self.assertNotIn('protective_mm2',drafts[0]['data'])
        self.assertEqual(self.q['status'],'pending');self.assertEqual(self.p.state['circuits'],[])
    def test_ambiguous_neighbour_is_not_assigned(self):
        self.p.add(0,[.22,.10,.26,.13],'QF2 C25');self.c['box']=[.17,.15,.19,.18]
        drafts=local_drafts(self.p.state,0)
        self.assertTrue(all(self.c['id'] not in d['source_ids'] for d in drafts))
        self.assertTrue(all(len(d['warnings'])>1 for d in drafts))
    def test_approve_only_selected_and_keep_original(self):
        card=self.p.confirm_draft(self.data,{self.q['id']:'QF1 C20',self.c['id']:self.c['text']},'Engineer')
        self.assertEqual(self.q['original'],'QF1 C16');self.assertEqual(self.q['text'],'QF1 C20')
        self.assertEqual(self.q['status'],'approved');self.assertEqual(self.other['status'],'pending')
        self.assertEqual(card['snapshot'][0]['text'],'QF1 C20')
        self.p.check_circuits('Engineer');self.assertTrue(all(r['status']=='not_checked' for r in self.p.state['checks']['circuits'][0]['rows']))
    def test_invalid_batch_changes_nothing(self):
        before=copy.deepcopy(self.p.state);disk=self.p.path.read_bytes()
        for data,edits in [({'name':'','evidence':'x'},{self.q['id']:'corrected'}),
                           (self.data,{self.q['id']:'corrected',self.c['id']:''}),
                           (self.data,{'absent':'x'}),(self.data,{})]:
            with self.assertRaises(ValueError):self.p.confirm_draft(data,edits,'Engineer')
            self.assertEqual(self.p.state,before);self.assertEqual(self.p.path.read_bytes(),disk)
    def test_failed_save_restores_memory(self):
        before=copy.deepcopy(self.p.state)
        with patch.object(self.p,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.p.confirm_draft(self.data,{self.q['id']:'changed'},'Engineer')
        self.assertEqual(self.p.state,before)
    def test_batch_invalidates_dependent_findings(self):
        self.p.confirm_draft(self.data,{self.q['id']:self.q['text']},'Engineer')
        old=self.p.state['circuits'][0];self.p.check_circuits('Engineer')
        self.p.confirm_draft(self.data,{self.q['id']:'QF1 C20'},'Engineer')
        self.assertEqual(old['status'],'stale');self.assertTrue(self.p.state['checks']['stale'])

if __name__=='__main__':unittest.main()
