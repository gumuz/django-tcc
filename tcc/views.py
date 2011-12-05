from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.http import (HttpResponseBadRequest, HttpResponseRedirect,
                         HttpResponse, Http404, HttpResponsePermanentRedirect)
from django.template import RequestContext
from django.utils import simplejson
from django.views.decorators.http import require_POST

from tcc import api, forms

from framework.utils import orm, forms as form_utils

# jinja
from coffin.shortcuts import render_to_response
'''Monkeypatch Django to mimic Jinja2 behaviour'''
from django.utils import safestring
if not hasattr(safestring, '__html__'):
    safestring.SafeString.__html__ = lambda self: str(self)
    safestring.SafeUnicode.__html__ = lambda self: unicode(self)


def _get_tcc_index(comment):
    return reverse('tcc_index',
                   args=[comment.content_type_id, comment.object_pk])


def _get_comment_form(content_type_id, object_pk, data=None, initial=None):
    if not initial:
        initial = {}

    initial['content_type'] = content_type_id
    initial['object_pk'] = object_pk
    form = forms.CommentForm(data, initial=initial)
    return form


def index(request, content_type_id, object_pk):
    comments = api.get_comments_limited(
        content_type_id, object_pk).order_by('-sort_date', 'path')
    form = _get_comment_form(content_type_id, object_pk)
    context = RequestContext(request, {'comments': comments, 'form': form })
    return render_to_response('tcc/index.html', context)


def replies(request, parent_id):
    comments = api.get_comment_replies(parent_id).wrap(orm.id_to_user)
    context = RequestContext(request, {'comments': comments})
    return render_to_response('tcc/replies.html', context)


def thread(request, thread_id):
    # thead_id here should be the root_id of the thread (even though
    # any comment_id will work) so the entire thread can cached *and*
    # invalidated with one entry
    comments = api.get_comment_thread(thread_id)
    if not comments:
        raise Http404()
    else:
        comments = comments.order_by('-sort_date', 'path')
    rootcomment = comments[0]
    form = _get_comment_form(rootcomment.content_type_id, rootcomment.object_pk)
    context = RequestContext(request, {'comments': comments, 'form': form})
    return render_to_response('tcc/index.html', context)


@login_required
@require_POST
def post(request):
    data = request.POST.copy()
    # inject the user and IP
    data['user'] = request.user.id
    form = forms.CommentForm(data, ip=request.META['REMOTE_ADDR'])
    if form.is_valid():
        comment = form.save()
        if comment:
            if request.is_ajax():
                context = RequestContext(request, {'c': comment})
                return render_to_response('tcc/comment.html', context)
            next = form.cleaned_data['next']
            if not next:
                next = comment.get_absolute_url()
            return HttpResponseRedirect(next)
    if request.is_ajax():
        return HttpResponseBadRequest(
            form_utils.error_form_serialization(form.errors),
            mimetype='application/json',
        )
    else:
        return content_type_redirect(
            request,
            content_type_id=data.get('content_type_id'),
            object_pk=data.get('object_pk'),
        )

@login_required
@require_POST
def flag(request):
    return HttpResponse('TODO')


@login_required
@require_POST
def unflag(request):
    return HttpResponse('TODO')


@login_required
@require_POST
def approve(request, comment_id):
    comment = api.approve_comment(comment_id, request.user)
    if comment:
        return HttpResponseRedirect(comment.get_absolute_url())
    raise Http404()


@login_required
@require_POST
def disapprove(request, comment_id):
    comment = api.disapprove_comment(comment_id, request.user)
    if comment:
        tcc_index = _get_tcc_index(comment)
        return HttpResponseRedirect(tcc_index)
    raise Http404()


@login_required
@require_POST
def remove(request, comment_id):
    comment = api.remove_comment(comment_id, request.user)
    if comment:
        if request.is_ajax():
            return HttpResponse() # 200 OK
        tcc_index = _get_tcc_index(comment)
        return HttpResponseRedirect(tcc_index)
    raise Http404()


@login_required
@require_POST
def restore(request, comment_id):
    comment = api.restore_comment(comment_id, request.user)
    if comment:
        return HttpResponseRedirect(comment.get_absolute_url())
    raise Http404()


@login_required
@require_POST
def subscribe(request, comment_id):
    comment = api.subscribe(comment_id, request.user)
    if comment:
        if request.is_ajax():
            return HttpResponse() # 200 OK
        tcc_index = _get_tcc_index(comment)
        return HttpResponseRedirect(tcc_index)
    raise Http404()


@login_required
@require_POST
def unsubscribe(request, comment_id):
    comment = api.unsubscribe(comment_id, request.user)
    if comment:
        if request.is_ajax():
            return HttpResponse() # 200 OK
        tcc_index = _get_tcc_index(comment)
        return HttpResponseRedirect(tcc_index)
    raise Http404()

def content_type_redirect(request, content_type_id, object_pk):
    content_type = ContentType.objects.get_for_id(content_type_id)
    object = content_type.get_object_for_this_type(pk=object_pk)

    url_method = getattr(object, 'get_comment_url', object.get_absolute_url)
    return HttpResponsePermanentRedirect(url_method())

