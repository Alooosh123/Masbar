from app.safety.output import sanitize_user_facing_text


def test_safe_arabic_answer_is_preserved():
    answer = "يمكن قياس الضغط باستخدام جهاز معاير وفق إجراء الموقع."
    assert sanitize_user_facing_text(answer) == answer


def test_internal_planning_fragments_are_rejected():
    assert sanitize_user_facing_text("User asks for a repair. We should respond with steps.") is None
    assert sanitize_user_facing_text("Analysis: The user likely means the pump.") is None
    assert sanitize_user_facing_text("<analysis>internal notes</analysis> الإجابة") is None


def test_invalid_or_oversized_output_is_rejected():
    assert sanitize_user_facing_text(None) is None
    assert sanitize_user_facing_text("   ") is None
    assert sanitize_user_facing_text("x" * 7001) is None
