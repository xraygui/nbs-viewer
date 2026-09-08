Notes:
- AppModel does not really hold everything. Doesn't seem to have any of the catalog creation/selection. To what extent should the AppModel capture all models? Is it acceptable for a view to hold parallel models, and do the work of connecting them?
- The original sin here seems to be the CatalogSwitcher (was DataSourceSwitcher), created by views/display/mainDisplay.py, which also digs the run_list_model and plot_model out of the display_manager, and does some routing
- However, no signals are set up in mainDisplay, so that is good
- We're not far from DisplayManager really being the actual AppModel
- mainWidget also mostly deals with DisplayManager

Models:

    AppModel
- ConfigModel
- DisplayRegistry
- DisplayManager
    - RunListModel
    - PlotModel
- CatalogManagerModel


mainWidget(takes AppModel)
    - MainDisplay/PlotDisplay(takes AppModel)
    - CatalogSwitcher(takes AppModel, RunListModel)
        - DisplayControlWidget(takes displayManager, RunListModel)
        - SourceDialog -> Creates catalogs via SourceModels and then registers them
    - PlotWidget(RunListModel, PlotModel)
- Other tabs (AppModel)

Top level: AppModel (app_model.py)
Owns
- ConfigModel
- DisplayRegistry
- DisplayManager
- CatalogManagerModel

Controls
- Active display
- Routes selected/deselected run from CatalogManagerModel to active display via display_manager

CatalogManagerModel (app_model.py)
Holds:
- ConfigModel
- Dictionary of catalogs (_catalogs)

Controls:
- Forwarding signals from catalogs on up


DisplayManager (models/plot/displayManager.py)
Owns:
- list of RunListModels
- list of PlotModels
-> list of Displays
- DisplayRegistry (passed in from outside? why?)
- How can something called "DisplayManager" be view-independent?
- How can we have a DisplayManager but not any Display class that is being managed?
- Just need a simple class that wraps a RunListModel, PlotModel, Name, UID -- does it need plot type?

Creates:
- New PlotModels
- New RunListModels

DisplayRegistry (models/plot/displayRegistry.py)
- Imports from views (only for "display class validation" -- probably a psychotic thing to do)
- Loads display classes from entrypoints. Collects possible displays
- Other classes need to get a display, then create it, then register it... why
- How to make headless...? Need to figure out if we have a real display?
    - Should this be creating views?
    - Should we have a DisplayController that's separate? Or this should be a view? A hybrid?
    - Are we making a PlotModel that's separate from any view?
- Really used by MainWidget._on_display_added

Refactoring Notes:

General:
- We should never be passing appModel + something else.
- AppModel should hold all child models, aside from temporary models
- Need a test catalog with totally constructed catalog (1D, 2D, 3D data)

DisplayManager
- Should get a Display class that holds the RunListModel, PlotModel, display name
- Just hold the Display Class with a UID

CatalogSwitcher / SourceDialog / CatalogManagerModel
- Catalog creation/registration should be done by CatalogManagerModel
- SourceDialog configures SourceModels (factories); CatalogSwitcher switches catalogs
- Take machinery from SourceDialog and move to CatalogManagerModel
- Going to be kinda hard...

Test Catalog
- Should have an in-memory catalog that can be totally constructed
- Need an in-memory run class first
- Need a way to load an in-memory catalog... custom test loader

Naming:
- CatalogSwitcher (was DataSourceSwitcher): switches between registered catalogs
- SourceDialog (was DataSourcePicker): creates catalogs from SourceView widgets
- SourceModel: factory/strategy for loading catalogs (many catalogs per source type)
