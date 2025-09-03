from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QStackedWidget,
    QCheckBox,
    QMessageBox,
)
from qtpy.QtCore import Signal
from tiled.client.context import password_grant, device_code_grant, Context
import httpx


class TiledAuthDialog(QDialog):
    """Dialog for handling Tiled authentication."""

    spec_changed = Signal()

    def __init__(self, context: Context, catalog_model=None, parent=None):
        """
        Initialize the Tiled authentication dialog.

        Parameters
        ----------
        context : Context
            The Tiled context that needs authentication
        catalog_model : SourceModel, optional
            The catalog source model that needs authentication
        parent : QWidget, optional
            The parent widget
        """
        super().__init__(parent)
        self.context = context
        self.catalog_model = catalog_model
        self.tokens = None
        self.remember_me = True

        self.setWindowTitle("Tiled Authentication")
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface components."""
        self.layout = QVBoxLayout(self)

        # Status label
        self.status_label = QLabel("Initializing authentication...")
        self.layout.addWidget(self.status_label)

        # Provider dropdown
        self.setup_provider_ui()

        # Stacked widget for different auth methods
        self.auth_stack = QStackedWidget()
        self.layout.addWidget(self.auth_stack)

        # Password grant UI
        self.setup_password_grant_ui()

        # Device code grant UI
        self.setup_device_code_grant_ui()

        # Remember me checkbox
        self.remember_checkbox = QCheckBox(
            "Remember my credentials (Disabled due to Tiled bug)"
        )
        # self.remember_checkbox.setChecked(self.remember_me)
        self.remember_checkbox.setChecked(True)
        self.remember_checkbox.setEnabled(False)
        self.remember_checkbox.setToolTip(
            "If checked, the credentials will be cached and reused for future connections.\n(Do not check for shared machines.)"
        )
        self.layout.addWidget(self.remember_checkbox)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.layout.addWidget(buttons)
        self.setLayout(self.layout)
        # Start authentication check
        self.check_auth_requirements()

    def setup_provider_ui(self):
        providers = self.context.server_info.authentication.providers
        if len(providers) == 1:
            # There is only one choice, so no need to prompt the user.
            self.spec = providers[0]
        else:
            self.spec_dropdown = QComboBox()
            self.spec_dropdown.addItems(
                [f"{i} - {spec.provider}" for i, spec in enumerate(providers, start=1)]
            )
            self.spec_dropdown.currentIndexChanged.connect(self.update_spec)
            self.layout.addWidget(self.spec_dropdown)

    def update_spec(self, index):
        self.spec = self.providers[index]
        self.spec_changed.emit()

    def setup_password_grant_ui(self):
        """Set up the password grant authentication UI."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Add catalog information header if available
        if self.catalog_model:
            catalog_header = self._create_catalog_header()
            layout.addWidget(catalog_header)
            layout.addWidget(QLabel(""))  # Spacer

        layout.addWidget(QLabel("Please enter your credentials:"))

        # Create a form layout for better alignment
        form_layout = QVBoxLayout()

        # Username field with fixed width
        username_layout = QHBoxLayout()
        username_label = QLabel("Username:")
        username_label.setFixedWidth(80)  # Fixed width for alignment
        username_layout.addWidget(username_label)
        self.username_edit = QLineEdit()
        self.username_edit.setMaxLength(20)  # Limit to 20 characters
        self.username_edit.setFixedWidth(200)  # Fixed width for consistency
        username_layout.addWidget(self.username_edit)
        username_layout.addStretch()  # Push fields to the left
        form_layout.addLayout(username_layout)

        # Password field with fixed width
        password_layout = QHBoxLayout()
        password_label = QLabel("Password:")
        password_label.setFixedWidth(80)  # Same width as username label
        password_layout.addWidget(password_label)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMaxLength(20)  # Limit to 20 characters
        self.password_edit.setFixedWidth(200)  # Same width as username field
        password_layout.addWidget(self.password_edit)
        password_layout.addStretch()  # Push fields to the left
        form_layout.addLayout(password_layout)

        layout.addLayout(form_layout)
        self.auth_stack.addWidget(widget)

    def _create_catalog_header(self):
        """Create a header widget showing catalog information."""
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 10, 10, 10)

        # Style the header to make it stand out
        header_widget.setStyleSheet(
            """
            QWidget {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 5px;
            }
            """
        )

        # Create catalog info text using the catalog model properties
        catalog_text = "Connecting to:"

        # Get display information from the catalog model
        if hasattr(self.catalog_model, "get_display_label"):
            display_label = self.catalog_model.get_display_label()
            if display_label:
                catalog_text += f"\n{display_label}"

        # Show profile if available
        if hasattr(self.catalog_model, "profile") and self.catalog_model.profile:
            catalog_text += f"\nProfile: {self.catalog_model.profile}"

        # Show selected catalog keys if available
        if (
            hasattr(self.catalog_model, "selected_keys")
            and self.catalog_model.selected_keys
        ):
            keys = self.catalog_model.selected_keys
            if isinstance(keys, list) and keys:
                catalog_text += f"\nCatalog: {'/'.join(keys)}"
            elif isinstance(keys, str) and keys:
                catalog_text += f"\nCatalog: {keys}"

        catalog_label = QLabel(catalog_text)
        catalog_label.setStyleSheet(
            """
            QLabel {
                color: #333333;
                font-weight: bold;
                font-size: 11px;
            }
            """
        )
        catalog_label.setWordWrap(True)

        header_layout.addWidget(catalog_label)
        return header_widget

    def setup_device_code_grant_ui(self):
        """Set up the device code grant authentication UI."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Please complete the authentication in your browser:"))

        # URL display
        self.url_label = QLabel()
        self.url_label.setWordWrap(True)
        layout.addWidget(self.url_label)

        # Code display
        self.code_label = QLabel()
        self.code_label.setWordWrap(True)
        layout.addWidget(self.code_label)

        # Status text
        self.auth_status = QLabel("Waiting for authentication...")
        layout.addWidget(self.auth_status)

        self.auth_stack.addWidget(widget)

    def check_auth_requirements(self):
        """Check what authentication method the server supports."""

        mode = self.spec.mode
        if mode == "internal" or mode == "password":
            self.auth_stack.setCurrentIndex(0)  # Password grant
            self.status_label.setText("Ready for authentication")
        elif mode == "external":
            self.auth_stack.setCurrentIndex(1)  # Device code grant
            self.status_label.setText(
                "Please complete the authentication in your browser:"
            )
        else:
            QMessageBox.critical(
                self,
                "Authentication Error",
                f"Unsupported authentication mode: {mode}",
            )
            self.reject()

    def accept(self):
        """Handle dialog acceptance."""
        try:
            http_client = self.context.http_client
            auth_endpoint = self.spec.links["auth_endpoint"]
            provider = self.spec.provider
            if self.auth_stack.currentIndex() == 0:  # Password grant
                username = self.username_edit.text()
                password = self.password_edit.text()

                if not username or not password:
                    QMessageBox.warning(
                        self,
                        "Authentication Error",
                        "Please enter both username and password.",
                    )
                    return

                # Here we would call the actual authentication method
                # For now, we'll raise NotImplementedError
                try:
                    twofactorMsg = QMessageBox.information(
                        self,
                        "Two-Factor Authentication",
                        "If you have enabled two-factor authentication, please check your authenticator app for a push after hitting ok",
                    )
                    self.tokens = password_grant(
                        http_client, auth_endpoint, provider, username, password
                    )
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == httpx.codes.UNAUTHORIZED:
                        QMessageBox.critical(
                            self,
                            "Authentication Error",
                            "Invalid username or password. Retry.",
                        )
                    else:
                        QMessageBox.critical(
                            self,
                            "Authentication Error",
                            f"Failed to authenticate: {e}",
                        )
                    return

            elif self.auth_stack.currentIndex() == 1:  # Device code grant
                # Device code grant would be handled differently
                self.tokens = device_code_grant(http_client, auth_endpoint)

            self.remember_me = self.remember_checkbox.isChecked()
            super().accept()

        except Exception as e:
            QMessageBox.critical(
                self, "Authentication Error", f"Authentication failed: {e}"
            )

    def get_tokens(self):
        """Get the authentication tokens."""
        return self.tokens

    def get_remember_me(self):
        """Get the remember me setting."""
        return self.remember_me
