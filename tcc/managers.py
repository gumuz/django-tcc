from django.db import models
from tcc.utils import get_content_types
from tcc import settings
from django.db.models.sql import compiler

quote = lambda s: '"%s"' % s


class ThreadedCommentsQueryCompiler(compiler.SQLCompiler):

    @classmethod
    def _get_table_alias(cls, i):
        return 'sub_%d' % i

    @classmethod
    def _get_column_alias(cls, table, column):
        return '%s_%s' % (table, column)

    def get_from_clause(self):
        from_, f_params = super(ThreadedCommentsQueryCompiler, self) \
            .get_from_clause()

        # Add the tables for the subcomments to the from clause
        for i in range(settings.REPLY_LIMIT):
            from_.append('''
            LEFT OUTER JOIN %(db_table)s %(alias)s
                ON %(alias)s.parent_id = %(db_table)s.id
                AND %(alias)s.index = %(db_table)s.child_count - %(i)d
            ''' % dict(
                i=i,
                alias=quote(self._get_table_alias(i)),
                db_table=from_[0],
            ))

        return from_, f_params


# Patch in our query compiler
compiler.ThreadedCommentsQueryCompiler = ThreadedCommentsQueryCompiler


class ThreadedCommentsQuery(models.sql.Query):
    compiler = 'ThreadedCommentsQueryCompiler'

    @classmethod
    def get_subcomment_table(cls, n):
        return 'sub_%d' % (n + 1)

    def get_columns(self, table, prefix=''):
        table = quote(table)


class ThreadedCommentsQuerySet(models.query.QuerySet):

    def _setup_query(self):
        self.query = self.query.clone(ThreadedCommentsQuery)


class CommentsQuerySet(models.query.QuerySet):

    def threaded(self):
        qs = self._clone(klass=ThreadedCommentsQuerySet, setup=True)
        select = {}
        for i in range(settings.REPLY_LIMIT):
            alias = ThreadedCommentsQueryCompiler._get_table_alias(i)

            for field in self.query.model._meta.fields:
                column_alias = ThreadedCommentsQueryCompiler \
                    ._get_column_alias(alias, field.column)

                select[column_alias] = '%s.%s' % (
                    quote(alias),
                    quote(field.column),
                )

        return qs.extra(select=select)

    def _clone(self, klass=None, setup=False, **kwargs):
        if klass is None:
            klass = CommentsQuerySet

        return super(CommentsQuerySet, self)._clone(klass=klass,
            setup=setup, **kwargs)


class CommentManager(models.Manager):

    def get_query_set(self):
        return CommentsQuerySet(self.model, using=self._db)

    def threaded(self):
        return self.get_query_set(self).threaded()


class CurrentCommentManager(CommentManager):
    """ Returns only approved comments that are not (marked as) removed

    Also filters is_public == False for backwards compatibility

    Also only returns comments whose CONTENT_TYPES are allowed
    """

    def get_query_set(self, *args, **kwargs):
        return (
            super(CurrentCommentManager, self).get_query_set(*args, **kwargs)
            .filter(
                is_removed=False,
                is_approved=True,
                is_public=True,
                content_type__id__in=get_content_types(),
                parent__is_approved=True,
                parent__is_public=True,
            )
        )


class LimitedCurrentCommentManager(CurrentCommentManager):

    def get_query_set(self, *args, **kwargs):
        return (super(LimitedCurrentCommentManager, self)
            .get_query_set(*args, **kwargs))


class RemovedCommentManager(models.Manager):
    """ Returns onle comments marked as removed

    To be able to unmark them...
    """

    def get_query_set(self, *args, **kwargs):
        return super(RemovedCommentManager, self).get_query_set(
            *args, **kwargs).filter(
            is_removed=True)


class DisapprovedCommentManager(models.Manager):
    """ Returns disapproved (unremoved) comments

    To be able to unmark them...
    """

    def get_query_set(self, *args, **kwargs):
        return super(DisapprovedCommentManager, self).get_query_set(
            *args, **kwargs).filter(
            is_removed=False, is_approved=False)

