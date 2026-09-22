from src.models import Detection
from src.tracking import CentroidTracker


def test_id_persists_and_assignments_are_unique():
    tracker = CentroidTracker(max_distance=60, max_missed_frames=2)
    first = tracker.update([Detection((10, 10, 20, 20)), Detection((100, 10, 20, 20))])
    ids = [track.track_id for track in first]
    second = tracker.update([Detection((18, 14, 20, 20)), Detection((108, 14, 20, 20))])
    assert [track.track_id for track in second] == ids
    assert len({track.track_id for track in second}) == 2


def test_tracking_loss_tolerance():
    tracker = CentroidTracker(max_distance=60, max_missed_frames=2)
    track_id = tracker.update([Detection((10, 10, 20, 20))])[0].track_id
    tracker.update([])
    recovered = tracker.update([Detection((14, 12, 20, 20))])
    assert recovered[0].track_id == track_id


def test_expired_track_gets_new_id():
    tracker = CentroidTracker(max_distance=60, max_missed_frames=1)
    first_id = tracker.update([Detection((10, 10, 20, 20))])[0].track_id
    tracker.update([])
    tracker.update([])
    second_id = tracker.update([Detection((10, 10, 20, 20))])[0].track_id
    assert second_id != first_id
