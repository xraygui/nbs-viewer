# NBS Viewer

NBS Viewer is a simple viewer application designed to visualize and interact with data stored in a Tiled database with Databroker formatted runs. It is optimized for the viewing of 1-d or 2-d data.

# Usage

## Installing and opening the application using Anaconda on a personal machine
1. Open the Anaconda prompt and activate a suitable environment.
2. Install the following packages:
   - `conda install pyqt`
   - `pip install nbs-viewer`

## Connecting to a Tiled Database

1. **Start the Application**: Run the `nbs-viewer` command.
2. **Select Data Source**: In the application, select the data source you want to connect to. You can choose from various options such as tiled URIs, or tiled profiles stored on your local machine. As a test, try selecting the Tiled URI, and pointing at https://tiled-demo.blueskyproject.io and loading the BMM example catalog.
   - For rsoxs, enter URI: https://tiled.nsls2.bnl.gov and Profile: rsoxs.  This may request a username and password to be typed in the message-box. A 2-factor push may be required. Then select the raw profile.
3. **Visualize Data**: Once connected, you can browse and the runs available in the Tiled database, filtered by time. Additional filtering based on the data in each row is available via Regular Expressions. The default lookback time is 1 month. The tiled-demo example catalogs have a date of 2022, so be sure to adjust the time range if you are trying them out.  "Reverse Data" will reverse the time order.  Note, the data may take some time to load especially if the viewer is being used on a local machine.
4. **Add Data to a Plot**: Selected runs will be added to the plot area via. The data in these runs can then be inspected, and X-Y data can be added to the plot by selecting the appropriate checkboxes. Selected runs can be added to a new tab via a right-click context menu. 
5. **View Images**: Images can be viewed by using the dimension controls to switch the plot to 2D. An image viewed in 1D will have a slider to step through the extra dimensions. Data which is 3D or higher can be added to an image grid tab, where multiple 2D images can be plotted at the same time in a grid.

## Useful Features
* It is possible to enter regular expressions to filter the catalog run list. Select the desired column to filter on, and then enter a regular expression in the text box.
* The "transform" checkbox in the X-Y data selection panel will enable arbitrary math functions to be run on the "y" data, using the `asteval` package. The y data may be referenced as 'y', and the most common numpy functions are automatically imported with no need for the np prefix. 
** For example, enter 'log(y)' (with no quotes), to plot the log of the y data. Or enter 'y/mean(y)' to normalize the data to its average value.
** Transforms are applied to all currently-selected data.
* The 'normalize' column is used to divide all the plotted y data by a single channel. For spectroscopy, this is usually a channel called 'i0'. When using transform, the already-normalized y-data is used, if a normalization channel is selected.
