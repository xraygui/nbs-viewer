"""
What to read for a plot, and every stage between the array and the bundle.

:mod:`request` is the frozen ``PlotRequest``. :mod:`plan` turns a request into
the storage indices to read, and is the only place a load is narrowed.
:mod:`stages` is the uniformly ``DataArray -> DataArray`` set that runs
between the read and the pack.

**No re-export surface, deliberately.** Every consumer is one of a handful of
files that names the module it wants, and the order the stages run in is not
here at all -- it is ``RunFetch.get_plot_bundle`` in :mod:`..run`, because the
pipeline is a thing an object does, not a fourth module. The draft named a
``pipeline.py`` for it; there is nothing to put in one.
"""
