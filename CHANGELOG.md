# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2025-08-21

### Added
- Authentication to Tiled via GUI (requires Tiled 0.1.0-b14 or higher) (#8)
- New entrypoint and display system for custom tabs
- ImageGrid tab for viewing series of images
- Tab renaming functionality (double-click to rename)
- Menu bars and context menus replacing button-based UI
- Display registry system for managing different display types
- Worker pool and threads for fast catalog population
- Widget registry system for custom plot widgets
- Collapsible panels for more compact layout

### Changed
- Major UI redesign with menu-driven interface
- Refactored RunListView to use Qt Model/View architecture
- Improved context menus with better organization
- Enhanced catalog management with better source handling
- Made layout more compact by removing one sidebar
- Better separation between models and views with Qt Model/View architecture


### Fixed
- Fixed location of tiledAuth components
- Improved table chunk loading optimization
- Better handling of large datasets with lazy loading
- Resolved issues with catalog population performance

### Removed
- Removed redundant menu actions and buttons
- Cleaned up unused code and imports

## [0.2.4] - 2025-05-23

### Fixed
- Worker cleanup fixed (#11)
- Bugs in link runs (#6)
- Some crashes fixed (#15, #17)

## [0.2.3] - 2025-03-14
### Added
- N-dimensional plotting with dimension control sliders
- Chunk-aware data caching from Tiled
- Clear Canvas buttons
- Ability to combine runs (averaging only)

### Changed
- Config file now allows for loading any catalog type

## [0.1.0] - Initial Release

### Added
- Basic NBS viewer functionality
- Support for Bluesky catalogs
- Simple plotting interface
