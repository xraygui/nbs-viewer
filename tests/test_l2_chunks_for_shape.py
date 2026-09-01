import numpy as np

from nbs_viewer.models.cache.tile_indices import l2_chunks_for_shape
from nbs_viewer.models.cache.zarr_l2_cache import ZarrL2Cache


def test_l2_chunks_for_shape_drops_leading_ones_for_lower_rank():
    template = (1, 1, 256, 256)
    assert l2_chunks_for_shape((41, 2160, 2560), template) == (1, 256, 256)
    assert l2_chunks_for_shape((2160, 2560), template) == (256, 256)


def test_l2_chunks_for_shape_unchanged_for_four_d():
    template = (1, 1, 256, 256)
    shape = (200, 5, 1024, 1026)
    assert l2_chunks_for_shape(shape, template) == template


def test_zarr_l2_register_three_d_detector_image():
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 256, 256))
    shape = (41, 2160, 2560)
    arr = l2.register_array("run-vppem", "PCOEdge_image", shape, "f4")
    assert arr.shape == shape
    assert arr.chunks == (1, 256, 256)
    assert l2._meta[("run-vppem", "PCOEdge_image")].l2_chunks == (1, 256, 256)

    tile = np.zeros((1, 256, 256), dtype=np.float32)
    l2.write_chunk("run-vppem", "PCOEdge_image", (0, 0, 0), tile)
    np.testing.assert_array_equal(
        l2.read_chunk("run-vppem", "PCOEdge_image", (0, 0, 0)),
        tile,
    )
