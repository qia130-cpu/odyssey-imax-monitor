from datetime import date
from monitor import Showtime, is_imax, upcoming_weekend_dates, walk_dicts, looks_like_show, normalize_show

def test_weekends():
    # 2026-08-23 is Sunday; current day must be excluded.
    result = upcoming_weekend_dates(date(2026, 8, 23))
    assert result[0].isoformat() == "2026-08-29"
    assert result[1].isoformat() == "2026-08-30"

def test_imax_detection():
    s = Showtime("2026-08-29", "19:00", "英语IMAX2D", "", "激光IMAX厅", "100", "1")
    assert is_imax(s)

def test_recursive_payload_extraction_shape():
    payload = {
        "showData": {
            "movies": [
                {
                    "shows": [
                        {
                            "plist": [
                                {
                                    "tm": "19:00",
                                    "lang": "英语IMAX2D",
                                    "th": "激光IMAX厅",
                                    "sellPr": "109",
                                    "seqNo": "abc123",
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }
    items = [d for d in walk_dicts(payload) if looks_like_show(d)]
    assert len(items) == 1
    show = normalize_show(items[0], "2026-08-29")
    assert show.time == "19:00"
    assert show.hall == "激光IMAX厅"
    assert show.key == "seq:abc123"
