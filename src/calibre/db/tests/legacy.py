#!/usr/bin/env python
# vim:fileencoding=utf-8
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__ = 'GPL v3'
__copyright__ = '2013, Kovid Goyal <kovid at kovidgoyal.net>'

import inspect
from repr import repr
from functools import partial
from tempfile import NamedTemporaryFile

from calibre.db.tests.base import BaseTest

class ET(object):

    def __init__(self, func_name, args, kwargs={}, old=None, legacy=None):
        self.func_name = func_name
        self.args, self.kwargs = args, kwargs
        self.old, self.legacy = old, legacy

    def __call__(self, test):
        old = self.old or test.init_old(test.cloned_library)
        legacy = self.legacy or test.init_legacy(test.cloned_library)
        oldres = getattr(old, self.func_name)(*self.args, **self.kwargs)
        newres = getattr(legacy, self.func_name)(*self.args, **self.kwargs)
        test.assertEqual(oldres, newres, 'Equivalence test for %s with args: %s and kwargs: %s failed' % (
            self.func_name, repr(self.args), repr(self.kwargs)))
        self.retval = newres
        return newres

def compare_argspecs(old, new, attr):
    ok = len(old.args) == len(new.args) and len(old.defaults or ()) == len(new.defaults or ()) and old.args[-len(old.defaults or ()):] == new.args[-len(new.defaults or ()):]  # noqa
    if not ok:
        raise AssertionError('The argspec for %s does not match. %r != %r' % (attr, old, new))

