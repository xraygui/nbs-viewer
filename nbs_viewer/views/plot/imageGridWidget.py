"""Image grid widget for displaying N-D data cubes as 2D image grids."""

from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSizePolicy,
    QSpinBox,
    QLabel,
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from qtpy.QtCore import QTimer

from ...utils import print_debug
from ...models.plot.plotDataModel import PlotDataModel
from .plotControl import PlotControls
from .plotWidget import PlotWorker


import numpy as np
import uuid


class ImageGridWidget(QWidget):
    """
    Widget for displaying N-D data cubes as a grid of 2D images.

    This widget takes N-D data and displays each 2D slice as a separate
    image in a grid layout, allowing simultaneous viewing of multiple
    images from a data cube.

    Uses a single FigureCanvas with subplots for better space utilization
    and built-in navigation functionality.
    """

    def __init__(self, run_list_model, parent=None):
        """
        Initialize the image grid widget.

        Parameters
        ----------
        run_list_model : RunListModel
            Model managing the canvas data
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.run_list_model = run_list_model

        # Initialize state
        self.plotArtists = {}
        self.workers = {}
        self._current_page = 1
        self._images_per_page = 9  # Start with 9 for testing
        self._total_images = 0
        self.cmap = "viridis"
        # Batch drawing system (consistent with MplCanvas)
        self._draw_pending = False

        # Create plot controls (for data selection)
        self._create_plot_controls()
        # Initial update
        self._setup_ui()
        self._update_grid()
        # Connect to model signals

        self._connect_signals()

    def _create_plot_controls(self):
        """Create plot controls."""
        self.plot_controls = PlotControls(self.run_list_model)

    def _connect_signals(self):
        """Connect signals to model."""
        self.run_list_model.selected_keys_changed.connect(self._on_selection_changed)
        self.run_list_model.visible_runs_changed.connect(self._on_visible_runs_changed)
        self.run_list_model.request_plot_update.connect(self._update_grid)

    def draw(self):
        """Draw the figure with throttling (consistent with MplCanvas)."""
        if not self._draw_pending:
            self._draw_pending = True
            QTimer.singleShot(16, self._do_draw)  # About 60fps

    def _do_draw(self):
        """Actually perform the draw operation (consistent with MplCanvas)."""
        self._draw_pending = False
        print_debug("ImageGridWidget._do_draw", "Drawing")
        try:
            self.canvas.draw()
        except Exception as e:
            print_debug("ImageGridWidget", f"Error in draw: {e}")

    def _setup_ui(self):
        """Set up the user interface."""
        # Main layout - grid and paging controls
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create single figure and canvas
        self.figure = Figure(figsize=(12, 12), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Create navigation toolbar
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        # Create paging controls
        self._create_paging_controls()

        # Add widgets to main layout
        main_layout.addWidget(self.toolbar)  # Toolbar at top
        main_layout.addWidget(self.canvas)  # Canvas takes most space
        main_layout.addWidget(self.paging_controls)  # Paging at bottom
        self.setLayout(main_layout)

    def _create_paging_controls(self):
        """Create paging controls as a separate component."""
        paging_widget = QWidget()
        paging_layout = QHBoxLayout(paging_widget)

        # Images per page control
        paging_layout.addWidget(QLabel("Images per page:"))
        self.images_per_page_spinbox = QSpinBox()
        self.images_per_page_spinbox.setMinimum(1)
        self.images_per_page_spinbox.setMaximum(100)
        self.images_per_page_spinbox.setValue(self._images_per_page)
        # Connect signal only once
        self.images_per_page_spinbox.valueChanged.connect(
            self._on_images_per_page_changed
        )
        paging_layout.addWidget(self.images_per_page_spinbox)

        # Page navigation
        paging_layout.addWidget(QLabel("Page:"))
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setValue(1)
        # Connect signal only once
        self.page_spinbox.valueChanged.connect(self._on_page_changed)
        paging_layout.addWidget(self.page_spinbox)

        # Total images label
        self.total_images_label = QLabel("Total: 0 images")
        paging_layout.addWidget(self.total_images_label)

        paging_layout.addStretch()

        # Store as a component
        self.paging_controls = paging_widget

    def _get_shape_info(self):
        """
        Get shape information from visible models.

        Returns
        -------
        tuple or None
            (shape, dim_names, axis_arrays, associated_data) or None if no data
        """
        print_debug("ImageGridWidget", "Getting shape info")
        visible_models = self.run_list_model.visible_models
        if not visible_models:
            print_debug("ImageGridWidget", "No visible models")
            return None

        # Get shape information from the first visible model
        run_model = visible_models[0]
        x_keys, y_keys, norm_keys = run_model.get_selected_keys()

        print_debug(
            "ImageGridWidget",
            f"Selected keys - x: {x_keys}, y: {y_keys}, norm: {norm_keys}",
        )

        if not y_keys:
            print_debug("ImageGridWidget", "No Y keys selected")
            return None

        y_key = y_keys[0]
        print_debug(
            "ImageGridWidget",
            f"Using y_key: {y_key}, x_key: {x_keys[0] if x_keys else 'None'}",
        )

        try:
            # Get dimension analysis
            axis_arrays, axis_names, associated_data = (
                run_model._run.get_dimension_axes(y_key, x_keys)
            )
            shape = tuple(len(arr) if len(arr) > 0 else 1 for arr in axis_arrays)

            print_debug("ImageGridWidget", f"Shape: {shape}")
            print_debug("ImageGridWidget", f"Dimension names: {axis_names}")
            print_debug(
                "ImageGridWidget",
                f"Axis arrays lengths: {[len(arr) for arr in axis_arrays]}",
            )

            return shape, axis_names, axis_arrays, associated_data
        except Exception as e:
            print_debug("ImageGridWidget", f"Error getting shape info: {e}")
            return None

    def _get_total_images(self, shape):
        """
        Process N-D shape and determine how many images to display.

        Parameters
        ----------
        shape : tuple
            Shape of the N-D data

        Returns
        -------
        tuple
            (total_images, image_shape, non_image_dims) or None if invalid
        """
        if len(shape) < 2:
            print_debug("ImageGridWidget", f"Data has less than 2 dimensions: {shape}")
            return None

        # Last 2 dimensions are always the image (height, width)
        image_shape = shape[-2:]
        non_image_dims = shape[:-2]

        # Calculate total images by multiplying non-image dimensions
        # Remove dummy dimensions (size 1) when calculating total
        non_dummy_dims = [dim for dim in non_image_dims if dim > 1]
        if non_dummy_dims:
            total_images = np.prod(non_dummy_dims)
        else:
            # If all non-image dimensions are dummy, we have 1 image
            total_images = 1

        return total_images, image_shape, non_image_dims

    def _update_grid(self):
        """Update the image grid with current data."""
        print_debug("ImageGridWidget", "Starting _update_grid")

        # Clear existing grid
        self._clear_grid()

        # Get shape information
        shape_info = self._get_shape_info()
        if not shape_info:
            print_debug("ImageGridWidget", "No shape info available")
            return

        shape, dim_names, axis_arrays, associated_data = shape_info

        # Process ND data
        total_images_result = self._get_total_images(shape)
        if not total_images_result:
            return

        total_images, image_shape, non_image_dims = total_images_result

        # Update state
        self._total_images = total_images

        # Update UI
        self.total_images_label.setText(f"Total: {total_images} images")
        max_pages = max(1, (total_images - 1) // self._images_per_page + 1)
        self.page_spinbox.setMaximum(max_pages)

        # Ensure current page is valid
        if self._current_page > max_pages:
            self._current_page = max_pages
            self.page_spinbox.setValue(self._current_page)

        print_debug("ImageGridWidget", f"Will create {total_images} images")
        print_debug("ImageGridWidget", f"Images per page: {self._images_per_page}")
        print_debug("ImageGridWidget", f"Current page: {self._current_page}")

        # Calculate start and end indices for current page

        # Create subplots for current page
        self._create_subplots_for_page(shape, image_shape)

    def _make_slice_info(self, shape, image_idx):
        slice_indices = [0] * len(shape)
        slice_indices[0] = image_idx  # Use first dimension for iteration

        # Convert to proper slice format
        slice_info = []
        for j, dim_size in enumerate(shape):
            if j < len(slice_indices):
                if j >= len(shape) - 2:
                    # Last 2 dimensions get full slices
                    slice_info.append(slice(None, None, None))
                else:
                    # Other dimensions get integer index
                    slice_info.append(slice_indices[j])
            else:
                slice_info.append(slice(None, None, None))

        slice_info = tuple(slice_info)
        return slice_info

    def _create_artist(self, ax, image_or_shape):
        if isinstance(image_or_shape, np.ndarray):
            artist = ax.imshow(image_or_shape, cmap=self.cmap, aspect="auto")
        else:
            artist = ax.imshow(np.zeros(image_or_shape), cmap=self.cmap, aspect="auto")
        return artist

    def _move_plot_data_to_axes(self, plot_data, ax):
        # Handle moving image artist to new axes
        if hasattr(plot_data.artist, "get_array"):
            # Get current image data and properties
            image_data = plot_data.artist.get_array()
            # Remove old artist
            if plot_data.artist.axes is not None:
                plot_data.artist.remove()

            # Create new image on target axes
            new_artist = self._create_artist(ax, image_data)
            plot_data.set_artist(new_artist)
            new_artist.autoscale()
        else:
            # Fallback to generic move (for non-image artists)
            plot_data.move_artist_to_axes(ax)

    def _style_axes(self, ax, slice_info, image_idx):
        ax.set_title(f"Image {image_idx}")

    def _create_subplots_for_page(self, shape, image_shape):
        """
        Create subplots for the current page.

        Parameters
        ----------
        shape : tuple
            Full shape of the data
        image_shape : tuple
            Shape of the image
        """
        start_idx = (self._current_page - 1) * self._images_per_page
        end_idx = min(start_idx + self._images_per_page, self._total_images)

        print_debug(
            "ImageGridWidget._create_subplots_for_page",
            f"Displaying images {start_idx} to {end_idx-1}",
        )
        visible_models = self.run_list_model.visible_models
        if not visible_models:
            return

        run_model = visible_models[0]
        print_debug("ImageGridWidget", f"Run model: {run_model.uid}")
        x_keys, y_keys, norm_keys = run_model.get_selected_keys()

        if not y_keys:
            return

        y_key = y_keys[0]

        # Calculate grid dimensions for this page
        images_this_page = end_idx - start_idx
        cols = int(np.ceil(np.sqrt(images_this_page)))  # Max 3 cols
        rows = int(np.ceil(images_this_page / cols))

        print_debug(
            "ImageGridWidget",
            f"Creating {images_this_page} images in {rows}x{cols} grid",
        )

        # Clear existing subplots
        self.figure.clear()

        # Create subplots for this page
        self.axes = {}
        for i in range(images_this_page):
            image_idx = start_idx + i
            row = i // cols
            col = i % cols
            subplot_idx = row * cols + col + 1

            # Create subplot
            ax = self.figure.add_subplot(rows, cols, subplot_idx)
            self.axes[image_idx] = ax

            slice_info = self._make_slice_info(shape, image_idx)

            try:
                # Create slice indices for this image
                print_debug(
                    "ImageGridWidget",
                    f"Processing image {image_idx} with indices {slice_info}",
                )
                # Create PlotDataModel for this image
                plot_data = self._create_image_plot_data(
                    run_model, slice_info, image_idx
                )
                if plot_data.artist is None:
                    artist = self._create_artist(ax, image_shape)
                    self._start_image_worker(plot_data, slice_info, artist)
                else:
                    print_debug(
                        "ImageGridWidget",
                        f"Moving artist {plot_data.label} to new axes",
                    )
                    self._move_plot_data_to_axes(plot_data, ax)

            except Exception as e:
                print_debug("ImageGridWidget", f"Error creating image {image_idx}: {e}")
            self._style_axes(ax, slice_info, image_idx)
        # Adjust layout for better spacing
        self.figure.tight_layout()
        self.canvas.draw()
        print_debug("ImageGridWidget", "Finished creating subplots")

    def _create_image_plot_data(self, run_model, slice_info, image_idx):
        """
        Create a PlotDataModel for a single image.

        Parameters
        ----------
        run_model : RunModel
            The run model containing the data
        x_keys : list
            X-axis keys
        y_key : str
            Y-axis key
        norm_keys : list
            Normalization keys
        slice_info : tuple
            Slice indices for this image
        image_idx : int
            Index of this image
        """
        # Create unique key for this image
        key = (run_model.uid, image_idx)
        x_keys, y_keys, norm_keys = run_model.get_selected_keys()
        y_key = y_keys[0]
        if key not in self.plotArtists:
            print_debug(
                "ImageGridWidget", f"Creating PlotDataModel for image {image_idx}"
            )

            # Create PlotDataModel
            plot_data = PlotDataModel(
                run_model,
                x_keys[0] if x_keys else "",
                y_key,
                norm_keys=norm_keys,
                label=f"Image {image_idx}",
                indices=slice_info,
                dimension=2,  # Always 2D for images
            )

            # Connect signals
            plot_data.data_changed.connect(self._start_image_worker)
            plot_data.draw_requested.connect(self._handle_image_draw)

            # Store reference
            self.plotArtists[key] = plot_data
        else:
            plot_data = self.plotArtists[key]
            plot_data.data_changed.connect(self._start_image_worker)
            plot_data.draw_requested.connect(self._handle_image_draw)
        return plot_data

    def _start_image_worker(self, plot_data, slice_info=None, artist=None):
        """
        Start a PlotWorker for loading image data.

        Parameters
        ----------
        plot_data : PlotDataModel
            The plot data model
        slice_info : tuple
            Slice indices

        """

        print_debug("ImageGridWidget", f"Starting worker for image {plot_data.label}")
        dimension = 2
        if slice_info is None:
            slice_info = plot_data._indices
        # Create worker
        worker_key = str(uuid.uuid4())
        worker = PlotWorker(plot_data, slice_info, dimension, artist)
        worker.data_ready.connect(self._handle_image_data)
        worker.error_occurred.connect(self._handle_image_error)
        worker.finished.connect(lambda: self._cleanup_worker(worker_key))

        # Store worker reference and start it
        self.workers[worker_key] = worker
        worker.start()

    def _handle_image_data(self, x, y, plot_data, artist=None):
        """
        Handle image data when it's ready.

        Parameters
        ----------
        x : list
            X-axis data
        y : np.ndarray
            Y-axis data (image data)
        plot_data : PlotDataModel
            The plot data model
        """
        print_debug(
            "ImageGridWidget", f"Received data for {plot_data.label}: shape {y.shape}"
        )

        # Find the axis for this plot data
        if artist is None:
            artist = plot_data.artist
        else:
            plot_data.set_artist(artist)
        if artist is None:
            print_debug("ImageGridWidget", "No artist found for plot data")
            return

        try:
            # Plot the image
            if len(y.shape) == 2:
                print_debug(
                    "ImageGridWidget", f"Successfully plotted {plot_data.label}"
                )
                artist.set_data(y)
                artist.autoscale()
            else:
                print_debug("ImageGridWidget", f"Error plotting image data: {y.shape}")
            # Redraw the canvas
            self.draw()

        except Exception as e:
            print_debug("ImageGridWidget", f"Error plotting image data: {e}")

    def _handle_image_draw(self):
        """Handle draw requests from plot data models."""
        # Redraw the canvas
        self.draw()

    def _handle_image_error(self, error_msg):
        """Handle errors from image workers."""
        print_debug("ImageGridWidget", f"Image worker error: {error_msg}")

    def _cleanup_worker(self, key):
        """Clean up a worker thread."""
        if key in self.workers:
            worker = self.workers.pop(key)
            try:
                worker.data_ready.disconnect()
                worker.error_occurred.disconnect()
                worker.quit()
                worker.wait()
                worker.deleteLater()
            except Exception as e:
                print_debug("ImageGridWidget", f"Error cleaning up worker: {e}")

    def _clear_grid(self):
        """Clear all images from the grid."""
        # Stop any active workers
        for key in list(self.workers.keys()):
            self._cleanup_worker(key)

        # Clear subplots
        if hasattr(self, "figure"):
            self.figure.clear()
            self.canvas.draw()

        # Clear plot data models
        for plot_data in self.plotArtists.values():
            plot_data.remove_artist_from_axes()

        # Clear axes reference
        if hasattr(self, "axes"):
            self.axes.clear()

    def _on_selection_changed(self, x_keys, y_keys, norm_keys):
        """Handle changes in data selection."""
        self._update_grid()

    def _on_visible_runs_changed(self, visible_runs):
        """Handle changes in visible runs."""
        self._update_grid()

    def _on_images_per_page_changed(self, value):
        """Handle changes in images per page setting."""
        if value != self._images_per_page:
            self._images_per_page = value
            # Update page spinbox maximum
            max_pages = max(1, (self._total_images - 1) // self._images_per_page + 1)
            self.page_spinbox.setMaximum(max_pages)
            # Adjust current page if it's now out of range
            if self._current_page > max_pages:
                self._current_page = max_pages
                self.page_spinbox.setValue(self._current_page)
            # Update grid layout without re-fetching data
            self._update_grid()

    def _on_page_changed(self, value):
        """Handle changes in page number."""
        if value != self._current_page:
            self._current_page = value
            # Update grid layout without re-fetching data
            self._update_grid()

    def resizeEvent(self, event):
        """Handle resize events."""
        super().resizeEvent(event)
        # Redraw the canvas
        self.draw()
