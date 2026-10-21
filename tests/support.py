"""Explicit search confirmation for reference-based journey fixtures."""
from conversation import submit


def prepare_reference(state, reference):
    if state['step'] == 'search_details':
        submit(state, reference)
    if state['step'] == 'search_confirm':
        submit(state, 'Confirm and search')



def demo_staff():
    from access import StaffPrincipal
    from time import time
    return StaffPrincipal('staff-test', ('C-001', 'C-002'), time() + 900)
