import unittest

import numpy as np

from run import _money20_from_volume_price_proxy


class RunLiquidityTest(unittest.TestCase):
    def test_money20_proxy_accepts_numpy_arrays(self):
        closes = np.array([10.0, 11.0, 12.0])
        volumes = np.array([1000.0, 1100.0, 1200.0])

        result = _money20_from_volume_price_proxy(closes, volumes)

        self.assertEqual(result, 1216666.67)

    def test_money20_proxy_returns_none_for_empty_inputs(self):
        self.assertIsNone(_money20_from_volume_price_proxy(np.array([]), np.array([])))


if __name__ == "__main__":
    unittest.main()
