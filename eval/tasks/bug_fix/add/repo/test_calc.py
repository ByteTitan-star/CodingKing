from calc import add


def test_add() -> None:
    assert add(2, 3) == 5
    assert add(0, 0) == 0
