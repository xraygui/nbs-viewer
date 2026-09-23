"""
The long-lived plot objects a session keeps, and what names them.

:mod:`key` is ``TraceKey``, the identity a trace keeps across every change to
its request. :mod:`trace` is ``Trace``, one plotted thing: its current
request, the last bundle fetched for it, and its visibility. :mod:`set` is
``TraceSet``, the mapping a session owns.

The package imports ``spec/`` and is imported by ``session.py``; nothing in
``spec/`` imports back, which is why ``TraceKey.of`` is a classmethod here
rather than a ``PlotRequest`` method.

**No re-export surface**: each module exports one class, and consumers name
the module they want.
"""
