"""
    COUP gray-area fixture: a parent that owns children and passes itself to
    each one so the child can report back. The two classes know each other, but
    through one narrow public method.
"""


class Playlist:
    def __init__(self) -> None:
        self._tracks: list["Track"] = []
        self.finished_count = 0

    def add(self, title: str) -> None:
        self._tracks.append(Track(title, self))

    def play_all(self) -> None:
        for track in self._tracks:
            track.play()

    def track_finished(self) -> None:
        self.finished_count += 1


class Track:
    def __init__(self, title: str, playlist: Playlist) -> None:
        self._title = title
        self._playlist = playlist

    def play(self) -> None:
        print(f"playing {self._title}")
        self._playlist.track_finished()
