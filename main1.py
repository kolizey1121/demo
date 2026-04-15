"""
🌌 Академия Транссерфинга Реальности — ПОЛНАЯ ВЕРСИЯ v3.0
Все модули: регистрация, квесты, обучение, комьюнити, рейтинг, выплаты
"""

from fastapi import FastAPI, Request, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Date, Boolean, JSON, DateTime, Text, func, Float
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.sql import func as sql_func
from datetime import date, datetime, timedelta
import os
from dotenv import load_dotenv
import httpx
import uuid
import hashlib
import hmac
import logging
import html
from urllib.parse import parse_qsl
from collections import defaultdict
import time
import asyncio
from difflib import SequenceMatcher
import re

# === ПЛАНИРОВЩИК ЗАДАЧ ===
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# === GOOGLE SHEETS ===
try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False
    print("⚠️ gspread не установлен. Google Sheets будет отключен.")

load_dotenv()

# ===================== ЛОГИРОВАНИЕ =====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===================== НАСТРОЙКИ =====================
settings = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN"),
    "WEBAPP_URL": os.getenv("WEBAPP_URL"),
    "YOOKASSA_SHOP_ID": os.getenv("YOOKASSA_SHOP_ID"),
    "YOOKASSA_SECRET": os.getenv("YOOKASSA_SECRET"),
    "DATABASE_URL": os.getenv("DATABASE_URL", "sqlite:///./academy.db"),
    "MIN_WITHDRAW": 300,
    "MAX_WITHDRAW": 100000,
    "RATE_LIMIT_REQUESTS": 100,
    "RATE_LIMIT_WINDOW": 3600,
    
    # === КАСТОМИЗИРУЙ ===
    "GOOGLE_SHEETS_ID": os.getenv("GOOGLE_SHEETS_ID", ""),
    "TELEGRAM_CHANNEL_ID": os.getenv("TELEGRAM_CHANNEL_ID", ""),  # ID закрытого канала
    "TELEGRAM_API_URL": "https://api.telegram.org/bot" + os.getenv("BOT_TOKEN", ""),
    
    # Время публикации вопроса (часы и минуты)
    "QUEST_PUBLISH_HOUR": 8,
    "QUEST_PUBLISH_MINUTE": 0,
    
    # Время публикации подсказки в соцсети
    "HINT_PUBLISH_START": 10,  # 10:00
    "HINT_PUBLISH_END": 17,    # 17:00
    
    # Время объявления победителя
    "WINNER_ANNOUNCE_HOUR": 18,
    "WINNER_ANNOUNCE_MINUTE": 0,
    
    # Размер приза за правильный ответ (в рублях)
    "QUEST_PRIZE_AMOUNT": 750,
    
    # Допустимое совпадение ответа (0-1)
    "ANSWER_MATCH_THRESHOLD": 0.85,
}

app = FastAPI(title="🌌 Академия Транссерфинга Реальности", version="3.0")
# ✅ ДОБАВЛЕНО
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ===================== RATE LIMITING =====================
class RateLimiter:
    def __init__(self, max_requests: int, window: int):
        self.max_requests = max_requests
        self.window = window
        self.requests = defaultdict(list)
    
    def is_allowed(self, user_id: int) -> bool:
        now = time.time()
        self.requests[user_id] = [t for t in self.requests[user_id] if now - t < self.window]
        
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        
        self.requests[user_id].append(now)
        return True

rate_limiter = RateLimiter(settings["RATE_LIMIT_REQUESTS"], settings["RATE_LIMIT_WINDOW"])

# ===================== БАЗА ДАННЫХ =====================
engine = create_engine(
    settings["DATABASE_URL"],
    connect_args={"check_same_thread": False} if "sqlite" in settings["DATABASE_URL"] else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# === ТАБЛИЦА: ПОЛЬЗОВАТЕЛИ ===
class User(Base):
    __tablename__ = "users"
    telegram_id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    balance = Column(Integer, default=0)
    payment_details = Column(JSON, nullable=True)
    is_subscribed = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=sql_func.now())
    withdraw_in_progress = Column(Boolean, default=False)
    last_withdraw_at = Column(DateTime, nullable=True)


# === ТАБЛИЦА: ЕЖЕДНЕВНЫЕ КВЕСТЫ ===
class DailyQuest(Base):
    __tablename__ = "daily_quests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    quest_date = Column(Date, unique=True, index=True)
    
    # 🎯 КАСТОМИЗИРУЙ ВОПРОСЫ И ОТВЕТЫ ===
    question = Column(String(500))  # Вопрос, который видят пользователи
    correct_answer = Column(String(500))  # Правильный ответ (может быть несколько вариантов)
    alternative_answers = Column(JSON, nullable=True)  # ["вариант1", "вариант2", "вариант3"]
    hint = Column(String(300), nullable=True)  # Подсказка для соцсетей
    
    prize_amount = Column(Integer, default=750)  # Приз за правильный ответ
    published_at = Column(DateTime, nullable=True)  # Когда вопрос был опубликован
    published_in_channel = Column(Boolean, default=False)
    published_in_social = Column(Boolean, default=False)
    
    # КАСТОМИЗИРУЙ СЛОЖНОСТЬ ===
    difficulty = Column(String(20), default="medium")  # easy, medium, hard
    category = Column(String(100), default="transsurfing")  # Категория вопроса
    
    created_at = Column(DateTime, server_default=sql_func.now())


# === ТАБЛИЦА: ОТВЕТЫ ПОЛЬЗОВАТЕЛЕЙ ===
class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, index=True)
    quest_id = Column(Integer, index=True)  # Связь с квестом
    quest_date = Column(Date, index=True)
    
    # Ответ пользователя
    answer = Column(String(500))
    submitted_at = Column(DateTime, server_default=sql_func.now())
    
    # Проверка ответа
    is_correct = Column(Boolean, default=False)
    match_score = Column(Float, default=0.0)  # Процент совпадения (0-1)
    checked_at = Column(DateTime, nullable=True)
    
    score = Column(Integer, default=0)


# === ТАБЛИЦА: ПРИЗЫ И ВЫПЛАТЫ ===
class Prize(Base):
    __tablename__ = "prizes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, index=True)
    quest_id = Column(Integer, nullable=True)
    amount = Column(Integer)
    status = Column(String(20), default="pending")  # pending / paid / failed
    payout_id = Column(String(100), nullable=True)
    paid_at = Column(DateTime, server_default=sql_func.now())
    description = Column(String(300), nullable=True)
    error_message = Column(Text, nullable=True)


# === ТАБЛИЦА: РЕЙТИНГ ПОЛЬЗОВАТЕЛЕЙ ===
class UserRating(Base):
    __tablename__ = "user_rating"
    telegram_id = Column(Integer, primary_key=True)
    wins = Column(Integer, default=0)  # Количество побед
    total_prizes = Column(Integer, default=0)  # Общий размер призов
    rank = Column(Integer, default=0)  # Место в рейтинге
    last_win_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=sql_func.now(), onupdate=sql_func.now())


