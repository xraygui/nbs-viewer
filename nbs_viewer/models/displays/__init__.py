"""
The multi-display shell: how many plots there are, and which model feeds one.

:mod:`manager` owns the set of displays and their lifecycle; :mod:`presenter`
is what one display is handed. Neither is about plotting -- they sit above it,
and nothing in ``models/plot`` imports either, which is why they moved out of
it.
"""
