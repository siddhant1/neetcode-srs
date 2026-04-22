from datetime import date, timedelta

from neetcode_srs.srs import CardState, initial_state, schedule, EASE_MIN, EASE_MAX


TODAY = date(2026, 4, 22)


def test_initial_state_defaults():
    s = initial_state()
    assert s.ease == 2.5
    assert s.interval_days == 0
    assert s.reps == 0


def test_first_correct_sets_interval_to_1():
    result = schedule(initial_state(), "y", TODAY)
    assert result.state.reps == 1
    assert result.state.interval_days == 1
    assert result.next_due == TODAY + timedelta(days=1)
    assert result.state.ease == 2.55  # +0.05


def test_second_correct_jumps_to_6():
    after_first = schedule(initial_state(), "y", TODAY).state
    result = schedule(after_first, "y", TODAY + timedelta(days=1))
    assert result.state.reps == 2
    assert result.state.interval_days == 6
    assert result.next_due == TODAY + timedelta(days=7)


def test_third_correct_multiplies_by_ease():
    s = initial_state()
    s = schedule(s, "y", TODAY).state                        # reps=1, i=1, ease=2.55
    s = schedule(s, "y", TODAY + timedelta(days=1)).state     # reps=2, i=6, ease=2.60
    result = schedule(s, "y", TODAY + timedelta(days=7))      # reps=3, i=round(6*2.60)=16
    assert result.state.reps == 3
    assert result.state.interval_days == round(6 * 2.60)
    assert result.state.interval_days == 16


def test_wrong_answer_resets_with_three_day_minimum():
    """User-requested: failing must not bring the card back tomorrow — min 3 days."""
    s = initial_state()
    s = schedule(s, "y", TODAY).state
    s = schedule(s, "y", TODAY + timedelta(days=1)).state
    s = schedule(s, "y", TODAY + timedelta(days=7)).state
    wrong = schedule(s, "n", TODAY + timedelta(days=23))
    assert wrong.state.reps == 0
    assert wrong.state.interval_days == 3
    assert wrong.next_due == TODAY + timedelta(days=23 + 3)


def test_wrong_from_fresh_card_also_minimum_three_days():
    result = schedule(initial_state(), "n", TODAY)
    assert result.state.interval_days == 3
    assert result.state.reps == 0
    assert result.next_due == TODAY + timedelta(days=3)


def test_ease_decreases_on_wrong_then_grows_on_correct():
    s = initial_state()
    s = schedule(s, "n", TODAY).state
    assert abs(s.ease - 2.3) < 1e-9
    s = schedule(s, "y", TODAY + timedelta(days=3)).state
    assert abs(s.ease - 2.35) < 1e-9


def test_ease_floor():
    s = CardState(ease=EASE_MIN, interval_days=1, reps=0)
    s = schedule(s, "n", TODAY).state
    assert s.ease == EASE_MIN  # no lower than 1.3


def test_ease_ceiling():
    s = CardState(ease=EASE_MAX, interval_days=10, reps=5)
    s = schedule(s, "y", TODAY).state
    assert s.ease == EASE_MAX  # no higher than 2.8


def test_invalid_outcome_raises():
    import pytest
    with pytest.raises(ValueError):
        schedule(initial_state(), "maybe", TODAY)
