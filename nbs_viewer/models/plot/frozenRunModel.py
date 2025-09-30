from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
import numpy as np
import uuid
from ..data.base import CatalogRun
from .runModel import RunModel


class FrozenRunModel(RunModel):
    """
    A frozen run is a run that has been frozen and cannot be modified.
    """

    def __init__(
        self,
        run: CatalogRun,
        y_key: str,
        parent=None,
    ):
        self._uid = str(uuid.uuid4())
        super().__init__(run)
        self._y_key = y_key
        run.data_changed.connect(self._on_data_changed)

    @property
    def uid(self) -> str:
        """Get the UID for the frozen run."""
        return self._uid

    def get_plot_data(
        self, x_keys, y_keys, norm_keys=None, slice_info=None, **kwargs
    ) -> Tuple[List[np.ndarray], np.ndarray]:
        """
        Get plot data for the frozen run. y_keys is ignored.
        """
        return super().get_plot_data(
            x_keys, self._y_key, norm_keys, slice_info, **kwargs
        )

    @property
    def display_name(self) -> str:
        """Get descriptive name for the combined run."""
        return f"{self._y_key} of {self.scan_id}"
