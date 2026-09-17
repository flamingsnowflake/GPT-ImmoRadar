import io
import urllib.parse
import unittest
from unittest.mock import patch

import enrichment


class BrandenburgGeoTest(unittest.TestCase):

    latitude = 52.4009
    longitude = 13.0590

    def _urlopen_response(self, xml):

        return io.BytesIO(
            xml.encode("utf-8")
        )

    def test_brandenburg_is_supported(self):

        self.assertTrue(
            enrichment.FEDERAL_STATES[
                "DE-BB"
            ]["geo_supported"]
        )

    def test_brandenburg_water_uses_official_projected_wfs(self):

        point_x, point_y = (
            enrichment._transform_to_25832.transform(
                self.longitude,
                self.latitude,
            )
        )

        xml = f"""
            <wfs:FeatureCollection
                xmlns:wfs="http://www.opengis.net/wfs/2.0"
                xmlns:gml="http://www.opengis.net/gml/3.2"
                xmlns:hy-p="urn:test:hy-p"
                xmlns:base="urn:test:base">
              <wfs:member>
                <hy-p:Watercourse>
                  <hy-p:width>
                    <hy-p:lower>3</hy-p:lower>
                    <hy-p:upper>6</hy-p:upper>
                  </hy-p:width>
                  <base:localId>bb-water-1</base:localId>
                  <gml:posList>
                    {point_x + 100} {point_y - 100}
                    {point_x + 100} {point_y + 100}
                  </gml:posList>
                </hy-p:Watercourse>
              </wfs:member>
            </wfs:FeatureCollection>
        """

        with patch.object(
            enrichment,
            "_federal_state_code",
            return_value="DE-BB",
        ), patch.object(
            enrichment.urllib.request,
            "urlopen",
            return_value=self._urlopen_response(
                xml
            ),
        ) as urlopen:

            result = enrichment.find_best_water(
                self.latitude,
                self.longitude,
            )

        self.assertEqual(
            result["water_class"],
            "small_river",
        )
        self.assertEqual(
            result["water_score"],
            17,
        )
        self.assertEqual(
            result["osm_id"],
            "bb-water-1",
        )
        self.assertIn(
            "Brandenburg",
            result["source"],
        )

        request = urlopen.call_args.args[0]
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(
                request.full_url
            ).query
        )

        self.assertIn(
            "inspire.brandenburg.de/services/"
            "hy-p_bdlm_wfs",
            request.full_url,
        )
        self.assertEqual(
            query["typeNames"],
            ["hy-p:Watercourse"],
        )
        self.assertEqual(
            query["srsName"],
            ["urn:ogc:def:crs:EPSG::25832"],
        )

    def test_brandenburg_buildings_use_official_projected_wfs(self):

        point_x, point_y = (
            enrichment._transform_to_25832.transform(
                self.longitude,
                self.latitude,
            )
        )

        def square(center_x, center_y, half=5):

            return " ".join(
                str(value)
                for value in (
                    center_x - half,
                    center_y - half,
                    center_x + half,
                    center_y - half,
                    center_x + half,
                    center_y + half,
                    center_x - half,
                    center_y + half,
                    center_x - half,
                    center_y - half,
                )
            )

        polygons = "".join(
            f"""
                <wfs:member>
                  <bu:Building>
                    <gml:posList>{square(point_x + offset, point_y)}</gml:posList>
                  </bu:Building>
                </wfs:member>
            """
            for offset in (0, 50, 150, 300)
        )

        xml = f"""
            <wfs:FeatureCollection
                xmlns:wfs="http://www.opengis.net/wfs/2.0"
                xmlns:gml="http://www.opengis.net/gml/3.2"
                xmlns:bu="urn:test:bu">
              {polygons}
            </wfs:FeatureCollection>
        """

        with patch.object(
            enrichment,
            "_federal_state_code",
            return_value="DE-BB",
        ), patch.object(
            enrichment.urllib.request,
            "urlopen",
            return_value=self._urlopen_response(
                xml
            ),
        ) as urlopen:

            result = enrichment.find_neighbour_buildings(
                self.latitude,
                self.longitude,
            )

        self.assertAlmostEqual(
            result["nearest_building_m"],
            45,
        )
        self.assertEqual(
            result["buildings_50m"],
            1,
        )
        self.assertEqual(
            result["buildings_100m"],
            1,
        )
        self.assertEqual(
            result["buildings_250m"],
            2,
        )
        self.assertEqual(
            result["buildings_500m"],
            3,
        )
        self.assertEqual(
            result["feature_count"],
            4,
        )

        request = urlopen.call_args.args[0]
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(
                request.full_url
            ).query
        )

        self.assertIn(
            "inspire.brandenburg.de/services/"
            "bu_alkis_wfs",
            request.full_url,
        )
        self.assertEqual(
            query["typeNames"],
            ["bu-core2d:Building"],
        )
        self.assertEqual(
            query["srsName"],
            ["urn:ogc:def:crs:EPSG::25832"],
        )


if __name__ == "__main__":
    unittest.main()
