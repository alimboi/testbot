# test_code_detection.py - Test the new functionality
from utils import (
    detect_programming_language, 
    extract_code_blocks, 
    format_text_with_code_blocks,
    parse_questions_from_text_enhanced
)

def test_language_detection():
    """Test programming language detection"""
    test_cases = [
        ("def hello():\n    print('Hello World')", "python"),
        ("function test() {\n    console.log('test');\n}", "javascript"),
        ("SELECT * FROM users WHERE age > 18;", "sql"),
        ("<div class='container'>Content</div>", "html"),
        ("Oddiy matn", None),
        ("const arr = [1, 2, 3];\nfor(let i of arr) console.log(i);", "javascript"),
        ("package main\nimport \"fmt\"\nfunc main() { fmt.Println(\"Hello\") }", "go"),
    ]
    
    print("=== Language Detection Tests ===")
    for text, expected in test_cases:
        detected, confidence = detect_programming_language(text)
        status = "✅" if detected == expected else "❌"
        print(f"{status} Text: {text[:30]}...")
        print(f"    Expected: {expected}, Got: {detected} (conf: {confidence:.2f})")
        print()

def test_code_formatting():
    """Test Telegram code formatting"""
    test_texts = [
        """1) JavaScript kodini tahlil qiling:
        function factorial(n) {
            if (n <= 1) return 1;
            return n * factorial(n - 1);
        }
        console.log(factorial(5));
        
        A) 120
        B) 24
        C) 5
        D) 1""",
        
        """2) Quyidagi Python kodi natijasini toping:
        def greet(name="World"):
            return f"Hello, {name}!"
        
        print(greet())
        print(greet("Python"))
        
        A) Hello, World! Hello, Python!
        B) Error
        C) Hello, ! Hello, Python!
        D) None""",
        
        """3) SQL so'rovini to'g'rilang:
        SELECT name, age 
        FROM users 
        WHERE age > 18 AND city = 'Tashkent'
        ORDER BY age DESC;
        
        A) Sintaksis xato
        B) To'g'ri
        C) WHERE kerak emas
        D) ORDER BY noto'g'ri""",
    ]
    
    print("=== Code Formatting Tests ===")
    for text in test_texts:
        print(f"Original:\n{text}")
        print("\nFormatted:")
        formatted = format_text_with_code_blocks(text)
        print(formatted)
        print("-" * 60)

def test_question_parsing():
    """Test enhanced question parsing"""
    sample_docx_content = """
    1) JavaScript array metodlarini tahlil qiling:
    let numbers = [1, 2, 3, 4, 5];
    let doubled = numbers.map(x => x * 2);
    console.log(doubled);
    
    A) [1, 2, 3, 4, 5]
    B) [2, 4, 6, 8, 10]
    C) [1, 4, 9, 16, 25]
    D) Error
    
    2) Python list comprehension natijasini aniqlang:
    squares = [x**2 for x in range(5)]
    print(squares)
    
    A) [0, 1, 4, 9, 16]
    B) [1, 2, 3, 4, 5]
    C) [0, 1, 2, 3, 4]
    D) Error
    
    3) HTML strukturasini tahlil qiling:
    <div class="container">
        <h1>Title</h1>
        <p>Paragraph text</p>
    </div>
    
    A) Sintaksis xato
    B) To'g'ri tuzilgan
    C) div tag yopilmagan
    D) class atributi noto'g'ri
    """
    
    print("=== Enhanced Question Parsing Test ===")
    questions = parse_questions_from_text_enhanced(sample_docx_content)
    
    for i, q in enumerate(questions, 1):
        print(f"Question {i}:")
        print(f"Index: {q['index']}")
        print(f"Text: {q['text']}")
        print("Options:")
        for key, value in q['options'].items():
            print(f"  {key}) {value}")
        print("-" * 40)

if __name__ == "__main__":
    test_language_detection()
    test_code_formatting()
    test_question_parsing()