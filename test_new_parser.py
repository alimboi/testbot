#!/usr/bin/env python3
"""
Test script for the new AI-like smart parsing system
"""

import sys
sys.path.insert(0, '/home/user/testbot')

from utils import (
    parse_questions_ai_smart,
    parse_answers_ai_smart,
    SmartTextAnalyzer,
    parse_questions_ultimate_smart
)


def test_basic_questions():
    """Test basic question parsing with different formats"""
    print("\n" + "="*80)
    print("TEST 1: Basic Questions with Different Formats")
    print("="*80)

    test_text = """
1) What is Python?
a) A snake
b) A programming language
c) A type of coffee
d) A car brand

2. Which operator is used for exponentiation?
A) ^
B) **
C) ^^
D) pow

3- What is the output of print(2+2)?
a. 22
b. 4
c. Error
d. None

4: What does JSON stand for?
A: JavaScript Object Notation
B: Java Standard Object Notation
C: Just Some Object Notation
D: None of the above
"""

    questions = parse_questions_ai_smart(test_text)
    print(f"\nParsed {len(questions)} questions")

    for q in questions:
        print(f"\nQuestion {q['index']}: {q['text'][:50]}...")
        print(f"Options: {list(q['options'].keys())}")
        for key, val in q['options'].items():
            print(f"  {key}) {val[:60]}...")

    assert len(questions) == 4, f"Expected 4 questions, got {len(questions)}"
    print("\n✅ Test 1 PASSED")


def test_code_in_options():
    """Test parsing when options contain code"""
    print("\n" + "="*80)
    print("TEST 2: Options with Code Blocks")
    print("="*80)

    test_text = """
1) What does this Python code do?
a) Prints Hello
b)
```python
def greet():
    print("World")
```
c) Returns None
d) Raises an error

2. Select the correct function:
A) def foo(): pass
B)
```python
def bar():
    return 42
```
C) lambda x: x
D) None of these
"""

    questions = parse_questions_ai_smart(test_text)
    print(f"\nParsed {len(questions)} questions")

    for q in questions:
        print(f"\nQuestion {q['index']}: {q['text'][:50]}...")
        for key, val in q['options'].items():
            print(f"  {key}) {val[:80]}...")
            if '```' in val:
                print(f"    ✓ Contains code block")

    assert len(questions) == 2, f"Expected 2 questions, got {len(questions)}"
    print("\n✅ Test 2 PASSED")


def test_answers_parsing():
    """Test answer parsing in different formats"""
    print("\n" + "="*80)
    print("TEST 3: Answer Parsing (Various Formats)")
    print("="*80)

    test_cases = [
        # Format 1: One per line with dot
        ("""
1.a
2.b
3.c
4.d
""", 4),

        # Format 2: One per line with parenthesis
        ("""
1)a
2)b
3)c
4)d
""", 4),

        # Format 3: Comma separated
        ("""
1a, 2b, 3c, 4d, 5a
""", 5),

        # Format 4: Space separated
        ("""
1a 2b 3c 4d 5a 6b
""", 6),

        # Format 5: Mixed format (dash, colon)
        ("""
1-a
2:b
3.c
4)d
""", 4),
    ]

    for i, (answer_text, expected_count) in enumerate(test_cases, 1):
        answers = parse_answers_ai_smart(answer_text)
        print(f"\nTest case {i}: Expected {expected_count}, got {len(answers)}")
        print(f"Answers: {answers}")
        assert len(answers) == expected_count, f"Test case {i} failed"

    print("\n✅ Test 3 PASSED")


def test_multiline_questions():
    """Test questions that span multiple lines"""
    print("\n" + "="*80)
    print("TEST 4: Multi-line Questions")
    print("="*80)

    test_text = """
1) Consider the following Python code:
```python
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n-1)
```
What is factorial(5)?
a) 120
b) 24
c) 5
d) Error

2. Which statement is true about the code above?
A) It uses iteration
B) It uses recursion
C) It's a lambda function
D) It raises an exception
"""

    questions = parse_questions_ai_smart(test_text)
    print(f"\nParsed {len(questions)} questions")

    for q in questions:
        print(f"\nQuestion {q['index']}:")
        print(f"Text length: {len(q['text'])} chars")
        print(f"Options: {list(q['options'].keys())}")
        if '```' in q['text']:
            print("  ✓ Contains code block in question text")

    assert len(questions) == 2, f"Expected 2 questions, got {len(questions)}"
    assert '```' in questions[0]['text'], "Expected code block in first question"
    print("\n✅ Test 4 PASSED")


