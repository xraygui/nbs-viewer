from .bluesky import BlueskyRun
from typing import List


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
        "exit_status": ["stop", "exit_status"],
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

    METADATA_KEYS = [
        "scan_id",
        "plan_name",
        "sample_name",
        "sample_id",
        "date",
        "exit_status",
        "uid",
    ]

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