# === ТАБЛИЦА: МОДУЛЬ ОБУЧЕНИЯ ===
class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 📖 КАСТОМИЗИРУЙ КУРСЫ ===
    title = Column(String(200))  # Название курса
    description = Column(Text)  # Описание
    content = Column(Text)  # HTML контент или ссылка на видео
    content_url = Column(String(500), nullable=True)  # Внешняя ссылка
    
    # ПАРАМЕТРЫ КУРСА ===
    duration_minutes = Column(Integer, default=30)  # Длительность
    level = Column(String(20), default="beginner")  # beginner, intermediate, advanced
    order = Column(Integer, default=0)  # Порядок отображения
    
    created_at = Column(DateTime, server_default=sql_func.now())
    is_active = Column(Boolean, default=True)


# === ТАБЛИЦА: ПРОГРЕСС ПОЛЬЗОВАТЕЛЯ В ОБУЧЕНИИ ===
class UserProgress(Base):
    __tablename__ = "user_progress"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, index=True)
    course_id = Column(Integer)
    
    started_at = Column(DateTime, server_default=sql_func.now())
    completed_at = Column(DateTime, nullable=True)
    progress_percent = Column(Integer, default=0)
    is_completed = Column(Boolean, default=False)


# === ТАБЛИЦА: СООБЩЕНИЯ КОМЬЮНИТИ ===
class CommunityMessage(Base):
    __tablename__ = "community_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, index=True)
    
    # 👥 КАСТОМИЗИРУЙ СООБЩЕНИЯ ===
    message = Column(Text)  # Сообщение пользователя
    message_type = Column(String(50), default="general")  # general, question, idea, success
    
    created_at = Column(DateTime, server_default=sql_func.now())
    likes = Column(Integer, default=0)
    is_pinned = Column(Boolean, default=False)
    status = Column(String(20), default="approved")  # approved, pending, rejected


# === ТАБЛИЦА: ОБРАТНАЯ СВЯЗЬ ===
class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, index=True)
    
    # 💬 КАСТОМИЗИРУЙ КАТЕГОРИИ ===
    category = Column(String(50))  # bug, feature, improvement, other
    feedback = Column(Text)
    
    status = Column(String(20), default="pending")  # pending, read, resolved
    response = Column(Text, nullable=True)
    
    created_at = Column(DateTime, server_default=sql_func.now())
    updated_at = Column(DateTime, nullable=True)


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===================== GOOGLE SHEETS ИНТЕГРАЦИЯ =====================
class GoogleSheetsManager:
    """
    Управление Google Sheets для логирования ответов
    
    НАСТРОЙКА:
    1. Создайте Google Sheet
    2. Скопируйте ID из URL: https://docs.google.com/spreadsheets/d/{ID}/edit
    3. Добавьте GOOGLE_SHEETS_ID в .env
    4. Скачайте credentials.json из Google Cloud Console
    """
    
    def __init__(self, sheet_id: str):
        self.sheet_id = sheet_id
        self.gc = None
        
        if HAS_GSPREAD and sheet_id:
            try:
                creds = Credentials.from_service_account_file(
                    'credentials.json',
                    scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
                self.gc = gspread.authorize(creds)
                logger.info("✅ Google Sheets подключен")
            except Exception as e:
                logger.error(f"❌ Ошибка подключения Google Sheets: {e}")
    
    async def log_submission(self, telegram_id: int, answer: str, is_correct: bool, quest_date: str):
        """Записать ответ в Google Sheets"""
        if not self.gc or not self.sheet_id:
            return
        
        try:
            sheet = self.gc.open_by_key(self.sheet_id)
            worksheet = sheet.worksheet("Ответы")  # 🎯 КАСТОМИЗИРУЙ: Название листа
            
            worksheet.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                telegram_id,
                answer,
                "✅ Верно" if is_correct else "❌ Неверно",
                quest_date
            ])
            logger.info(f"📊 Ответ записан в Google Sheets: user={telegram_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка при записи в Google Sheets: {e}")
    
    async def get_quiz_results(self) -> dict:
        """Получить результаты из Google Sheets"""
        if not self.gc or not self.sheet_id:
            return {}
        
        try:
            sheet = self.gc.open_by_key(self.sheet_id)
            worksheet = sheet.worksheet("Результаты")  # 🎯 КАСТОМИЗИРУЙ
            records = worksheet.get_all_records()
            return records
        except Exception as e:
            logger.error(f"❌ Ошибка при чтении из Google Sheets: {e}")
            return {}


gs_manager = GoogleSheetsManager(settings["GOOGLE_SHEETS_ID"])


# ===================== ЛОГИКА ПРОВЕРКИ ОТВЕТОВ =====================
class AnswerChecker:
    """
    Проверка ответов пользователей с поддержкой:
    - Точного совпадения
    - Нечеткого совпадения (для опечаток)
    - Альтернативных ответов
    - Игнорирования пунктуации и регистра
    """
    
    @staticmethod
    def normalize_text(text: str) -> str:
        """Нормализация текста для сравнения"""
        # Преобразуем в нижний регистр
        text = text.lower().strip()
        # Удаляем пунктуацию
        text = re.sub(r'[^\w\s]', '', text)
        # Удаляем лишние пробелы
        text = ' '.join(text.split())
        return text
    
    @staticmethod
    def calculate_similarity(text1: str, text2: str) -> float:
        """
        Вычислить процент совпадения между двумя текстами
        Возвращает значение от 0 до 1
        """
        text1 = AnswerChecker.normalize_text(text1)
        text2 = AnswerChecker.normalize_text(text2)
        
        matcher = SequenceMatcher(None, text1, text2)
        return matcher.ratio()
    
    @staticmethod
    def check_answer(
        user_answer: str,
        correct_answer: str,
        alternative_answers: list = None,
        threshold: float = 0.85
    ) -> tuple[bool, float]:
        """
        Проверить ответ пользователя
        
        Args:
            user_answer: Ответ от пользователя
            correct_answer: Правильный ответ
            alternative_answers: Альтернативные правильные ответы
            threshold: Минимальный процент совпадения (0-1)
        
        Returns:
            (is_correct, similarity_score)
        
        🎯 КАСТОМИЗИРУЙ: Измени threshold для строгости проверки
        """
        
        all_correct_answers = [correct_answer]
        if alternative_answers:
            all_correct_answers.extend(alternative_answers)
        
        best_score = 0
        
        for correct in all_correct_answers:
            score = AnswerChecker.calculate_similarity(user_answer, correct)
            best_score = max(best_score, score)
            
            # Точное совпадение
            if AnswerChecker.normalize_text(user_answer) == AnswerChecker.normalize_text(correct):
                return True, 1.0
        
        is_correct = best_score >= threshold
        return is_correct, best_score


