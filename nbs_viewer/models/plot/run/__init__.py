"""
One run as the plot layer sees it: what it is, and how to read it.

:mod:`source` is ``RunSource``, the object a trace holds. It is the union of
a catalog run and its frozen synthetic keys under one key space, and it is
the *reader* for them -- the six methods anything asks a run for.

:mod:`cache` is ``BlockCache``, the one block a run holds and the window
arithmetic that decides whether a new plan needs a read. ``RunSource`` owns
one and hands its own reads to it, so the cache is a collaborator rather than
a layer wrapped around the reader; there is no non-caching reader class,
because the reader is ``RunSource`` itself.

The stages between a request and a bundle used to live here too, as
``pipeline.RunFetch``. They are now ``PlotRequest.plot_bundle``, in the
package that holds the rest of the description chain: the sequencer reads
nine attributes of the request and one of the plan, so it belongs with them.
Nothing in this package describes a plot any more.

:mod:`frozen_spectrum` is a reduction frozen into a synthetic key so it can
be plotted beside live data.

**No re-export surface**: each module exports one class, and the handful of
consumers name the module they want.
"""
