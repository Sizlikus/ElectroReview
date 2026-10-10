import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from pypdf import PdfReader
from core import Project,create_demo,export,ocr_directions
from electrical import evaluate,parse_labels,suggested_data,validate_data

def facts(**updates):
    data={'name':'QF1','evidence':'Учебный лист 1, подтверждено инженером','voltage':230,'current_kind':'AC',
          'phases':'1','earthing':'TN-S','phase_material':'Cu','phase_mm2':2.5,
          'protective_type':'PE','protective_material':'Cu','protective_mm2':2.5,
          'pe_method':'table','pe_route':'in_cable','switch_protective':'no','rejoin_after_split':'no'}
    data.update(updates);return data

def rows(data):return {r['rule']:r for r in evaluate(data)}

class RuleTests(unittest.TestCase):
    def test_pe_table_boundaries(self):
        for phase,minimum in [(1.5,1.5),(16,16),(16.01,16),(35,16),(35.01,17.505),(50,25)]:
            with self.subTest(phase=phase):
                self.assertEqual(rows(facts(phase_mm2=phase,protective_mm2=minimum))['PE_TABLE']['status'],'pass')
                self.assertEqual(rows(facts(phase_mm2=phase,protective_mm2=minimum-.01))['PE_TABLE']['status'],'violation')
    def test_no_pe_false_positive_for_calculation_or_unknown_method(self):
        for method in ('calculation','unknown'):
            self.assertEqual(rows(facts(phase_mm2=50,protective_mm2=1.5,pe_method=method))['PE_TABLE']['status'],'not_checked')
    def test_different_materials_not_checked(self):
        self.assertEqual(rows(facts(protective_material='Al'))['PE_TABLE']['status'],'not_checked')
    def test_separate_pe_minimum(self):
        for material,route,mechanical,minimum in [('Cu','separate','yes',2.5),('Cu','separate','no',4),('Cu','common','yes',2.5),('Al','common','unknown',16)]:
            with self.subTest(material=material,route=route,mechanical=mechanical):
                d=facts(protective_material=material,pe_route=route,mechanical=mechanical,protective_mm2=minimum)
                self.assertEqual(rows(d)['PE_SEPARATE']['status'],'pass')
                d['protective_mm2']=minimum-.1;self.assertEqual(rows(d)['PE_SEPARATE']['status'],'violation')
        self.assertEqual(rows(facts(pe_route='separate'))['PE_SEPARATE']['status'],'not_checked')
    def test_pen_minimum_and_applicability(self):
        for mat,minimum in [('Cu',10),('Al',16)]:
            d=facts(protective_type='PEN',phases='3',earthing='TN-C',fixed_cable='yes',phase_material=mat,phase_mm2=minimum,protective_material=mat,protective_mm2=minimum)
            self.assertEqual(rows(d)['PEN_SECTION']['status'],'pass')
            d['protective_mm2']=minimum-.1;self.assertEqual(rows(d)['PEN_SECTION']['status'],'violation')
            d['fixed_cable']='unknown';self.assertEqual(rows(d)['PEN_SECTION']['status'],'not_checked')
            d['fixed_cable']='yes';d['earthing']='TT';self.assertEqual(rows(d)['PEN_SECTION']['status'],'not_checked')
    def test_pen_undersized_phase_not_passed(self):
        d=facts(protective_type='PEN',phases='3',earthing='TN-C',fixed_cable='yes',phase_mm2=6,protective_mm2=10)
        self.assertEqual(rows(d)['PEN_SECTION']['status'],'violation')
    def test_pen_single_exception(self):
        for branch,outcome in [('unknown','not_checked'),('yes','not_applicable'),('no','violation')]:
            self.assertEqual(rows(facts(protective_type='PEN',overhead_branch=branch))['PEN_SINGLE']['status'],outcome)
    def test_switch_exceptions_never_assumed(self):
        for exception,outcome in [('unknown','not_checked'),('none','violation'),('plug','not_checked'),('house_overhead','not_checked')]:
            self.assertEqual(rows(facts(switch_protective='yes',switch_exception=exception))['PE_SWITCH']['status'],outcome)
    def test_rejoining(self):
        self.assertEqual(rows(facts(rejoin_after_split='yes'))['N_PE_REJOIN']['status'],'violation')
        self.assertEqual(rows(facts(rejoin_after_split='unknown'))['N_PE_REJOIN']['status'],'not_checked')
    def test_unknown_voltage_blocks_all_checks(self):
        self.assertEqual({r['status'] for r in evaluate(facts(voltage=None))},{'not_checked'})
        for kind in ('unknown','DC'):
            self.assertEqual({r['status'] for r in evaluate(facts(current_kind=kind))},{'not_checked'})
    def test_invalid_data(self):
        for value in ('NaN','inf',-1,0):
            with self.assertRaises(ValueError):validate_data(facts(protective_mm2=value))
        for value in (219,401,10000):
            with self.assertRaises(ValueError):validate_data(facts(voltage=value))
        with self.assertRaises(ValueError):validate_data(facts(evidence=''))

