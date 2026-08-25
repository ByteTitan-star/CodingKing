from geometry import box_area, square_area


def test_areas() -> None:
    assert box_area(3, 4) == 12
    assert square_area(5) == 25
