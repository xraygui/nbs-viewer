import time
import webbrowser

import httpx
from qtpy.QtCore import Qt, QThread, QTimer, Signal
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
    QProgressBar,
)
from tiled.client.context import password_grant, Context
from tiled.client.utils import handle_error


class DeviceCodeGrantWorker(QThread):
    """
    Poll Tiled/OIDC device-code grant without blocking the Qt event loop.

    Parameters
    ----------
    http_client : httpx.Client
        Authenticated Tiled HTTP client (cookies/CSRF must already be set).
    auth_endpoint : str
        Device-authorization endpoint URL.
    client_id : str or None
        OAuth2 client id when the server uses an external OIDC device flow.
    token_endpoint : str or None
        Token endpoint for OAuth2 device flow. Unused for Tiled's own flow.
    scopes : str, optional
        Space-separated OAuth2 scopes. Default is ``"openid offline_access"``.
    parent : QObject, optional
        Qt parent.
    """

    verification_ready = Signal(str, str, float)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        http_client,
        auth_endpoint,
        client_id=None,
        token_endpoint=None,
        scopes="openid offline_access",
        parent=None,
    ):
        super().__init__(parent)
        self.http_client = http_client
        self.auth_endpoint = auth_endpoint
        self.client_id = client_id
        self.token_endpoint = token_endpoint
        self.scopes = scopes

    def _interrupted_sleep(self, seconds):
        """
        Sleep in short chunks so cancellation remains responsive.

        Parameters
        ----------
        seconds : float
            Total sleep duration in seconds.

        Returns
        -------
        bool
            True if interruption was requested during the sleep.
        """
        end = time.monotonic() + float(seconds)
        while time.monotonic() < end:
            if self.isInterruptionRequested():
                return True
            time.sleep(min(0.2, end - time.monotonic()))
        return self.isInterruptionRequested()

    def run(self):
        """
        Request a device code and poll until authorized, expired, or cancelled.
        """
        try:
            if self.client_id and self.token_endpoint:
                oauth2_spec = True
                verification_response = self.http_client.post(
                    self.auth_endpoint,
                    data={"client_id": self.client_id, "scope": self.scopes},
                )
                handle_error(verification_response)
                verification = verification_response.json()
                keys = [
                    "verification_uri_complete",
                    "verification_uri",
                    "verification_url",
                ]
                verification_uri = None
                for key in keys:
                    verification_uri = verification.get(key)
                    if verification_uri:
                        break
                if not verification_uri:
                    raise KeyError(
                        "Verification response is missing expected keys. "
                        f"Expected one of {keys}. Got: {verification}"
                    )
                token_endpoint = self.token_endpoint
            else:
                oauth2_spec = False
                verification_response = self.http_client.post(self.auth_endpoint)
                handle_error(verification_response)
                verification = verification_response.json()
                token_endpoint = verification["verification_uri"]
                verification_uri = verification["authorization_uri"]

            user_code = verification["user_code"]
            expires_in = float(verification["expires_in"])
            interval = float(verification["interval"])
            self.verification_ready.emit(verification_uri, user_code, expires_in)

            deadline = expires_in + time.monotonic()
            access_response = None
            while True:
                if self._interrupted_sleep(interval):
                    return
                if time.monotonic() > deadline:
                    self.failed.emit("Authentication deadline expired.")
                    return

                if oauth2_spec:
                    access_response = self.http_client.post(
                        token_endpoint,
                        data={
                            "device_code": verification["device_code"],
                            "grant_type": (
                                "urn:ietf:params:oauth:grant-type:device_code"
                            ),
                            "client_id": self.client_id,
                        },
                    )
                else:
                    access_response = self.http_client.post(
                        token_endpoint,
                        json={
                            "device_code": verification["device_code"],
                            "grant_type": (
                                "urn:ietf:params:oauth:grant-type:device_code"
                            ),
                        },
                        auth=None,
                    )

                if access_response.status_code == httpx.codes.BAD_REQUEST:
                    payload = access_response.json()
                    access_response_error = (
                        payload["error"]
                        if oauth2_spec
                        else payload["detail"]["error"]
                    )
                    if access_response_error == "authorization_pending":
                        continue
                    access_response.raise_for_status()

                handle_error(access_response)
                if self.isInterruptionRequested():
                    return
                self.succeeded.emit(access_response.json())
                return
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


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
        self.providers = list(context.server_info.authentication.providers)
        self._device_worker = None
        self._auth_deadline = None

        self.setWindowTitle("Tiled Authentication")
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface components."""
        self.layout = QVBoxLayout(self)

        self.status_label = QLabel("Initializing authentication...")
        self.layout.addWidget(self.status_label)

        self.setup_provider_ui()

        self.auth_stack = QStackedWidget()
        self.layout.addWidget(self.auth_stack)

        self.setup_password_grant_ui()
        self.setup_device_code_grant_ui()

        self.remember_checkbox = QCheckBox(
            "Remember my credentials"
        )
        self.remember_checkbox.setChecked(True)
        self.remember_checkbox.setToolTip(
            "If checked, the credentials will be cached and reused for future connections.\n(Do not check for shared machines.)"
        )
        self.layout.addWidget(self.remember_checkbox)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)
        self.setLayout(self.layout)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(200)
        self._countdown_timer.timeout.connect(self._update_countdown)

        self.check_auth_requirements()

    def setup_provider_ui(self):
        """
        Configure the authentication provider selector.
        """
        if len(self.providers) == 1:
            self.spec = self.providers[0]
        else:
            self.spec = self.providers[0]
            self.spec_dropdown = QComboBox()
            self.spec_dropdown.addItems(
                [
                    f"{i} - {spec.provider}"
                    for i, spec in enumerate(self.providers, start=1)
                ]
            )
            self.spec_dropdown.currentIndexChanged.connect(self.update_spec)
            self.layout.addWidget(self.spec_dropdown)

    def update_spec(self, index):
        """
        Update the selected authentication provider.

        Parameters
        ----------
        index : int
            Index into ``self.providers``.
        """
        self.spec = self.providers[index]
        self.spec_changed.emit()
        self.check_auth_requirements()

    def setup_password_grant_ui(self):
        """Set up the password grant authentication UI."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        if self.catalog_model:
            catalog_header = self._create_catalog_header()
            layout.addWidget(catalog_header)
            layout.addWidget(QLabel(""))

        layout.addWidget(QLabel("Please enter your credentials:"))

        form_layout = QVBoxLayout()

        username_layout = QHBoxLayout()
        username_label = QLabel("Username:")
        username_label.setFixedWidth(80)
        username_layout.addWidget(username_label)
        self.username_edit = QLineEdit()
        self.username_edit.setMaxLength(20)
        self.username_edit.setFixedWidth(200)
        username_layout.addWidget(self.username_edit)
        username_layout.addStretch()
        form_layout.addLayout(username_layout)

        password_layout = QHBoxLayout()
        password_label = QLabel("Password:")
        password_label.setFixedWidth(80)
        password_layout.addWidget(password_label)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMaxLength(20)
        self.password_edit.setFixedWidth(200)
        password_layout.addWidget(self.password_edit)
        password_layout.addStretch()
        form_layout.addLayout(password_layout)

        layout.addLayout(form_layout)
        self.auth_stack.addWidget(widget)

    def _create_catalog_header(self):
        """Create a header widget showing catalog information."""
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 10, 10, 10)

        header_widget.setStyleSheet(
            """
            QWidget {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 5px;
            }
            """
        )

        catalog_text = "Connecting to:"

        if hasattr(self.catalog_model, "get_display_label"):
            display_label = self.catalog_model.get_display_label()
            if display_label:
                catalog_text += f"\n{display_label}"

        if hasattr(self.catalog_model, "profile") and self.catalog_model.profile:
            catalog_text += f"\nProfile: {self.catalog_model.profile}"

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

        self.url_label = QLabel()
        self.url_label.setWordWrap(True)
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.url_label)

        self.code_label = QLabel()
        self.code_label.setWordWrap(True)
        self.code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.code_label)

        self.auth_status = QLabel("Starting authentication...")
        layout.addWidget(self.auth_status)

        self.expiry_label = QLabel("")
        layout.addWidget(self.expiry_label)

        self.expiry_progress = QProgressBar()
        self.expiry_progress.setTextVisible(False)
        self.expiry_progress.setMinimum(0)
        self.expiry_progress.setMaximum(1)
        self.expiry_progress.setValue(1)
        layout.addWidget(self.expiry_progress)

        self.auth_stack.addWidget(widget)

    def check_auth_requirements(self):
        """Check what authentication method the server supports."""
        self._stop_device_code_grant()

        mode = self.spec.mode
        ok_button = self.buttons.button(QDialogButtonBox.Ok)
        if mode == "internal" or mode == "password":
            self.auth_stack.setCurrentIndex(0)
            self.status_label.setText("Ready for authentication")
            if ok_button is not None:
                ok_button.setEnabled(True)
                ok_button.setVisible(True)
        elif mode == "external":
            self.auth_stack.setCurrentIndex(1)
            self.status_label.setText(
                "Please complete the authentication in your browser:"
            )
            if ok_button is not None:
                ok_button.setEnabled(False)
                ok_button.setVisible(False)
            self._start_device_code_grant()
        else:
            QMessageBox.critical(
                self,
                "Authentication Error",
                f"Unsupported authentication mode: {mode}",
            )
            self.reject()

    def _scopes_for_spec(self):
        """
        Build the OAuth2 scope string for the current provider.

        Returns
        -------
        str
            Space-separated scope string.
        """
        extra = getattr(self.spec, "extra_scopes", None) or []
        return " ".join(sorted({"openid", "offline_access"} | set(extra)))

    def _start_device_code_grant(self):
        """
        Begin the device-code flow on a background worker.
        """
        self.url_label.setText("Requesting verification URL...")
        self.code_label.setText("")
        self.auth_status.setText("Waiting for authentication...")
        self.expiry_label.setText("")
        self.expiry_progress.setMaximum(1)
        self.expiry_progress.setValue(1)

        worker = DeviceCodeGrantWorker(
            self.context.http_client,
            self.spec.links["auth_endpoint"],
            client_id=self.spec.links.get("client_id"),
            token_endpoint=self.spec.links.get("token_endpoint"),
            scopes=self._scopes_for_spec(),
        )
        worker.verification_ready.connect(self._on_verification_ready)
        worker.succeeded.connect(self._on_device_code_succeeded)
        worker.failed.connect(self._on_device_code_failed)
        worker.finished.connect(worker.deleteLater)
        self._device_worker = worker
        worker.start()

    def _stop_device_code_grant(self):
        """
        Cancel any in-flight device-code worker and stop the countdown.
        """
        self._countdown_timer.stop()
        self._auth_deadline = None
        worker = self._device_worker
        self._device_worker = None
        if worker is None:
            return
        for signal, slot in (
            (worker.verification_ready, self._on_verification_ready),
            (worker.succeeded, self._on_device_code_succeeded),
            (worker.failed, self._on_device_code_failed),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        worker.requestInterruption()
        if worker.isRunning():
            worker.wait(5000)

    def _on_verification_ready(self, verification_uri, user_code, expires_in):
        """
        Update the UI once the verification URI and user code are available.

        Parameters
        ----------
        verification_uri : str
            Browser URL the user should open.
        user_code : str
            Code the user enters at the verification URI.
        expires_in : float
            Seconds until the device code expires.
        """
        self.url_label.setText(f"URL: {verification_uri}")
        self.code_label.setText(f"Code: {user_code}")
        self.auth_status.setText("Enter the code in the browser tab to start authentication.\nIf a browser did not open automatically, please go to the URL manually.")
        self._auth_deadline = time.monotonic() + float(expires_in)
        maximum = max(1, int(float(expires_in)))
        self.expiry_progress.setMaximum(maximum)
        self.expiry_progress.setValue(maximum)
        self._update_countdown()
        self._countdown_timer.start()
        webbrowser.open(verification_uri)

    def _update_countdown(self):
        """
        Refresh the expiry progress bar and remaining-time label.
        """
        if self._auth_deadline is None:
            return
        remaining = max(0.0, self._auth_deadline - time.monotonic())
        self.expiry_progress.setValue(int(remaining))
        total_seconds = int(remaining)
        minutes, seconds = divmod(total_seconds, 60)
        self.expiry_label.setText(f"Code expires in {minutes}m {seconds:02d}s")
        if remaining <= 0:
            self._countdown_timer.stop()

    def _on_device_code_succeeded(self, tokens):
        """
        Finish the dialog after a successful device-code grant.

        Parameters
        ----------
        tokens : dict
            Access and refresh tokens from the token endpoint.
        """
        self._countdown_timer.stop()
        self._device_worker = None
        self.tokens = tokens
        self.remember_me = self.remember_checkbox.isChecked()
        self.auth_status.setText("Authentication successful.")
        super().accept()

    def _on_device_code_failed(self, message):
        """
        Show an error when device-code grant fails or expires.

        Parameters
        ----------
        message : str
            Failure description.
        """
        self._countdown_timer.stop()
        self._device_worker = None
        self.auth_status.setText("Authentication failed.")
        QMessageBox.critical(
            self, "Authentication Error", f"Authentication failed: {message}"
        )

    def accept(self):
        """Handle dialog acceptance for password grant."""
        try:
            if self.auth_stack.currentIndex() != 0:
                return

            http_client = self.context.http_client
            auth_endpoint = self.spec.links["auth_endpoint"]
            provider = self.spec.provider
            username = self.username_edit.text()
            password = self.password_edit.text()

            if not username or not password:
                QMessageBox.warning(
                    self,
                    "Authentication Error",
                    "Please enter both username and password.",
                )
                return

            QMessageBox.information(
                self,
                "Two-Factor Authentication",
                "If you have enabled two-factor authentication, please check your authenticator app for a push after hitting ok",
            )
            try:
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

            self.remember_me = self.remember_checkbox.isChecked()
            super().accept()

        except Exception as e:
            QMessageBox.critical(
                self, "Authentication Error", f"Authentication failed: {e}"
            )

    def reject(self):
        """
        Cancel authentication and stop any background device-code worker.
        """
        self._stop_device_code_grant()
        super().reject()

    def closeEvent(self, event):
        """
        Ensure background work stops when the dialog is closed.

        Parameters
        ----------
        event : QCloseEvent
            Qt close event.
        """
        self._stop_device_code_grant()
        super().closeEvent(event)

    def get_tokens(self):
        """Get the authentication tokens."""
        return self.tokens

    def get_remember_me(self):
        """Get the remember me setting."""
        return self.remember_me
