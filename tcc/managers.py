from django.db import models
from tcc.utils import get_content_types
from tcc import settings
from django.db.models.sql import compiler

quote = lambda s: '"%s"' % s


class ThreadedCommentsQueryCompiler(compiler.SQLCompiler):
    '''
    Query compiler which automatically joins in the subcomments for a given
    comment.

    We need this because the only kind of `LEFT OUTER JOIN` Django supports is
    in this form:
    LEFT OUTER JOIN table
        ON other_table.column = table.column

    Advanced join clauses which use more than 1 column in the join are not
    supported.
    i.e. this is not possible:
    LEFT OUTER JOIN table
        ON other_table.column = table.column
        AND other_table.other_column = table.other_column
    '''
    @classmethod
    def _get_table_alias(cls, i):
        '''Returns the table alias
        
        >>> ThreadedCommentsQueryCompiler._get_table_alias(0)
        'sub_0'
        '''
        return 'sub_%d' % i

    @classmethod
    def _get_column_alias(cls, table, column):
        '''Returns the column alias for the given table/colum.
        
        >>> ThreadedCommentsQueryCompiler._get_column_alias('sub_0', 'test')
        'sub_0_test'
        '''
        return '%s_%s' % (table, column)

    def get_from_clause(self):
        '''Get the patched from clause which includes the subcomments'''
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


# Django doesn't support manual compilers so we add this to the compiler
# manually
compiler.ThreadedCommentsQueryCompiler = ThreadedCommentsQueryCompiler


class ThreadedCommentsQuery(models.sql.Query):
    '''Override the default query to use our compiler'''
    compiler = 'ThreadedCommentsQueryCompiler'


class ThreadedCommentsQuerySet(models.query.QuerySet):

    def _setup_query(self):
        self.query = self.query.clone(ThreadedCommentsQuery)

    def iterator(self):
        '''Execute the queryset and return the model instances

        This automatically moves the subcomments to the `subcomments`
        attribute of a comment
        '''
        for object_ in super(ThreadedCommentsQuerySet, self).iterator():
            object_.subcomments = []

            for i in range(settings.REPLY_LIMIT):
                alias = ThreadedCommentsQueryCompiler._get_table_alias(i)

                columns = {}
                for field in self.query.model._meta.fields:
                    column_alias = ThreadedCommentsQueryCompiler \
                        ._get_column_alias(alias, field.column)

                    columns[field.column] = getattr(object_, column_alias)
                    delattr(object_, column_alias)

                subcomment = self.model(**columns)
                if subcomment.pk:
                    subcomment.subcomments = []
                    object_.subcomments.insert(0, subcomment)

            yield object_

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

        return qs.extra(select=select).filter(parent__isnull=True)

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
        qs = super(CurrentCommentManager, self).get_query_set(*args, **kwargs)
        return qs.filter(
            is_removed=False,
            is_approved=True,
            is_public=True,
            content_type__id__in=get_content_types(),
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

