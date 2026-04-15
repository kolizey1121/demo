"""
Простые тесты API без запуска бота
"""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_main():
    """Тест главной страницы"""
    response = requests.get(f"{BASE_URL}/")
    print(f"GET / → {response.status_code}")
    assert response.status_code == 200

def test_registration():
    """Тест регистрации"""
    init_data = "user%5Bid%5D=6728183219&user%5Bfirst_name%5D="Виктор""
    response = requests.post(
        f"{BASE_URL}/auth/register",
        headers={"X-Telegram-Init-Data": init_data}
    )
    print(f"POST /auth/register → {response.status_code}")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    print("🧪 Тестирование API...")
    try:
        test_main()
        # test_registration()  # Раскомментируй если нужно
        print("✅ Тесты пройдены!")
    except Exception as e:
        print(f"❌ Ошибка: {e}")