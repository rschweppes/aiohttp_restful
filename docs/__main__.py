import ast
import inspect
import json
import os

import astor
from aiohttp.hdrs import METH_ALL

from configs.urls import urls
from utils.fields.base import Field
from utils.view import View


class RecTree:
    def __init__(self):
        self.errors = []
        self.status = 200

    def __parse_abort(self, node):
        status, n = node.value.args
        help_ = list(filter(lambda x: x.arg == 'help_text', node.value.keywords))
        message = astor.to_source(n)
        if type(n) is ast.Str:
            message = n.s

        error = {
            'status': status.n,
            'message': message
        }

        if any(help_):
            help_text = astor.to_source(help_[0].value)
            if type(help_[0].value) is ast.Str:
                help_text = help_[0].value.s

            error['help'] = help_text
        self.errors.append(error)

    def __parse_return(self, node):
        status = list(filter(lambda x: x.arg == 'status', node.value.keywords))
        if any(status):
            self.status = status[0].value.n

    def method(self, node):
        if isinstance(node, ast.Return):
            self.__parse_return(node)

        if hasattr(node, 'body'):
            for n in node.body:
                self.method(n)

        if hasattr(node, 'handlers'):
            for n in node.handlers:
                self.method(n)

        return self

    def abort(self, node):
        is_func = isinstance(node, ast.Expr) and hasattr(node.value, 'func')
        if is_func and node.value.func.__dict__.get('id', False) == 'abort':
            self.__parse_abort(node)

        if hasattr(node, 'body'):
            for n in node.body:
                self.abort(n)

        if hasattr(node, 'handlers'):
            for n in node.handlers:
                self.abort(n)

        return self


def get_errors_meta(cls, method):
    meta = dict(filter(lambda x: issubclass(x[1].__class__, Field), getattr(cls, 'Meta').__dict__.items()))
    errors = {}
    for key, object_ in meta.items():
        if method.upper() not in object_.methods:
            continue

        fields = object_.__class__.mro()[:-3]
        errors[key] = []
        for field in fields:
            tree = ast.parse(inspect.getsource(field.set_value).strip())
            errors[key] += RecTree().abort(tree).errors
    return errors


def get_errors_method(method):
    tree = ast.parse(inspect.getsource(method).strip())
    return RecTree().abort(tree).errors


def get_success_method(method):
    tree = ast.parse(inspect.getsource(method).strip())
    try:
        json_doc = json.loads(method.__doc__)
    except TypeError:
        json_doc = None

    success = {
        'status': RecTree().method(tree).status,
        'example': json.dumps(json_doc, sort_keys=True, indent=(4 * ' '))
    }

    return success


def get_method_data(cls, methods):
    errors = {}
    success = {}
    for method in methods:
        error = {
            'fields': get_errors_meta(cls, method),
            'method': get_errors_method(getattr(cls, method.lower()))
        }
        errors[method] = error
        success[method] = get_success_method(getattr(cls, method.lower()))

    return errors, success


def create_folder_get_filename(url):
    folder = url.split('/')
    file_name = folder.pop()
    folder = os.path.join(os.path.dirname(__file__), 'md', *folder)

    if not os.path.isdir(folder):
        os.makedirs(folder)

    file_name = os.path.join(folder, '%s.md' % file_name.replace('{', '__').replace('}', '__'))
    return file_name


def get_markdown(errors, success, url, methods, doc):
    text = "# %s" % doc

    text += "\n* [main](docs/main.md)\n* [menu methods](docs/menu.md)"

    for method in methods:
        text += "\n## %s" % method
        text += "\n```\n%s %s\n```" % (method, url)
        m_success = success[method]
        m_errors = errors[method]
        text += '\n### success'
        text += '\n#### example\n```json\nhead status: %s\n%s\n```' % (m_success['status'], m_success['example'])
        text += '\n### errors\n#### fields'
        for field, error in m_errors['fields'].items():
            json_text = ''
            for e in error:
                json_text += '\nhead status: %s' % e['status']
                del e['status']
                json_text += '\n%s' % json.dumps(e, sort_keys=True, indent=(4 * ' '))

            if json_text:
                text += '\n##### %s \n```json\n%s\n```' % (field, json_text)

        json_text = ''
        for e in m_errors['method']:
            json_text += '\nhead status: %s' % e['status']
            del e['status']
            json_text += '\n%s' % json.dumps(e, sort_keys=True, indent=(4 * ' '))
        if json_text:
            text += '\n#### method\n```json\n%s\n```' % json_text

    return text


def _get_doc(cls):
    doc = cls.__name__
    if cls.__doc__:
        doc = "%s (%s)" % (cls.__doc__, cls.__name__)
    return doc


def get_markdown_menu(urls_filter):
    text = '# Menu'
    for url in urls_filter:
        __, url, cls = url
        doc = _get_doc(cls)
        url = '%s.md' % url.replace('{', '__').replace('}', '__')
        url = os.path.join('docs', 'md', *url.split('/'))
        text += '\n* [%s](%s)' % (doc, url)

    return text


def read(filename, text):
    with open(filename, 'w') as f:
        f.write(text)


if __name__ == '__main__':
    urls_filter = list(filter(lambda x: issubclass(x[2], View), urls))
    menu_filename = os.path.join(os.path.dirname(__file__), 'menu.md')
    read(menu_filename, get_markdown_menu(urls_filter))

    for url in urls_filter:
        __, url, cls = url
        methods = set(filter(lambda x: hasattr(cls, x.lower()), METH_ALL))
        errors, success = get_method_data(cls, methods)
        filename = create_folder_get_filename(url)
        doc = _get_doc(cls)

        read(filename, get_markdown(errors, success, url, methods, doc))
