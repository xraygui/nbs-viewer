import argparse
from qtpy.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QWidget,
    QMainWindow,
    QAction,
    QInputDialog,
    QMessageBox,
)

from .mainWidget import MainWidget
from .models.app_model import AppModel
from .utils import turn_on_debugging, turn_off_debugging, set_top_level_model
from .logging_setup import setup_logging

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
        # Create app-level model and pass into MainWidget
        self.app_model = AppModel(config_file)
        set_top_level_model(self.app_model)
        self.mainWidget = MainWidget(
            central_widget, config_file=config_file, app_model=self.app_model
        )
        self.main_display = self.mainWidget.main_display
        self.data_source = self.main_display.data_source
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

        """
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
        """

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
        add_source_action = QAction("&Add Catalog...", self)
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
        """
        refresh_action = QAction("&Refresh Current Catalog", self)
        refresh_action.setShortcut("F5")
        refresh_action.setStatusTip("Refresh current catalog")
        refresh_action.triggered.connect(self._on_refresh_catalogs)
        catalog_menu.addAction(refresh_action)
        """

        clear_selected_run_action = QAction("&Deselect Runs", self)
        clear_selected_run_action.setShortcut("Ctrl+Shift+D")
        clear_selected_run_action.setStatusTip("Deselect all runs")
        clear_selected_run_action.triggered.connect(self._on_clear_selected_run)
        catalog_menu.addAction(clear_selected_run_action)

        """
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
        catalog_menu.addAction(catalog_settings_action) """

        # Switch Catalog (submenu)
        self.switch_catalog_menu = catalog_menu.addMenu("&Switch Catalog")
        self.app_model.catalogs.catalogs_changed.connect(
            self._update_switch_catalog_menu
        )
        self._update_switch_catalog_menu()

        # Display Menu
        display_menu = menubar.addMenu("&Display")

        # New Display
        new_display_action = QAction("&New Display", self)
        new_display_action.setShortcut("Ctrl+N")
        new_display_action.setStatusTip("Create a new display")
        new_display_action.triggered.connect(self._on_new_display)
        display_menu.addAction(new_display_action)

        display_menu.addSeparator()

        # New Matplotlib Display
        new_mpl_display_action = QAction("New &Matplotlib Display", self)
        new_mpl_display_action.setShortcut("Ctrl+Shift+M")
        new_mpl_display_action.setStatusTip("Create a new matplotlib display")
        new_mpl_display_action.triggered.connect(self._on_new_matplotlib_display)
        display_menu.addAction(new_mpl_display_action)

        # New Image Grid Display
        new_image_grid_action = QAction("New &Image Grid Display", self)
        new_image_grid_action.setShortcut("Ctrl+Shift+I")
        new_image_grid_action.setStatusTip("Create a new image grid display")
        new_image_grid_action.triggered.connect(self._on_new_image_grid_display)
        display_menu.addAction(new_image_grid_action)

        display_menu.addSeparator()

        rename_display_action = QAction("&Rename Display", self)
        rename_display_action.setShortcut("Ctrl+Shift+R")
        rename_display_action.setStatusTip("Rename the current display")
        rename_display_action.triggered.connect(self._on_rename_display)
        display_menu.addAction(rename_display_action)

        # Close Display
        close_display_action = QAction("&Close Display", self)
        close_display_action.setShortcut("Ctrl+W")
        close_display_action.setStatusTip("Close the current display")
        close_display_action.triggered.connect(self._on_close_display)
        display_menu.addAction(close_display_action)

        # Keep duplicate for potential quick copy; no-op for now

        display_menu.addSeparator()

        # Remove unused display actions for now

        # Remove unused display actions for now

    def _update_switch_catalog_menu(self):
        """Update the switch catalog submenu with available catalogs."""
        # Clear existing items
        self.switch_catalog_menu.clear()
        labels = self.app_model.catalogs.get_catalog_labels()
        for label in labels:
            action = QAction(label, self)
            action.triggered.connect(
                lambda checked=False, lbl=label: self._on_switch_catalog(lbl)
            )
            self.switch_catalog_menu.addAction(action)

    # File menu action handlers
    def _on_open_catalog_config(self):
        """Handle opening a catalog configuration file."""
        from qtpy.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Catalog Configuration",
            "",
            "TOML files (*.toml);;All files (*)",
        )
        if path:
            self.data_source.load_catalog_config(path)
            self._update_switch_catalog_menu()

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
        self.data_source.add_uri_source()

    def _on_add_catalog_source(self):
        """Handle adding a catalog source."""
        self.data_source.add_new_source()

    def _on_remove_catalog(self):
        """Handle removing a catalog source."""
        self.data_source.remove_current_source()

    '''
    def _on_refresh_catalogs(self):
        """Handle refreshing all catalogs."""
        self.data_source.refresh_catalog()
    '''

    def _on_clear_selected_run(self):
        """Handle clearing selected run."""
        self.data_source.deselect_all()

    def _on_clear_cache(self):
        """Handle clearing cache."""
        # TODO: Implement cache clearing
        print("Clear cache - not implemented yet")

    def _on_catalog_settings(self):
        """Handle catalog settings."""
        # TODO: Implement catalog settings dialog
        print("Catalog settings - not implemented yet")

    def _on_switch_catalog(self, label: str):
        """Switch active catalog by label from submenu."""
        self.data_source.switch_to_label(label)
        if self.app_model is not None:
            self.app_model.catalogs.set_current_catalog(label)

    # Display menu action handlers
    def _on_new_display(self):
        """Handle creating a new display."""
        self.mainWidget.create_display("matplotlib")

    def _on_new_matplotlib_display(self):
        """Handle creating a new matplotlib display."""
        # TODO: Implement matplotlib display creation
        self.mainWidget.create_matplotlib_display()

    def _on_new_image_grid_display(self):
        """Handle creating a new image grid display."""
        # TODO: Implement image grid display creation
        self.mainWidget.create_image_grid_display()

    def _on_close_display(self):
        """Handle closing the current display."""
        # TODO: Implement display closing
        self.mainWidget.close_current_display()

    def _on_duplicate_display(self):
        """Handle duplicating the current display."""
        # TODO: Implement display duplication
        self.mainWidget.duplicate_current_display()

    def _on_display_settings(self):
        """Handle display settings."""
        # TODO: Implement display settings dialog
        print("Display settings - not implemented yet")

    def _on_save_display_layout(self):
        """Handle saving display layout."""
        # TODO: Implement display layout saving
        print("Save display layout - not implemented yet")

    def _on_rename_display(self):
        """Handle renaming the current display."""
        current_display_id = self.mainWidget.get_current_display().display_id
        if current_display_id == "main":
            QMessageBox.warning(self, "Cannot Rename", "Cannot rename the main display")
            return
        popup = QInputDialog(self)
        popup.setWindowTitle("Rename Display")
        popup.setLabelText("Enter the new name for the display:")
        if popup.exec_():
            new_name = popup.textValue()
            self.app_model.display_manager.rename_display(current_display_id, new_name)


def main():
    parser = argparse.ArgumentParser(description="NBS Viewer")
    parser.add_argument("-f", "--config", help="Path to the catalog config file")
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug mode (equivalent to --log-level DEBUG)",
    )
    parser.add_argument(
        "--log-level",
        choices=[
            "CRITICAL",
            "ERROR",
            "WARNING",
            "INFO",
            "DEBUG",
            "NOTSET",
        ],
        help="Set logging verbosity (overrides --debug if provided)",
    )
    args = parser.parse_args()
    effective_level = args.log_level or ("DEBUG" if args.debug else "INFO")
    setup_logging(level=effective_level, http_to_file="http_debug.log")
    if effective_level == "DEBUG":
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
