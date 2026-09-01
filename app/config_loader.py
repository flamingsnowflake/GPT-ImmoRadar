import os
import yaml


class ConfigLoader:

    def __init__(self, config_dir="/config"):

        self.config_dir = config_dir

        self._cache = {}
        self._mtimes = {}


    def _load(self, filename):

        path = os.path.join(
            self.config_dir,
            filename
        )

        try:
            mtime = os.path.getmtime(path)

        except FileNotFoundError:
            return {}

        if (
            filename not in self._cache
            or self._mtimes.get(filename) != mtime
        ):

            with open(
                path,
                "r",
                encoding="utf-8"
            ) as f:

                self._cache[filename] = (
                    yaml.safe_load(f) or {}
                )

            self._mtimes[filename] = mtime

            print(
                f"Configuration reloaded: {filename}",
                flush=True
            )

        return self._cache[filename]


    def blacklist_terms(self):

        config = self._load(
            "blacklist.yaml"
        )

        return [
            str(term).strip().lower()
            for term in config.get(
                "terms",
                []
            )
            if str(term).strip()
        ]


    def score_config(self):

        return self._load(
            "score.yaml"
        )

    def property_types_config(self):

        return self._load(
            "property_types.yaml"
        )

    def score_config(self):

        return self._load(
            "score.yaml"
        )


    def property_types_config(self):

        return self._load(
            "property_types.yaml"
        )


    def house_condition_config(self):

        return self._load(
            "house_condition.yaml"
        )


CONFIG = ConfigLoader()
