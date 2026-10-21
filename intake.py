"""Required search details, deterministic normalisation and confirmation gate."""
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
import re

SNAPSHOT = date(2026, 10, 20)
CURRENCIES = {'GBP', 'EUR', 'USD', 'INR', 'CAD', 'AUD', 'CHF', 'SGD', 'AED'}
SYMBOLS = {'£': 'GBP', '€': 'EUR', '₹': 'INR'}  # $ is intentionally ambiguous.
DATE_FIELDS = {'transaction_date', 'date_end', 'original_date', 'cancellation_date', 'refund_date'}
AMOUNT_FIELDS = {'charged_amount', 'expected_amount', 'original_amount', 'refund_amount'}
FIELDS = sorted(DATE_FIELDS | AMOUNT_FIELDS | {'charged_currency', 'expected_currency', 'original_currency', 'refund_currency', 'merchant', 'transaction_reference'})
LABELS = {
    'transaction_date': 'Payment date', 'date_end': 'End of payment date range',
    'original_date': 'Original purchase date', 'charged_amount': 'Amount actually charged',
    'charged_currency': 'Currency actually charged', 'expected_amount': 'Amount expected',
    'expected_currency': 'Currency expected', 'merchant': 'Merchant or statement descriptor',
    'original_amount': 'Original purchase amount', 'original_currency': 'Original purchase currency',
    'refund_amount': 'Expected refund amount', 'refund_currency': 'Expected refund currency',
    'refund_date': 'Reported refund date', 'cancellation_date': 'Cancellation date',
    'transaction_reference': 'Transaction reference',
}


def normalise(field, text):
    text = text.strip()
    if field in DATE_FIELDS:
        for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%d %B %Y', '%d %b %Y'):
            try:
                value = datetime.strptime(text, fmt).date()
                if value > SNAPSHOT:
                    raise ValueError('Future date relative to demo snapshot')
                return value.isoformat()
            except ValueError:
                continue
        raise ValueError('Enter a valid date as DD-MM-YYYY, on or before 20-10-2026.')
    if field in AMOUNT_FIELDS:
        raw = re.sub(r'\b(?:' + '|'.join(sorted(CURRENCIES)) + r')\b', '', text, flags=re.I)
        raw = re.sub(r'[£€₹$]', '', raw).strip()
        if not re.fullmatch(r'\d{1,9}(?:\.\d{1,2})?', raw):
            raise ValueError('Enter a positive amount with at most two decimal places, for example 10.00.')
        amount = Decimal(raw)
        if amount <= 0:
            raise ValueError('Amount must be positive.')
        return format(amount, '.2f')
    if field.endswith('_currency'):
        value = SYMBOLS.get(text, text.upper())
        if value not in CURRENCIES:
            raise ValueError('Please enter a supported currency code, such as INR, GBP, EUR or USD. A $ symbol alone is ambiguous.')
        return value
    if field == 'transaction_reference':
        if not re.fullmatch(r'TX-\d{4,12}', text.upper()):
            raise ValueError('Please enter the exact TX reference.')
        return text.upper()
    if field == 'merchant':
        if not 2 <= len(text) <= 100:
            raise ValueError('Please provide a merchant name or descriptor between 2 and 100 characters.')
        return text
    raise ValueError('Unknown field')


def currency_in(text):
    found = {code for symbol, code in SYMBOLS.items() if symbol in text}
    found.update(re.findall(r'\b(?:' + '|'.join(sorted(CURRENCIES)) + r')\b', text.upper()))
    return next(iter(found)) if len(found) == 1 else None


def set_field(state, field, raw, source='customer_answer'):
    value = normalise(field, raw)
    fields = state.setdefault('intake', {})
    fields[field] = value
    state.setdefault('intake_assertions', []).append({'field': field, 'value': value, 'source_text': raw, 'source': source, 'verified': False})
    if field in AMOUNT_FIELDS:
        currency = currency_in(raw)
        if currency:
            key = field.replace('_amount', '_currency')
            fields[key] = currency
    state['search_confirmed'] = False


