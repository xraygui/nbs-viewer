"""Matplotlib canvas for N-D image grid display."""

import time as ttime

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from qtpy.QtCore import QTimer, Signal
from qtpy.QtWidgets import QSizePolicy

from nbs_viewer.models.data.array_contract import index_placeholders
from nbs_viewer.models.plot.trace import Trace
from nbs_viewer.models.plot.fetch.request import TraceKey, PlotRequest
from nbs_viewer.models.plot.view import Projection
from nbs_viewer.utils import print_debug
from .plot_worker import PlotWorker, retire_plot_worker


class ImageGridCanvas(FigureCanvasQTAgg):
    """
    Canvas for displaying N-D data cubes as a paginated grid of 2D images.

    Parameters
    ----------
    presenter : PlotPresenter
        Plot session presenter.
    parent : QWidget, optional
        Parent widget.
    width : float, optional
        Figure width in inches.
    height : float, optional
        Figure height in inches.
    dpi : int, optional
        Figure resolution.
    """

    paging_limits_changed = Signal(int, int)

    def __init__(self, presenter, parent=None, width=12, height=12, dpi=100):
        self.figure = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.figure)
        self.setParent(parent)
        self.presenter = presenter
        self.plot_model = presenter.session

        self._traces = {}
        self._artists = {}
        self._worker_generations = {}
        self._active_workers = {}
        self._pending_workers = set()
        self._current_page = 1
        self._images_per_page = 9
        self._total_images = 0
        self.cmap = "viridis"
        self._draw_pending = False
        self.axes = {}

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._connect_signals()
        self._update_grid()

    @property
    def images_per_page(self):
        """
        Number of images shown on each page.
        """
        return self._images_per_page

    def set_page(self, page):
        """
        Show the given page of images.

        Parameters
        ----------
        page : int
            One-based page index.
        """
        if page == self._current_page:
            return
        self._current_page = page
        self._update_grid()

    def set_images_per_page(self, count):
        """
        Change how many images are shown per page.

        Parameters
        ----------
        count : int
            Images per page.
        """
        if count == self._images_per_page:
            return
        self._images_per_page = count
        max_pages = max(1, (self._total_images - 1) // self._images_per_page + 1)
        if self._current_page > max_pages:
            self._current_page = max_pages
        self._update_grid()

    def _connect_signals(self):
        self.plot_model.selection.selected_keys_changed.connect(self._on_selection_changed)
        self.plot_model.collection.visible_runs_changed.connect(self._on_visible_runs_changed)
        self.plot_model.request_plot_update.connect(self._update_grid)

    def draw(self):
        """
        Draw the figure with throttling.
        """
        if not self._draw_pending:
            self._draw_pending = True
            QTimer.singleShot(16, self._do_draw)

    def _do_draw(self):
        self._draw_pending = False
        t0 = ttime.time()
        try:
            super().draw()
            print_debug(
                "ImageGridCanvas._do_draw",
                f"FigureCanvas.draw {ttime.time() - t0:.4f}s",
                category="plots",
            )
        except Exception as e:
            print_debug("ImageGridCanvas", f"Error in draw: {e}", category="plots")

    def _get_shape_info(self):
        """
        Return shape information from visible models.

        Returns
        -------
        tuple or None
            ``(shape, dim_names, axis_arrays, associated_data)`` or None.
        """
        print_debug("ImageGridCanvas", "Getting shape info", category="plots")
        visible_models = self.plot_model.collection.visible_models
        if not visible_models:
            print_debug("ImageGridCanvas", "No visible models", category="plots")
            return None

        run_model = visible_models[0]
        sel = self.plot_model.selection.selection_for(run_model.uid)
        x_keys, y_keys, norm_keys = sel.as_lists()

        print_debug(
            "ImageGridCanvas",
            f"Selected keys - x: {x_keys}, y: {y_keys}, norm: {norm_keys}",
            category="plots",
        )

        if not y_keys:
            print_debug("ImageGridCanvas", "No Y keys selected", category="plots")
            return None

        y_key = y_keys[0]
        print_debug(
            "ImageGridCanvas",
            f"Using y_key: {y_key}, x_key: {x_keys[0] if x_keys else 'None'}",
            category="plots",
        )

        try:
            shape = run_model.describe(y_key).shape
            dim_names = list(run_model.plot_axis_names(y_key, x_keys))
            axis_arrays = list(index_placeholders(shape))
            # Always empty on the describe path; the associated-axis payload
            # only ever came from a load.
            associated_data = {}

            print_debug("ImageGridCanvas", f"Shape: {shape}", category="plots")
            print_debug(
                "ImageGridCanvas", f"Dimension names: {dim_names}", category="plots"
            )
            print_debug(
                "ImageGridCanvas",
                f"Axis arrays lengths: {[len(arr) for arr in axis_arrays]}",
                category="plots",
            )

            return shape, dim_names, axis_arrays, associated_data
        except Exception as e:
            print_debug(
                "ImageGridCanvas", f"Error getting shape info: {e}", category="plots"
            )
            return None

    def _get_total_images(self, shape):
        """
        Determine how many 2D images an N-D shape contains.

        Parameters
        ----------
        shape : tuple
            Shape of the N-D data.

        Returns
        -------
        tuple or None
            ``(total_images, image_shape, non_image_dims)`` or None.
        """
        if len(shape) < 2:
            print_debug(
                "ImageGridCanvas",
                f"Data has less than 2 dimensions: {shape}",
                category="plots",
            )
            return None

        image_shape = shape[-2:]
        non_image_dims = shape[:-2]

        non_dummy_dims = [dim for dim in non_image_dims if dim > 1]
        if non_dummy_dims:
            total_images = np.prod(non_dummy_dims)
        else:
            total_images = 1

        return total_images, image_shape, non_image_dims

    def _update_grid(self):
        """
        Refresh the image grid for the current data and page.
        """
        print_debug("ImageGridCanvas", "Starting _update_grid", category="plots")

        self._clear_grid()

        shape_info = self._get_shape_info()
        if not shape_info:
            print_debug(
                "ImageGridCanvas", "No shape info available", category="plots"
            )
            self.paging_limits_changed.emit(0, 1)
            return

        shape, dim_names, axis_arrays, associated_data = shape_info

        total_images_result = self._get_total_images(shape)
        if not total_images_result:
            self.paging_limits_changed.emit(0, 1)
            return

        total_images, image_shape, non_image_dims = total_images_result

        self._total_images = total_images

        max_pages = max(1, (total_images - 1) // self._images_per_page + 1)
        if self._current_page > max_pages:
            self._current_page = max_pages

        self.paging_limits_changed.emit(total_images, max_pages)

        print_debug(
            "ImageGridCanvas", f"Will create {total_images} images", category="plots"
        )
        print_debug(
            "ImageGridCanvas",
            f"Images per page: {self._images_per_page}",
            category="plots",
        )
        print_debug(
            "ImageGridCanvas",
            f"Current page: {self._current_page}",
            category="plots",
        )

        self._create_subplots_for_page(shape, image_shape)

    def _make_slice_info(self, shape, image_idx):
        slice_indices = [0] * len(shape)
        slice_indices[0] = image_idx

        slice_info = []
        for j, dim_size in enumerate(shape):
            if j < len(slice_indices):
                if j >= len(shape) - 2:
                    slice_info.append(slice(None, None, None))
                else:
                    slice_info.append(slice_indices[j])
            else:
                slice_info.append(slice(None, None, None))

        return tuple(slice_info)

    def _create_artist(self, ax, image_or_shape):
        if isinstance(image_or_shape, np.ndarray):
            artist = ax.imshow(image_or_shape, cmap=self.cmap, aspect="auto")
        else:
            artist = ax.imshow(np.zeros(image_or_shape), cmap=self.cmap, aspect="auto")
        return artist

    def _artist_for(self, grid_key):
        """
        Return the artist drawn for one grid cell, if any.

        Parameters
        ----------
        grid_key : tuple
            ``(run uid, image index)`` cell key.

        Returns
        -------
        Artist or None
        """
        return self._artists.get(grid_key)

    def _move_artist_to_axes(self, grid_key, ax):
        """
        Re-home one cell's artist on a freshly created subplot.

        Parameters
        ----------
        grid_key : tuple
            ``(run uid, image index)`` cell key.
        ax : Axes
            Destination axes.
        """
        artist = self._artists.get(grid_key)
        if artist is None:
            return
        if hasattr(artist, "get_array"):
            image_data = artist.get_array()
            if artist.axes is not None:
                artist.remove()
            new_artist = self._create_artist(ax, image_data)
            self._artists[grid_key] = new_artist
            new_artist.autoscale()
        elif artist.axes is not ax:
            if artist.axes is not None:
                artist.remove()
            ax.add_artist(artist)
            self.draw()

    def _style_axes(self, ax, slice_info, image_idx):
        ax.set_title(f"Image {image_idx}")

    def _create_subplots_for_page(self, shape, image_shape):
        start_idx = (self._current_page - 1) * self._images_per_page
        end_idx = min(start_idx + self._images_per_page, self._total_images)

        print_debug(
            "ImageGridCanvas._create_subplots_for_page",
            f"Displaying images {start_idx} to {end_idx-1}",
            category="plots",
        )
        visible_models = self.plot_model.collection.visible_models
        if not visible_models:
            return

        run_model = visible_models[0]
        print_debug(
            "ImageGridCanvas", f"Run model: {run_model.uid}", category="plots"
        )
        x_keys, y_keys, norm_keys = self.plot_model.selection.selection_for(
            run_model.uid
        ).as_lists()

        if not y_keys:
            return

        images_this_page = end_idx - start_idx
        cols = int(np.ceil(np.sqrt(images_this_page)))
        rows = int(np.ceil(images_this_page / cols))

        print_debug(
            "ImageGridCanvas",
            f"Creating {images_this_page} images in {rows}x{cols} grid",
            category="plots",
        )

        self.figure.clear()

        self.axes = {}
        for i in range(images_this_page):
            image_idx = start_idx + i
            row = i // cols
            col = i % cols
            subplot_idx = row * cols + col + 1

            ax = self.figure.add_subplot(rows, cols, subplot_idx)
            self.axes[image_idx] = ax

            slice_info = self._make_slice_info(shape, image_idx)

            try:
                print_debug(
                    "ImageGridCanvas",
                    f"Processing image {image_idx} with indices {slice_info}",
                    category="plots",
                )
                trace = self._create_image_trace(
                    run_model, slice_info, image_idx
                )
                grid_key = self._grid_worker_key(run_model.uid, image_idx)
                if self._artist_for(grid_key) is None:
                    artist = self._create_artist(ax, image_shape)
                    self._start_image_worker(
                        trace, slice_info, artist, image_idx
                    )
                else:
                    print_debug(
                        "ImageGridCanvas",
                        f"Moving artist {trace.label} to new axes",
                        category="plots",
                    )
                    self._move_artist_to_axes(grid_key, ax)

            except Exception as e:
                print_debug(
                    "ImageGridCanvas",
                    f"Error creating image {image_idx}: {e}",
                    category="plots",
                )
            self._style_axes(ax, slice_info, image_idx)
        self.figure.tight_layout()
        super().draw()
        print_debug(
            "ImageGridCanvas", "Finished creating subplots", category="plots"
        )

    def _create_image_trace(self, run_model, slice_info, image_idx):
        key = (run_model.uid, image_idx)
        sel = self.plot_model.selection.selection_for(run_model.uid)
        x_keys, y_keys, norm_keys = sel.as_lists()
        y_key = y_keys[0]
        if key not in self._traces:
            print_debug(
                "ImageGridCanvas",
                f"Creating Trace for image {image_idx}",
                category="plots",
            )

            xkey = x_keys[0] if x_keys else ""
            transform = ""
            if self.plot_model.transform.get("enabled"):
                transform = self.plot_model.transform.get("text", "") or ""
            dims = run_model.plot_axis_names(y_key, [xkey] if xkey else [])
            request = PlotRequest(
                uid=run_model.uid,
                xkeys=(xkey,) if xkey else (),
                ykey=y_key,
                norm_keys=tuple(norm_keys or ()),
                view=Projection.from_slice_info(tuple(slice_info), 2),
                dims=tuple(dims),
                transform=transform,
            )
            trace = Trace(
                run_model,
                request,
                label=f"Image {image_idx}",
                trace_key=TraceKey(
                    run_model.uid, xkey, y_key, fan_out_index=image_idx
                ),
            )

            trace.data_changed.connect(self._start_image_worker)

            self._traces[key] = trace
        else:
            trace = self._traces[key]
            trace.set_projection(Projection.from_slice_info(tuple(slice_info), 2))
        return trace

    def _grid_worker_key(self, run_uid, image_idx):
        return (run_uid, image_idx)

    def _image_idx_for_trace(self, trace):
        for key, model in self._traces.items():
            if model is trace:
                return key[1]
        raise KeyError(f"No grid index for plot data {trace.label}")

    def _start_image_worker(
        self, trace, slice_info=None, artist=None, image_idx=None
    ):
        print_debug(
            "ImageGridCanvas",
            f"Starting worker for image {trace.label}",
            category="plots",
        )
        dimension = 2
        if slice_info is None:
            slice_info = trace.request.view.base_slice()
        if image_idx is None:
            image_idx = self._image_idx_for_trace(trace)

        worker_key = self._grid_worker_key(trace.run.uid, image_idx)
        generation = self._worker_generations.get(worker_key, 0) + 1
        self._worker_generations[worker_key] = generation

        old_worker = self._active_workers.pop(worker_key, None)
        retire_plot_worker(old_worker, self._pending_workers)

        request = trace.request
        if slice_info is not None:
            trace.set_projection(
                Projection.from_slice_info(tuple(slice_info), dimension), emit=False
            )
            request = trace.request
        worker = PlotWorker(trace, request, generation, artist)
        worker.data_ready.connect(self._handle_image_data)
        worker.error_occurred.connect(self._handle_image_error)
        worker.finished.connect(
            lambda wk=worker_key, w=worker: self._on_image_worker_finished(wk, w)
        )
        self._active_workers[worker_key] = worker
        worker.start()

    def _on_image_worker_finished(self, worker_key, worker):
        if self._active_workers.get(worker_key) is worker:
            self._active_workers.pop(worker_key, None)

    def _handle_image_data(self, bundle, trace, artist=None, generation=0):
        worker_key = self._grid_worker_key(
            trace.run.uid, self._image_idx_for_trace(trace)
        )
        if generation != self._worker_generations.get(worker_key):
            print_debug(
                "ImageGridCanvas",
                f"Stale worker gen={generation} for {trace.label}, skipping",
                category="plots",
            )
            return
        y = bundle.y
        print_debug(
            "ImageGridCanvas",
            f"Received data for {trace.label}: shape {y.shape}",
            category="plots",
        )

        if artist is None:
            artist = self._artist_for(worker_key)
        else:
            self._artists[worker_key] = artist
        if artist is None:
            print_debug(
                "ImageGridCanvas", "No artist found for plot data", category="plots"
            )
            return

        try:
            if len(y.shape) == 2:
                print_debug(
                    "ImageGridCanvas",
                    f"Successfully plotted {trace.label}",
                    category="plots",
                )
                artist.set_data(y)
                artist.autoscale()
            else:
                print_debug(
                    "ImageGridCanvas",
                    f"Error plotting image data: {y.shape}",
                    category="plots",
                )
            self.draw()

        except Exception as e:
            print_debug(
                "ImageGridCanvas", f"Error plotting image data: {e}", category="plots"
            )

    def _handle_image_error(self, error_msg):
        print_debug(
            "ImageGridCanvas", f"Image worker error: {error_msg}", category="plots"
        )

    def _clear_grid(self):
        for worker in list(self._active_workers.values()):
            retire_plot_worker(worker, self._pending_workers)
        self._active_workers.clear()
        self._worker_generations.clear()

        if hasattr(self, "figure"):
            self.figure.clear()
            super().draw()

        for artist in self._artists.values():
            if artist.axes is not None:
                artist.remove()

        self.axes.clear()

    def _on_selection_changed(self, x_keys, y_keys, norm_keys):
        self._update_grid()

    def _on_visible_runs_changed(self, visible_runs):
        self._update_grid()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.draw()
