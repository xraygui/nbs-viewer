"""Image grid widget for displaying N-D data cubes as 2D image grids."""

from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QGridLayout,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QLabel,
    QPushButton,
)
from qtpy.QtCore import Qt, QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from ...utils import print_debug
from .plotControl import PlotControls
from ...models.plot.plotDataModel import PlotDataModel
import numpy as np
import uuid


class ImageGridWidget(QWidget):
    """
    Widget for displaying N-D data cubes as a grid of 2D images.

    This widget takes N-D data and displays each 2D slice as a separate
    image in a grid layout, allowing simultaneous viewing of multiple
    images from a data cube.

    Uses the same PlotDataModel + PlotWorker architecture as MplCanvas
    for threaded data loading and proper data management.
    """

    __widget_name__ = "Image Grid"
    __widget_description__ = "Display N-D data as a grid of 2D images"
    __widget_capabilities__ = ["2d", "3d", "4d"]
    __widget_version__ = "1.0.0"
    __widget_author__ = "NBS Viewer Team"

    def __init__(self, plotModel, parent=None):
        """
        Initialize the image grid widget.

        Parameters
        ----------
        plotModel : PlotModel
            The plot model containing the data
        parent : QWidget, optional
            Parent widget
        """
        super().__init__(parent)
        self.plotModel = plotModel

        # Data management (similar to MplCanvas)
        self.plotArtists = {}  # key -> PlotDataModel
        self.workers = {}  # (model_key, worker_key) -> PlotWorker
        self._update_timer_active = False

        # Grid management
        self._current_page = 0
        self._images_per_page = 9  # Default limit
        self._total_images = 0
        self._image_shape = None
        self._full_shape = None

        # UI setup
        self._setup_ui()

        # Connect to model signals
        self.plotModel.selected_keys_changed.connect(self._on_selection_changed)
        self.plotModel.visible_runs_changed.connect(self._on_visible_runs_changed)
        self.plotModel.request_plot_update.connect(self._update_grid)

        # Initial update
        self._update_grid()

    def _setup_ui(self):
        """Set up the user interface."""
        # Main layout
        main_layout = QHBoxLayout(self)  # Changed to horizontal for sidebars

        # Center area with grid and paging controls
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)

        # Grid area (takes most space)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Grid container
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(10)
        self.scroll_area.setWidget(self.grid_container)

        # Paging controls (at bottom)
        paging_widget = QWidget()
        paging_layout = QHBoxLayout(paging_widget)

        # Images per page control
        paging_layout.addWidget(QLabel("Images per page:"))
        self.images_per_page_spinbox = QSpinBox()
        self.images_per_page_spinbox.setMinimum(1)
        self.images_per_page_spinbox.setMaximum(100)
        self.images_per_page_spinbox.setValue(
            self._images_per_page
        )  # Start with 9 for testing
        self.images_per_page_spinbox.valueChanged.connect(
            self._on_images_per_page_changed
        )
        paging_layout.addWidget(self.images_per_page_spinbox)

        # Page navigation
        paging_layout.addWidget(QLabel("Page:"))
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setValue(1)
        self.page_spinbox.valueChanged.connect(self._on_page_changed)
        paging_layout.addWidget(self.page_spinbox)

        # Total images label
        self.total_images_label = QLabel("Total: 0 images")
        paging_layout.addWidget(self.total_images_label)

        paging_layout.addStretch()

        # Add widgets to center layout
        center_layout.addWidget(self.scroll_area)  # Grid takes most space
        center_layout.addWidget(paging_widget)  # Paging at bottom

        # Right sidebar (plot controls)
        self.plotControls = PlotControls(self.plotModel)

        # Add all widgets to main layout
        main_layout.addWidget(center_widget)  # Center area first
        main_layout.addWidget(self.plotControls)  # Right sidebar

        # Set layout proportions (center: 70%, right sidebar: 30%)
        main_layout.setStretch(0, 70)  # center_widget
        main_layout.setStretch(1, 30)  # plotControls

    def _get_shape_info(self):
        """
        Get shape information from visible models.

        Returns
        -------
        tuple or None
            (shape, dim_names, axis_arrays, associated_data) or None if no data
        """
        visible_models = self.plotModel.visible_models
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

    def _process_nd_data(self, shape):
        """
        Process N-D data and determine how many images to display.

        Parameters
        ----------
        shape : tuple
            Shape of the N-D data

        Returns
        -------
        tuple
            (total_images, image_shape, non_image_dims, full_shape) or None if invalid
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

        print_debug("ImageGridWidget", f"Image shape: {image_shape}")
        print_debug("ImageGridWidget", f"Non-image dims: {non_image_dims}")
        print_debug("ImageGridWidget", f"Non-dummy dims: {non_dummy_dims}")
        print_debug("ImageGridWidget", f"Total images: {total_images}")

        return total_images, image_shape, non_image_dims, shape

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
        nd_result = self._process_nd_data(shape)
        if not nd_result:
            return

        total_images, image_shape, non_image_dims, full_shape = nd_result

        # Update state
        self._total_images = total_images
        self._image_shape = image_shape
        self._full_shape = full_shape

        # Update UI
        self.total_images_label.setText(f"Total: {total_images} images")
        self.page_spinbox.setMaximum(
            max(1, (total_images - 1) // self._images_per_page + 1)
        )

        print_debug("ImageGridWidget", f"Will create {total_images} images")
        print_debug("ImageGridWidget", f"Images per page: {self._images_per_page}")
        print_debug("ImageGridWidget", f"Current page: {self._current_page}")

        # Calculate start and end indices for current page
        start_idx = self._current_page * self._images_per_page
        end_idx = min(start_idx + self._images_per_page, total_images)

        print_debug("ImageGridWidget", f"Displaying images {start_idx} to {end_idx-1}")

        # Create images for current page only
        self._create_images_for_page(start_idx, end_idx, full_shape)

    def _create_images_for_page(self, start_idx, end_idx, full_shape):
        """
        Create images for the specified page range.

        Parameters
        ----------
        start_idx : int
            Starting image index
        end_idx : int
            Ending image index (exclusive)
        full_shape : tuple
            Full shape of the data
        """
        visible_models = self.plotModel.visible_models
        if not visible_models:
            return

        run_model = visible_models[0]
        x_keys, y_keys, norm_keys = run_model.get_selected_keys()

        if not y_keys:
            return

        y_key = y_keys[0]

        # Calculate grid dimensions for this page only
        images_this_page = end_idx - start_idx
        cols = min(3, int(np.ceil(np.sqrt(images_this_page))))  # Max 3 cols
        rows = int(np.ceil(images_this_page / cols))

        print_debug(
            "ImageGridWidget",
            f"Creating {images_this_page} images in {rows}x{cols} grid",
        )

        # Create images for this page only
        for i in range(images_this_page):
            image_idx = start_idx + i
            row = i // cols
            col = i % cols

            try:
                # Create slice indices for this image
                # Keep all dimensions, including dummy ones
                slice_indices = [0] * len(full_shape)
                slice_indices[0] = image_idx  # Use first dimension for iteration

                # Convert to proper slice format
                # Last 2 dimensions should be full slices for 2D image data
                slice_info = []
                for j, dim_size in enumerate(full_shape):
                    if j < len(slice_indices):
                        if j >= len(full_shape) - 2:
                            # Last 2 dimensions get full slices
                            slice_info.append(slice(None, None, None))
                        else:
                            # Other dimensions get integer index
                            slice_info.append(slice_indices[j])
                    else:
                        slice_info.append(slice(None, None, None))

                slice_info = tuple(slice_info)
                print_debug(
                    "ImageGridWidget",
                    f"Processing image {image_idx} with indices {slice_info}",
                )

                # Create PlotDataModel for this image
                self._create_image_plot_data(
                    run_model, x_keys, y_key, norm_keys, slice_info, image_idx, row, col
                )

            except Exception as e:
                print_debug("ImageGridWidget", f"Error creating image {image_idx}: {e}")

    def _create_image_plot_data(
        self, run_model, x_keys, y_key, norm_keys, slice_info, image_idx, row, col
    ):
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
        row : int
            Grid row position
        col : int
            Grid column position
        """
        # Create unique key for this image
        key = (x_keys[0] if x_keys else "", y_key, run_model.uid, image_idx)

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
            plot_data.data_changed.connect(self._handle_image_data)
            plot_data.draw_requested.connect(self._handle_image_draw)

            # Store reference
            self.plotArtists[key] = plot_data

            # Create canvas for this image
            self._create_image_canvas(key, row, col, image_idx)

            # Start data loading
            self._start_image_worker(plot_data, slice_info, 2, key)

    def _create_image_canvas(self, key, row, col, image_idx):
        """
        Create a matplotlib canvas for a single image.

        Parameters
        ----------
        key : tuple
            Unique key for this image
        row : int
            Grid row position
        col : int
            Grid column position
        image_idx : int
            Index of this image
        """
        # Create figure and canvas
        fig = Figure(figsize=(4, 4), dpi=100)
        canvas = FigureCanvasQTAgg(fig)
        canvas.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        canvas.setFixedSize(250, 250)  # Larger size

        # Create axes
        ax = fig.add_subplot(111)
        ax.set_title(f"Image {image_idx}")

        # Store canvas reference
        if not hasattr(self, "_image_canvases"):
            self._image_canvases = {}
        self._image_canvases[key] = canvas

        # Add to grid
        self.grid_layout.addWidget(canvas, row, col)

    def _start_image_worker(self, plot_data, slice_info, dimension, key):
        """
        Start a PlotWorker for loading image data.

        Parameters
        ----------
        plot_data : PlotDataModel
            The plot data model
        slice_info : tuple
            Slice indices
        dimension : int
            Plot dimension
        key : tuple
            Unique key for this image
        """
        from .plotWidget import PlotWorker

        print_debug("ImageGridWidget", f"Starting worker for image {plot_data.label}")

        # Create worker
        worker_key = str(uuid.uuid4())
        worker = PlotWorker(plot_data, slice_info, dimension)
        worker.data_ready.connect(self._handle_image_data)
        worker.error_occurred.connect(self._handle_image_error)
        worker.finished.connect(lambda: self._cleanup_worker((key, worker_key)))

        # Store worker reference and start it
        self.workers[(key, worker_key)] = worker
        worker.start()

    def _handle_image_data(self, x, y, plot_data):
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

        # Find the canvas for this plot data
        canvas = None
        for key, stored_plot_data in self.plotArtists.items():
            if stored_plot_data == plot_data:
                if hasattr(self, "_image_canvases") and key in self._image_canvases:
                    canvas = self._image_canvases[key]
                break

        if canvas is None:
            print_debug("ImageGridWidget", "No canvas found for plot data")
            return

        try:
            # Clear existing plot
            ax = canvas.figure.axes[0]
            ax.clear()

            # Plot the image
            if len(y.shape) == 2:
                im = ax.imshow(y, cmap="viridis", aspect="auto")
                ax.set_title(f"Image {plot_data.label}")

                # Add colorbar
                canvas.figure.colorbar(im, ax=ax)

                # Remove axis labels for cleaner look
                ax.set_xticks([])
                ax.set_yticks([])

            canvas.draw()
            print_debug("ImageGridWidget", f"Successfully plotted {plot_data.label}")

        except Exception as e:
            print_debug("ImageGridWidget", f"Error plotting image data: {e}")

    def _handle_image_draw(self):
        """Handle draw requests from plot data models."""
        # Redraw all canvases
        if hasattr(self, "_image_canvases"):
            for canvas in self._image_canvases.values():
                canvas.draw()

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

        # Clear canvases
        if hasattr(self, "_image_canvases"):
            for canvas in self._image_canvases.values():
                canvas.deleteLater()
            self._image_canvases.clear()

        # Clear plot data models
        for plot_data in self.plotArtists.values():
            plot_data.clear()
        self.plotArtists.clear()

    def _on_selection_changed(self, x_keys, y_keys, norm_keys):
        """Handle changes in data selection."""
        self._update_grid()

    def _on_visible_runs_changed(self, visible_runs):
        """Handle changes in visible runs."""
        self._update_grid()

    def _on_images_per_page_changed(self, value):
        """Handle changes in images per page setting."""
        self._images_per_page = value
        self._update_grid()

    def _on_page_changed(self, value):
        """Handle changes in page number."""
        self._current_page = value - 1  # Convert to 0-based
        self._update_grid()

    def resizeEvent(self, event):
        """Handle resize events."""
        super().resizeEvent(event)
        # Redraw all canvases
        if hasattr(self, "_image_canvases"):
            for canvas in self._image_canvases.values():
                canvas.draw()