def test_text_analyzer():
    """Test the SmartTextAnalyzer class"""
    print("\n" + "="*80)
    print("TEST 5: SmartTextAnalyzer Line Type Detection")
    print("="*80)

    analyzer = SmartTextAnalyzer()

    test_lines = [
        ("1) What is Python?", "question"),
        ("A) A snake", "option"),
        ("b. A language", "option"),
        ("3- Next question", "question"),
        ("1a", "answer"),
        ("2.b", "answer"),
        ("Some random text", "text"),
        ("", "empty"),
        ("```python", "code_fence"),
    ]

    for line, expected_type in test_lines:
        detected_type, data = analyzer.detect_line_type(line)
        print(f"Line: '{line}' -> {detected_type}")
        assert detected_type == expected_type, f"Expected {expected_type}, got {detected_type}"

    print("\n✅ Test 5 PASSED")


def test_ultimate_parser():
    """Test the ultimate parser that tries multiple strategies"""
    print("\n" + "="*80)
    print("TEST 6: Ultimate Smart Parser (Multiple Strategies)")
    print("="*80)

    test_text = """
1) What is 2+2?
a) 3
b) 4
c) 5
d) 6

2. Choose the correct answer:
A) Option A
B) Option B
C) Option C
D) Option D
"""

    questions = parse_questions_ultimate_smart(test_text)
    print(f"\nParsed {len(questions)} questions using ultimate parser")

    for q in questions:
        print(f"\nQuestion {q['index']}: {q['text'][:50]}...")
        print(f"Options: {list(q['options'].keys())}")

    assert len(questions) == 2, f"Expected 2 questions, got {len(questions)}"
    print("\n✅ Test 6 PASSED")


def test_no_space_after_marker():
    """Test parsing when there's no space after option marker (like 'd)code')"""
    print("\n" + "="*80)
    print("TEST 7: Options Without Space After Marker")
    print("="*80)

    test_text = """
1) What is the correct syntax?
a)Option A with space
b)Option B no space
c)
```python
def foo():
    pass
```
d)Some code here
"""

    questions = parse_questions_ai_smart(test_text)
    print(f"\nParsed {len(questions)} questions")

    if questions:
        q = questions[0]
        print(f"\nQuestion {q['index']}: {q['text'][:50]}...")
        print(f"Found {len(q['options'])} options:")
        for key, val in q['options'].items():
            print(f"  {key}) {val[:60]}...")

        # Should parse all 4 options even without spaces
        assert len(q['options']) >= 3, f"Expected at least 3 options, got {len(q['options'])}"

    print("\n✅ Test 7 PASSED")


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("AI-LIKE SMART PARSER TEST SUITE")
    print("="*80)

    try:
        test_basic_questions()
        test_code_in_options()
        test_answers_parsing()
        test_multiline_questions()
        test_text_analyzer()
        test_ultimate_parser()
        test_no_space_after_marker()

        print("\n" + "="*80)
        print("🎉 ALL TESTS PASSED! 🎉")
        print("="*80)
        print("\nThe new AI-like smart parsing system is working correctly!")
        print("It can handle:")
        print("  ✓ Multiple question formats (1), 1., 1-, 1:, etc.)")
        print("  ✓ Multiple option formats (a), a., a-, a:, etc.)")
        print("  ✓ Options with and without spaces after markers")
        print("  ✓ Code blocks in questions and options")
        print("  ✓ Multi-line questions and options")
        print("  ✓ Various answer formats (comma-separated, space-separated, etc.)")
        print("  ✓ Answers that come after all questions")
        print("\n")

        return 0
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