# ===================== ПЛАНИРОВЩИК ЗАДАЧ =====================
class QuestScheduler:
    """
    Управление автоматическими задачами:
    - Публикация вопроса в канал
    - Объявление победителя
    - Начисление призов
    """
    
    def __init__(self, db_session_factory):
        self.db_session_factory = db_session_factory
        self.scheduler = BackgroundScheduler()
    
    def start(self):
        """Запустить планировщик"""
        # === 8:00 - Публикация вопроса ===
        self.scheduler.add_job(
            self.publish_daily_quest,
            CronTrigger(
                hour=settings["QUEST_PUBLISH_HOUR"],
                minute=settings["QUEST_PUBLISH_MINUTE"],
                timezone="Europe/Moscow"  # 🎯 КАСТОМИЗИРУЙ ВРЕМЕННУЮ ЗОНУ
            ),
            id='publish_quest',
            name='Публикация ежедневного вопроса',
            misfire_grace_time=60
        )
        
        # === 18:00 - Объявление победителя ===
        self.scheduler.add_job(
            self.announce_winner,
            CronTrigger(
                hour=settings["WINNER_ANNOUNCE_HOUR"],
                minute=settings["WINNER_ANNOUNCE_MINUTE"],
                timezone="Europe/Moscow"
            ),
            id='announce_winner',
            name='Объявление победителя',
            misfire_grace_time=60
        )
        
        self.scheduler.start()
        logger.info("✅ Планировщик запущен")
    
    async def publish_daily_quest(self):
        """
        📢 ЕЖЕДНЕВНАЯ ПУБЛИКАЦИЯ ВОПРОСА (8:00)
        
        Логика:
        1. Получить вопрос на сегодня из DB
        2. Отправить в Telegram канал
        3. Опубликовать в соцсетях (Instagram, Facebook)
        """
        db = self.db_session_factory()
        try:
            today = date.today().isoformat()
            
            # Получить или создать вопрос на сегодня
            quest = db.query(DailyQuest).filter(
                DailyQuest.quest_date == today
            ).first()
            
            if not quest:
                logger.warning(f"❌ Вопрос на {today} не найден")
                # 🎯 КАСТОМИЗИРУЙ: Создай вопрос по умолчанию
                return
            
            # === ОТПРАВИТЬ В TELEGRAM КАНАЛ ===
            message_text = f"""
🌌 <b>ЕЖЕДНЕВНЫЙ КВЕСТ - {today.strftime('%d.%m.%Y')}</b>

📋 <b>Вопрос:</b>
{quest.question}

💡 <b>Сложность:</b> {quest.difficulty.upper()}

⏰ <b>Правила:</b>
1️⃣ Найдите ответ в одном из наших постов (10:00-17:00)
2️⃣ Отправьте боту правильный ответ
3️⃣ Победитель объявляется в 18:00!

🎁 <b>Приз:</b> {quest.prize_amount}₽

/start Начать квест
            """
            
            if settings["TELEGRAM_CHANNEL_ID"]:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{settings['TELEGRAM_API_URL']}/sendMessage",
                        json={
                            "chat_id": settings["TELEGRAM_CHANNEL_ID"],
                            "text": message_text,
                            "parse_mode": "HTML"
                        }
                    )
                    
                    if response.status_code == 200:
                        quest.published_at = datetime.now()
                        quest.published_in_channel = True
                        db.commit()
                        logger.info(f"✅ Вопрос опубликован в канал: {quest.id}")
                    else:
                        logger.error(f"❌ Ошибка отправки в Telegram: {response.text}")
            
            # === 🎯 КАСТОМИЗИРУЙ: ПУБЛИКАЦИЯ В СОЦСЕТИ ===
            # Здесь нужно добавить код для Instagram/Facebook/VK
            # Пример с Instagram через инстабот или API
            
        except Exception as e:
            logger.error(f"❌ Ошибка при публикации вопроса: {e}")
        finally:
            db.close()
    
    async def announce_winner(self):
        """
        🏆 ОБЪЯВЛЕНИЕ ПОБЕДИТЕЛЯ (18:00)
        
        Логика:
        1. Получить все правильные ответы за сегодня
        2. Выбрать первого по времени отправки
        3. Начислить приз
        4. Отправить сообщение победителю
        5. Обновить рейтинг
        """
        db = self.db_session_factory()
        try:
            today = date.today().isoformat()
            
            # Получить вопрос на сегодня
            quest = db.query(DailyQuest).filter(
                DailyQuest.quest_date == today
            ).first()
            
            if not quest:
                logger.warning(f"❌ Вопрос на {today} не найден для объявления")
                return
            
            # Получить все ПРАВИЛЬНЫЕ ответы, отсортированные по времени
            correct_submissions = db.query(Submission)\
                .filter(
                    Submission.quest_date == today,
                    Submission.is_correct == True
                )\
                .order_by(Submission.submitted_at.asc())\
                .all()
            
            if not correct_submissions:
                logger.info(f"ℹ️ Сегодня ({today}) нет правильных ответов")
                
                # 🎯 КАСТОМИЗИРУЙ: Отправить сообщение о том, что побед не было
                if settings["TELEGRAM_CHANNEL_ID"]:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{settings['TELEGRAM_API_URL']}/sendMessage",
                            json={
                                "chat_id": settings["TELEGRAM_CHANNEL_ID"],
                                "text": "😢 Сегодня победителей нет. Приз переносится на завтра!",
                                "parse_mode": "HTML"
                            }
                        )
                return
            
            # ПЕРВЫЙ правильный ответ = ПОБЕДИТЕЛЬ
            winner_submission = correct_submissions[0]
            winner_id = winner_submission.telegram_id
            
            # Получить пользователя
            user = db.query(User).filter(User.telegram_id == winner_id).first()
            
            if not user:
                logger.error(f"❌ Пользователь {winner_id} не найден")
                return
            
            # === НАЧИСЛИТЬ ПРИЗ ===
            prize = Prize(
                telegram_id=winner_id,
                quest_id=quest.id,
                amount=quest.prize_amount,
                status="paid",
                paid_at=datetime.now(),
                description=f"Победа в квесте от {today}"
            )
            db.add(prize)
            
            # Увеличить баланс
            user.balance += quest.prize_amount
            
            # === ОБНОВИТЬ РЕЙТИНГ ===
            rating = db.query(UserRating).filter(
                UserRating.telegram_id == winner_id
            ).first()
            
            if not rating:
                rating = UserRating(
                    telegram_id=winner_id,
                    wins=1,
                    total_prizes=quest.prize_amount
                )
                db.add(rating)
            else:
                rating.wins += 1
                rating.total_prizes += quest.prize_amount
                rating.last_win_at = datetime.now()
            
            db.commit()
            
            logger.info(f"🏆 Победитель найден: {winner_id}, приз: {quest.prize_amount}₽")
            
            # === ОТПРАВИТЬ СООБЩЕНИЕ ПОБЕДИТЕЛЮ ===
            async with httpx.AsyncClient() as client:
                # Сообщение в канал
                await client.post(
                    f"{settings['TELEGRAM_API_URL']}/sendMessage",
                    json={
                        "chat_id": settings["TELEGRAM_CHANNEL_ID"],
                        "text": f"""
🎉 <b>ПОБЕДИТЕЛЬ НАЙДЕН!</b>

👤 Поздравляем пользователя <b>@{user.username or user.full_name}</b>

🎁 Приз: <b>{quest.prize_amount}₽</b>

Верный ответ: <b>{quest.correct_answer}</b>
Время ответа: {winner_submission.submitted_at.strftime('%H:%M:%S')}

💰 Приз добавлен на баланс!
                        """,
                        "parse_mode": "HTML"
                    }
                )
                
                # Личное сообщение победителю (если есть прямой контакт)
                # await client.post(...)
        
        except Exception as e:
            logger.error(f"❌ Ошибка при объявлении победителя: {e}")
        finally:
            db.close()


