from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes import generic
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse, get_callable
from django.db import models
from django.template.defaultfilters import striptags
from django.utils.http import int_to_base36
from django.utils.translation import ugettext_lazy as _

from tcc import managers
from tcc import signals
from tcc import utils
from tcc import settings as tcc_settings
from django.utils.safestring import mark_safe

SITE_ID = getattr(settings, 'SITE_ID', 1)

TWO_MINS = timedelta(minutes=2)


class Subscription(models.Model):
    user = models.ForeignKey(User)
    comment = models.ForeignKey('Comment')
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    @property
    def read(self):
        return bool(self.read_at)

    @property
    def unread(self):
        return not self.read

    class Meta:
        unique_together = (
            ('user', 'comment'),
        )


class Comment(models.Model):

    ''' A comment table, aimed to be compatible with django.contrib.comments

    '''

  # constants

    MAX_REPLIES = tcc_settings.MAX_REPLIES
    REPLY_LIMIT = tcc_settings.REPLY_LIMIT

  # From comments BaseCommentAbstractModel
    content_type = models.ForeignKey(ContentType,
        verbose_name=_('content type'),
        related_name='content_type_set_for_tcc_comment',
        limit_choices_to=utils.get_content_types_q(),
    )
    object_pk = models.IntegerField(_('object id'))
    content_object = generic.GenericForeignKey(ct_field='content_type',
        fk_field='object_pk')

  # The actual comment fields
    parent = models.ForeignKey('self', verbose_name=_('Reply to'), null=True,
        blank=True, related_name='children')
    user = models.ForeignKey(User, verbose_name='Commenter')

  # These are here mainly for backwards compatibility
    ip_address = models.IPAddressField()
    user_name = models.CharField(_('user\'s name'), max_length=50, blank=True)
    user_email = models.EmailField(_('user\'s email address'), blank=True)
    user_url = models.URLField(_('user\'s URL'), blank=True)
    submit_date = models.DateTimeField(_('Date'), db_index=True,
        default=datetime.now)

  # Protip: Use postgres...
    comment = models.TextField(_('Comment'),
        max_length=tcc_settings.COMMENT_MAX_LENGTH)
    comment_raw = models.TextField(_('Raw Comment'),
        max_length=tcc_settings.COMMENT_MAX_LENGTH)

  # still accepting replies?
    is_open = models.BooleanField(_('Open'), default=True)
    is_removed = models.BooleanField(_('Removed'), default=False)
    is_approved = models.BooleanField(_('Approved'),

        default=not tcc_settings.MODERATED)

  # is_public is rather pointless icw is_removed?
  # Keeping it for compatibility w/ contrib.comments
    is_public = models.BooleanField(_('Public'), default=True)
    is_spam = models.BooleanField(_('Spam'), default=False)
    spam_report_count = models.IntegerField(_('Spam reports'), default=0)

  # subscription (for notification)
    unsubscribers = models.ManyToManyField(User,
        related_name='thread_unsubscribers')
    subscribers = models.ManyToManyField(
        User,
        through=Subscription,
        related_name='comment_subscriptions',
    )

  # denormalized cache
    child_count = models.IntegerField(_('Reply count'), default=0)
    sort_date = models.DateTimeField(_('Sortdate'), db_index=True,

        default=datetime.now)
    index = models.IntegerField(default=0)

    unfiltered = managers.CommentManager()
    objects = managers.CurrentCommentManager()
    limited = managers.LimitedCurrentCommentManager()
    removed = managers.RemovedCommentManager()
    disapproved = managers.DisapprovedCommentManager()

    class Meta:
        ordering = ['sort_date']
        unique_together = (
            ('content_type', 'object_pk', 'parent', 'index'),
        )

    def get_subscribers(self):
  # get all related comments
        comments = self.get_comments_in_thread()
  # get at most `MAX_REPLIES` and the parent thread
        comments = comments[:tcc_settings.MAX_REPLIES+1]
  # append the user ids to the list of user_ids
        return comments.values_list('user_id', flat=True)

    def get_parsed_comment(self, reparse=settings.DEBUG):
        if reparse:
            signals.comment_will_be_posted.send(
                sender = self.__class__, comment = self)
        parsed_comment = self.comment
        safe_comment = mark_safe(parsed_comment)
        return safe_comment

    def __repr__(self):
        return (u'<%s[%d]: at %s by %s: %r>' % (
            self.__class__.__name__,
            self.id,
            self.submit_date,
            self.user_name,
            self.comment_raw[:50],
        )).encode('utf-8', 'replace')

    def __unicode__(self):
        return u"%05d %s % 8s: %s" % (
            self.id, self.submit_date.isoformat(), self.user_name, self.comment[:20])

    @models.permalink
    def get_absolute_url(self):
        return ('content_type_redirect', (), {
            'content_type_id': self.content_type_id,
            'object_pk': self.object_pk,
        })

    def clean(self):
        if self.parent:
            if not self.pk and self.parent.child_count >= self.MAX_REPLIES:
                raise ValidationError(_('Maximum number of replies reached'))

        comment = self.comment_raw or self.comment
        if striptags(comment).strip() == '':
            raise ValidationError(_("This field is required."))

  # Check for identical messages
        identical_msgs = Comment.objects.filter(
            user=self.user,
            comment_raw=self.comment,
            submit_date__gte=(datetime.now() - TWO_MINS),
        )

        if self.id:
            identical_msgs = identical_msgs.exclude(id=self.id)

        if identical_msgs.count() > 0:
            raise ValidationError(_("You just posted the exact same content."))

    def get_thread(self):
        """ returns the entire 'thread' (a 'root' comment and all replies)

        a root comment is a comment without a parent
        """
        return Comment.objects.filter(parent=self)

    def get_replies(self, levels=None, include_self=False):
        if self.parent_id and self.parent.depth == tcc_settings.MAX_DEPTH - 1:
            return Comment.objects.none()
        else:
            replies = Comment.objects.filter(parent=self)
            if levels:
  # 'z' is the highest value in base36 (as implemented in django)
                replies = replies.filter(index__gte=self.child_count-tcc_settings.REPLY_LIMIT)

            if not include_self:
                replies = replies.exclude(id=self.id)
            return replies

    def get_root(self):
        if self.parent:
            return self.parent
        else:
            return self

    def get_related_comments(self):
        return Comment.unfiltered.filter(
            object_pk=self.object_pk,
            content_type=self.content_type_id,
        )

    def get_comments_in_thread(self):
        qs = self.get_related_comments()
        if self.parent_id:
            return (qs.filter(id=self.parent_id)
                | qs.filter(parent=self.parent_id))
        else:
            return qs.filter(id=self.id)

    def save(self, simple=False, *args, **kwargs):
        '''save the comment and add the index, update the parent child count

        simple -- only save, don't do any magic
        '''
        if simple:
            super(Comment, self).save(*args, **kwargs)

        if self.id:
            is_new = False
        else:
            is_new = True

  # Make sure we always have a raw comment available
            if self.comment_raw is None or self.comment_raw == '':
                self.comment_raw = self.comment

            responses = signals.comment_will_be_posted.send(
                sender = self.__class__, comment = self)

  # only save the comment if none of the signals return False
            for (receiver, response) in responses:
                if response == False:
                    raise ValidationError(
                        'Comment blocked by `comment_will_be_posted` listener.')

        self.clean()

  # Find the comment index to use
        if is_new:
            comments = self.get_related_comments()

            if self.parent_id:
                parents = comments.filter(id=self.parent_id)
                parents.update(
                    child_count=models.F('child_count') + 1,
                    sort_date=self.submit_date,
                )
                self.index = parents.values_list('child_count', flat=True)[0]

            else:
                comments = comments.order_by('-index')
                indices = list(comments.values_list('index', flat=True)[:1])
                if indices:
                    self.index = indices[0] + 1
                else:
                    self.index = 1

        super(Comment, self).save(*args, **kwargs)

  # We should have an ID by now
        assert self.id

        if is_new:
  # Sending this signal so *it* can be handled rather than
  # post_save which is triggered 'too soon': before
  # self.path is saved.  If there is an exception in a
  # post_save handler the path is never set and the database
  # will refuse to save another comment which is quite bad
  # for a commenting system.
            responses = signals.comment_was_posted.send(
                sender  = self.__class__, comment = self)

    def delete(self, *args, **kwargs):
        self.get_replies(include_self=True).delete()

        super(Comment, self).delete(*args, **kwargs)

        if self.parent_id:
            comments = self.get_related_comments()

            comments.filter(id=self.parent_id).update(
                child_count=models.F('child_count') - 1,
            )

            comments.filter(
                parent=self.parent_id,
                index__gt=self.index,
            ).update(
                index=models.F('index') - 1,
            )

    def _set_limit(self):
        replies = self.get_replies(levels=1).order_by('-submit_date')
        n = replies.count()
        self.child_count = n
        if n == 0:
            self.limit = None
        elif n < tcc_settings.REPLY_LIMIT:
            self.limit = replies[n-1].submit_date
        else:
            self.limit = replies[tcc_settings.REPLY_LIMIT-1].submit_date
        self.save()

    def get_depth(self):
        if self.parent_id:
            return 1
        else:
            return 0

    depth = property(get_depth)

    def reply_allowed(self):
        return self.is_open and self.child_count < self.MAX_REPLIES \
            and (self.depth < tcc_settings.MAX_DEPTH - 1 )

    def can_open(self, user):
        return self.user == user

    def can_close(self, user):
        return self.user == user

    def can_approve(self, user):
        return self.user == user

    def can_disapprove(self, user):
        return self.user == user

    def can_report_spam(self, user):
        # we might want to limit this later, but for now every user can
        # report spam
        return user.is_authenticated()

    def can_remove_spam(self, user):
        return self.can_remove(user)

    def can_remove(self, user):
        return (
            self.user == user
            or (
                self.content_type_id == utils.get_content_type_id('auth.user')
                and self.object_pk == user.id
            )
            or (
                self.content_type_id == utils.get_content_type_id('lists.userlist')
                and self.content_object.user_id == user.id
            )
            or user.has_perm('delete', self)
        )
  # Why always fetch all users if you only need to know if a single
  # user has remove rights?
  # >>> user in self.get_enabled_users('remove')

    def can_restore(self, user):
        return self.user == user

    def get_base36(self):
        return int_to_base36(self.id)

    def get_enabled_users(self, action):
        if not callable(tcc_settings.ADMIN_CALLBACK):
            return []
        assert action in ['open', 'close', 'remove', 'restore',
                          'approve', 'disapprove']
        func = get_callable(tcc_settings.ADMIN_CALLBACK)
        return func(self, action)

class SpamReport(models.Model):
    comment = models.ForeignKey(Comment)
    user = models.ForeignKey(User)

    class Meta:
        unique_together = ['user', 'comment']