def missing_field(state):
    f = state.get('intake', {})
    if f.get('transaction_reference'):
        return None
    kind = state.get('issue_kind')
    date_key = 'original_date' if kind == 'refund' else 'transaction_date'
    if not f.get(date_key):
        return date_key
    if f.get('date_end') and f['date_end'] < f[date_key]:
        return 'date_end'
    if kind == 'wrong_amount':
        if not f.get('charged_amount'): return 'charged_amount'
    else:
        amount = 'original_amount' if kind == 'refund' else 'charged_amount'
        if not f.get(amount):
            return 'identifier'
    return None


def search_question(state):
    field = state['pending_search_field']
    if field == 'identifier':
        return 'What amount was charged? Include the currency if known, for example INR 42. You can also enter the exact TX reference. For refunds, use the original purchase amount, not the refund amount. Merchant names are not used to search.'
    if field in DATE_FIELDS:
        return f"What is the {LABELS[field].lower()}? Please use DD-MM-YYYY. You may provide a range as DD-MM-YYYY to DD-MM-YYYY, or enter the exact TX reference if available."
    if field.endswith('_currency'):
        return f"What was the {LABELS[field].lower()}? Please enter the currency code, for example INR."
    return f"What was the {LABELS[field].lower()}? Include the currency if known, for example INR 10.00."


def confirmation_text(state):
    parts = [f"Selected card: {state['answers']['card_id']}"]
    for field in sorted(state.get('intake', {})):
        if field == 'merchant':
            continue
        value = state['intake'][field]
        if field in DATE_FIELDS:
            value = date.fromisoformat(value).strftime('%d-%m-%Y')
        parts.append(f'{LABELS[field]}: {value}')
    if state.get('intake', {}).get('transaction_reference'):
        parts.append('Search uses the exact reference; other reported details will be compared after selection.')
    else:
        currency = 'original_currency' if state.get('issue_kind') == 'refund' else 'charged_currency'
        if not state.get('intake', {}).get(currency):
            parts.append('Currency: not provided. Search will match the amount across currencies; each result will show its recorded currency. No currency or FX conversion is assumed.')
    return 'Please confirm these details before I search your card transactions:\n\n' + '\n\n'.join(parts) + '\n\nThese are your reported details, not yet verified bank facts.'


def advance(state):
    missing = missing_field(state)
    state['search_confirmed'] = False
    if missing:
        state['step'] = 'search_details'
        state['pending_search_field'] = missing
        state['messages'].append(('assistant', search_question(state)))
    else:
        state['step'] = 'search_confirm'
        state.pop('pending_search_field', None)
        state['messages'].append(('assistant', confirmation_text(state)))


def collect(state, text):
    if state.get('pending_search_field') in ('charged_currency', 'original_currency') and text in ('I don’t know / need help', "I don't know", 'I don’t know'):
        # Resume older saved journeys that still asked for search currency.
        state.setdefault('intake', {}).pop(state['pending_search_field'], None)
        advance(state)
        return
    if text == 'I don’t know / need help':
        from review import offer_review
        offer_review(state)
        from conversation import prompt
        prompt(state)
        return
    field = state['pending_search_field']
    try:
        if re.fullmatch(r'TX-\d{4,12}', text.upper()):
            set_field(state, 'transaction_reference', text)
        elif field == 'identifier':
            amount = 'original_amount' if state['issue_kind'] == 'refund' else 'charged_amount'
            set_field(state, amount, text)
        elif field in DATE_FIELDS and ' to ' in text:
            start, end = text.split(' to ', 1)
            values = normalise(field, start), normalise('date_end', end)
            if values[1] < values[0]:
                raise ValueError('The end date must be on or after the start date.')
            set_field(state, field, start); set_field(state, 'date_end', end)
        else:
            set_field(state, field, text)
    except ValueError as exc:
        state['messages'].append(('assistant', str(exc)))
        return
    advance(state)
