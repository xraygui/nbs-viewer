#!/usr/bin/env python3
"""Test script for debugging ImageGridWidget data access issues."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nbs_viewer.models.plot.plotModel import PlotModel
from nbs_viewer.models.plot.runSource import RunSource
from nbs_viewer.utils import print_debug
import numpy as np
from tiled.client import from_uri
from nbs_viewer.models.catalog.bluesky import NBSCatalog


def setup_catalog_and_run():
    """Set up the catalog and load a specific run."""
    print("=== Setting up Catalog and Run ===")

    # Load the catalog
    c = from_uri("https://tiled.nsls2.bnl.gov")["rsoxs"]["raw"]
    catalog = NBSCatalog(c)

    # Get the specific run
    run = catalog.get_run("aed162c4")
    print(f"Loaded run: {run.uid}")
    print(f"Available keys: {run.available_keys}")

    return catalog, run


def test_direct_data_access(run):
    """Test direct data access without RunSource."""
    print("\n=== Testing Direct Data Access ===")

    # Test the slice indices that work for matplotlib
    test_indices = (0, 0, slice(None, None, None), slice(None, None, None))
    print(f"Testing with indices: {test_indices}")

    try:
        # Get image data directly
        image_data = run.getData("Wide Angle CCD Detector_image", test_indices)
        print(f"Direct image data shape: {image_data.shape}")
        print(f"Direct image data type: {type(image_data)}")
        print(f"Direct image data min/max: {image_data.min()}/{image_data.max()}")
        return True
    except Exception as e:
        print(f"Direct data access failed: {e}")
        return False


def test_runmodel_data_access(run):
    """Test data access through RunSource."""
    print("\n=== Testing RunSource Data Access ===")

    # Create a RunSource for the run
    run_model = RunSource(run)
    print(f"Created RunSource for run: {run_model.uid}")

    # Get the default selection
    x_keys, y_keys, norm_keys = run_model.get_selected_keys()
    print(f"Default selection - x: {x_keys}, y: {y_keys}, norm: {norm_keys}")

    # Test getting plot data with default selection
    try:
        x_data, y_data = run_model.get_plot_data(x_keys, y_keys[0], norm_keys)
        print(f"RunSource data - x shapes: {[x.shape for x in x_data]}")
        print(f"RunSource data - y shape: {y_data.shape}")
        return True
    except Exception as e:
        print(f"RunSource data access failed: {e}")
        return False


def test_plotmodel_data_access(run):
    """Test data access through PlotModel."""
    print("\n=== Testing PlotModel Data Access ===")

    # Create a PlotModel
    plot_model = PlotModel(is_main_canvas=True)
    plot_model.add_run(run)

    # Get the default selection
    x_keys, y_keys, norm_keys = plot_model.get_selected_keys()
    print(f"PlotModel selection - x: {x_keys}, y: {y_keys}, norm: {norm_keys}")

    # Test getting data from visible models
    visible_models = plot_model.visible_models
    print(f"Visible models: {len(visible_models)}")

    for model in visible_models:
        try:
            x_keys, y_keys, norm_keys = model.get_selected_keys()
            print(f"Model {model.uid} - x: {x_keys}, y: {y_keys}, norm: {norm_keys}")

            if y_keys:
                x_data, y_data = model.get_plot_data(x_keys, y_keys[0], norm_keys)
                print(f"Model {model.uid} data - x shapes: {[x.shape for x in x_data]}")
                print(f"Model {model.uid} data - y shape: {y_data.shape}")
        except Exception as e:
            print(f"Model {model.uid} data access failed: {e}")


def test_image_data_access(run):
    """Test data access with explicitly selected image data."""
    print("\n=== Testing Image Data Access ===")

    # Create a RunSource for the run
    run_model = RunSource(run)
    print(f"Created RunSource for run: {run_model.uid}")

    # Explicitly select image data
    image_keys = [key for key in run.available_keys if "image" in key.lower()]
    if image_keys:
        image_key = image_keys[0]
        print(f"Explicitly selecting image key: {image_key}")

        # Set selected keys to use the image
        run_model.set_selected_keys([], [image_key], [], force_update=False)

        # Get the selected keys to confirm
        x_keys, y_keys, norm_keys = run_model.get_selected_keys()
        print(f"Selected keys after setting: x={x_keys}, y={y_keys}, norm={norm_keys}")

        # Test getting plot data
        try:
            x_data, y_data = run_model.get_plot_data(x_keys, y_keys[0], norm_keys)
            print(f"Image data - x shapes: {[x.shape for x in x_data]}")
            print(f"Image data - y shape: {y_data.shape}")
            print(f"Image data - y min/max: {y_data.min()}/{y_data.max()}")
            return True
        except Exception as e:
            print(f"Image data access failed: {e}")
            return False
    else:
        print("No image keys found")
        return False


# Copy key methods from ImageGridWidget for testing
def get_shape_info_from_models(visible_models):
    """
    Get shape information from visible models (copied from ImageGridWidget).

    Parameters
    ----------
    visible_models : list
        List of visible RunSource instances

    Returns
    -------
    tuple or None
        (shape, dim_names, axis_arrays, associated_data) or None if no data
    """
    print("ImageGridWidget: Getting shape info from models")

    if not visible_models:
        print("ImageGridWidget: No visible models")
        return None

    # Get shape information from the first visible model
    run_model = visible_models[0]
    x_keys, y_keys, norm_keys = run_model.get_selected_keys()

    if not y_keys:
        print("ImageGridWidget: No Y keys selected")
        return None

    y_key = y_keys[0]
    print(
        f"ImageGridWidget: Using y_key: {y_key}, x_key: {x_keys[0] if x_keys else 'None'}"
    )

    try:
        # Get dimension analysis
        axis_arrays, axis_names, associated_data = run_model._run.get_dimension_axes(
            y_key, x_keys
        )
        shape = tuple(len(arr) if len(arr) > 0 else 1 for arr in axis_arrays)

        print(f"ImageGridWidget: Shape: {shape}")
        print(f"ImageGridWidget: Dimension names: {axis_names}")
        print(
            f"ImageGridWidget: Associated data keys: {list(associated_data.keys()) if associated_data else 'None'}"
        )

        return shape, axis_names, axis_arrays, associated_data
    except Exception as e:
        print(f"ImageGridWidget: Error getting shape info: {e}")
        return None


def process_nd_data(shape):
    """
    Process N-D data and determine how many images to display (copied from ImageGridWidget).

    Parameters
    ----------
    shape : tuple
        Shape of the N-D data

    Returns
    -------
    tuple
        (total_images, image_shape, non_image_dims, full_shape) or None if invalid
    """
    if len(shape) < 2:
        print(f"ImageGridWidget: Data has less than 2 dimensions: {shape}")
        return None

    # Last 2 dimensions are always the image (height, width)
    image_shape = shape[-2:]
    non_image_dims = shape[:-2]

    # Calculate total images by multiplying non-image dimensions
    # Remove dummy dimensions (size 1) when calculating total
    non_dummy_dims = [dim for dim in non_image_dims if dim > 1]
    if non_dummy_dims:
        total_images = np.prod(non_dummy_dims)
    else:
        # If all non-image dimensions are dummy, we have 1 image
        total_images = 1

    print(f"ImageGridWidget: Image shape: {image_shape}")
    print(f"ImageGridWidget: Non-image dims: {non_image_dims}")
    print(f"ImageGridWidget: Non-dummy dims: {non_dummy_dims}")
    print(f"ImageGridWidget: Total images: {total_images}")

    return total_images, image_shape, non_image_dims, shape


def test_imagegrid_methods(run):
    """Test the ImageGridWidget methods with the actual data."""
    print("\n=== Testing ImageGridWidget Methods ===")

    # Create a RunSource and PlotModel
    run_model = RunSource(run)
    plot_model = PlotModel(is_main_canvas=True)
    plot_model.add_run(run)

    # Explicitly select image data
    image_keys = [key for key in run.available_keys if "image" in key.lower()]
    if image_keys:
        image_key = image_keys[0]
        run_model.set_selected_keys([], [image_key], [], force_update=False)
        plot_model.set_selected_keys([], [image_key], [], force_update=False)

    # Test shape info method
    visible_models = plot_model.visible_models
    shape_info = get_shape_info_from_models(visible_models)

    if shape_info:
        shape, dim_names, axis_arrays, associated_data = shape_info

        # Test ND data processing
        nd_result = process_nd_data(shape)
        if nd_result:
            total_images, image_shape, non_image_dims, full_shape = nd_result

            # Test getting individual image data
            print(f"\nImageGridWidget: Testing individual image data access")
            print(f"ImageGridWidget: Will create {total_images} images")

            # Test the first few images
            for i in range(min(3, total_images)):
                try:
                    # Create slice indices for this image
                    # Keep all dimensions, including dummy ones
                    slice_indices = [0] * len(shape)
                    slice_indices[0] = i  # Use first dimension for iteration

                    # Convert to proper slice format
                    slice_info = []
                    for j, dim_size in enumerate(shape):
                        if j < len(slice_indices):
                            slice_info.append(slice_indices[j])
                        else:
                            slice_info.append(slice(None, None, None))

                    slice_info = tuple(slice_info)
                    print(
                        f"ImageGridWidget: Processing image {i} with indices {slice_info}"
                    )

                    # Try to get data with these indices
                    x_data, y_data = run_model.get_plot_data(
                        [], image_key, [], slice_info
                    )
                    print(f"ImageGridWidget: Image {i} data shape: {y_data.shape}")
                    print(
                        f"ImageGridWidget: Image {i} data min/max: {y_data.min()}/{y_data.max()}"
                    )

                except Exception as e:
                    print(f"ImageGridWidget: Error getting image {i}: {e}")


def main():
    """Run all tests."""
    print("=== ImageGridWidget Debug Test ===")

    # Set up catalog and run
    catalog, run = setup_catalog_and_run()

    # Run tests
    test_direct_data_access(run)
    test_runmodel_data_access(run)
    test_plotmodel_data_access(run)
    test_image_data_access(run)
    test_imagegrid_methods(run)

    print("\n=== Test Complete ===")


if __name__ == "__main__":
    main()