# ===================== БЕЗОПАСНОСТЬ =====================
def verify_telegram_init_data(init_data: str) -> dict:
    """Проверка подписи Telegram с расширенной отладкой"""
    try:
        if not init_data or not isinstance(init_data, str):
            logger.warning("❌ initData пуст или неверного типа")
            raise HTTPException(401, "Нет initData")
        
        data = dict(parse_qsl(init_data))
        received_hash = data.pop('hash', None)
        
        if not received_hash:
            logger.warning("❌ Попытка доступа без hash")
            raise HTTPException(401, "Нет hash в данных")
        
        if not settings["BOT_TOKEN"]:
            logger.error("❌ BOT_TOKEN не установлен в .env")
            raise HTTPException(500, "Ошибка конфигурации сервера")
        
        data_check_string = "\n".join(
            f"{k}={str(v)}" for k, v in sorted(data.items())
        )
        
        logger.info(f"🔍 Проверка подписи для пользователя: {data.get('user', {}).get('id')}")
        
        secret_key = hashlib.sha256(settings["BOT_TOKEN"].encode()).digest()
        calculated_hash = hmac.new(
            secret_key, 
            data_check_string.encode(), 
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning(f"❌ Неверная подпись!")
            raise HTTPException(401, "Неверные данные Telegram")
        
        logger.info(f"✅ Подпись верна!")
        return data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке Telegram данных: {str(e)}")
        raise HTTPException(401, f"Ошибка аутентификации")


def get_current_user(request: Request):
    """Получение текущего пользователя из Telegram"""
    init_data = request.headers.get("X-Telegram-Init-Data") or request.query_params.get("initData")
    if not init_data:
        raise HTTPException(401, "Требуется Telegram данные")
    return verify_telegram_init_data(init_data)


# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================
def get_or_create_user(telegram_id: int, user_data: dict, db: Session) -> User:
    """Получить или создать пользователя"""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    
    if not user:
        username = user_data.get("user", {}).get("username", "unknown")
        full_name = user_data.get("user", {}).get("first_name", "User")
        
        full_name = html.escape(str(full_name)[:200]) if full_name else "User"
        username = html.escape(str(username)[:100]) if username else None
        
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name
        )
        db.add(user)
        try:
            db.commit()
            logger.info(f"Создан новый пользователь: {telegram_id}")
        except Exception as e:
            db.rollback()
            logger.error(f"Ошибка при создании пользователя {telegram_id}: {str(e)}")
            raise HTTPException(500, "Ошибка регистрации")
    
    return user


def validate_phone(phone: str) -> bool:
    """Валидация номера телефона для СБП"""
    if not isinstance(phone, str):
        return False
    
    phone = phone.strip()
    if not phone.startswith("+7") or len(phone) != 12:
        return False
    
    return phone[1:].isdigit()


# ===================== API =====================

