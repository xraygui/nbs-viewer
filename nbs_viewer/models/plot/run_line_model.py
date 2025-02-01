from typing import Dict, Optional
from qtpy.QtCore import QObject, Signal
from qtpy.QtGui import QColor
import numpy as np

from ..data.base import CatalogRun
from .run_data import RunData


class RunLineModel(QObject):
    """
    Model for managing line appearance properties.

    Manages line style, color, width, and other display properties for a run.
    Uses RunData service for data access while maintaining its own style state.

    Parameters
    ----------
    run : CatalogRun
        The run object providing the data
    run_data : RunData
        The RunData service for data access and transformation

    Signals
    -------
    style_changed : Signal
        Emitted when line style properties change
    """

    style_changed = Signal()

    def __init__(self, run: CatalogRun, run_data: RunData):
        super().__init__()
        self._run = run
        self._run_data = run_data

        # Style state
        self._color = QColor(0, 0, 0)  # Default black
        self._line_width = 1.0
        self._line_style = "-"  # Solid line
        self._marker = "None"
        self._marker_size = 6.0
        self._alpha = 1.0
        self._label = ""

        # Custom styles per key
        self._key_styles: Dict[str, Dict] = {}

        # Additional attributes for plotting
        self._line = None  # matplotlib Line2D object
        self._plot = None  # matplotlib Axes object
        self._x = None
        self._y = None

    @property
    def color(self) -> QColor:
        """Get line color."""
        return self._color

    @color.setter
    def color(self, value: QColor) -> None:
        """Set line color."""
        if value != self._color:
            self._color = value
            self.style_changed.emit()

    @property
    def line_width(self) -> float:
        """Get line width."""
        return self._line_width

    @line_width.setter
    def line_width(self, value: float) -> None:
        """Set line width."""
        if value != self._line_width:
            self._line_width = value
            self.style_changed.emit()

    @property
    def line_style(self) -> str:
        """Get line style."""
        return self._line_style

    @line_style.setter
    def line_style(self, value: str) -> None:
        """Set line style."""
        if value != self._line_style:
            self._line_style = value
            self.style_changed.emit()

    @property
    def marker(self) -> str:
        """Get marker style."""
        return self._marker

    @marker.setter
    def marker(self, value: str) -> None:
        """Set marker style."""
        if value != self._marker:
            self._marker = value
            self.style_changed.emit()

    @property
    def marker_size(self) -> float:
        """Get marker size."""
        return self._marker_size

    @marker_size.setter
    def marker_size(self, value: float) -> None:
        """Set marker size."""
        if value != self._marker_size:
            self._marker_size = value
            self.style_changed.emit()

    @property
    def alpha(self) -> float:
        """Get line alpha."""
        return self._alpha

    @alpha.setter
    def alpha(self, value: float) -> None:
        """Set line alpha."""
        if value != self._alpha:
            self._alpha = value
            self.style_changed.emit()

    @property
    def label(self) -> str:
        """Get line label."""
        return self._label

    @label.setter
    def label(self, value: str) -> None:
        """Set line label."""
        if value != self._label:
            self._label = value
            self.style_changed.emit()

    def get_key_style(self, key: str) -> Dict:
        """
        Get style properties for a specific key.

        Parameters
        ----------
        key : str
            The data key to get style for

        Returns
        -------
        Dict
            Dictionary of style properties
        """
        if key in self._key_styles:
            return self._key_styles[key].copy()
        return {
            "color": self._color,
            "linewidth": self._line_width,
            "linestyle": self._line_style,
            "marker": self._marker,
            "markersize": self._marker_size,
            "alpha": self._alpha,
            "label": self._label or key,
        }

    def set_key_style(self, key: str, style: Optional[Dict] = None) -> None:
        """
        Set style properties for a specific key.

        Parameters
        ----------
        key : str
            The data key to set style for
        style : Optional[Dict], optional
            Style properties to set, by default None
        """
        if style is None:
            if key in self._key_styles:
                del self._key_styles[key]
                self.style_changed.emit()
        else:
            self._key_styles[key] = style.copy()
            self.style_changed.emit()

    def attach_plot(self, plot):
        """
        Attach this line model to a plot.

        Parameters
        ----------
        plot : MplCanvas
            The plot to attach to
        """
        self._plot = plot.axes
        self._update_line()

    def set_data(self, x: np.ndarray, y: np.ndarray) -> None:
        """
        Set the line data.

        Parameters
        ----------
        x : np.ndarray
            X-axis data
        y : np.ndarray
            Y-axis data
        """
        self._x = x
        self._y = y
        self._update_line()

    def _update_line(self) -> None:
        """Update or create the matplotlib line with current data and style."""
        if self._plot is None:
            return

        # Get current style
        style = self.get_key_style(self._run.key) or {
            "color": self._color,
            "linestyle": self._line_style,
            "linewidth": self._line_width,
            "marker": self._marker,
            "markersize": self._marker_size,
            "alpha": self._alpha,
            "label": self._label or self._run.key,
        }

        if self._line is None and self._x is not None and self._y is not None:
            # Create new line
            self._line = self._plot.plot(
                self._x,
                self._y,
                color=style["color"].name(),
                linestyle=style["linestyle"],
                linewidth=style["linewidth"],
                marker=style["marker"],
                markersize=style["markersize"],
                alpha=style["alpha"],
                label=style["label"],
            )[0]
        elif self._line is not None:
            # Update existing line
            if self._x is not None and self._y is not None:
                self._line.set_data(self._x, self._y)
            self._line.set_color(style["color"].name())
            self._line.set_linestyle(style["linestyle"])
            self._line.set_linewidth(style["linewidth"])
            self._line.set_marker(style["marker"])
            self._line.set_markersize(style["markersize"])
            self._line.set_alpha(style["alpha"])
            self._line.set_label(style["label"])

        # Update plot
        if self._plot.figure.canvas is not None:
            self._plot.figure.canvas.draw_idle()

    def cleanup(self) -> None:
        """Remove the line from the plot and clean up resources."""
        if self._line is not None:
            self._line.remove()
            self._line = None
        if self._plot is not None and self._plot.figure.canvas is not None:
            self._plot.figure.canvas.draw_idle()
