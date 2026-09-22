from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.domain.consumer_voice import prepare_reviews


class ConsumerVoiceRepository:
    """Loads the reviewed Consumer Voice dump bundled with the API."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path(__file__).resolve().parents[2] / "data" / "consumer_voice_reviews.csv"
        self._data: pd.DataFrame | None = None

    def get(self) -> pd.DataFrame:
        if self._data is None:
            self._data = prepare_reviews(pd.read_csv(self.path, keep_default_na=False))
        return self._data.copy(deep=False)
