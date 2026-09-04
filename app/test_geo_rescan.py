import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
from config_loader import CONFIG
import monitor
import manual_coordinates as manual
import noise_sources


class GeoRescanTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = str(Path(self.directory.name) / 'test.sqlite3')
        for obj, attr, value in [(monitor, 'DB_PATH', self.db), (manual, 'DB_PATH', self.db),
                                 (CONFIG, 'config_dir', str(Path(__file__).resolve().parent.parent / 'config'))]:
            patcher = patch.object(obj, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        con = monitor.get_db()
        con.execute("INSERT INTO properties (portal, portal_id, title, location, first_seen, last_seen, property_type, latitude, longitude, geo_precision, manual_latitude, manual_longitude, price, condition_class, plot_area, living_area, energy_updated_at, energy_class, energy_certificate_status, water_score, neighbour_class, neighbour_checked_at, noise_checked_at, rail_distance_m, score, rating) VALUES ('test', 'test-id', 'Synthetic house', 'Example street 1', 'now', 'now', 'house', 52, 11, 'exact', 52, 11, 120000, 'good', 2000, 200, 'checked', 'C', 'available', 20, 'isolated', 'old', 'old', 42, 99, 'dream')")
        con.commit()
        con.close()

    def row(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.row_factory = sqlite3.Row
            return dict(con.execute('SELECT * FROM properties').fetchone())

    def test_manual_update_rechecks_all_modules_at_new_coordinates(self):
        def water(lat, lon):
            self.assertEqual((lat, lon), (52.001, 11.002))
            current = self.row()
            self.assertIsNone(current['water_score'])
            self.assertIsNone(current['rail_distance_m'])
            self.assertIsNone(current['score'])
            return None
        buildings = dict(nearest_building_m=100, buildings_100m=2, buildings_250m=3, buildings_500m=5)
        with patch.object(monitor, 'find_best_water', side_effect=water) as w, \
             patch.object(monitor, 'find_neighbour_buildings', return_value=buildings) as n, \
             patch.object(monitor, 'get_noise', return_value={'rail': {'rail_distance_m': 600, 'annual_traffic': 1000}, 'road': {}, 'air': {}}) as noise:
            result = manual.set_manual_coordinates('test-id', 52.001, 11.002)
            for lookup in (w, n, noise):
                lookup.assert_called_once_with(52.001, 11.002)
        row = self.row()
        self.assertEqual(row['water_score'], 0)
        self.assertEqual(row['rail_distance_m'], 600)
        self.assertIsNotNone(row['score'])
        self.assertIn('✅ Wasser: neu berechnet', result)

    def test_failed_module_does_not_stop_others_and_is_persisted(self):
        with patch.object(monitor, 'find_best_water', side_effect=RuntimeError('coverage unavailable')), \
             patch.object(monitor, 'find_neighbour_buildings', side_effect=RuntimeError('service unavailable')) as n, \
             patch.object(monitor, 'get_noise', return_value={'rail': {}, 'road': {}, 'air': {}}) as noise:
            result = manual.rescan_geo('test-id')
            n.assert_called_once()
            noise.assert_called_once()
        self.assertIn('Wasser: RuntimeError: coverage unavailable', result)
        self.assertIn('Nachbarn: RuntimeError: service unavailable', result)
        self.assertIn('✅ Lärm/Bahn', result)
        row = self.row()
        self.assertIsNone(row['water_score'])
        self.assertIsNone(row['score'])
        self.assertIn('Wasser', json.loads(row['score_details'])['geo_errors'])

    def test_fatal_failure_cannot_leave_old_score(self):
        with patch.object(manual, 'enrich_property', side_effect=RuntimeError('failed')):
            self.assertIn('fehlgeschlagen', manual.rescan_geo('test-id'))
        self.assertIsNone(self.row()['score'])
        self.assertIsNone(self.row()['water_score'])

    def test_all_noise_sources_are_attempted_after_rail_failure(self):
        with patch.object(noise_sources, 'get_rail_noise', side_effect=RuntimeError('rail unavailable')), \
             patch.object(noise_sources, 'get_road_noise', return_value={}) as road, \
             patch.object(noise_sources, 'get_air_noise', return_value={}) as air:
            with self.assertRaisesRegex(RuntimeError, 'rail unavailable'):
                noise_sources.get_noise(52, 11)
            road.assert_called_once()
            air.assert_called_once()
