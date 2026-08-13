"""
    BOUND false-positive fixture: Playlist hands out its track list only
    as a copy, never the live internal list. Should NOT be flagged as
    leaking its internal representation — external code mutating the
    returned list has no effect on the playlist's real state.
"""


class Playlist:
    def __init__(self) -> None:
        self._tracks: list[str] = []

    def add_track(self, track_name: str) -> None:
        self._tracks.append(track_name)

    def tracks(self) -> list[str]:
        return list(self._tracks)
