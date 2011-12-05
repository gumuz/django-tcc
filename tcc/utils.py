from django.contrib.contenttypes.models import ContentType
from django.db import models
from tcc.settings import CONTENT_TYPES
import operator

_CONTENT_TYPES_MAP = None

def get_content_types_map():
    global _CONTENT_TYPES_MAP
    if not _CONTENT_TYPES_MAP:
        _CONTENT_TYPES_MAP = {}
        for label in CONTENT_TYPES:
            app, model = label.split('.')
            ct = ContentType.objects.get_by_natural_key(app, model)
            _CONTENT_TYPES_MAP[label] = ct.id
            if app not in _CONTENT_TYPES_MAP:
                _CONTENT_TYPES_MAP[app] = {}

            _CONTENT_TYPES_MAP[app][model] = ct.id
    return _CONTENT_TYPES_MAP

def get_content_type_id(label):
    return get_content_types_map().get(label)

def get_content_types():
    return [v for v in get_content_types_map().itervalues()
        if isinstance(v, (int, long))]

def get_content_types_q():
    qs = []
    for label in CONTENT_TYPES:
        app_label, model = label.split('.')
        qs.append(models.Q(app_label=app_label, model=model))

    # simply does (a | b | c) for qs=[a, b, c]
    return reduce(operator.or_, qs[1:], qs[0])

