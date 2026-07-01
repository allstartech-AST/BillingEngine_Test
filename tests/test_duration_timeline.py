from app.engine.duration import merged_timeline_minutes


def test_merged_timeline_non_overlapping():
    minutes = merged_timeline_minutes([
        ("00:00:00", "00:30:00"),
        ("00:30:00", "01:00:00"),
    ])
    assert minutes == 60.0


def test_merged_timeline_overlapping():
    minutes = merged_timeline_minutes([
        ("00:00:00", "00:45:00"),
        ("00:30:00", "01:00:00"),
    ])
    assert minutes == 60.0


def test_merged_timeline_identical_windows():
    minutes = merged_timeline_minutes([
        ("01:00:00", "01:30:00"),
        ("01:00:00", "01:30:00"),
    ])
    assert minutes == 30.0
