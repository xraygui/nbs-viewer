"""
The chain of descriptions of one plot, and the machinery it drives.

Each module holds one link and gets more concrete as the chain runs:
:mod:`projection` says how an array of known rank is sliced and oriented,
:mod:`region` holds the shapes drawn on the result, :mod:`request` adds the
keys and the transform, :mod:`plan` says what to read for one, and
:mod:`bundle` is the payload the view layer draws. :mod:`axes` is the
projection spoken in dimension names, and :mod:`stages` is the array
arithmetic the links sequence.

Imports run one way through that order and end at :mod:`request`, which is
the only module that knows the whole chain.

**There is no facade here on purpose.** A flat re-export would let a caller
write ``from ...spec import PlotRequest`` and learn nothing; naming the
module says which link is being reached for, which is the property this
package exists to make visible. The three packages it replaces --
``view/``, ``geometry/`` and ``fetch/`` -- each held half a chain and half a
vocabulary behind exactly such a facade, and the vocabulary now lives below
in :mod:`..plane`.
"""