class ParserTests(unittest.TestCase):
    def test_cables_decimal_and_x_variants(self):
        for text in ('ВВГнг(А)-LS 3х2,5','ВВГнг 3×2.5','NYM-5x6','АВВГ 4*16'):
            with self.subTest(text=text):
                cables=[c for c in parse_labels(text) if c['kind']=='cable'];self.assertEqual(len(cables),1)
                self.assertGreater(cables[0]['phase_mm2'],0)
        self.assertEqual(parse_labels('АВВГ 4х16')[0]['material'],'Al')
    def test_mixed_sizes_not_guessed(self):
        d,c=suggested_data('ВВГ 3x50+1x25')
        self.assertIsNone(d['phase_mm2']);self.assertNotIn('protective_mm2',d)
    def test_devices_and_rcd(self):
        d,c=suggested_data('QF1 C16 ВВГнг 3х2,5 PE 30 мА')
        self.assertEqual(d['name'],'QF1');self.assertEqual(d['breaker_a'],16);self.assertEqual(d['rcd_ma'],30)
        self.assertNotIn('protective_type',d)
    def test_ambiguous_multiple_devices_not_associated(self):
        d,c=suggested_data('QF1 C16 ВВГ 3x2,5 QF2 C10 ВВГ 3x1,5')
        self.assertNotIn('name',d);self.assertNotIn('phase_mm2',d);self.assertNotIn('breaker_a',d)
    def test_do_not_correct_ocr_letters_to_digits(self):
        d,c=suggested_data('QF1 C1O ВВГ 3x2,S')
        self.assertNotIn('breaker_a',d);self.assertFalse([x for x in c if x['kind']=='cable'])
    def test_rotated_box_mapping_and_duplicates(self):
        image=Image.new('RGB',(200,100))
        horizontal=[{'text':'QF1','box':[.7,.2,.9,.4],'confidence':95}]
        rotated=[{'text':'QF1','box':[.2,.1,.4,.3],'confidence':95},
                 {'text':'КАБЕЛЬ','box':[.5,.6,.8,.8],'confidence':80}]
        with patch('core.ocr',side_effect=[horizontal,rotated,[]]):result=ocr_directions(image)
        self.assertEqual(len(result),2)
        for actual,expected in zip(result[1]['box'],[.2,.5,.4,.8]):self.assertAlmostEqual(actual,expected)
    def test_opposite_rotation_and_grouped_lines(self):
        words=[{'text':'ВВГ','box':[.1,.1,.2,.2],'confidence':95,'line_id':('1','1','1')},
               {'text':'3x2,5','box':[.21,.1,.4,.2],'confidence':65,'line_id':('1','1','1')}]
        with patch('core.ocr',side_effect=[[],[],words]):result=ocr_directions(Image.new('RGB',(200,100)))
        self.assertEqual(result[0]['text'],'ВВГ 3x2,5');self.assertEqual(result[0]['confidence'],65)
        for actual,expected in zip(result[0]['box'],[.1,.6,.2,.9]):self.assertAlmostEqual(actual,expected)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.p=create_demo(self.root/'project');self.r=self.p.state['regions'][0]
        self.p.decide(self.r['id'],'QF1 C16 ВВГ 3х2,5 PE 1,5','Инженер','approved')
    def tearDown(self):self.p.close();self.tmp.cleanup()
    def confirm(self,**updates):return self.p.confirm_circuit(facts(**updates),[self.r['id']],'Инженер')
    def test_requires_approved_source_and_reviewer(self):
        self.p.decide(self.r['id'],self.r['text'],'Инженер','pending')
        with self.assertRaises(ValueError):self.confirm()
        with self.assertRaises(ValueError):self.p.confirm_circuit(facts(),[],'Инженер')
        with self.assertRaises(ValueError):self.p.check_circuits('')
    def test_findings_pending_idempotent_and_audited(self):
        self.confirm(protective_mm2=1.5);check=self.p.check_circuits('Инженер')
        self.assertEqual(len(check['circuits'][0]['rows']),6)
        findings=[r for r in self.p.state['regions'] if r['kind']=='finding']
        self.assertEqual(len(findings),1);self.assertEqual(findings[0]['status'],'pending');self.assertEqual(findings[0]['severity'],90)
        self.assertIn('1.7.126',findings[0]['basis'])
        self.p.decide(findings[0]['id'],findings[0]['text'],'Инженер','approved',findings[0]['basis'])
        self.p.check_circuits('Инженер');self.assertEqual(len([r for r in self.p.state['regions'] if r['kind']=='finding']),1)
        self.assertEqual(findings[0]['status'],'approved')
    def test_reading_change_invalidates_and_blocks_old_approval(self):
        c=self.confirm(protective_mm2=1.5);self.p.check_circuits('Инженер')
        finding=next(r for r in self.p.state['regions'] if r['kind']=='finding')
        self.p.decide(self.r['id'],'Изменено','Инженер','approved')
        self.assertTrue(self.p.state['checks']['stale']);self.assertEqual(c['status'],'stale');self.assertTrue(finding['superseded'])
        with self.assertRaises(ValueError):self.p.decide(finding['id'],finding['text'],'Инженер','approved',finding['basis'])
        check=self.p.check_circuits('Инженер');self.assertEqual({r['status'] for r in check['circuits'][0]['rows']},{'not_checked'})
    def test_card_correction_replaces_old_results(self):
        c=self.confirm(protective_mm2=1.5);self.p.check_circuits('Инженер')
        self.p.confirm_circuit(facts(),[self.r['id']],'Инженер',c['id']);self.p.check_circuits('Инженер')
        self.assertFalse([r for r in self.p.state['regions'] if r['kind']=='finding' and r['status']!='excluded'])
    def test_save_reopen_and_export_coverage(self):
        self.confirm(protective_mm2=1.5,switch_protective='unknown');self.p.check_circuits('Инженер')
        self.p.close();self.p=Project(self.root/'project')
        output=export(self.p,self.root/'result.pdf');reader=PdfReader(output)
        text='\n'.join(p.extract_text() for p in reader.pages)
        self.assertIn('1.7.126',text);self.assertIn('Не проверено',text);self.assertIn('подтверждено инженером',text)
        self.assertEqual(len(reader.pages[0]['/Annots']),1)
    def test_stale_export_is_labelled(self):
        self.confirm();self.p.check_circuits('Инженер')
        self.p.decide(self.r['id'],self.r['text'],'Инженер','pending')
        output=export(self.p,self.root/'stale.pdf');text='\n'.join(p.extract_text() for p in PdfReader(output).pages)
        self.assertIn('РЕЗУЛЬТАТЫ УСТАРЕЛИ',text)
    def test_old_project_without_new_fields(self):
        self.p.close();path=self.root/'project/project.json';state=json.loads(path.read_text(encoding='utf-8'))
        state.pop('circuits',None);state.pop('checks',None);path.write_text(json.dumps(state),encoding='utf-8')
        self.p=Project(self.root/'project');self.assertEqual(self.p.state['circuits'],[]);self.assertIsNone(self.p.state['checks'])
    def test_repeat_ocr_preserves_confirmed_text_and_avoids_duplicates(self):
        text=self.r['text'];box=self.r['box']
        self.p.state['pages'][0]['ocr']='done'
        self.p.ingest(0,[{'text':text,'box':box,'confidence':99},{'text':'NYM 5x6','box':[.7,.1,.8,.2],'confidence':80}],repeat=True)
        self.assertEqual(self.r['status'],'approved');self.assertEqual(self.r['text'],text)
        self.assertEqual(len(self.p.state['regions']),2);self.assertEqual(self.p.state['regions'][-1]['status'],'pending')

if __name__=='__main__':unittest.main()
