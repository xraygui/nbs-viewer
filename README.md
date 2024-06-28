# NBS Viewer

NBS Viewer is a simple viewer application designed to visualize and interact with data stored in a Tiled database with Databroker formatted runs. It is optimized for the viewing of 1-d or 2-d data.

# Usage

## Connecting to a Tiled Database

1. **Start the Application**: Run the `nbs-viewer` command.
2. **Select Data Source**: In the application, select the data source you want to connect to. You can choose from various options such as tiled URIs, or tiled profiles stored on your local machine. As a test, try selecting the Tiled URI, and pointing at https://tiled-demo.blueskyproject.io and loading the BMM example catalog.
3. **Visualize Data**: Once connected, you can browse and the runs available in the Tiled database, filtered by time. Additional filtering based on the data in each row is available via Regular Expressions. The default lookback time is 1 month. The tiled-demo example catalogs have a date of 2022, so be sure to adjust the time range if you are trying them out.
4. **Add Data to a Plot**: Selected runs can be added to the plot area via the "Add Data to Current Plot" button. The data in these runs can then be inspected, and X-Y data can be added to the plot by selecting the appropriate checkboxes and using the "Update Plot" button. Image data is supported, but not optimized. Be careful when trying to plot large images.

## Useful Features
* It is possible to enter regular expressions to filter the catalog run list. Select the desired column to filter on, and then enter a regular expression in the text box.
* The "transform" checkbox in the X-Y data selection panel will enable arbitrary math functions to be run on the "y" data, using the `asteval` package. The y data may be referenced as 'y', and the most common numpy functions are automatically imported with no need for the np prefix. 
** For example, enter 'log(y)' (with no quotes), to plot the log of the y data. Or enter 'y/mean(y)' to normalize the data to its average value.
** Transforms are applied to all currently-selected data.
* The 'normalize' column is used to divide all the plotted y data by a single channel. For spectroscopy, this is usually a channel called 'i0'. When using transform, the already-normalized y-data is used, if a normalization channel is selected.
