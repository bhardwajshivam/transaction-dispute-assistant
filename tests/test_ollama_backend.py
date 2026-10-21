import json
import os
import socket
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from evidence_agent import propose
from model_proposer import build_context, INSTRUCTIONS, PROPOSAL_SCHEMA, make_proposer
from ollama_backend import OllamaBackend, OllamaConfig, BackendError, local_chat


def state():
    return {'step': 'recognise', 'answers': {'transaction': 'TX-1001'}, 'evidence': {}}


def response(**kwargs):
    result = {'done': True, 'done_reason': 'stop',
              'message': {'role': 'assistant', 'content': json.dumps(propose(state()))},
              'prompt_eval_count': 100, 'eval_count': 30}
    result.update(kwargs)
    return result


class OllamaTests(unittest.TestCase):
    def test_defaults_and_invalid_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(OllamaConfig.from_env().model, 'smollm2:135m')
        for value in ('nan', '0', '121', 'bad'):
            with patch.dict(os.environ, {'OLLAMA_TIMEOUT_SECONDS': value}, clear=True):
                with self.assertRaises(BackendError): OllamaConfig.from_env()
        with self.assertRaises(BackendError): OllamaConfig(model='some-model:cloud')

    def test_structured_request_and_metadata(self):
        transport = Mock(return_value=response())
        backend = OllamaBackend(OllamaConfig(), transport)
        raw = backend(build_context(state()), PROPOSAL_SCHEMA, INSTRUCTIONS)
        self.assertEqual(json.loads(raw), propose(state()))
        payload, timeout = transport.call_args.args
        self.assertEqual(payload['format'], PROPOSAL_SCHEMA)
        self.assertFalse(payload['stream'])
        self.assertEqual(payload['options'], {'temperature': 0, 'num_predict': 256})
        self.assertNotIn('tools', payload)
        self.assertEqual(timeout, 30)
        self.assertEqual(backend.last_metadata['input_tokens'], 100)

    def test_invalid_responses_fallback(self):
        for value in [response(done=False), response(done_reason='length'), response(message={'role': 'assistant', 'content': ''}),
                      response(message={'role': 'assistant', 'content': 'bad'}),
                      response(message={'role': 'assistant', 'content': 'x' * 5000}),
                      response(message={'role': 'assistant', 'content': json.dumps(dict(propose(state()), transaction_id='OTHER'))}),
                      response(message={'role': 'assistant', 'tool_calls': [{}], 'content': '{}'}), None]:
            with self.subTest(value=str(value)[:60]):
                backend = OllamaBackend(transport=Mock(return_value=value))
                s = state()
                self.assertEqual(make_proposer(backend)(s), propose(s))
                self.assertTrue(s['proposer_trace'][0]['fallback'])

    def test_contract_rejection_no_transport(self):
        transport = Mock()
        backend = OllamaBackend(transport=transport)
        with self.assertRaises(BackendError): backend(build_context(state()), {}, INSTRUCTIONS)
        ctx = build_context(state()); ctx['api_key'] = 'private'
        with self.assertRaises(BackendError): backend(ctx, PROPOSAL_SCHEMA, INSTRUCTIONS)
        transport.assert_not_called()

    def test_http_fixed_loopback_and_bounded_read(self):
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = json.dumps(response()).encode()
        with patch('ollama_backend.HTTPConnection', return_value=connection) as factory:
            self.assertTrue(local_chat({'model': 'smollm2:135m'}, 5)['done'])
            factory.assert_called_once_with('127.0.0.1', 11434, timeout=5)
            self.assertEqual(connection.request.call_args.args[:2], ('POST', '/api/chat'))
            connection.getresponse.return_value.read.assert_called_once_with(65537)
            connection.close.assert_called_once()

    def test_http_errors_timeout_and_no_retry(self):
        for status, code in [(404, 'MODEL_NOT_FOUND'), (500, 'OLLAMA_REQUEST_FAILED')]:
            connection = Mock()
            connection.getresponse.return_value.status = status
            with patch('ollama_backend.HTTPConnection', return_value=connection):
                with self.assertRaisesRegex(BackendError, code): local_chat({}, 1)
                self.assertEqual(connection.request.call_count, 1)
                connection.close.assert_called_once()
        connection = Mock(); connection.request.side_effect = socket.timeout('private detail')
        with patch('ollama_backend.HTTPConnection', return_value=connection):
            with self.assertRaisesRegex(BackendError, '^MODEL_TIMEOUT$'): local_chat({}, 1)
            self.assertEqual(connection.request.call_count, 1)

    def test_malformed_and_oversize_envelope(self):
        for raw in (b'bad json', b'x' * 65537, b'[]'):
            connection = Mock()
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read.return_value = raw
            with patch('ollama_backend.HTTPConnection', return_value=connection):
                with self.assertRaises(BackendError): local_chat({}, 1)
