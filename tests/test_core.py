import copy
import unittest
from datetime import datetime, timedelta, timezone
from ai_core.integration import validate_payload
from ai_core.features import telemetry_features
from ai_core import guardrails, iob, llm


def payload():
    return {'pet': {'id': 1, 'name': 'Thor', 'species': 'dog'},
            'readings': [{'ts': (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),
                          'temperature_c': 38.5}]}


class CoreTests(unittest.TestCase):
    def test_valid_payload(self):
        validate_payload(payload())

    def test_nan_and_impossible_values_are_rejected(self):
        for value in [float('nan'), float('inf'), 99, True, '38.5']:
            p=payload();p['readings'][0]['temperature_c']=value
            with self.assertRaises(ValueError): validate_payload(p)

    def test_duplicate_and_unordered_readings_are_rejected(self):
        p=payload();p['readings'] *= 2
        with self.assertRaises(ValueError): validate_payload(p)

    def test_unsupported_species_and_future_are_rejected(self):
        p=payload();p['pet']['species']='bird'
        with self.assertRaises(ValueError): validate_payload(p)
        p=payload();p['readings'][0]['ts']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError): validate_payload(p)

    def test_baseline_does_not_learn_from_current_abnormal_window(self):
        rows=[{'temperature_c':38.5} for _ in range(30)]+[{'temperature_c':40.5} for _ in range(10)]
        result=telemetry_features(rows,'dog')
        self.assertEqual(result['baseline_source']['temp'],'individual')
        self.assertGreater(result['temp_z'],10)
        self.assertEqual(result['baseline']['temp']['mean'],38.5)

    def test_no_data_and_cold_start_are_explicit(self):
        self.assertEqual(telemetry_features([])['baseline_source']['temp'],'none')
        self.assertEqual(telemetry_features([{'temperature_c':38.5}])['baseline_source']['temp'],'prior')

    def test_guardrail_blocks_dose(self):
        self.assertFalse(guardrails.validate_tutor_message('Thor deve tomar 10 mg de dipirona antes da consulta.','Thor')['ok'])

    def test_iob_changes_with_observed_interactions(self):
        sent=[{'event_type':'message_sent'} for _ in range(5)]
        effective=sent+[{'event_type':'opened','channel':'portal','ts':'2026-11-01T19:00:00'} for _ in range(5)]
        self.assertLess(iob.tutor_profile({},sent)['engagement_score'],iob.tutor_profile({},effective)['engagement_score'])
        self.assertEqual(iob.tutor_profile({},effective)['preferred_channel'],'portal')

if __name__=='__main__': unittest.main()
