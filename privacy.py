"""Conservative deterministic input minimisation. Detection is not exhaustive."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ProtectedText:
    text: str
    categories: tuple
    contains_secrets: bool


PATTERNS = [
    ('SECRET', re.compile(r'\b(?:otp|pin|cvv|cvc)\s*(?:is\s*|[:=]\s*)?\d{3,8}\b', re.I)),
    ('SECRET', re.compile(r'\b(?:password|passcode|access[_ ]token|api[_ ]key)\s*(?:is\s+|[:=]\s*|\s+)\S+', re.I)),
    ('SECRET', re.compile(r'\bsk-[A-Za-z0-9_-]{12,}\b')),
    ('SECRET', re.compile(r'\bBearer\s+[A-Za-z0-9._~-]{12,}', re.I)),
    ('GOVERNMENT_ID', re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b')),
    ('EMAIL', re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)),
    ('IBAN', re.compile(r'\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b')),
    ('GOVERNMENT_ID', re.compile(r'\b(?:aadhaar|aadhar|ssn|tax id|national id|passport(?: number)?)\s*(?:is\s*|[:=]\s*)?[A-Z0-9][A-Z0-9 -]{4,22}', re.I)),
    ('GOVERNMENT_ID', re.compile(r'\b\d{3}-\d{2}-\d{4}\b')),
    ('NAME', re.compile(r'\b(?i:my name is)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b')),
    ('ADDRESS', re.compile(r'\bmy (?:home |postal )?address is\s+[^.;\n]{3,120}', re.I)),
]
LONG_NUMBER = re.compile(r'(?<![\w.])\+?\d(?:[ ()-]?\d){8,18}(?!\w|\.\d)')
DATE = re.compile(r'(?:\d{2}-\d{2}-\d{4}|\d{4}-\d{2}-\d{2})')


def protect(text):
    categories = set()
    result = text
    for category, pattern in PATTERNS:
        def replace(match):
            categories.add(category)
            return f'[{category}_REDACTED]'
        result = pattern.sub(replace, result)
    def number(match):
        value = match.group()
        if DATE.fullmatch(value):
            return value
        digits = re.sub(r'\D', '', value)
        category = 'CARD_NUMBER' if len(digits) >= 13 else 'PHONE_OR_IDENTIFIER'
        categories.add(category)
        return f'[{category}_REDACTED]'
    result = LONG_NUMBER.sub(number, result)
    return ProtectedText(result, tuple(sorted(categories)), 'SECRET' in categories)


def sanitise(value):
    """Defence-in-depth for nested snapshots, summaries, evidence and exports."""
    if isinstance(value, str):
        return protect(value).text
    if isinstance(value, dict):
        return {key: ('[SECRET_REDACTED]' if str(key).lower() in {'api_key', 'password', 'otp', 'pin', 'cvv', 'access_token'} else sanitise(item)) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(sanitise(item) for item in value)
    if isinstance(value, list):
        return [sanitise(item) for item in value]
    return value


CUSTOMER_FIELDS = ('issue', 'card_id', 'elaborate', 'different_issue', 'expected_amount',
                   'cancel_type', 'cancel_date', 'cancel_method', 'refund_status', 'refund_date',
                   'refund_amount', 'refund_method', 'satisfaction', 'follow_up_updates')


def customer_export(state, concern_id, events):
    """Explicit customer-facing allowlist: excludes raw tool payloads and traces."""
    return sanitise({
        'concern_id': concern_id,
        'reported_details_unverified': {k: state['answers'][k] for k in CUSTOMER_FIELDS if k in state['answers']},
        'confirmed_search_details': state.get('search_confirmation'),
        'routing': {k: state['decision'].get(k) for k in ('route','reason','explanation','policy_conclusion','decision_type','policy_reason_code','policy_context')} if state.get('decision') else None,
        'review_requirement': state.get('review_requirement'), 'review_reason_codes': state.get('review_reason_codes'),
        'handoff_status': state.get('handoff_status'),
        'simulated_case': {k: state.get('case_command', {}).get(k) for k in ('case_id', 'status', 'reason_code')},
        'activity_checks': {'status': state.get('unusual_activity', {}).get('status'),
                            'rules_version': state.get('unusual_activity', {}).get('rules_version'),
                            'reason_codes': [s['reason_code'] for s in state.get('unusual_activity', {}).get('signals', [])]},
        'clustering': {k: state.get('clustering', {}).get(k) for k in ('status','version','mode','anomaly_score','reason_code')},
        'policy_information': {k: state.get('policy_qa', {}).get(k) for k in ('status','as_of','sources','clauses','policy_conclusion','reason_code')},
        'conversation': [{'role': role, 'text': text} for role, text in state['messages']],
        'customer_updates': [{k: e[k] for k in ('recorded_at','question_key','customer_statement')} for e in events],
        'notice': 'Sanitised demo concern history; no real bank dispute or callback was submitted.'})
