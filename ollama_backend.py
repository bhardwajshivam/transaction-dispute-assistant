"""Local Ollama /api/chat adapter, using Python's standard library only."""
from dataclasses import dataclass
from copy import deepcopy
from http.client import HTTPConnection
import json
import math
import os
import re
import socket
from time import monotonic

from privacy import sanitise
from model_proposer import INSTRUCTIONS, MAX_RESPONSE_BYTES, PROPOSAL_SCHEMA, parse_response


class BackendError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OllamaConfig:
    model: str = 'smollm2:135m'
    timeout_seconds: float = 30.0
    max_output_tokens: int = 256

    def __post_init__(self):
        if not isinstance(self.model, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}', self.model) or 'cloud' in self.model.lower():
            raise BackendError('INVALID_LOCAL_MODEL')
        if type(self.timeout_seconds) not in (float, int) or not math.isfinite(self.timeout_seconds) or not 1 <= self.timeout_seconds <= 120:
            raise BackendError('INVALID_TIMEOUT')
        if type(self.max_output_tokens) is not int or not 128 <= self.max_output_tokens <= 1024:
            raise BackendError('INVALID_OUTPUT_LIMIT')

    @classmethod
    def from_env(cls):
        try:
            return cls(model=os.environ.get('OLLAMA_MODEL', 'smollm2:135m').strip(),
                       timeout_seconds=float(os.environ.get('OLLAMA_TIMEOUT_SECONDS', '30')),
                       max_output_tokens=int(os.environ.get('OLLAMA_MAX_OUTPUT_TOKENS', '256')))
        except (ValueError, TypeError):
            raise BackendError('INVALID_CONFIGURATION') from None


def local_chat(payload, timeout):
    """Fixed loopback address; no proxies, redirects, automatic retries or pulls."""
    connection = HTTPConnection('127.0.0.1', 11434, timeout=timeout)
    try:
        connection.request('POST', '/api/chat', body=json.dumps(sanitise(payload)).encode('utf-8'),
                           headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise BackendError({404: 'MODEL_NOT_FOUND', 429: 'SERVER_BUSY'}.get(response.status, 'OLLAMA_REQUEST_FAILED'))
        raw = response.read(65537)
        if len(raw) > 65536:
            raise BackendError('RESPONSE_TOO_LARGE')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise BackendError('MALFORMED_RESPONSE')
        return result
    except BackendError:
        raise
    except (socket.timeout, TimeoutError):
        raise BackendError('MODEL_TIMEOUT') from None
    except Exception as exc:
        code = 'MALFORMED_RESPONSE' if isinstance(exc, (ValueError, UnicodeError)) else 'OLLAMA_UNAVAILABLE'
        raise BackendError(code) from None
    finally:
        connection.close()


class OllamaBackend:
    def __init__(self, config=None, transport=None):
        self.config = config if config is not None else OllamaConfig.from_env()
        self._transport = transport or local_chat
        self.last_metadata = None

    def __call__(self, context, schema, instructions):
        self.last_metadata = None
        if schema != PROPOSAL_SCHEMA or instructions != INSTRUCTIONS:
            raise BackendError('CONTRACT_MISMATCH')
        fields = {'contract_version', 'workflow_step', 'selected_transaction_reference',
                  'remaining_tool_budget', 'allowed_proposals', 'evidence_statuses'}
        if not isinstance(context, dict) or set(context) != fields:
            raise BackendError('INVALID_CONTEXT')
        encoded = json.dumps(context, ensure_ascii=False)
        if len(encoded.encode('utf-8')) > 16384:
            raise BackendError('CONTEXT_TOO_LARGE')
        if not context['allowed_proposals'] or context['remaining_tool_budget'] <= 0:
            raise BackendError('NO_ALLOWED_PROPOSAL')
        payload = {'model': self.config.model, 'stream': False,
                   'messages': [{'role': 'system', 'content': INSTRUCTIONS},
                                {'role': 'user', 'content': encoded}],
                   'format': deepcopy(PROPOSAL_SCHEMA),
                   'options': {'temperature': 0, 'num_predict': self.config.max_output_tokens}}
        started = monotonic()
        try:
            result = self._transport(payload, self.config.timeout_seconds)
            if not isinstance(result, dict) or result.get('error'):
                raise BackendError('MALFORMED_RESPONSE')
            if result.get('done') is not True or result.get('done_reason') != 'stop':
                raise BackendError('INCOMPLETE_RESPONSE')
            message = result.get('message')
            if not isinstance(message, dict) or message.get('role') != 'assistant' or message.get('tool_calls'):
                raise BackendError('UNEXPECTED_RESPONSE_ITEM')
            raw = message.get('content')
            if not isinstance(raw, str) or not raw.strip():
                raise BackendError('EMPTY_RESPONSE')
            if len(raw.encode('utf-8')) > MAX_RESPONSE_BYTES:
                raise BackendError('OUTPUT_TOO_LARGE')
            try:
                proposal = parse_response(raw)
            except (ValueError, TypeError, RecursionError):
                raise BackendError('INVALID_MODEL_OUTPUT') from None
            if proposal not in context['allowed_proposals']:
                raise BackendError('PROPOSAL_NOT_ALLOWED')
            self.last_metadata = {'provider': 'ollama', 'configured_model': self.config.model,
                                  'elapsed_ms': round((monotonic() - started) * 1000), 'status': 'SUCCESS'}
            for target, source in [('input_tokens', 'prompt_eval_count'), ('output_tokens', 'eval_count')]:
                count = result.get(source)
                if type(count) is int and count >= 0:
                    self.last_metadata[target] = count
            return raw
        except BackendError:
            raise
        except Exception:
            raise BackendError('OLLAMA_UNAVAILABLE') from None


def backend_from_env():
    return OllamaBackend(OllamaConfig.from_env())
