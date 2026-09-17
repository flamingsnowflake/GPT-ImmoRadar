import copy
import unittest
from unittest.mock import patch
from pathlib import Path
from config_loader import CONFIG
from scoring import plot_points, score_house


class HouseBudgetTests(unittest.TestCase):
    def setUp(self):
        config_path = str(Path(__file__).resolve().parent.parent / 'config')
        self.patch = patch.object(CONFIG, 'config_dir', config_path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        # Synthetic policy for stable boundary tests across deployment profiles.
        config = copy.deepcopy(CONFIG.score_config())
        self.score_config = config
        config['house']['hard_filters']['max_price'] = 300000
        config['house']['scoring']['price']['condition_surcharge']['good'] = 15000
        policy = patch.object(CONFIG, 'score_config', return_value=config)
        policy.start()
        self.addCleanup(policy.stop)

    def house(self, **values):
        return dict(property_type='house', geo_precision='exact',
                    plot_area=2000, living_area=200, neighbour_class='isolated',
                    neighbour_checked_at='checked', noise_checked_at='checked',
                    water_score=20, energy_updated_at='checked', energy_class='A+',
                    energy_certificate_status='available', **values)

    def test_necessary_costs_are_explained_and_cannot_be_bypassed(self):
        for bypass in (False, True):
            result = score_house(self.house(price=295000, condition_class='good',
                                            portal='ohne-makler'), ignore_search_limits=bypass)
            self.assertTrue(result['ko'])
            reason = ' '.join(result['ko_reasons'])
            for amount in ('295.000', '15.000', '310.000', '300.000'):
                self.assertIn(amount, reason)

    def test_exact_budget_is_allowed(self):
        self.assertFalse(score_house(self.house(price=285000, condition_class='good'))['ko'])

    def test_unknown_condition_waits_for_review(self):
        result = score_house(self.house(price=295000, condition_class='unknown'))
        self.assertFalse(result['ko'])
        self.assertEqual(result['rating'], 'incomplete')
        self.assertIn('Preis/Zustand', result['incomplete_reasons'])

    def test_known_purchase_price_can_already_exceed_limit(self):
        self.assertTrue(score_house(self.house(price=300001, condition_class='unknown'))['ko'])

    def test_missing_price_is_not_zero_or_ko(self):
        result = score_house(self.house(price=None, condition_class='good'))
        self.assertFalse(result['ko'])
        self.assertIsNone(result['score'])

    def test_limit_comes_from_configuration(self):
        config = copy.deepcopy(CONFIG.score_config())
        config['house']['hard_filters']['max_price'] = 310000
        with patch.object(CONFIG, 'score_config', return_value=config):
            self.assertFalse(score_house(self.house(price=295000, condition_class='good'))['ko'])

    def test_plot_below_1000_square_metres_is_ko(self):
        house = self.house(
            price=120000,
            condition_class='good',
        )
        house['plot_area'] = 999
        result = score_house(house)

        self.assertTrue(result['ko'])
        self.assertIn('Grundstück nur 999 m²', ' '.join(result['ko_reasons']))

    def test_plot_at_1000_square_metres_is_allowed(self):
        house = self.house(
            price=120000,
            condition_class='good',
        )
        house['plot_area'] = 1000
        result = score_house(house)

        self.assertFalse(result['ko'])

    def test_plot_points_drop_sharply_below_2000_square_metres(self):
        plot_config = self.score_config['house']['scoring']['plot_area']

        self.assertEqual(plot_points(5000, plot_config), 20)
        self.assertEqual(plot_points(3000, plot_config), 15)
        self.assertEqual(plot_points(2000, plot_config), 10)
        self.assertEqual(plot_points(1500, plot_config), 7)
        self.assertEqual(plot_points(1000, plot_config), 3)
        self.assertEqual(plot_points(999, plot_config), 0)
