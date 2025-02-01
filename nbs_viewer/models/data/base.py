from abc import ABC, abstractmethod


class CatalogRun(ABC):
    """
    Abstract base class for catalog run implementations.

    This class defines the interface that all run implementations must follow,
    whether they are reading from a catalog, Kafka stream, or other source.

    Parameters
    ----------
    run : object
        The underlying run object
    key : str
        The key/identifier for this run
    catalog : object, optional
        The catalog containing this run, by default None
    """

    @classmethod
    @abstractmethod
    def METADATA_KEYS(cls):
        """
        Abstract class method that subclasses must define.
        Should return a list of metadata keys.

        Returns
        -------
        list
            List of metadata keys required by this run type
        """
        pass

    def __init__(self, run, key, catalog):
        self._run = run
        self._key = key
        self._catalog = catalog

    def __repr__(self):
        """
        Returns a string representation of the CatalogRun object.

        Returns
        -------
        str
            String representation including class name and run info
        """
        return f"{self.__class__.__name__}({self._run!r})"

    @abstractmethod
    def setup(self):
        """
        Set up the run object.

        This method should initialize all attributes defined in METADATA_KEYS
        and any other required state.
        """
        pass

    def refresh(self):
        """
        Refresh the run data from its source.

        Default implementation reloads from catalog. Subclasses may override
        for different refresh behavior.
        """
        self._run = self._catalog[self._key]
        self.setup()

    @abstractmethod
    def getData(self, key):
        """
        Get data for a given key.

        Parameters
        ----------
        key : str
            The key to get data for

        Returns
        -------
        array-like
            The data for the given key
        """
        pass

    @abstractmethod
    def getShape(self, key):
        """
        Get the shape of data for a given key.

        Parameters
        ----------
        key : str
            The key to get shape for

        Returns
        -------
        tuple
            The shape of the data
        """
        pass

    def getPlotHints(self):
        """
        Get plot hints for this run.

        Returns
        -------
        dict
            Dictionary of plot hints. Default implementation returns empty dict.
        """
        return {}

    @abstractmethod
    def to_header(self):
        """
        Get a dictionary of metadata suitable for display in a header.

        Returns
        -------
        dict
            Dictionary of metadata key-value pairs
        """
        pass
