"""
📊 init_db.py - Первая инициализация базы данных
Использование: python scripts/init_db.py
"""

from datetime import date, timedelta
from sqlalchemy.orm import Session
import sys

# Добавь корневую папку в path
sys.path.append('..')

from main import engine, Base, DailyQuest, Course

def init_database():
    """
    Инициализировать БД с начальными данными
    """
    
    print("\n" + "="*70)
    print("📊 ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ")
    print("="*70 + "\n")
    
    # === ШАГ 1: СОЗДАТЬ ТАБЛИЦЫ ===
    print("1️⃣  Создание таблиц...")
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Таблицы созданы успешно\n")
    except Exception as e:
        print(f"❌ Ошибка создания таблиц: {e}\n")
        return False
    
    # === ШАГ 2: ДОБАВИТЬ ВОПРОСЫ ===
    print("2️⃣  Добавление вопросов квестов...")
    
    quests = [
        {
            "quest_date": date.today(),
            "question": "Что такое волны вероятности в Транссерфинге?",
            "correct_answer": "альтернативные линии реальности",
            "alternative_answers": ["линии реальности", "вероятности", "волны"],
            "hint": "Это множество возможных вариантов развития событий",
            "difficulty": "medium",
            "prize_amount": 750,
            "category": "transsurfing"
        },
        {
            "quest_date": date.today() + timedelta(days=1),
            "question": "Кто автор книги 'Апокрифический Транссерфинг'?",
            "correct_answer": "Вадим Зеланд",
            "alternative_answers": ["Зеланд", "В. Зеланд"],
            "hint": "Русский философ и писатель",
            "difficulty": "easy",
            "prize_amount": 500,
            "category": "transsurfing"
        },
        {
            "quest_date": date.today() + timedelta(days=2),
            "question": "Что означает принцип 'Важность' в Транссерфинге?",
            "correct_answer": "наше внимание притягивает маятники",
            "alternative_answers": ["важность событий", "маятники", "внимание"],
            "hint": "То, на что мы обращаем внимание, становится более реальным",
            "difficulty": "hard",
            "prize_amount": 1000,
            "category": "transsurfing"
        },
        {
            "quest_date": date.today() + timedelta(days=3),
            "question": "Какие три шага входят в практику Транссерфинга?",
            "correct_answer": "расслабление осознавание доверие",
            "alternative_answers": ["релаксация осознание вера", "расслабление сознание доверие"],
            "hint": "Первый шаг - расслабить внимание",
            "difficulty": "hard",
            "prize_amount": 1500,
            "category": "practice"
        },
        {
            "quest_date": date.today() + timedelta(days=4),
            "question": "Что такое маятники в Транссерфинге?",
            "correct_answer": "вибрирующие объекты реальности",
            "alternative_answers": ["вибрирующие объекты", "энергетические вихри"],
            "hint": "Они управляют нашим вниманием и эмоциями",
            "difficulty": "medium",
            "prize_amount": 750,
            "category": "transsurfing"
        },
        {
            "quest_date": date.today() + timedelta(days=5),
            "question": "На сколько книг разделена серия 'Трансcёрфинг'?",
            "correct_answer": "5",
            "alternative_answers": ["пять", "5 книг"],
            "hint": "Это число от 1 до 10",
            "difficulty": "easy",
            "prize_amount": 600,
            "category": "transsurfing"
        },
    ]
    
    db = Session(engine)
    
    try:
        for idx, quest_data in enumerate(quests, 1):
            # Проверить что вопроса еще нет
            existing = db.query(DailyQuest).filter(
                DailyQuest.quest_date == quest_data["quest_date"]
            ).first()
            
            if existing:
                print(f"  ⏭️  {idx}. {quest_data['quest_date']} - уже существует")
                continue
            
            quest = DailyQuest(**quest_data)
            db.add(quest)
            print(f"  ✅ {idx}. {quest_data['quest_date']} - добавлен")
        
        db.commit()
        print(f"✅ Добавлено {len(quests)} вопросов\n")
        
    except Exception as e:
        print(f"❌ Ошибка при добавлении вопросов: {e}\n")
        db.rollback()
        return False
    finally:
        db.close()
    
    # === ШАГ 3: ДОБАВИТЬ КУРСЫ ===
    print("3️⃣  Добавление курсов обучения...")
    
    courses = [
        {
            "title": "🌟 Введение в Транссерфинг",
            "description": "Основные принципы управления реальностью через волны вероятности",
            "content": """
            <h2>Основные концепции</h2>
            <p>Транссёрфинг реальности - это техника осознанного управления своей жизнью через понимание и работу с волнами вероятности.</p>
            <h3>Главные принципы:</h3>
            <ul>
                <li>1. Волны вероятности</li>
                <li>2. Маятники</li>
                <li>3. Важность</li>
                <li>4. Целевое скольжение</li>
                <li>5. Разворот ситуации</li>
            </ul>
            """,
            "content_url": "https://youtube.com/playlist?list=...",
            "level": "beginner",
            "duration_minutes": 45,
            "order": 1
        },
        {
            "title": "🎯 Практика Транссерфинга",
            "description": "Практические упражнения и техники для освоения методики",
            "content": """
            <h2>Практические упражнения</h2>
            <p>В этом курсе ты научишься применять принципы Транссёрфинга на практике.</p>
            <h3>Упражнения:</h3>
            <ul>
                <li>Упражнение 1: Осознание волн</li>
                <li>Упражнение 2: Распознавание маятников</li>
                <li>Упражнение 3: Целевое скольжение</li>
                <li>Упражнение 4: Медитация осознания</li>
            </ul>
            """,
            "content_url": "https://youtube.com/playlist?list=...",
            "level": "intermediate",
            "duration_minutes": 60,
            "order": 2
        },
        {
            "title": "⭐ Продвинутый Транссерфинг",
            "description": "Глубокое понимание и продвинутые техники управления реальностью",
            "content": """
            <h2>Продвинутые техники</h2>
            <p>Для тех кто хочет полностью овладеть техникой Транссёрфинга.</p>
            <h3>Темы:</h3>
            <ul>
                <li>Глубокая работа с маятниками</li>
                <li>Множественные волны вероятности</li>
                <li>Создание своих маятников</li>
                <li>Трансформация сценариев</li>
            </ul>
            """,
            "content_url": "https://youtube.com/playlist?list=...",
            "level": "advanced",
            "duration_minutes": 90,
            "order": 3
        },
        {
            "title": "💡 Психология и Мышление",
            "description": "Психологические основы Транссёрфинга",
            "content": """
            <h2>Психология Транссёрфинга</h2>
            <p>Понимание психологических процессов лежащих в основе методики.</p>
            """,
            "content_url": "https://youtube.com/playlist?list=...",
            "level": "intermediate",
            "duration_minutes": 75,
            "order": 4
        },
    ]
    
    db = Session(engine)
    
    try:
        for idx, course_data in enumerate(courses, 1):
            # Проверить что курса еще нет
            existing = db.query(Course).filter(
                Course.title == course_data["title"]
            ).first()
            
            if existing:
                print(f"  ⏭️  {idx}. {course_data['title']} - уже существует")
                continue
            
            course = Course(**course_data)
            db.add(course)
            print(f"  ✅ {idx}. {course_data['title']} - добавлен")
        
        db.commit()
        print(f"✅ Добавлено {len(courses)} курсов\n")
        
    except Exception as e:
        print(f"❌ Ошибка при добавлении курсов: {e}\n")
        db.rollback()
        return False
    finally:
        db.close()
    
    # === ИТОГОВАЯ СТАТИСТИКА ===
    print("="*70)
    print("✅ ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
    print("="*70)
    print(f"\n📊 Статистика:")
    print(f"   📋 Вопросов добавлено: {len(quests)}")
    print(f"   📚 Курсов добавлено: {len(courses)}")
    print(f"   📁 Файл БД: academy.db")
    print(f"\n🎯 Что дальше:")
    print(f"   1. Запусти: python main.py")
    print(f"   2. Открой браузер: http://localhost:8000")
    print(f"   3. Проверь интерфейс")
    print(f"\n📝 Для добавления новых вопросов:")
    print(f"   python scripts/add_quest.py\n")
    
    return True


if __name__ == "__main__":
    success = init_database()
    
    if not success:
        print("\n❌ ИНИЦИАЛИЗАЦИЯ НЕ УДАЛАСЬ")
        print("Проверь ошибки выше\n")
        sys.exit(1)