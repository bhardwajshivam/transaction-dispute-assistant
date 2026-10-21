"""Portable report metadata: preserve evidence, omit machine identity and paths."""
import re

# Recognise common machine-local roots without treating URLs or relative source
# paths as filesystem metadata. This is report minimisation, not a PII detector.
LOCAL_PATH = re.compile(
    r"(?:/(?:Users|home)/[^/\s\"'<>\\]+|/(?:private/)?tmp|/(?:private/)?var/folders|/opt/homebrew|/usr/local)"
    r"(?:/[^\s\"'<>\\]*)?"
    r"|[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s\"'<>]+"
)
DETAIL_FIELDS = ('format','family','families','parameter_size','quantization_level','context_length','embedding_length')


def portable(value):
    if isinstance(value,str):return LOCAL_PATH.sub('[LOCAL_PATH_REDACTED]',value)
    if isinstance(value,dict):return {k:portable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [portable(v) for v in value]
    return value


def model_metadata(model):
    """Never copy unrestricted server model details such as parent_model paths."""
    details=model.get('details')
    details=details if isinstance(details,dict) else {}
    return portable({'name':model.get('name'),'digest':model.get('digest'),
                     'details':{k:details[k] for k in DETAIL_FIELDS if k in details}})
