import argparse
from qtpy.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QMainWindow,
    QMenuBar,
    QMenu,
    QAction,
)
from qtpy.QtCore import Qt
from .mainWidget import MainWidget
from .utils import turn_on_debugging, turn_off_debugging

# import logging

# logging.basicConfig(
#    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
# )


class Viewer(QMainWindow):
    def __init__(self, config_file=None, parent=None):
        super(Viewer, self).__init__(parent)

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.layout = QVBoxLayout(central_widget)
        # Create a QTabWidget
        self.mainWidget = MainWidget(central_widget, config_file=config_file)
        self.layout.addWidget(self.mainWidget)
        central_widget.setLayout(self.layout)
        self._create_menu_bar()

    def _create_menu_bar(self):
        """Create the application menu bar."""
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("&File")

        # Open Catalog Config
        open_config_action = QAction("&Open Catalog Config...", self)
        open_config_action.setShortcut("Ctrl+O")
        open_config_action.setStatusTip("Open a catalog configuration file")
        open_config_action.triggered.connect(self._on_open_catalog_config)
        file_menu.addAction(open_config_action)

        file_menu.addSeparator()

        # Save Plot
        save_plot_action = QAction("&Save Plot As...", self)
        save_plot_action.setShortcut("Ctrl+S")
        save_plot_action.setStatusTip("Save the current plot as an image")
        save_plot_action.triggered.connect(self._on_save_plot)
        file_menu.addAction(save_plot_action)

        # Export Data
        export_data_action = QAction("&Export Data...", self)
        export_data_action.setShortcut("Ctrl+E")
        export_data_action.setStatusTip("Export plot data to a file")
        export_data_action.triggered.connect(self._on_export_data)
        file_menu.addAction(export_data_action)

        file_menu.addSeparator()

        # Print
        print_action = QAction("&Print...", self)
        print_action.setShortcut("Ctrl+P")
        print_action.setStatusTip("Print the current plot")
        print_action.triggered.connect(self._on_print)
        file_menu.addAction(print_action)

        file_menu.addSeparator()

        # Exit
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.setStatusTip("Exit the application")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Catalog Menu
        catalog_menu = menubar.addMenu("&Catalog")

        # Connect to Tiled URI
        connect_uri_action = QAction("Connect to &Tiled URI...", self)
        connect_uri_action.setShortcut("Ctrl+Shift+O")
        connect_uri_action.setStatusTip("Connect to a remote Tiled server")
        connect_uri_action.triggered.connect(self._on_connect_tiled_uri)
        catalog_menu.addAction(connect_uri_action)

        # Add Catalog Source
        add_source_action = QAction("&Add Catalog Source...", self)
        add_source_action.setShortcut("Ctrl+Shift+A")
        add_source_action.setStatusTip("Add a new catalog source")
        add_source_action.triggered.connect(self._on_add_catalog_source)
        catalog_menu.addAction(add_source_action)

        # Remove Catalog
        remove_catalog_action = QAction("&Remove Catalog...", self)
        remove_catalog_action.setShortcut("Ctrl+Shift+R")
        remove_catalog_action.setStatusTip("Remove a catalog source")
        remove_catalog_action.triggered.connect(self._on_remove_catalog)
        catalog_menu.addAction(remove_catalog_action)

        catalog_menu.addSeparator()

        # Refresh All Catalogs
        refresh_action = QAction("&Refresh Current Catalog", self)
        refresh_action.setShortcut("F5")
        refresh_action.setStatusTip("Refresh current catalog")
        refresh_action.triggered.connect(self._on_refresh_catalogs)
        catalog_menu.addAction(refresh_action)

        # Refresh All Catalogs
        clear_selected_run_action = QAction("&Deselect Runs", self)
        clear_selected_run_action.setShortcut("Ctrl+Shift+D")
        clear_selected_run_action.setStatusTip("Deselect all runs")
        clear_selected_run_action.triggered.connect(self._on_clear_selected_run)
        catalog_menu.addAction(clear_selected_run_action)

        # Clear Cache
        clear_cache_action = QAction("&Clear Cache", self)
        clear_cache_action.setShortcut("Ctrl+Shift+C")
        clear_cache_action.setStatusTip("Clear catalog cache")
        clear_cache_action.triggered.connect(self._on_clear_cache)
        catalog_menu.addAction(clear_cache_action)

        catalog_menu.addSeparator()

        # Catalog Settings
        catalog_settings_action = QAction("Catalog &Settings...", self)
        catalog_settings_action.setShortcut("Ctrl+Shift+S")
        catalog_settings_action.setStatusTip("Configure catalog settings")
        catalog_settings_action.triggered.connect(self._on_catalog_settings)
        catalog_menu.addAction(catalog_settings_action)

        # Switch Catalog (submenu)
        self.switch_catalog_menu = catalog_menu.addMenu("&Switch Catalog")
        self._update_switch_catalog_menu()

        # Canvas Menu
        canvas_menu = menubar.addMenu("&Canvas")

        # New Canvas
        new_canvas_action = QAction("&New Canvas", self)
        new_canvas_action.setShortcut("Ctrl+N")
        new_canvas_action.setStatusTip("Create a new canvas")
        new_canvas_action.triggered.connect(self._on_new_canvas)
        canvas_menu.addAction(new_canvas_action)

        canvas_menu.addSeparator()

        # New Matplotlib Canvas
        new_mpl_canvas_action = QAction("New &Matplotlib Canvas", self)
        new_mpl_canvas_action.setShortcut("Ctrl+Shift+M")
        new_mpl_canvas_action.setStatusTip("Create a new matplotlib canvas")
        new_mpl_canvas_action.triggered.connect(self._on_new_matplotlib_canvas)
        canvas_menu.addAction(new_mpl_canvas_action)

        # New Image Grid Canvas
        new_image_grid_action = QAction("New &Image Grid Canvas", self)
        new_image_grid_action.setShortcut("Ctrl+Shift+I")
        new_image_grid_action.setStatusTip("Create a new image grid canvas")
        new_image_grid_action.triggered.connect(self._on_new_image_grid_canvas)
        canvas_menu.addAction(new_image_grid_action)

        canvas_menu.addSeparator()

        # Close Canvas
        close_canvas_action = QAction("&Close Canvas", self)
        close_canvas_action.setShortcut("Ctrl+W")
        close_canvas_action.setStatusTip("Close the current canvas")
        close_canvas_action.triggered.connect(self._on_close_canvas)
        canvas_menu.addAction(close_canvas_action)

        # Duplicate Canvas
        duplicate_canvas_action = QAction("&Duplicate Canvas", self)
        duplicate_canvas_action.setShortcut("Ctrl+D")
        duplicate_canvas_action.setStatusTip("Duplicate the current canvas")
        duplicate_canvas_action.triggered.connect(self._on_duplicate_canvas)
        canvas_menu.addAction(duplicate_canvas_action)

        canvas_menu.addSeparator()

        # Canvas Settings
        canvas_settings_action = QAction("Canvas &Settings...", self)
        canvas_settings_action.setShortcut("Ctrl+Shift+E")
        canvas_settings_action.setStatusTip("Configure canvas settings")
        canvas_settings_action.triggered.connect(self._on_canvas_settings)
        canvas_menu.addAction(canvas_settings_action)

        # Save Canvas Layout
        save_layout_action = QAction("Save Canvas &Layout...", self)
        save_layout_action.setShortcut("Ctrl+Shift+L")
        save_layout_action.setStatusTip("Save the current canvas layout")
        save_layout_action.triggered.connect(self._on_save_canvas_layout)
        canvas_menu.addAction(save_layout_action)

    def _update_switch_catalog_menu(self):
        """Update the switch catalog submenu with available catalogs."""
        # Clear existing items
        self.switch_catalog_menu.clear()

        for label in self.mainWidget.data_source.get_catalog_labels():
            self.switch_catalog_menu.addAction(QAction(label, self))

    # File menu action handlers
    def _on_open_catalog_config(self):
        """Handle opening a catalog configuration file."""
        # TODO: Implement file dialog and catalog loading
        print("Open catalog config - not implemented yet")

    def _on_save_plot(self):
        """Handle saving the current plot."""
        # TODO: Implement plot saving
        print("Save plot - not implemented yet")

    def _on_export_data(self):
        """Handle exporting data."""
        # TODO: Implement data export
        print("Export data - not implemented yet")

    def _on_print(self):
        """Handle printing."""
        # TODO: Implement printing
        print("Print - not implemented yet")

    # Catalog menu action handlers
    def _on_connect_tiled_uri(self):
        """Handle connecting to a Tiled URI."""
        self.mainWidget.data_source.add_uri_source()

    def _on_add_catalog_source(self):
        """Handle adding a catalog source."""
        self.mainWidget.data_source.add_new_source()

    def _on_remove_catalog(self):
        """Handle removing a catalog source."""
        self.mainWidget.data_source.remove_current_source()

    def _on_refresh_catalogs(self):
        """Handle refreshing all catalogs."""
        self.mainWidget.data_source.refresh_catalog()

    def _on_clear_selected_run(self):
        """Handle clearing selected run."""
        catalog = self.mainWidget.data_source.get_current_catalog()
        if catalog is not None:
            catalog.deselect_all()

    def _on_clear_cache(self):
        """Handle clearing cache."""
        # TODO: Implement cache clearing
        print("Clear cache - not implemented yet")

    def _on_catalog_settings(self):
        """Handle catalog settings."""
        # TODO: Implement catalog settings dialog
        print("Catalog settings - not implemented yet")

    # Canvas menu action handlers
    def _on_new_canvas(self):
        """Handle creating a new canvas."""
        self.mainWidget.create_canvas("matplotlib")

    def _on_new_matplotlib_canvas(self):
        """Handle creating a new matplotlib canvas."""
        # TODO: Implement matplotlib canvas creation
        self.mainWidget.create_matplotlib_canvas()

    def _on_new_image_grid_canvas(self):
        """Handle creating a new image grid canvas."""
        # TODO: Implement image grid canvas creation
        self.mainWidget.create_image_grid_canvas()

    def _on_close_canvas(self):
        """Handle closing the current canvas."""
        # TODO: Implement canvas closing
        self.mainWidget.close_current_canvas()

    def _on_duplicate_canvas(self):
        """Handle duplicating the current canvas."""
        # TODO: Implement canvas duplication
        self.mainWidget.duplicate_current_canvas()

    def _on_canvas_settings(self):
        """Handle canvas settings."""
        # TODO: Implement canvas settings dialog
        print("Canvas settings - not implemented yet")

    def _on_save_canvas_layout(self):
        """Handle saving canvas layout."""
        # TODO: Implement canvas layout saving
        print("Save canvas layout - not implemented yet")


def main():
    parser = argparse.ArgumentParser(description="NBS Viewer")
    parser.add_argument("-f", "--config", help="Path to the catalog config file")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    if args.debug:
        print("Debug statements on")
        turn_on_debugging()
    else:
        turn_off_debugging()
    print("Starting Viewer Main")
    app = QApplication([])
    viewer = Viewer(config_file=args.config)
    viewer.show()
    app.exec_()


if __name__ == "__main__":
    main()
