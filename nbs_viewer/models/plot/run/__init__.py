"""
One run as the plot layer sees it: what it is, and how to read it.

:mod:`source` is ``RunSource``, the object a trace holds. :mod:`pipeline` is
``RunFetch``, which it owns and hands out as ``.fetch``, and which runs the
stages between a request and a bundle.

It is ``pipeline.py`` and not ``fetch.py``, which is what the plan called it,
because ``models/plot/fetch/`` is the package next door holding the request,
the plan and the stages. Two things called ``fetch`` one directory apart is
the kind of name this whole reorganisation exists to remove, and the
distinction is real: that package *describes* a fetch, this class *performs*
one. It is also the ``pipeline.py`` the plan wanted inside ``fetch/`` and
could find no contents for -- the pipeline is a thing an object does. :mod:`identity` is how two runs are
told apart, and :mod:`frozen_spectrum` is a reduction frozen into a synthetic
key so it can be plotted beside live data.

**No re-export surface**: each module exports one class, and the handful of
consumers name the module they want.
"""
