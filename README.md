# NBS Viewer

NBS Viewer is a simple Tiled viewer application designed to visualize and interact with data stored in a Tiled database with Databroker formatted runs. It is optimized for the viewing of 1-d or 2-d data.

# Usage

## Connecting to a Tiled Database

1. **Start the Application**: Run the `nbs-viewer` command.
2. **Select Data Source**: In the application, select the data source you want to connect to. You can choose from various options such as tiled URIs, or tiled profiles stored on your local machine.
3. **Visualize Data**: Once connected, you can browse and the runs available in the Tiled database, filtered by time. Additional filtering based on the data in each row is available via Regular Expressions.
4. **Add Data to a Plot**: Selected runs can be added to the plot area via the "Add Data to Current Plot" button. The data in these runs can then be inspected, and X-Y data can be added to the plot by selecting the appropriate checkboxes and using the "Update Plot" button