class LegacyTest(BaseTest):

    ''' Test the emulation of the legacy interface. '''

    def test_library_wide_properties(self):  # {{{
        'Test library wide properties'
        def get_props(db):
            props = ('user_version', 'is_second_db', 'library_id', 'field_metadata',
                    'custom_column_label_map', 'custom_column_num_map', 'library_path', 'dbpath')
            fprops = ('last_modified', )
            ans = {x:getattr(db, x) for x in props}
            ans.update({x:getattr(db, x)() for x in fprops})
            ans['all_ids'] = frozenset(db.all_ids())
            return ans

        old = self.init_old()
        oldvals = get_props(old)
        old.close()
        del old
        db = self.init_legacy()
        newvals = get_props(db)
        self.assertEqual(oldvals, newvals)
        db.close()
    # }}}

    def test_get_property(self):  # {{{
        'Test the get_property interface for reading data'
        def get_values(db):
            ans = {}
            for label, loc in db.FIELD_MAP.iteritems():
                if isinstance(label, int):
                    label = '#'+db.custom_column_num_map[label]['label']
                label = type('')(label)
                ans[label] = tuple(db.get_property(i, index_is_id=True, loc=loc)
                                   for i in db.all_ids())
                if label in ('id', 'title', '#tags'):
                    with self.assertRaises(IndexError):
                        db.get_property(9999, loc=loc)
                    with self.assertRaises(IndexError):
                        db.get_property(9999, index_is_id=True, loc=loc)
                if label in {'tags', 'formats'}:
                    # Order is random in the old db for these
                    ans[label] = tuple(set(x.split(',')) if x else x for x in ans[label])
                if label == 'series_sort':
                    # The old db code did not take book language into account
                    # when generating series_sort values (the first book has
                    # lang=deu)
                    ans[label] = ans[label][1:]
            return ans

        old = self.init_old()
        old_vals = get_values(old)
        old.close()
        old = None
        db = self.init_legacy()
        new_vals = get_values(db)
        db.close()
        self.assertEqual(old_vals, new_vals)

    # }}}

    def test_refresh(self):  # {{{
        ' Test refreshing the view after a change to metadata.db '
        db = self.init_legacy()
        db2 = self.init_legacy()
        self.assertEqual(db2.data.cache.set_field('title', {1:'xxx'}), set([1]))
        db2.close()
        del db2
        self.assertNotEqual(db.title(1, index_is_id=True), 'xxx')
        db.check_if_modified()
        self.assertEqual(db.title(1, index_is_id=True), 'xxx')
    # }}}

    def test_legacy_getters(self):  # {{{
        ' Test various functions to get individual bits of metadata '
        old = self.init_old()
        getters = ('path', 'abspath', 'title', 'authors', 'series',
                   'publisher', 'author_sort', 'authors', 'comments',
                   'comment', 'publisher', 'rating', 'series_index', 'tags',
                   'timestamp', 'uuid', 'pubdate', 'ondevice',
                   'metadata_last_modified', 'languages')
        oldvals = {g:tuple(getattr(old, g)(x) for x in xrange(3)) + tuple(getattr(old, g)(x, True) for x in (1,2,3)) for g in getters}
        old_rows = {tuple(r)[:5] for r in old}
        old.close()
        db = self.init_legacy()
        newvals = {g:tuple(getattr(db, g)(x) for x in xrange(3)) + tuple(getattr(db, g)(x, True) for x in (1,2,3)) for g in getters}
        new_rows = {tuple(r)[:5] for r in db}
        for x in (oldvals, newvals):
            x['tags'] = tuple(set(y.split(',')) if y else y for y in x['tags'])
        self.assertEqual(oldvals, newvals)
        self.assertEqual(old_rows, new_rows)

    # }}}

    def test_legacy_direct(self):  # {{{
        'Test methods that are directly equivalent in the old and new interface'
        from calibre.ebooks.metadata.book.base import Metadata
        ndb = self.init_legacy()
        db = self.init_old()
        for meth, args in {
            'get_next_series_num_for': [('A Series One',)],
            'author_sort_from_authors': [(['Author One', 'Author Two', 'Unknown'],)],
            'has_book':[(Metadata('title one'),), (Metadata('xxxx1111'),)],
        }.iteritems():
            for a in args:
                self.assertEqual(getattr(db, meth)(*a), getattr(ndb, meth)(*a),
                                 'The method: %s() returned different results for argument %s' % (meth, a))
        db.close()
        # }}}

    def test_legacy_adding_books(self):  # {{{
        'Test various adding books methods'
        from calibre.ebooks.metadata.book.base import Metadata
        legacy, old = self.init_legacy(self.cloned_library), self.init_old(self.cloned_library)
        mi = Metadata('Added Book0', authors=('Added Author',))
        with NamedTemporaryFile(suffix='.aff') as f:
            f.write(b'xxx')
            f.flush()
            T = partial(ET, 'add_books', ([f.name], ['AFF'], [mi]), old=old, legacy=legacy)
            T()(self)
            book_id = T(kwargs={'return_ids':True})(self)[1][0]
            self.assertEqual(legacy.new_api.formats(book_id), ('AFF',))
            T(kwargs={'add_duplicates':False})(self)
            mi.title = 'Added Book1'
            mi.uuid = 'uuu'
            T = partial(ET, 'import_book', (mi,[f.name]), old=old, legacy=legacy)
            book_id = T()(self)
            self.assertNotEqual(legacy.uuid(book_id, index_is_id=True), old.uuid(book_id, index_is_id=True))
            book_id = T(kwargs={'preserve_uuid':True})(self)
            self.assertEqual(legacy.uuid(book_id, index_is_id=True), old.uuid(book_id, index_is_id=True))
            self.assertEqual(legacy.new_api.formats(book_id), ('AFF',))
        with NamedTemporaryFile(suffix='.opf') as f:
            f.write(b'zzzz')
            f.flush()
            T = partial(ET, 'import_book', (mi,[f.name]), old=old, legacy=legacy)
            book_id = T()(self)
            self.assertFalse(legacy.new_api.formats(book_id))

        mi.title = 'Added Book2'
        T = partial(ET, 'create_book_entry', (mi,), old=old, legacy=legacy)
        T()
        T({'add_duplicates':False})
        T({'force_id':1000})
    # }}}

    def test_legacy_coverage(self):  # {{{
        ' Check that the emulation of the legacy interface is (almost) total '
        cl = self.cloned_library
        db = self.init_old(cl)
        ndb = self.init_legacy()

        SKIP_ATTRS = {
            'TCat_Tag', '_add_newbook_tag', '_clean_identifier', '_library_id_', '_set_authors',
            '_set_title', '_set_custom', '_update_author_in_cache',
        }
        SKIP_ARGSPEC = {
            '__init__', 'get_next_series_num_for', 'has_book', 'author_sort_from_authors',
        }

        missing = []

        try:
            total = 0
            for attr in dir(db):
                if attr in SKIP_ATTRS:
                    continue
                total += 1
                if not hasattr(ndb, attr):
                    missing.append(attr)
                    continue
                obj, nobj  = getattr(db, attr), getattr(ndb, attr)
                if attr not in SKIP_ARGSPEC:
                    try:
                        argspec = inspect.getargspec(obj)
                    except TypeError:
                        pass
                    else:
                        compare_argspecs(argspec, inspect.getargspec(nobj), attr)
        finally:
            for db in (ndb, db):
                db.close()
                db.break_cycles()

        if missing:
            pc = len(missing)/total
            raise AssertionError('{0:.1%} of API ({2} attrs) are missing. For example: {1}'.format(pc, missing[0], len(missing)))

    # }}}

