import json
from unittest import TestCase
from unittest.mock import patch
from report_metadata import portable, model_metadata
from scripts.evaluate_live_extraction import server_metadata


class ReportMetadataTests(TestCase):
    def test_nested_paths_redacted_but_evidence_and_relative_paths_preserved(self):
        home='/'+'Users'+'/sampleuser/private/model.bin'
        linux='/'+'home'+'/sampleuser/model.bin'
        windows='C:'+chr(92)+'Users'+chr(92)+'sampleuser'+chr(92)+'model.bin'
        source={'diagnostics':[home,linux,windows], 'source':'card_service.py',
                'url':'http://127.0.0.1:11434/api/chat','passed':47,'digest':'a'*64}
        clean=portable(source)
        self.assertNotIn('sampleuser',json.dumps(clean))
        self.assertEqual(clean['source'],source['source'])
        self.assertEqual(clean['url'],source['url'])
        self.assertEqual(clean['passed'],47)
        self.assertEqual(clean['digest'],source['digest'])

    def test_model_details_are_allowlisted(self):
        model={'name':'smollm2:135m','digest':'a'*64,'details':{
            'parent_model':'/'+'Users'+'/sampleuser/model',
            'username':'sampleuser','hostname':'private-host','family':'llama',
            'parameter_size':'134.52M','context_length':8192}}
        clean=model_metadata(model)
        self.assertEqual(set(clean['details']),{'family','parameter_size','context_length'})
        self.assertNotIn('sampleuser',json.dumps(clean))
        self.assertNotIn('private-host',json.dumps(clean))

    def test_actual_collector_uses_allowlist_for_models_and_server(self):
        from unittest.mock import MagicMock
        model={'name':'smollm2:135m','digest':'a'*64,'details':{
            'parent_model':'/'+'home'+'/sampleuser/model','family':'llama'}}
        server={'version':'0.33.2','username':'sampleuser','hostname':'private-host'}
        replies=[]
        for payload in (server,{'models':[model]}):
            response=MagicMock(status=200);response.read.return_value=json.dumps(payload).encode();replies.append(response)
        with patch('scripts.evaluate_live_extraction.HTTPConnection') as factory:
            factory.return_value.getresponse.side_effect=replies
            result=server_metadata()
        self.assertEqual(result['server'],{'version':'0.33.2'})
        self.assertNotIn('sampleuser',json.dumps(result))
        self.assertEqual(result['models'][0]['details'],{'family':'llama'})
