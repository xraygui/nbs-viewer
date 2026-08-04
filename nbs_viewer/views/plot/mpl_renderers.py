"""
Matplotlib renderers for 1D lines, uniform 2D images, and non-uniform meshes.
"""

from __future__ import annotations

import time as ttime
from typing import Optional, Tuple

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
from matplotlib.lines import Line2D

from ...models.plot.plot_geometry import PlotBundle
from ...models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.utils import print_debug


class LineRenderer:
    """Render 1D line plots."""

    @staticmethod
    def create(axes: Axes, bundle: PlotBundle, label: str) -> Line2D:
        t0 = ttime.time()
        x = bundle.x_line if bundle.x_line is not None else np.arange(bundle.y.size)
        artist = axes.plot(x, bundle.y, clip_on=True, label=label)[0]
        print_debug(
            "LineRenderer.create",
            f"n={bundle.y.size} {ttime.time() - t0:.4f}s",
            category="plots",
        )
        return artist

    @staticmethod
    def update(artist: Line2D, bundle: PlotBundle) -> None:
        t0 = ttime.time()
        x = bundle.x_line if bundle.x_line is not None else np.arange(bundle.y.size)
        artist.set_data(x, bundle.y)
        print_debug(
            "LineRenderer.update",
            f"n={bundle.y.size} {ttime.time() - t0:.4f}s",
            category="plots",
        )

    @staticmethod
    def set_labels(axes: Axes, bundle: PlotBundle) -> None:
        if bundle.axis_names:
            axes.set_xlabel(bundle.axis_names[0])


class ImageRenderer:
    """Render uniform-grid 2D data with imshow."""

    @staticmethod
    def create(
        axes: Axes,
        fig: Figure,
        bundle: PlotBundle,
        label: str,
        colorbar_state: dict,
    ) -> Tuple[AxesImage, object]:
        t0 = ttime.time()
        extent = bundle.extent
        artist = axes.imshow(
            bundle.y,
            extent=extent,
            aspect="auto",
            origin="upper",
            interpolation="nearest",
            label=label,
        )
        cbar = fig.colorbar(artist, ax=axes)
        cbar.set_label(label)
        colorbar_state["colorbar"] = cbar
        ImageRenderer.set_labels(axes, bundle)
        print_debug(
            "ImageRenderer.create",
            f"shape={bundle.y.shape} {ttime.time() - t0:.4f}s",
            category="plots",
        )
        return artist, cbar

    @staticmethod
    def update(
        artist: AxesImage,
        bundle: PlotBundle,
        autoscale: bool,
        colorbar_state: dict,
    ) -> None:
        t0 = ttime.time()
        artist.set_data(bundle.y)
        if bundle.extent is not None:
            artist.set_extent(bundle.extent)
            axes = artist.axes
            if axes is not None:
                left, right, bottom, top = bundle.extent
                axes.set_xlim(left, right)
                axes.set_ylim(bottom, top)
        if autoscale:
            finite = bundle.y[np.isfinite(bundle.y)]
            if finite.size > 0:
                artist.set_clim(float(np.min(finite)), float(np.max(finite)))
        cbar = colorbar_state.get("colorbar")
        if cbar is not None and autoscale:
            cbar.update_ticks()
        print_debug(
            "ImageRenderer.update",
            f"shape={bundle.y.shape} {ttime.time() - t0:.4f}s",
            category="plots",
        )

    @staticmethod
    def set_labels(axes: Axes, bundle: PlotBundle) -> None:
        frame = frame_from_bundle(bundle)
        axes.set_xlabel(frame.plot_x_name)
        axes.set_ylabel(frame.plot_y_name)


class MeshRenderer:
    """Render non-uniform 2D data with pcolormesh."""

    @staticmethod
    def create(
        axes: Axes,
        fig: Figure,
        bundle: PlotBundle,
        label: str,
        colorbar_state: dict,
    ):
        t0 = ttime.time()
        mesh = axes.pcolormesh(
            bundle.mesh_x,
            bundle.mesh_y,
            bundle.y,
            shading="flat",
            label=label,
        )
        cbar = fig.colorbar(mesh, ax=axes)
        cbar.set_label(label)
        colorbar_state["colorbar"] = cbar
        MeshRenderer.set_labels(axes, bundle)
        MeshRenderer._set_limits(axes, bundle)
        print_debug(
            "MeshRenderer.create",
            f"shape={bundle.y.shape} {ttime.time() - t0:.4f}s",
            category="plots",
        )
        return mesh, cbar

    @staticmethod
    def update(
        artist,
        bundle: PlotBundle,
        autoscale: bool,
        colorbar_state: dict,
    ) -> None:
        t0 = ttime.time()
        artist.set_array(bundle.y.ravel())
        if autoscale:
            finite = bundle.y[np.isfinite(bundle.y)]
            if finite.size > 0:
                vmin = float(np.min(finite))
                vmax = float(np.max(finite))
                artist.set_clim(vmin=vmin, vmax=vmax)
        MeshRenderer._set_limits(artist.axes, bundle)
        print_debug(
            "MeshRenderer.update",
            f"shape={bundle.y.shape} {ttime.time() - t0:.4f}s",
            category="plots",
        )

    @staticmethod
    def _set_limits(axes: Axes, bundle: PlotBundle) -> None:
        if bundle.mesh_x is not None and bundle.mesh_y is not None:
            axes.set_xlim(np.min(bundle.mesh_x), np.max(bundle.mesh_x))
            axes.set_ylim(np.min(bundle.mesh_y), np.max(bundle.mesh_y))

    @staticmethod
    def set_labels(axes: Axes, bundle: PlotBundle) -> None:
        frame = frame_from_bundle(bundle)
        axes.set_xlabel(frame.plot_x_name)
        axes.set_ylabel(frame.plot_y_name)


def remove_2d_artists(
    axes: Axes, colorbar_state: dict, fig: Optional[Figure] = None
) -> None:
    """
    Remove 2D plot artists and colorbar from axes.

    Parameters
    ----------
    axes : Axes
        Target axes.
    colorbar_state : dict
        Mutable dict holding optional ``colorbar`` key.
    fig : Figure, optional
        Parent figure; when given, removes orphaned colorbar axes left on
        the figure after switching plots or runs.
    """
    cbar = colorbar_state.pop("colorbar", None)
    if cbar is not None:
        try:
            cbar.remove()
        except Exception:
            pass

    for image in list(axes.images):
        try:
            image.remove()
        except Exception:
            pass

    while axes.collections:
        try:
            axes.collections[0].remove()
        except Exception:
            break

    if fig is not None:
        for ax in list(fig.axes):
            if ax is not axes:
                try:
                    ax.remove()
                except Exception:
                    pass
