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

    def __init__(self, context: Context, parent=None):
        """
        Initialize the Tiled authentication dialog.

        Parameters
        ----------
        context : Context
            The Tiled context that needs authentication
        parent : QWidget, optional
            The parent widget
        """
        super().__init__(parent)
        self.context = context
        self.tokens = None
        self.remember_me = True

        self.setWindowTitle("Tiled Authentication")
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface components."""
        self.layout = QVBoxLayout(self)

        # Status label
        self.status_label = QLabel("Checking authentication requirements...")
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
        self.remember_checkbox = QCheckBox("Remember my credentials")
        self.remember_checkbox.setChecked(self.remember_me)
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

        layout.addWidget(QLabel("Please enter your credentials:"))

        # Username field
        username_layout = QHBoxLayout()
        username_layout.addWidget(QLabel("Username:"))
        self.username_edit = QLineEdit()
        username_layout.addWidget(self.username_edit)
        layout.addLayout(username_layout)

        # Password field
        password_layout = QHBoxLayout()
        password_layout.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        password_layout.addWidget(self.password_edit)
        layout.addLayout(password_layout)

        self.auth_stack.addWidget(widget)

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
            self.status_label.setText("Please enter your credentials:")
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
