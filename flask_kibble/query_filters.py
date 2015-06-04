from datetime import datetime, timedelta

import flask
from markupsafe import Markup
# from werkzeug.utils import cached_property

from google.appengine.ext import ndb


class BaseFilter(object):
    """
    Base filter class.

    :param str field: Field column to filter on. If filtering on
        :py:class:`google.appengine.ext.ndb.StructuredProperty`, nested models
        can be specified with ``.``.
    :param str title: Column title, if ``None`` will be created based on field
        name.
    :param type: Callable to coerce strings from URL to a type.
    """

    def __init__(self, field, title=None, type=unicode):
        self.field = field
        self.title = title or field.replace('_', ' ').title()
        self.type = type

    def preload(self):
        """
        Called when the view is first called. Used to pre-load any queries
        asynchronously.
        """

    def value_to_url(self, value):
        """
        Generate a url-safe value for the given pythonic value.

        This should perform the opposite as :py:member:`url_to_value`.

        :param value: Pythonic type for the given filter value.
        """
        return value

    def url_to_value(self, url_value):
        """
        Convert a url-safe value from the URL to a pythonic value.

        This should perform the opposite as :py:member:`value_to_url`.

        :param url_value: URLsafe representation of pythonic filter value.
        """
        return url_value

    def get(self, *args):
        """
        Retrieve the url-safe value from the URL.

        :param default: If the value is not present in the URL, this will be
            returned.
        """
        return self.url_to_value(flask.request.args.get(self.field, *args))

    def url_for_value(self, value):
        """
        Generate a URL for the given pythonc python value.

        :param value: Pythonic value to filter on.
        :returns: URL with filter parameters.
        """
        args = flask.request.view_args.copy()
        args.update(flask.request.args)
        args[self.field] = self.value_to_url(value)
        return flask.url_for(flask.request.endpoint, **args)

    def model_property(self, model):
        """
        Get the :py:class:`google.appengine.ext.ndb.Property` for the given
        ``model``.

        :param model: The :py:class:`google.appengine.ext.ndb.Model` to
            retrieve the property from.
        """
        path = self.field.split('.')
        prop = model
        while path:
            prop = getattr(prop, path.pop(0))
        return prop

    def filter(self, model, query):
        """
        Perform the filter on the query. If the value evaluates to false
        no filter be applied.

        :param model: The model class to filter.
        :param query: The query to apply the filter to.
        :rtype: :py:class:`google.appengine.ext.ndb.Query`
        :return: Query
        """
        val = self.get(None)
        if val:
            return query.filter(self.model_property(model) == val)
        return query

    def render(self):
        """
        Render the filter as HTML.
        """
        return ''


class ChoicesFilter(BaseFilter):
    """
    A filter for a pre-defined set of values to filter on.

    :param field: The field name to filter on
    :param chocies: A list of (value, Label) pairs.
    """
    def __init__(self, field, choices):
        super(ChoicesFilter, self).__init__(field)
        self._choices = choices

    @property
    def choices(self):
        return iter(self._choices)

    def _render_choice(self, value, label):
        return Markup("<li  class='{klass}'><a href='{url}'>{label}</a></li>")\
            .format(
                klass='active' if value == self.get() else '',
                url=self.url_for_value(value),
                label=label)

    def render(self):
        choices = [self._render_choice(None, 'All')] + [
            self._render_choice(*c) for c in self.choices
        ]
        return Markup("<ul class='{}'>{}</ul>")\
            .format(
                'list-unstyled',
                Markup("").join(choices))


class BoolFilter(ChoicesFilter):
    """
    A filter for boolean properties.
    """

    def __init__(self, field):
        BaseFilter.__init__(self, field)

    @property
    def choices(self):
        return iter([('t', 'True'), ('f', 'False')])

    def filter(self, model, query):
        val = {
            't': True,
            'f': False,
        }.get(self.get(None))

        if isinstance(val, bool):
            prop = getattr(model, self.field)
            return query.filter(prop == val)
        return query


class KeyFilter(ChoicesFilter):
    """
    A filter for :py:class:`google.appengine.ext.ndb.KeyPropery` properties.

    :param field: The field to filter on.
    :param query: A :py:class:`google.appengine.ext.ndb.Query` or
        :py:class:`google.appengine.ext.ndb.Model` to use as choices.
    """

    def __init__(self, field, query):
        BaseFilter.__init__(self, field)

        if isinstance(query, type) and issubclass(query, ndb.Model):
            query = query.query()

        self.query = query

    def preload(self):
        self._query = self.query.fetch_async()

    def value_to_url(self, key):
        if key:
            return key.urlsafe()

    def url_to_value(self, url_value):
        if url_value:
            return ndb.Key(urlsafe=url_value)

    @property
    def choices(self):
        for row in self._query.get_result():
            yield (row.key, unicode(row))


class DateTimeFilter(ChoicesFilter):
    def __init__(self, field, title=None, past=True, future=True,
                 present=True, none=False):

        super(ChoicesFilter, self).__init__(field, title=title)

        self.none = none
        self.past = past
        self.future = future
        self.present = present

    @property
    def choices(self):
        if self.none:
            yield ('none', 'None')

        if self.past:
            yield ('past_month', 'Past month')
            yield ('past_week', 'Past 7 days')

        if self.present:
            yield ('today', 'Today')

        if self.future:
            yield ('next_week', 'Next 7 days')
            yield ('next_month', 'Next month')

    def _filter_none(self, model, query):
        prop = self.model_property(model)
        return query.filter(prop == None)  # noqa

    def _filter_today(self, model, query):
        now = datetime.utcnow()
        start = now.replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=1)

        prop = self.model_property(model)
        return query.filter(
            prop > start,
            prop < end
        )

    def _filter_past_week(self, model, query):
        now = datetime.utcnow()
        end = now - timedelta(days=7)

        prop = self.model_property(model)
        return query.filter(
            prop < now,
            prop > end,
        )

    def _filter_past_month(self, model, query):
        now = datetime.utcnow()
        end = now - timedelta(days=28)

        prop = self.model_property(model)
        return query.filter(
            prop < now,
            prop > end
        )

    def _filter_next_week(self, model, query):
        now = datetime.utcnow()
        end = now - timedelta(days=7)

        prop = self.model_property(model)
        return query.filter(
            prop > now,
            prop < end,
        )

    def _filter_next_month(self, model, query):
        now = datetime.utcnow()
        end = now + timedelta(days=28)

        prop = self.model_property(model)
        return query.filter(
            prop > now,
            prop < end
        )

    def filter(self, model, query):
        val = self.get(None)
        if not val:
            return query

        filter_func = getattr(self, '_filter_'+val, None)
        if filter_func:
            query = filter_func(model, query)

        return query


class PolymodelFilter(ChoicesFilter):
    def __init__(self, base_class):
        self.base_class = base_class
        self.title = 'Class'
        self.field = 'class'

    @property
    def choices(self):
        base_key = tuple(self.base_class._class_key())
        base_len = len(base_key)

        class_map = self.base_class._class_map.keys()

        output = []

        for cls_key in sorted(class_map):
            if cls_key[:base_len] == base_key \
                    and cls_key != base_key:
                val = cls_key[-1]
                label = flask.g.kibble.label_for_kind(val)
                output.append((val, label))

        return sorted(output, key=lambda x: x[1])

    def filter(self, model, query):
        val = self.get(None)
        if not val:
            return query
        return query.filter(ndb.GenericProperty('class') == val)
