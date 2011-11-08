from django.contrib.contenttypes.models import ContentType
from django.db import models
from tcc.settings import CONTENT_TYPES
import operator

_CONTENT_TYPES = None

def get_content_types():
    global _CONTENT_TYPES
    if not _CONTENT_TYPES:
        _CONTENT_TYPES = []
        for label in CONTENT_TYPES:
            ct = ContentType.objects.get_by_natural_key(*label.split("."))
            _CONTENT_TYPES.append(ct.id)
    return _CONTENT_TYPES

def get_content_types_q():
    qs = []
    for label in CONTENT_TYPES:
        app_label, model = label.split('.')
        qs.append(models.Q(app_label=app_label, model=model))

    # simply does (a | b | c) for qs=[a, b, c]
    return reduce(operator.or_, qs[1:], qs[0])

