"""Full pipeline: installed dependencies and freshly trained model required."""
import importlib.util
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

AVAILABLE=all(importlib.util.find_spec(p) for p in ('flask','sklearn','pandas','yaml','joblib','requests','dotenv'))
if os.getenv('CI') and not AVAILABLE:
    raise RuntimeError('CI must install all requirements; skipping ML is not allowed')


@unittest.skipUnless(AVAILABLE, 'ML/API dependencies unavailable: inference not validated')
class PipelineTests(unittest.TestCase):
    def setUp(self):
        from app import app
        self.client=app.test_client()
        self.env=patch.dict(os.environ,{'COPILOT_API_TOKEN':'test-token','CLYVO_LLM_PROVIDER':'template'})
        self.env.start();self.addCleanup(self.env.stop)

    def data(self, scenario='normal'):
        now=datetime.now(timezone.utc)-timedelta(seconds=1)
        rows=[{'ts':(now-timedelta(minutes=39-i)).isoformat(),
               'temperature_c':40.5 if scenario=='fever' and i>=30 else 38.5,
               'heart_rate_bpm':90,'spo2_pct':97.5,'activity_score':0.5} for i in range(40)]
        return {'pet':{'id':1,'name':'Thor','species':'dog','birth_date':'2020-01-01',
                       'weight_kg':20,'tutor_name':'Tutor'},'readings':rows,'simulated':True}

    def analyze(self,p):
        res=self.client.post('/v1/analyze',json=p,headers={'Authorization':'Bearer test-token'})
        self.assertEqual(res.status_code,200,res.get_json())
        return res.get_json()

    def test_auth_and_validation(self):
        self.assertEqual(self.client.post('/v1/analyze',json=self.data()).status_code,401)
        self.assertEqual(self.client.post('/v1/analyze',json={},headers={'Authorization':'Bearer test-token'}).status_code,400)

    def test_actual_model_and_urgent_rules(self):
        normal=self.analyze(self.data());fever=self.analyze(self.data('fever'))
        self.assertEqual(normal['risk']['mode'],'model')
        self.assertGreater(fever['risk']['risk_score'],normal['risk']['risk_score'])
        self.assertEqual(fever['priority'],1)
        self.assertEqual(fever['llm_mode'],'template')
        self.assertFalse(fever['rag_used'])
        self.assertTrue(fever['rag_sources'])

    def test_stale_telemetry_is_excluded(self):
        p=self.data()
        for row in p['readings']:
            row['ts']=(datetime.fromisoformat(row['ts'])-timedelta(days=2)).isoformat()
        result=self.analyze(p)
        self.assertTrue(any('desatualizada' in w for w in result['warnings']))
        self.assertEqual(result['baseline_source']['temp'],'none')

    def test_provider_failure_is_visible(self):
        with patch.dict(os.environ,{'CLYVO_LLM_PROVIDER':'ollama'}), patch('requests.post',side_effect=RuntimeError('offline')):
            result=self.analyze(self.data('fever'))
        self.assertEqual(result['llm_mode'],'template');self.assertIsNotNone(result['llm_error'])
        self.assertFalse(result['rag_used'])

    def test_rag_and_generation_contract_with_mock(self):
        import json
        from unittest.mock import Mock
        response=Mock()
        response.json.return_value={'response':json.dumps({'tutor_message':'Thor apresenta alterações nos sensores. Entre em contato com a clínica agora para avaliação.',
            'vet_briefing':'Thor: alterações na janela recente. Revisar sinais, prioridade e histórico antes de orientar o tutor.'})}
        with patch.dict(os.environ,{'CLYVO_LLM_PROVIDER':'ollama'}), patch('requests.post',return_value=response):
            result=self.analyze(self.data('fever'))
        self.assertEqual(result['llm_mode'],'ollama');self.assertTrue(result['rag_used'])
        self.assertTrue(result['rag_sources'])

if __name__=='__main__': unittest.main()
