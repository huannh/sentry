"""
sentry.tasks.fetch_source
~~~~~~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2010-2012 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""

import urllib2
from collections import namedtuple
from urlparse import urljoin

from celery.task import task
from sentry.utils.cache import cache
from sentry.utils.lrucache import lrucache
from sentry.utils.sourcemaps import sourcemap_to_index, find_source

BAD_SOURCE = -1

# number of surrounding lines (on each side) to fetch
LINES_OF_CONTEXT = 5


UrlResult = namedtuple('UrlResult', ['url', 'headers', 'body'])


def get_source_context(source, lineno, context=LINES_OF_CONTEXT):
    # lineno's in JS are 1-indexed
    lineno -= 1

    lower_bound = max(0, lineno - context)
    upper_bound = min(lineno + 1 + context, len(source))

    try:
        pre_context = [line.strip('\n') for line in source[lower_bound:lineno]]
    except IndexError:
        pre_context = []

    try:
        context_line = source[lineno].strip('\n')
    except IndexError:
        context_line = ''

    try:
        post_context = [line.strip('\n') for line in source[(lineno + 1):upper_bound]]
    except IndexError:
        post_context = []

    return pre_context, context_line, post_context


def discover_sourcemap(result, logger=None):
    """
    Given a UrlResult object, attempt to discover a sourcemap.
    """
    sourcemap = result.headers.get('X-SourceMap', None)

    if not sourcemap:
        parsed_body = result.body.splitlines()
        indicator = parsed_body[-1]
        if indicator.startswith('//@'):
            try:
                parsed = dict(v.split('=') for v in indicator[3:].strip().split(' '))
            except Exception:
                if logger:
                    logger.error('Failed parsing source map line for %r (line was %r)', result.url, indicator, exc_info=True)
            else:
                sourcemap = parsed.get('sourceMappingURL')

    if sourcemap:
        # fix url so its absolute
        sourcemap = urljoin(result.url, sourcemap)

    return sourcemap


@lrucache.memoize
def fetch_url(url, logger=None):
    """
    Pull down a URL, returning a UrlResult object.

    Attempts to fetch from the cache.
    """
    import sentry

    cache_key = 'fetch_url:%s' % url
    result = cache.get(cache_key)
    if result is not None:
        return result

    try:
        opener = urllib2.build_opener()
        opener.addheaders = [('User-Agent', 'Sentry/%s' % sentry.VERSION)]
        req = opener.open(url)
        headers = dict(req.headers)
        body = req.read().rstrip('\n')
    except Exception:
        if logger:
            logger.error('Unable to fetch remote source for %r', url, exc_info=True)
        return BAD_SOURCE

    result = UrlResult(url, headers, body)

    cache.set(cache_key, result, 60 * 5)

    return result


@task(ignore_result=True)
def fetch_javascript_source(event, **kwargs):
    """
    Attempt to fetch source code for javascript frames.

    Frames must match the following requirements:

    - lineno >= 0
    - colno >= 0
    - abs_path is the HTTP URI to the source
    - context_line is empty
    """
    import logging
    logger = fetch_javascript_source.get_logger()
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())

    try:
        stacktrace = event.data['sentry.interfaces.Stacktrace']
    except KeyError:
        logger.info('No stacktrace for event %r', event.id)
        return

    # build list of frames that we can actually grab source for
    frames = [f for f in stacktrace['frames']
        if f.get('lineno') is not None
            and f.get('colno') is not None
            and f.get('abs_path', '').startswith(('http://', 'https://'))
            and f.get('context_line') is None]
    if not frames:
        logger.info('Event %r has no frames with enough context to fetch remote source', event.id)
        return

    file_list = set((f['abs_path'] for f in frames))
    source_code = {}
    sourcemaps = {}

    while file_list:
        filename = file_list.pop()

        # TODO: respect cache-contro/max-age headers to some extent
        result = fetch_url(filename)

        if result == BAD_SOURCE:
            continue

        # TODO: we're currently running splitlines twice
        sourcemap = discover_sourcemap(result, logger=logger)
        source_code[filename] = (result.body.splitlines(), sourcemap)
        if sourcemap:
            logger.info('Found sourcemap %r for minified script %r', sourcemap, result.url)

        # pull down sourcemap
        if sourcemap and sourcemap not in sourcemaps:
            result = fetch_url(sourcemap, logger=logger)
            if result == BAD_SOURCE:
                continue

            index = sourcemap_to_index(result.body)
            sourcemaps[sourcemap] = index

            # queue up additional source files for download
            for source in index.sources:
                if source not in source_code:
                    file_list.add(urljoin(result.url, source))

    for frame in frames:
        try:
            source, sourcemap = source_code[frame['abs_path']]
        except KeyError:
            # we must've failed pulling down the source
            continue

        if sourcemap:
            state = find_source(sourcemaps[sourcemap], frame['lineno'], frame['colno'])
            # TODO: is this urljoin right? (is it relative to the sourcemap or the originating file)
            abs_path = urljoin(sourcemap, state.src)
            try:
                source, _ = source_code[abs_path]
            except KeyError:
                pass
            else:
                # SourceMap's return zero-indexed lineno's
                frame['lineno'] = state.src_line + 1
                frame['colno'] = state.src_col
                frame['name'] = state.name
                frame['abs_path'] = abs_path
                frame['filename'] = state.src

        # TODO: theoretically a minified source could point to another mapped, minified source
        frame['pre_context'], frame['context_line'], frame['post_context'] = get_source_context(
            source=source, lineno=int(frame['lineno']))

    event.save()
