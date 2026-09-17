"""Preview/apply current scoring without geo requests or external messages."""
import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from config_loader import CONFIG
from scoring import score_house, score_land
from property_types import is_house_type
from neighbour_policy import reclassify_stored_neighbours


def rescore(db_path, apply=False):
    uri = Path(db_path).resolve().as_uri() + ('?mode=rw' if apply else '?mode=ro')
    conn = sqlite3.connect(uri, uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    counts = Counter()
    try:
        conn.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        rows = conn.execute("SELECT * FROM properties WHERE property_type IN ('house', 'farm', 'land')").fetchall()
        for row in rows:
            p = dict(row)
            details = json.loads(p.get('score_details') or '{}')
            if p.get('rating') in ('blacklisted', 'deleted', 'offline', 'not_interested') or details.get('blacklisted'):
                counts['preserved_exclusions'] += 1
                continue
            current_neighbour_class = p.get('neighbour_class')
            p['neighbour_class'] = reclassify_stored_neighbours(p)
            if p['neighbour_class'] != current_neighbour_class:
                counts['neighbour_class_changed'] += 1
            scorer = score_house if is_house_type(p['property_type']) else score_land
            result = scorer(p)
            if details.get('geo_errors'):
                result['geo_errors'] = details['geo_errors']
            counts['reviewed'] += 1
            if any(str(reason).startswith('Budget überschritten') for reason in result.get('ko_reasons', [])):
                counts['budget_ko'] += 1
            if (p.get('score'), p.get('rating'), bool(p.get('is_ko'))) != (result['score'], result['rating'], result['ko']):
                counts['changed'] += 1
            if apply:
                conn.execute('UPDATE properties SET neighbour_class=?, score=?, rating=?, is_ko=?, score_details=? WHERE id=?',
                             (p['neighbour_class'], result['score'], result['rating'], int(result['ko']), json.dumps(result, ensure_ascii=False), p['id']))
        conn.commit() if apply else conn.rollback()
        return dict(counts)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='/data/database.sqlite3')
    parser.add_argument('--config-dir', default='/config')
    parser.add_argument('--apply', action='store_true', help='Write scores after making a SQLite backup')
    parser.add_argument('--backup', help='New backup file, required with --apply')
    args = parser.parse_args()
    CONFIG.config_dir = args.config_dir
    if args.apply:
        if not args.backup or Path(args.backup).exists():
            parser.error('--apply requires a new --backup path')
        with sqlite3.connect(Path(args.db).resolve().as_uri() + '?mode=ro', uri=True) as source:
            target = sqlite3.connect(args.backup)
            try:
                source.backup(target)
            finally:
                target.close()
        source.close()
    print(json.dumps({'applied': args.apply, **rescore(args.db, apply=args.apply)}))


if __name__ == '__main__':
    main()