# === РЕГИСТРАЦИЯ ===
@app.post("/auth/register")
async def register(
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Регистрация пользователя"""
    try:
        telegram_id = int(user_data.get("user", {}).get("id"))
        if not telegram_id:
            raise HTTPException(400, "Неверный Telegram ID")
        
        user = get_or_create_user(telegram_id, user_data, db)
        
        return {
            "status": "ok",
            "message": "Пользователь зарегистрирован",
            "user_id": telegram_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка регистрации: {str(e)}")
        raise HTTPException(500, "Ошибка регистрации")


# === МОДУЛЬ КВЕСТОВ ===

@app.get("/quest/today")
async def get_today_quest(
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить вопрос на сегодня"""
    try:
        today = date.today().isoformat()
        quest = db.query(DailyQuest).filter(
            DailyQuest.quest_date == today
        ).first()
        
        if not quest:
            return {
                "status": "no_quest",
                "message": "Вопрос на сегодня еще не опубликован"
            }
        
        # Проверить, ответил ли уже пользователь
        submission = db.query(Submission).filter(
            Submission.telegram_id == int(user_data["user"]["id"]),
            Submission.quest_date == today
        ).first()
        
        return {
            "status": "ok",
            "quest": {
                "id": quest.id,
                "question": quest.question,
                "difficulty": quest.difficulty,
                "prize": quest.prize_amount,
                "hint": quest.hint,
                "published_at": quest.published_at.isoformat() if quest.published_at else None,
                "already_answered": submission is not None,
                "answer_status": submission.is_correct if submission else None
            }
        }
    except Exception as e:
        logger.error(f"Ошибка получения вопроса: {str(e)}")
        raise HTTPException(500, "Ошибка при получении вопроса")


@app.post("/quest/submit-answer")
async def submit_answer(
    answer: str = Query(...),
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📝 ОТПРАВКА ОТВЕТА НА КВЕСТ
    
    Логика:
    1. Проверить что сегодняшний вопрос существует
    2. Проверить что пользователь еще не ответил
    3. Проверить ответ (точное совпадение + fuzzy match)
    4. Сохранить в DB
    5. Записать в Google Sheets
    """
    try:
        telegram_id = int(user_data["user"]["id"])
        today = date.today().isoformat()
        
        # === ПОЛУЧИТЬ ВОПРОС НА СЕГОДНЯ ===
        quest = db.query(DailyQuest).filter(
            DailyQuest.quest_date == today
        ).first()
        
        if not quest:
            raise HTTPException(400, "Вопрос на сегодня не найден")
        
        # === ПРОВЕРИТЬ ЧТО ПОЛЬЗОВАТЕЛЬ ЕЩЕ НЕ ОТВЕТИЛ ===
        existing_submission = db.query(Submission).filter(
            Submission.telegram_id == telegram_id,
            Submission.quest_date == today
        ).first()
        
        if existing_submission:
            return {
                "status": "already_answered",
                "message": "Вы уже ответили на сегодняшний вопрос",
                "previous_answer": existing_submission.answer,
                "was_correct": existing_submission.is_correct
            }
        
        # === ПРОВЕРИТЬ ОТВЕТ ===
        is_correct, match_score = AnswerChecker.check_answer(
            answer,
            quest.correct_answer,
            quest.alternative_answers,
            threshold=settings["ANSWER_MATCH_THRESHOLD"]
        )
        
        # === СОХРАНИТЬ ОТВЕТ В DB ===
        submission = Submission(
            telegram_id=telegram_id,
            quest_id=quest.id,
            quest_date=today,
            answer=answer,
            is_correct=is_correct,
            match_score=match_score,
            checked_at=datetime.now(),
            score=quest.prize_amount if is_correct else 0
        )
        db.add(submission)
        db.commit()
        
        logger.info(f"Ответ сохранен: user={telegram_id}, correct={is_correct}, score={match_score}")
        
        # === ЗАПИСАТЬ В GOOGLE SHEETS ===
        await gs_manager.log_submission(
            telegram_id,
            answer,
            is_correct,
            str(today)
        )
        
        return {
            "status": "ok",
            "is_correct": is_correct,
            "match_score": round(match_score * 100, 2),
            "message": "✅ Верно!" if is_correct else f"❌ Неверно. Совпадение: {round(match_score * 100, 2)}%"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при отправке ответа: {str(e)}")
        raise HTTPException(500, "Ошибка при обработке ответа")


# === МОДУЛЬ ОБУЧЕНИЯ ===

@app.get("/courses/list")
async def get_courses(
    level: str = Query("all"),  # all, beginner, intermediate, advanced
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📖 ПОЛУЧИТЬ СПИСОК КУРСОВ
    
    🎯 КАСТОМИЗИРУЙ КУРСЫ:
    - Добавь свои курсы в таблицу Course
    - Измени title, description, content_url
    """
    try:
        query = db.query(Course).filter(Course.is_active == True)
        
        if level != "all":
            query = query.filter(Course.level == level)
        
        courses = query.order_by(Course.order).all()
        
        telegram_id = int(user_data["user"]["id"])
        
        result = []
        for course in courses:
            # Получить прогресс пользователя
            progress = db.query(UserProgress).filter(
                UserProgress.telegram_id == telegram_id,
                UserProgress.course_id == course.id
            ).first()
            
            result.append({
                "id": course.id,
                "title": course.title,
                "description": course.description,
                "level": course.level,
                "duration": course.duration_minutes,
                "content_url": course.content_url,
                "progress": progress.progress_percent if progress else 0,
                "completed": progress.is_completed if progress else False
            })
        
        return {
            "status": "ok",
            "courses": result
        }
    except Exception as e:
        logger.error(f"Ошибка получения курсов: {str(e)}")
        raise HTTPException(500, "Ошибка при получении курсов")


@app.post("/courses/start/{course_id}")
async def start_course(
    course_id: int,
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Начать курс"""
    try:
        telegram_id = int(user_data["user"]["id"])
        
        # Проверить наличие курса
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise HTTPException(404, "Курс не найден")
        
        # Проверить что уже не начал
        progress = db.query(UserProgress).filter(
            UserProgress.telegram_id == telegram_id,
            UserProgress.course_id == course_id
        ).first()
        
        if progress:
            return {
                "status": "already_started",
                "progress": progress.progress_percent,
                "message": "Вы уже начали этот курс"
            }
        
        # Создать новый прогресс
        progress = UserProgress(
            telegram_id=telegram_id,
            course_id=course_id,
            progress_percent=0
        )
        db.add(progress)
        db.commit()
        
        logger.info(f"Курс начат: user={telegram_id}, course={course_id}")
        
        return {
            "status": "ok",
            "message": f"Курс '{course.title}' начат!",
            "course": {
                "title": course.title,
                "duration": course.duration_minutes,
                "content_url": course.content_url
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при начале курса: {str(e)}")
        raise HTTPException(500, "Ошибка при начале курса")


@app.post("/courses/complete/{course_id}")
async def complete_course(
    course_id: int,
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Завершить курс"""
    try:
        telegram_id = int(user_data["user"]["id"])
        
        progress = db.query(UserProgress).filter(
            UserProgress.telegram_id == telegram_id,
            UserProgress.course_id == course_id
        ).first()
        
        if not progress:
            raise HTTPException(404, "Прогресс не найден")
        
        progress.progress_percent = 100
        progress.completed_at = datetime.now()
        progress.is_completed = True
        db.commit()
        
        logger.info(f"Курс завершен: user={telegram_id}, course={course_id}")
        
        return {
            "status": "ok",
            "message": "✅ Курс завершен! Поздравляем!",
            "completed_at": progress.completed_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при завершении курса: {str(e)}")
        raise HTTPException(500, "Ошибка при завершении курса")


# === МОДУЛЬ РЕЙТИНГА ===

@app.get("/rating/top")
async def get_top_rating(
    limit: int = Query(10, ge=5, le=100),
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🏆 ПОЛУЧИТЬ ТОП РЕЙТИНГА
    
    🎯 КАСТОМИЗИРУЙ: Измени limit и сортировку
    """
    try:
        top_users = db.query(UserRating)\
            .order_by(UserRating.total_prizes.desc())\
            .limit(limit)\
            .all()
        
        result = []
        for idx, rating in enumerate(top_users, 1):
            user = db.query(User).filter(User.telegram_id == rating.telegram_id).first()
            result.append({
                "place": idx,
                "user": user.full_name if user else "Unknown",
                "username": user.username if user else None,
                "wins": rating.wins,
                "total_prizes": rating.total_prizes,
                "last_win": rating.last_win_at.isoformat() if rating.last_win_at else None
            })
        
        return {
            "status": "ok",
            "rating": result
        }
    except Exception as e:
        logger.error(f"Ошибка получения рейтинга: {str(e)}")
        raise HTTPException(500, "Ошибка при получении рейтинга")


@app.get("/rating/my-position")
async def get_my_rating(
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить свою позицию в рейтинге"""
    try:
        telegram_id = int(user_data["user"]["id"])
        
        my_rating = db.query(UserRating).filter(
            UserRating.telegram_id == telegram_id
        ).first()
        
        if not my_rating:
            my_rating = UserRating(telegram_id=telegram_id)
            db.add(my_rating)
            db.commit()
        
        # Получить свою позицию
        position = db.query(UserRating)\
            .filter(UserRating.total_prizes > my_rating.total_prizes)\
            .count() + 1
        
        return {
            "status": "ok",
            "position": position,
            "wins": my_rating.wins,
            "total_prizes": my_rating.total_prizes
        }
    except Exception as e:
        logger.error(f"Ошибка получения позиции: {str(e)}")
        raise HTTPException(500, "Ошибка при получении позиции")


# === МОДУЛЬ КОМЬЮНИТИ ===

@app.get("/community/messages")
async def get_community_messages(
    message_type: str = Query("general"),
    limit: int = Query(20, ge=5, le=100),
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    👥 ПОЛУЧИТЬ СООБЩЕНИЯ КОМЬЮНИТИ
    
    🎯 КАСТОМИЗИРУЙ: Типы сообщений в message_type
    """
    try:
        query = db.query(CommunityMessage).filter(
            CommunityMessage.status == "approved"
        )
        
        if message_type != "all":
            query = query.filter(CommunityMessage.message_type == message_type)
        
        messages = query.order_by(
            CommunityMessage.is_pinned.desc(),
            CommunityMessage.created_at.desc()
        ).limit(limit).all()
        
        result = []
        for msg in messages:
            user = db.query(User).filter(User.telegram_id == msg.telegram_id).first()
            result.append({
                "id": msg.id,
                "author": user.full_name if user else "Unknown",
                "username": user.username if user else None,
                "message": msg.message,
                "type": msg.message_type,
                "likes": msg.likes,
                "is_pinned": msg.is_pinned,
                "created_at": msg.created_at.isoformat()
            })
        
        return {
            "status": "ok",
            "messages": result
        }
    except Exception as e:
        logger.error(f"Ошибка получения сообщений: {str(e)}")
        raise HTTPException(500, "Ошибка при получении сообщений")


@app.post("/community/post")
async def post_message(
    message: str = Query(...),
    message_type: str = Query("general"),
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    💬 ОПУБЛИКОВАТЬ СООБЩЕНИЕ В КОМЬЮНИТИ
    
    message_type: general, question, idea, success
    
    🎯 КАСТОМИЗИРУЙ: Добавь модерацию сообщений
    """
    try:
        telegram_id = int(user_data["user"]["id"])
        
        # Валидация
        if len(message) < 5 or len(message) > 1000:
            raise HTTPException(400, "Сообщение должно быть от 5 до 1000 символов")
        
        # Санитизация
        message = html.escape(message[:1000])
        
        # 🎯 КАСТОМИЗИРУЙ: Добавь проверку на спам/мат
        
        new_message = CommunityMessage(
            telegram_id=telegram_id,
            message=message,
            message_type=message_type,
            status="pending"  # Нужна модерация или автоматически одобрить?
        )
        db.add(new_message)
        db.commit()
        
        logger.info(f"Сообщение отправлено: user={telegram_id}, type={message_type}")
        
        return {
            "status": "ok",
            "message": "Сообщение отправлено на модерацию",
            "post_id": new_message.id
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при отправке сообщения: {str(e)}")
        raise HTTPException(500, "Ошибка при отправке сообщения")


@app.post("/community/like/{message_id}")
async def like_message(
    message_id: int,
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Лайк сообщению"""
    try:
        message = db.query(CommunityMessage).filter(
            CommunityMessage.id == message_id
        ).first()
        
        if not message:
            raise HTTPException(404, "Сообщение не найдено")
        
        message.likes += 1
        db.commit()
        
        return {
            "status": "ok",
            "likes": message.likes
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при лайке: {str(e)}")
        raise HTTPException(500, "Ошибка при лайке")


# === МОДУЛЬ ОБРАТНОЙ СВЯЗИ ===

@app.post("/feedback/submit")
async def submit_feedback(
    category: str = Query(...),  # bug, feature, improvement, other
    feedback: str = Query(...),
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    💬 ОТПРАВИТЬ ОБРАТНУЮ СВЯЗЬ
    
    категории: bug, feature, improvement, other
    
    🎯 КАСТОМИЗИРУЙ: Добавь отправку на email
    """
    try:
        telegram_id = int(user_data["user"]["id"])
        
        if not feedback or len(feedback) < 10:
            raise HTTPException(400, "Обратная связь должна быть минимум 10 символов")
        
        feedback = html.escape(feedback[:2000])
        
        new_feedback = Feedback(
            telegram_id=telegram_id,
            category=category,
            feedback=feedback,
            status="pending"
        )
        db.add(new_feedback)
        db.commit()
        
        logger.info(f"Обратная связь отправлена: user={telegram_id}, category={category}")
        
        # 🎯 КАСТОМИЗИРУЙ: Отправить email админам
        # await send_email_notification(...)
        
        return {
            "status": "ok",
            "message": "✅ Спасибо за обратную связь!",
            "feedback_id": new_feedback.id
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при отправке обратной связи: {str(e)}")
        raise HTTPException(500, "Ошибка при отправке")


# === МОДУЛЬ ВЫПЛАТ (из предыдущей версии) ===

@app.get("/user/payment-details")
async def get_payment_details(
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить сохранённые реквизиты пользователя"""
    try:
        telegram_id = int(user_data["user"]["id"])
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        
        if not user:
            return {"payment_details": None, "status": "user_not_found"}
        
        return {
            "payment_details": user.payment_details,
            "status": "ok"
        }
    except Exception as e:
        logger.error(f"Ошибка получения реквизитов: {str(e)}")
        raise HTTPException(500, "Ошибка при получении реквизитов")


@app.post("/user/save-payment-details")
async def save_payment_details(
    phone: str = Query(...),
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Сохранить реквизиты для выплат (СБП)"""
    try:
        telegram_id = int(user_data["user"]["id"])
        
        if not validate_phone(phone):
            raise HTTPException(400, "Неверный формат телефона. Используйте +7XXXXXXXXXX")
        
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        
        if not user:
            raise HTTPException(404, "Пользователь не найден")
        
        user.payment_details = {
            "type": "sbp",
            "phone": phone
        }
        
        db.commit()
        logger.info(f"Реквизиты обновлены для пользователя {telegram_id}")
        
        return {
            "status": "ok",
            "message": "Реквизиты успешно сохранены"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка сохранения реквизитов: {str(e)}")
        raise HTTPException(500, "Ошибка при сохранении реквизитов")


@app.get("/prizes/balance")
async def get_balance(
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить баланс пользователя"""
    try:
        telegram_id = int(user_data["user"]["id"])
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        
        return {
            "balance": user.balance if user else 0,
            "status": "ok"
        }
    except Exception as e:
        logger.error(f"Ошибка получения баланса: {str(e)}")
        raise HTTPException(500, "Ошибка при получении баланса")


@app.get("/prizes/history")
async def get_prize_history(
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """История всех выплат пользователя"""
    try:
        telegram_id = int(user_data["user"]["id"])
        
        prizes = db.query(Prize)\
                   .filter(Prize.telegram_id == telegram_id)\
                   .order_by(Prize.paid_at.desc())\
                   .limit(50).all()
        
        return {
            "status": "ok",
            "history": [{
                "id": p.id,
                "amount": p.amount,
                "status": p.status,
                "date": p.paid_at.strftime("%d.%m.%Y %H:%M") if p.paid_at else "-",
                "description": p.description or "Вывод приза",
                "error": p.error_message if p.status == "failed" else None
            } for p in prizes]
        }
    except Exception as e:
        logger.error(f"Ошибка получения истории: {str(e)}")
        raise HTTPException(500, "Ошибка при получении истории")


@app.post("/prizes/withdraw")
async def withdraw(
    amount: int = Query(...),
    user_data: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Вывод денег на карту/СБП с полной обработкой ошибок"""
    telegram_id = int(user_data["user"]["id"])
    
    try:
        # === ВАЛИДАЦИЯ ===
        if amount <= 0:
            raise HTTPException(400, "Сумма должна быть больше нуля")
        
        if amount < settings["MIN_WITHDRAW"]:
            raise HTTPException(
                400,
                f"Минимальная сумма вывода — {settings['MIN_WITHDRAW']} ₽"
            )
        
        if amount > settings["MAX_WITHDRAW"]:
            raise HTTPException(
                400,
                f"Максимальная сумма вывода — {settings['MAX_WITHDRAW']} ₽"
            )
        
        # === ПОЛУЧЕНИЕ ПОЛЬЗОВАТЕЛЯ ===
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        
        if not user:
            raise HTTPException(404, "Пользователь не найден")
        
        # === ПРОВЕРКА БАЛАНСА ===
        if amount > user.balance:
            raise HTTPException(
                400,
                f"Недостаточно средств. Баланс: {user.balance} ₽"
            )
        
        # === ПРОВЕРКА РЕКВИЗИТОВ ===
        if not user.payment_details or user.payment_details.get("type") != "sbp":
            raise HTTPException(
                400,
                "Сначала укажите реквизиты для выплат"
            )
        
        # === ПРОВЕРКА RACE CONDITION ===
        if user.withdraw_in_progress:
            raise HTTPException(
                429,
                "Выплата уже обрабатывается. Подождите завершения"
            )
        
        # === RATE LIMITING ===
        if not rate_limiter.is_allowed(telegram_id):
            raise HTTPException(429, "Слишком много попыток вывода. Подождите.")
        
        # Блокируем дальнейшие попытки
        user.withdraw_in_progress = True
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Ошибка блокировки выплаты: {str(e)}")
            raise HTTPException(500, "Ошибка обработки выплаты")
        
        # === РЕАЛЬНАЯ ВЫПЛАТА ЧЕРЕЗ YOOKASSA ===
        payout_data = None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.yookassa.ru/v3/payouts",
                    json={
                        "amount": {
                            "value": str(amount),
                            "currency": "RUB"
                        },
                        "payment_method": {
                            "type": "sbp",
                            "phone": user.payment_details["phone"]
                        },
                        "description": "Приз Академии Транссерфинга Реальности",
                        "metadata": {
                            "telegram_id": str(telegram_id)
                        }
                    },
                    auth=(settings["YOOKASSA_SHOP_ID"], settings["YOOKASSA_SECRET"]),
                    headers={"Idempotency-Key": str(uuid.uuid4())}
                )
            
            if resp.status_code not in [200, 201]:
                error_text = resp.text[:500]
                logger.error(f"YooKassa ошибка {resp.status_code}: {error_text}")
                
                failed_prize = Prize(
                    telegram_id=telegram_id,
                    amount=amount,
                    status="failed",
                    payout_id=None,
                    paid_at=datetime.now(),
                    description=f"Ошибка выплаты на СБП {user.payment_details['phone']}",
                    error_message=error_text
                )
                db.add(failed_prize)
                db.commit()
                logger.warning(f"Выплата записана как неудачная для {telegram_id}")
                
                raise HTTPException(
                    400,
                    "Ошибка обработки выплаты. Попробуйте позже."
                )
            
            payout_data = resp.json()
            payout_id = payout_data.get("id", "unknown")
            
        except httpx.TimeoutException:
            logger.error(f"Timeout при выплате для {telegram_id}")
            raise HTTPException(504, "Сервис платежей недоступен. Попробуйте позже.")
        except httpx.RequestError as e:
            logger.error(f"Ошибка сети при выплате: {str(e)}")
            raise HTTPException(503, "Ошибка соединения. Попробуйте позже.")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка YooKassa: {str(e)}")
            raise HTTPException(500, "Ошибка обработки платежа")
        
        # === УСПЕШНАЯ ВЫПЛАТА - ОБНОВЛЕНИЕ БД ===
        try:
            paid_prize = Prize(
                telegram_id=telegram_id,
                amount=amount,
                status="paid",
                payout_id=payout_id,
                paid_at=datetime.now(),
                description=f"Успешный вывод на СБП {user.payment_details['phone']}"
            )
            db.add(paid_prize)
            
            user.balance -= amount
            user.last_withdraw_at = datetime.now()
            user.withdraw_in_progress = False
            
            db.commit()
            logger.info(f"Выплата {amount}₽ выполнена для {telegram_id}. Payout ID: {payout_id}")
            
            return {
                "status": "success",
                "message": f"{amount} ₽ успешно выведено",
                "payout_id": payout_id,
                "new_balance": user.balance
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Ошибка сохранения успешной выплаты: {str(e)}")
            try:
                error_prize = Prize(
                    telegram_id=telegram_id,
                    amount=amount,
                    status="pending",
                    payout_id=payout_id,
                    paid_at=datetime.now(),
                    description="Выплата отправлена, но ошибка БД",
                    error_message=str(e)
                )
                db.add(error_prize)
                db.commit()
            except:
                pass
            raise HTTPException(500, "Ошибка сохранения выплаты в системе")
    
    except HTTPException:
        try:
            user = db.query(User).filter(User.telegram_id == telegram_id).first()
            if user:
                user.withdraw_in_progress = False
                db.commit()
        except:
            pass
        raise
    except Exception as e:
        logger.error(f"Неожиданная ошибка вывода: {str(e)}")
        raise HTTPException(500, "Неожиданная ошибка. Свяжитесь с поддержкой.")


# ===================== MINI APP HTML =====================
MINI_APP_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Академия Транссерфинга</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/@twa-dev/sdk@1"></script>
    <style>
        body { background: linear-gradient(180deg, #1E0F4F 0%, #0F0A2E 100%); color: #F8F1E3; }
        .gold { color: #F5C400; }
        .section { display: none; }
        .section.active { display: block; }
        .loader { border: 4px solid rgba(245, 196, 0, 0.3); border-top: 4px solid #F5C400; border-radius: 50%; width: 40px; height: 40px; animation: spin 3s linear infinite; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body class="min-h-screen pb-20">
<div class="max-w-xl mx-auto p-4">
    <h1 class="text-4xl font-bold gold text-center mb-6">🌌 Академия Транссерфинга</h1>

    <!-- Навигация -->
    <div class="fixed bottom-0 left-0 right-0 bg-[#1E0F4F] border-t border-[#6B46C0]">
        <div class="flex justify-around py-2 text-xs">
            <button onclick="navigate(0)" class="nav-btn active flex flex-col items-center" id="nav-0">🎯<br>Квест</button>
            <button onclick="navigate(1)" class="nav-btn flex flex-col items-center" id="nav-1">📖<br>Обучение</button>
            <button onclick="navigate(2)" class="nav-btn flex flex-col items-center" id="nav-2">🏆<br>Рейтинг</button>
            <button onclick="navigate(3)" class="nav-btn flex flex-col items-center" id="nav-3">💬<br>Комьюнити</button>
            <button onclick="navigate(4)" class="nav-btn flex flex-col items-center" id="nav-4">💰<br>Призы</button>
        </div>
    </div>

    <!-- КВЕСТ -->
    <div id="sec-0" class="section active">
        <div class="bg-[#6B46C0]/30 backdrop-blur-xl rounded-3xl p-8">
            <h2 class="text-3xl gold mb-4 text-center">🎯 Сегодняшний Квест</h2>
            <div id="quest-container" class="space-y-4">
                <div class="text-center opacity-60">Загрузка...</div>
            </div>
        </div>
    </div>

    <!-- ОБУЧЕНИЕ -->
    <div id="sec-1" class="section">
        <div class="bg-[#6B46C0]/30 backdrop-blur-xl rounded-3xl p-8">
            <h2 class="text-3xl gold mb-4 text-center">📖 Обучение</h2>
            <div id="courses-container" class="space-y-4">
                <div class="text-center opacity-60">Загрузка курсов...</div>
            </div>
        </div>
    </div>

    <!-- РЕЙТИНГ -->
    <div id="sec-2" class="section">
        <div class="bg-[#6B46C0]/30 backdrop-blur-xl rounded-3xl p-8">
            <h2 class="text-3xl gold mb-4 text-center">🏆 Рейтинг</h2>
            <div id="rating-container" class="space-y-4">
                <div class="text-center opacity-60">Загрузка рейтинга...</div>
            </div>
        </div>
    </div>

    <!-- КОМЬЮНИТИ -->
    <div id="sec-3" class="section">
        <div class="bg-[#6B46C0]/30 backdrop-blur-xl rounded-3xl p-8">
            <h2 class="text-3xl gold mb-4 text-center">💬 Комьюнити</h2>
            <div id="community-container" class="space-y-4">
                <div class="text-center opacity-60">Загрузка сообщений...</div>
            </div>
        </div>
    </div>

    <!-- ПРИЗЫ -->
    <div id="sec-4" class="section">
        <div class="bg-[#6B46C0]/30 backdrop-blur-xl rounded-3xl p-8 text-center">
            <h2 class="text-3xl gold mb-2">Ваш баланс</h2>
            <div id="balance" class="text-7xl font-bold text-emerald-400 my-4">0 ₽</div>
            
            <button onclick="showWithdrawScreen()" 
                    class="w-full bg-[#F5C400] text-[#1E0F4F] font-bold py-6 rounded-3xl text-2xl mb-4">
                💸 Вывести деньги
            </button>
            
            <button onclick="showHistory()" 
                    class="w-full bg-white/10 py-4 rounded-3xl text-lg">
                📜 История выплат
            </button>
        </div>
    </div>

</div>

<script>
console.log('=== ИНИЦИАЛИЗАЦИЯ МИНИ-ПРИЛОЖЕНИЯ ===');

let tg = window.Telegram?.WebApp;
let initData = null;
let currentBalance = 0;

if (!tg) {
    console.error('❌ Telegram WebApp не найден');
    document.body.innerHTML = '<h1>❌ Откройте приложение из Telegram</h1>';
} else {
    tg.ready();
    tg.expand();

    initData = tg.initData;

    console.log('✅ Telegram.WebApp готов');
    console.log('📝 initData:', initData);
    console.log('👤 Пользователь:', tg.initDataUnsafe?.user);

    if (!initData) {
        console.error('❌ initData пустой');
        document.body.innerHTML = '<h1>❌ Запустите из Telegram</h1>';
    }
}

    function navigate(section) {
        document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
        document.getElementById(`sec-${section}`).classList.add('active');
        
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        document.getElementById(`nav-${section}`).classList.add('active');
        
        if (section === 0) loadQuest();
        if (section === 1) loadCourses();
        if (section === 2) loadRating();
        if (section === 3) loadCommunity();
        if (section === 4) loadBalance();
    }

    async function loadQuest() {
        try {
            console.log('🔍 initData длина:', initData.length);
            
            if (!initData) {
                console.error('❌ initData пуст!');
                document.getElementById('quest-container').innerHTML = 
                    '<p style="color: red;">❌ Ошибка: нет данных Telegram</p>';
                return;
            }
            
            const res = await fetch('/quest/today', {
                method: 'GET',
                headers: {
                    "X-Telegram-Init-Data": initData,
                    "Content-Type": "application/json"
                }
            });
            
            console.log('📊 Статус:', res.status);
            
            if (!res.ok) {
                const errorData = await res.json();
                console.error('❌ Ошибка:', errorData);
                document.getElementById('quest-container').innerHTML = 
                    `<p style="color: red;">❌ Ошибка ${res.status}: ${errorData.detail}</p>`;
                return;
            }
            
            const data = await res.json();
            console.log('✅ Получены данные:', data);
            
            const container = document.getElementById('quest-container');
            
            if (data.status === 'no_quest') {
                container.innerHTML = '<p class="text-center opacity-60">Вопрос еще не опубликован</p>';
            } else {
                const quest = data.quest;
                container.innerHTML = `
                    <div class="bg-white/10 p-6 rounded-2xl">
                        <p class="text-sm opacity-60 mb-2">Сложность: ${quest.difficulty}</p>
                        <h3 class="text-2xl mb-4">${quest.question}</h3>
                        <p class="text-gold mb-4">Приз: ${quest.prize}₽</p>
                        <input id="answer-input" type="text" placeholder="Ваш ответ..." 
                               class="w-full bg-white/10 border border-purple-500 rounded-2xl px-5 py-4 mb-4 text-white">
                        <button onclick="submitAnswer()" 
                                class="w-full bg-emerald-400 text-black font-bold py-4 rounded-3xl">
                            Отправить ответ
                        </button>
                    </div>
                `;
            }
        } catch (err) {
            console.error('❌ ОШИБКА:', err);
            document.getElementById('quest-container').innerHTML = 
                `<p style="color: red;">❌ Ошибка: ${err.message}</p>`;
        }
    }

    async function submitAnswer() {
        const answer = document.getElementById('answer-input').value;
        if (!answer) return alert('Введите ответ');
        
        try {
            const res = await fetch(`/quest/submit-answer?answer=${encodeURIComponent(answer)}`, {
                method: 'POST',
                headers: {"X-Telegram-Init-Data": initData}
            });
            const data = await res.json();
            alert(data.message);
            loadQuest();
        } catch (err) {
            alert('Ошибка отправки');
        }
    }

    async function loadCourses() {
        try {
            const res = await fetch('/courses/list', {
                headers: {"X-Telegram-Init-Data": initData}
            });
            const data = await res.json();
            const container = document.getElementById('courses-container');
            
            container.innerHTML = data.courses.map(course => `
                <div class="bg-white/10 p-4 rounded-2xl">
                    <h3 class="text-lg font-bold mb-2">${course.title}</h3>
                    <p class="text-sm opacity-70 mb-3">${course.description}</p>
                    <button onclick="startCourse(${course.id})" class="w-full bg-gold text-black font-bold py-2 rounded-xl text-sm">Начать</button>
                </div>
            `).join('');
        } catch (err) {
            console.error('Ошибка:', err);
        }
    }

    async function startCourse(courseId) {
        try {
            const res = await fetch(`/courses/start/${courseId}`, {
                method: 'POST',
                headers: {"X-Telegram-Init-Data": initData}
            });
            const data = await res.json();
            alert(data.message);
        } catch (err) {
            alert('Ошибка');
        }
    }

    async function loadRating() {
        try {
            const res = await fetch('/rating/top?limit=10', {
                headers: {"X-Telegram-Init-Data": initData}
            });
            const data = await res.json();
            const container = document.getElementById('rating-container');
            
            container.innerHTML = data.rating.map((user) => `
                <div class="bg-white/10 p-4 rounded-2xl flex justify-between">
                    <div><p class="font-bold">${user.place}. ${user.user}</p></div>
                    <p class="text-gold">${user.total_prizes}₽</p>
                </div>
            `).join('');
        } catch (err) {
            console.error('Ошибка:', err);
        }
    }

    async function loadCommunity() {
        try {
            const res = await fetch('/community/messages?limit=10', {
                headers: {"X-Telegram-Init-Data": initData}
            });
            const data = await res.json();
            const container = document.getElementById('community-container');
            container.innerHTML = data.messages.map(msg => `
                <div class="bg-white/10 p-4 rounded-2xl">
                    <p class="font-bold">${msg.author}</p>
                    <p>${msg.message}</p>
                </div>
            `).join('');
        } catch (err) {
            console.error('Ошибка:', err);
        }
    }

    async function loadBalance() {
        try {
            const res = await fetch('/prizes/balance', {
                headers: {"X-Telegram-Init-Data": initData}
            });
            const data = await res.json();
            currentBalance = data.balance || 0;
            document.getElementById('balance').textContent = currentBalance + ' ₽';
        } catch (err) {
            console.error('Ошибка:', err);
        }
    }

    function showWithdrawScreen() {
        alert('Минимум 300₽');
    }

    function showHistory() {
        alert('История выплат');
    }

    window.onload = () => {
        loadBalance();
    };
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def mini_app():
    return MINI_APP_HTML


# ===================== ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ =====================
@app.on_event("startup")
async def startup():
    """Запуск приложения"""
    logger.info("🚀 Запуск Академии Транссерфинга v3.0 FULL")
    
    # Запустить планировщик
    quest_scheduler = QuestScheduler(SessionLocal)
    quest_scheduler.start()
    
    logger.info("✅ Все модули инициализированы")


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "status": "error"},
    )


if __name__ == "__main__":
    import uvicorn
    logger.info("🌌 Академия Транссерфинга v3.0 ЗАПУСКАЕТСЯ")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")