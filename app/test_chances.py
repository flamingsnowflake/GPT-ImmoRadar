import copy
import unittest
from unittest.mock import patch
from pathlib import Path
from config_loader import CONFIG
from chances import best_case_result, max_reachable_score, qualifies_as_chance
from scoring import score_house, score_land


class ChanceTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.object(CONFIG, 'config_dir', str(Path(__file__).resolve().parent.parent / 'config'))
        self.config.start()
        self.addCleanup(self.config.stop)
        config = copy.deepcopy(CONFIG.score_config())
        config['house']['hard_filters']['max_price'] = 300000
        house = config['house']['scoring']
        house['price']['condition_surcharge']['good'] = 15000
        house['plot_area']['brackets'] = [{'min': 2000, 'points': 16}, {'min': 0, 'points': 0}]
        house['neighbours']['values'].update(dense=7, isolated=25)
        config['land']['scoring']['price']['brackets'] = [
            {'max': 30000, 'points': 30}, {'max': 40000, 'points': 25},
            {'max': 50000, 'points': 20}, {'max': None, 'points': 0}]
        policy = patch.object(CONFIG, 'score_config', return_value=config)
        policy.start()
        self.addCleanup(policy.stop)

    def house(self):
        return dict(property_type='house', geo_precision='exact', price=120000,
                    condition_class='turnkey', plot_area=2000, living_area=200,
                    neighbour_class='dense', neighbour_checked_at='checked',
                    water_score=0, noise_checked_at='checked', energy_class='D',
                    energy_certificate_status='available', energy_updated_at='checked')

    def land(self):
        return dict(property_type='land', geo_precision='exact', price=50000,
                    plot_area=2000, neighbour_class='dense', water_score=0,
                    noise_checked_at='checked', primary_residence='confirmed',
                    buildability='BUILDING_PERMIT')

    def test_strict_threshold_for_both_property_types(self):
        for kind in ('house', 'land'):
            for maximum in (74, 75, 76):
                p = self.house() if kind == 'house' else self.land()
                if kind == 'house':
                    p['water_score'] = (maximum - score_house(p)['score']) * 2
                else:
                    p['price'] = 40000
                    p['water_score'] = maximum - score_land(p)['score']
                self.assertEqual(max_reachable_score(p), maximum)
                self.assertEqual(qualifies_as_chance(p), maximum == 76)

    def test_known_bad_components_are_not_replaced(self):
        for p, scorer in [(self.house(), score_house), (self.land(), score_land)]:
            before = copy.deepcopy(p)
            self.assertEqual(max_reachable_score(p), scorer(p)['score'])
            self.assertEqual(p, before)

    def test_multiple_unknowns_add_only_their_possible_points(self):
        p = self.house()
        known = score_house(p)['score']
        p['neighbour_class'] = None
        p['water_score'] = None
        self.assertEqual(max_reachable_score(p), known - 7 + 25 + 10)
        self.assertIsNone(score_house(p)['score'])

    def test_known_energy_penalty_survives_unfinished_checks(self):
        p = self.house()
        p.update(energy_class='H', energy_updated_at=None, water_score=None)
        result = best_case_result(p)
        self.assertIn('Energie: -8', ' '.join(result['reasons']))

    def test_budget_and_land_ko_remain_excluded(self):
        p = self.house()
        p.update(price=295000, condition_class='good', water_score=None)
        self.assertEqual(max_reachable_score(p), 0)
        p = self.land()
        p['residential_building_allowed'] = False
        self.assertEqual(max_reachable_score(p), 0)

    def test_unknown_condition_is_resolved_only_in_best_case(self):
        p = self.house()
        p['condition_class'] = 'unknown'
        self.assertEqual(best_case_result(p)['score'], score_house(self.house())['score'])
        self.assertEqual(p['condition_class'], 'unknown')

    def test_existing_rail_fallback_is_not_replaced_by_quiet(self):
        for p in (self.house(), self.land()):
            p.update(rail_distance_m=360, rail_annual_traffic=18738)
            result = best_case_result(p)
            self.assertIsNotNone(result['score'])
            self.assertIn('Ersatzwert', ' '.join(result['reasons']))
