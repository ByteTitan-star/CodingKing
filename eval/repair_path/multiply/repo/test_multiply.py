from multiply import multiply


def test_multiply() -> None:
    assert multiply(3, 4) == 12
    assert multiply(0, 9) == 0
