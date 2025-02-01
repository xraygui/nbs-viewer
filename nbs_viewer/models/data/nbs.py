from .bluesky import BlueskyRun
from typing import Dict, List, Tuple


class NBSRun(BlueskyRun):
    """
    A specialized BlueskyRun for NBS data.

    This class extends BlueskyRun with additional metadata fields specific
    to NBS data collection, such as edge and sample information.
    """

    _METADATA_MAP = {
        "uid": ["start", "uid"],
        "date": [],
        "scan_id": ["start", "scan_id"],
        "scantype": ["start", "scantype"],
        "plan_name": ["start", "plan_name"],
        "edge": ["start", "edge"],
        "sample_name": ["start", "sample_name"],
        "sample_id": ["start", "sample_id"],
        "num_points": [],
    }

    DISPLAY_KEYS = {
        "uid": "UID",
        "date": "Date",
        "scan_id": "Scan ID",
        "scantype": "Scan Type",
        "plan_name": "Plan Name",
        "edge": "Edge",
        "sample_name": "Sample Name",
        "sample_id": "Sample ID",
        "num_points": "Scan Points",
    }

    @classmethod
    def METADATA_KEYS(cls):
        """
        Define required metadata keys.

        Returns
        -------
        list
            List of required metadata keys
        """
        return list(cls._METADATA_MAP.keys())

    def __str__(self):
        """
        Get a string representation of the NBS run.

        Returns a description including scan ID, edge type, scan type,
        and sample information.

        Returns
        -------
        str
            Human-readable description of the run
        """
        scan_desc = ["Scan", str(self.scan_id)]
        if self.edge:
            scan_desc.extend([self.edge, "edge"])
        if self.scantype:
            scan_desc.append(self.scantype)
        elif self.plan_name:
            scan_desc.append(self.plan_name)
        if self.sample_name:
            scan_desc.extend(["of", self.sample_name])
        else:
            scan_desc.append("of")
            scan_desc.append(
                self.get_md_value(["start", "sample_md", "name"], "Unknown")
            )
        return " ".join(scan_desc)

    def get_hinted_keys(self) -> Dict[int, List[str]]:
        """
        Get filtered keys based on NBS run's hints.

        Uses plot hints to filter keys, focusing on primary signals
        and their dimensions.

        Returns
        -------
        Dict[int, List[str]]
            Keys filtered by hints, organized by dimension
        """
        hints = self.getPlotHints()
        _, all_keys = self.getRunKeys()

        # Collect hinted fields
        hinted = []
        for fields in hints.values():
            for field in fields:
                if isinstance(field, dict):
                    if "signal" in field:
                        signal = field["signal"]
                        if isinstance(signal, list):
                            hinted.extend(signal)
                        else:
                            hinted.append(signal)
                else:
                    hinted.append(field)

        # Filter keys by dimension
        filtered = {}
        for dim, key_list in all_keys.items():
            filtered[dim] = [key for key in key_list if key in hinted]

        return filtered

    def get_default_selection(self) -> Tuple[List[str], List[str], List[str]]:
        """
        Get default key selection for NBS run.

        For NBS data, typically selects:
        - First non-zero dimension x key
        - Primary signals from hints for y
        - Normalization signals from hints for norm

        Returns
        -------
        Tuple[List[str], List[str], List[str]]
            Default (x_keys, y_keys, norm_keys) for this run
        """
        x_keys, _ = self.getRunKeys()
        hints = self.getPlotHints()

        # Select x keys
        selected_x = []
        if 1 in x_keys:
            for n in x_keys.keys():
                if n != 0:
                    selected_x.append(x_keys[n][0])
        elif 0 in x_keys:
            selected_x = [x_keys[0][0]]

        # Get y keys from primary hints
        selected_y = self._get_flattened_fields(hints.get("primary", []))

        # Get normalization keys from hints
        selected_norm = self._get_flattened_fields(hints.get("normalization", []))

        return selected_x, selected_y, selected_norm

    def _get_flattened_fields(self, fields: list) -> List[str]:
        """
        Get flattened list of fields from hints.

        Parameters
        ----------
        fields : list
            List of fields from hints

        Returns
        -------
        List[str]
            Flattened list of field names
        """
        flattened = []
        for field in fields:
            if isinstance(field, dict):
                if "signal" in field:
                    signal = field["signal"]
                    if isinstance(signal, list):
                        flattened.extend(signal)
                    else:
                        flattened.append(signal)
            else:
                flattened.append(field)
        return flattened

    @property
    def name(self) -> str:
        """
        Get a descriptive name for the run.

        Returns
        -------
        str
            A descriptive name including scan type and sample info
        """
        parts = []
        if self.scantype:
            parts.append(self.scantype)
        elif self.plan_name:
            parts.append(self.plan_name)

        if self.sample_name:
            parts.append(f"of {self.sample_name}")

        return " ".join(parts) if parts else "Unknown"
