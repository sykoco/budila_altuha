#!/usr/bin/env python3
"""
Telegram Bot - Будильник
Звонит пока не встанешь. Выключается только решением примера.
Потому что кнопка "отложить" — это путь слабаков.
"""

import asyncio
import re
import os
import random
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Tuple
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Попытка загрузить .env файл
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from call import TelegramCaller, load_config
from database import Database
from state_manager import StateManager
from scheduler import AlarmScheduler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
DEFAULT_ALLOWED_USERNAMES: list[str] = []  # Заполни в .env или добавь через БД
CALL_DURATION = 40.0  # Длительность звонка в секундах
CALL_INTERVAL = 120.0  # Интервал между звонками в секундах (2 минуты)
MAX_ALARMS_PER_USER = 5  # Максимум будильников на пользователя
MAX_REMINDERS_PER_USER = 10  # Максимум напоминалок на пользователя

# Кнопки меню
BUTTON_START = "🚀 Стартуем"
BUTTON_STATUS = "📊 Статус"
BUTTON_INFO = "ℹ️ Инфо"
BUTTON_MY_ALARMS = "⏰ Мои Будильники"
BUTTON_ALL_ALARMS = "👥 Все будильники"
BUTTON_NEW_REMINDER = "📝 Напоминалка"
BUTTON_MY_REMINDERS = "🗒 Мои Напоминалки"

# API для фактов
FACTS_API_URL = "https://uselessfacts.jsph.pl/random.json?language=en"

# ─────────────────────────────────────────────────────────────
# БАНК СООБЩЕНИЙ — всё веселье живёт здесь
# ─────────────────────────────────────────────────────────────

WAKE_UP_MESSAGES = [
    "⏰ ПОДЪЁМ. Звоню. Сам виноват.",
    "⏰ Вот и настало то самое время. Буду звонить как проклятый.",
    "⏰ Пора страдать. Звонки пошли.",
    "⏰ Хватит дрыхнуть, работа не ждёт. Ну или хотя бы притворись что встал.",
    "⏰ Доброе утро! Сказал бы, если бы оно было добрым. Звоню.",
    "⏰ Время будильника. Кровать — это ловушка. Выбирайся.",
    "⏰ ТЫ САМ ЭТО ПОПРОСИЛ. Помни об этом когда будешь проклинать бота.",
    "⏰ Вставай, засоня. Звонки начались, математика ждёт.",
    "⏰ Привет из прошлого — это ты поставил будильник. Ты и расхлёбывай.",
    "⏰ Бот не спал всю ночь ради этого момента. Ну, технически спал, но неважно. ВСТАВАЙ.",
]

WRONG_ANSWER_MESSAGES = [
    "❌ Нет. Просто нет. Попробуй ещё раз.",
    "❌ Ты серьёзно? Это школьная программа, братан.",
    "❌ Неправильно. Звонки продолжаются. Удачи.",
    "❌ НЕВЕРНО. Может стоит сначала проснуться, а потом считать?",
    "❌ Блин... Ну это же не квантовая физика.",
    "❌ Мимо. Либо ты ещё спишь, либо в школе прогуливал.",
    "❌ Нет-нет-нет. Считай снова.",
    "❌ Хорошая попытка, но нет. Я буду звонить ещё.",
    "❌ Математика говорит: неа. Звонки говорят: да. Удачи.",
    "❌ Стоп, это вообще число было? Не понял.",
]

CORRECT_ANSWER_MESSAGES = [
    "✅ О! Живой! Звонки остановлены. Можешь умыться.",
    "✅ Математика 1, подушка 0. Доброе утро!",
    "✅ ПРАВИЛЬНО! Поздравляю с выживанием ещё одного утра.",
    "✅ Решил пример из 3 класса. Горжусь тобой. Вставай.",
    "✅ Ладно, верю. Свободен. Но кровать — ловушка, не возвращайся!",
    "✅ Ура! Мозг включился. Теперь включи тело.",
    "✅ Считать умеешь — уже хорошо. Теперь иди умойся.",
    "✅ Звонки остановлены. Это была победа человека над подушкой.",
]

NEW_EXAMPLE_MESSAGES = [
    "🔔 Новый пример. Предыдущий ты проигнорировал, этот тоже не советую.\n\n🧮 {example} = ?\n\nЧисло в ответ, живо.",
    "🔔 ВСЁ ЕЩЁ ЗВОНЮ. Новый пример:\n\n🧮 {example} = ?\n\nОтветь уже наконец.",
    "📞 Звонок #{n}. Пример:\n\n🧮 {example} = ?\n\nМожет на этот раз?",
    "🔔 Ты думал я устану? Нет. Новый пример:\n\n🧮 {example} = ?",
    "😤 Хорошо, ещё один шанс. Пример:\n\n🧮 {example} = ?\n\nЯ никуда не тороплюсь.",
    "📢 ВНИМАНИЕ: я всё ещё здесь. Пример:\n\n🧮 {example} = ?",
    "🔔 Звонок #{n}. Ты уже устал? Я нет. Вот пример:\n\n🧮 {example} = ?",
]

ALARM_SET_MESSAGES = [
    "✅ Будильник на *{time}* ({date}) поставлен. Ты сам это выбрал.\n\n📞 Звонки: каждые {interval} мин по {duration} сек\n🧮 Выключить: решить пример\n\n*⏱ До будильника: {remaining}*",
    "✅ Записал. *{time}* ({date}). Буду звонить как проклятый.\n\n📞 Каждые {interval} мин по {duration} сек, пока не решишь пример.\n\n*⏱ До будильника: {remaining}*",
    "✅ Окей, *{time}* ({date}). Удачи тебе. Понадобится.\n\n📞 Звонки каждые {interval} мин\n🧮 Реши пример — и свободен\n\n*⏱ До будильника: {remaining}*",
    "✅ *{time}* ({date}) — принял. Ложись спать пока можешь.\n\n📞 Буду будить каждые {interval} мин\n\n*⏱ Осталось: {remaining}*",
]

RANDOM_GIBBERISH_RESPONSES = [
    "🤷 Чё? Я будильник, а не ChatGPT.",
    "🤷 Интересно, но я умею только звонить и считать.",
    "🤷 Ты что-то написал. Я это видел. Смысла не понял.",
    "🤷 Слушай, это база данных будильников, а не исповедальня. Используй кнопки.",
    "🤷 Я бы помог, но у меня IQ будильника. Буквально.",
    "🤷 Не понял. Может лучше поставишь будильник?",
]

SNOOZE_DENIED_MESSAGES = [
    "🚫 Кнопки «отложить» нет. Специально.",
    "🚫 Отложить? Серьёзно? Нет.",
    "🚫 «Ещё 5 минут» — это не ко мне. Реши пример.",
]


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает главную клавиатуру с кнопками"""
    keyboard = [
        [KeyboardButton(BUTTON_START), KeyboardButton(BUTTON_MY_ALARMS)],
        [KeyboardButton(BUTTON_NEW_REMINDER), KeyboardButton(BUTTON_MY_REMINDERS)],
        [KeyboardButton(BUTTON_STATUS), KeyboardButton(BUTTON_ALL_ALARMS)],
        [KeyboardButton(BUTTON_INFO)]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def translate_text(text: str, source: str = "en", target: str = "ru") -> str:
    """Перевести текст через MyMemory API (бесплатный)"""
    try:
        url = f"https://api.mymemory.translated.net/get?q={text}&langpair={source}|{target}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("responseStatus") == 200:
                        translated = data.get("responseData", {}).get("translatedText", "")
                        if translated:
                            return translated
    except Exception as e:
        logger.warning(f"Ошибка перевода: {e}")
    return None


async def get_random_fact() -> str:
    """Получить рандомный факт с API и перевести на русский"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(FACTS_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    fact_en = data.get("text", "")
                    
                    if fact_en:
                        # Пробуем перевести через MyMemory API
                        translated = await translate_text(fact_en)
                        if translated:
                            return translated
                        # Если не удалось — возвращаем на английском
                        return f"🇬🇧 {fact_en}"
    except Exception as e:
        logger.error(f"Ошибка получения факта: {e}")
    
    # Fallback факты — смешанные обычные и абсурдные
    fallback_facts = [
        "Осьминоги имеют три сердца. Ты едва встал с одним — слабак.",
        "Мёд никогда не портится. Найден мёд возрастом 3000 лет. Ты за 8 часов сна протух больше.",
        "Коровы могут подниматься по лестнице, но не могут спускаться. Как некоторые карьеры.",
        "Акулы существовали раньше деревьев. То есть акула древнее леса. Осмысли это за завтраком.",
        "Кошки спят 70% своей жизни. Теперь понятно откуда у тебя такая цель в жизни.",
        "Банан — это ягода, а клубника — нет. Вся твоя жизнь — ложь.",
        "Слоны — единственные животные, которые не могут прыгать. И ничего, живут нормально.",
        "На Венере день длиннее года. То есть если бы ты жил на Венере, ты бы ещё не лёг спать.",
        "Национальное животное Шотландии — единорог. Реальное. Официальное. Государственное.",
        "Самая короткая война в истории длилась 38 минут. Столько же длится твоё утреннее «ещё 5 минут».",
        "Буква «й» называется «краткое». Мало кто об этом помнит. Теперь ты помнишь. С добрым утром.",
        "Если убрать пустое пространство из всех атомов человека, человечество поместится в сахарный кубик. Немного утешает, правда?",
        "Мозг не чувствует боли — у него нет болевых рецепторов. Это не значит что тебе не больно вставать.",
        "Первый компьютерный баг — это была буквально моль застрявшая в реле в 1947 году. Программисты с тех пор мало изменились.",
        "Среднестатистический человек проводит 6 лет жизни во сне. Ты явно выше среднего.",
        "Осьминог может открыть банку с едой. Ты не можешь встать. Осьминог умнее.",
        "Муравьи не спят. Вообще. Никогда. Им незнакомо твоё страдание.",
    ]
    return random.choice(fallback_facts)


def format_time_remaining(alarm_time: datetime) -> str:
    """Форматирует оставшееся время до будильника"""
    now = datetime.now()
    diff = alarm_time - now
    
    if diff.total_seconds() <= 0:
        return "уже прошло"
    
    total_seconds = int(diff.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours} ч")
    if minutes > 0:
        parts.append(f"{minutes} мин")
    if seconds > 0 and hours == 0:  # Показываем секунды только если меньше часа
        parts.append(f"{seconds} сек")
    
    return " ".join(parts) if parts else "меньше секунды"


class AlarmBot:
    """Основной класс бота-будильника"""
    
    def __init__(self, bot_token: str, database_url: str):
        self.bot_token = bot_token
        self.db = Database(database_url)
        self.state = StateManager()
        self.scheduler = AlarmScheduler()
        self.application: Optional[Application] = None
        self._bot: Optional[Bot] = None
    
    async def is_allowed_user(self, username: Optional[str]) -> bool:
        """Проверяет, разрешено ли пользователю использовать бота"""
        if not username:
            return False
        return await self.db.is_username_allowed(username)
    
    async def check_user_allowed(self, update: Update) -> bool:
        """Проверка пользователя из Update"""
        user = update.effective_user
        if not user or not user.username:
            return False
        return await self.is_allowed_user(user.username)
    
    async def check_user_allowed_from_query(self, query) -> bool:
        """Проверка пользователя из callback query"""
        user = query.from_user
        if not user or not user.username:
            return False
        return await self.is_allowed_user(user.username)
    
    @staticmethod
    def generate_math_example() -> Tuple[str, float]:
        """Генерирует математический пример (только целочисленное деление)"""
        operation_type = random.randint(1, 5)
        
        if operation_type == 1:
            # a/b + c — a кратно b
            b = random.randint(2, 10)
            multiplier = random.randint(3, 12)
            a = b * multiplier  # a кратно b
            c = random.randint(10, 30)
            example_text = f"{a}/{b} + {c}"
            correct_answer = float(multiplier + c)
        elif operation_type == 2:
            # a*b - c
            a = random.randint(5, 15)
            b = random.randint(2, 8)
            c = random.randint(1, 20)
            example_text = f"{a}*{b} - {c}"
            correct_answer = float((a * b) - c)
        elif operation_type == 3:
            # a/b * c — a кратно b
            b = random.randint(2, 8)
            multiplier = random.randint(4, 10)
            a = b * multiplier  # a кратно b
            c = random.randint(2, 5)
            example_text = f"{a}/{b} * {c}"
            correct_answer = float(multiplier * c)
        elif operation_type == 4:
            # a + b - c
            a = random.randint(20, 50)
            b = random.randint(10, 40)
            c = random.randint(5, 25)
            example_text = f"{a} + {b} - {c}"
            correct_answer = float(a + b - c)
        else:
            # a*b + c
            a = random.randint(3, 12)
            b = random.randint(2, 8)
            c = random.randint(5, 25)
            example_text = f"{a}*{b} + {c}"
            correct_answer = float((a * b) + c)
        
        return (example_text, correct_answer)
    
    @staticmethod
    def parse_time(time_str: str) -> Optional[Tuple[int, int]]:
        """Парсит время в разных форматах"""
        time_str = time_str.strip()
        time_str = re.sub(r':\s+', ':', time_str)
        
        patterns = [
            r'^(\d{1,2}):(\d{2})$',
            r'^(\d{1,2})\s+(\d{2})$',
        ]
        
        for pattern in patterns:
            match = re.match(pattern, time_str)
            if match:
                try:
                    hour = int(match.group(1))
                    minute = int(match.group(2))
                    
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        return (hour, minute)
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def calculate_alarm_time(hour: int, minute: int, for_tomorrow: bool = False) -> datetime:
        """Вычисляет время будильника"""
        now = datetime.now()
        alarm_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if for_tomorrow:
            alarm_time += timedelta(days=1)
        elif alarm_time <= now:
            alarm_time += timedelta(days=1)
        
        return alarm_time
    
    async def on_alarm_triggered(self, user_id: int, alarm_id: int):
        """Callback при срабатывании будильника"""
        logger.info(f"⏰ Будильник сработал: user_id={user_id}, alarm_id={alarm_id}")
        
        if not self._bot:
            logger.error("Bot не инициализирован")
            return
        
        # Проверяем, не звонит ли уже другой будильник этому пользователю
        if self.state.is_user_calling(user_id):
            current_alarm = self.state.get_active_calling_alarm_id(user_id)
            logger.warning(f"Пользователю {user_id} уже звонит будильник {current_alarm}, откладываем {alarm_id}")
            try:
                await self._bot.send_message(
                    chat_id=user_id,
                    text=random.choice([
                        f"⏳ Будильник #{alarm_id} занял очередь. Сначала разберись с текущим примером!",
                        f"⏳ Эй, у тебя ещё один будильник (#{alarm_id}) стоит. Реши сначала пример, потом разберёмся.",
                        f"⏳ #{alarm_id} ждёт своей очереди. Я терпеливый. Ты нет, наверное.",
                    ])
                )
            except Exception:
                pass
            
            # Перепланируем будильник на 3 минуты позже
            new_time = datetime.now() + timedelta(minutes=3)
            self.scheduler.schedule_alarm(user_id, alarm_id, new_time)
            return
        
        # Проверяем, есть ли будильник в state
        if not self.state.has_alarm(user_id, alarm_id):
            logger.warning(f"Будильник {alarm_id} не найден в state, добавляем...")
            alarm = await self.db.get_alarm_by_id(alarm_id)
            if alarm:
                self.state.add_alarm(user_id, alarm_id, alarm.alarm_time)
            else:
                logger.error(f"Будильник {alarm_id} не найден в БД")
                return
        
        # Получаем username из БД
        user = await self.db.get_user(user_id)
        if not user or not user.username:
            logger.error(f"Не удалось найти username для user_id={user_id}")
            try:
                await self._bot.send_message(
                    chat_id=user_id,
                    text="❌ Ошибка: не удалось определить ваш username для звонков"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения: {e}")
            return
        
        username = user.username
        self.state.set_username(user_id, username)
        logger.info(f"Username получен: @{username}")
        
        # Проверяем caller
        if not self.state.caller:
            logger.error("TelegramCaller не инициализирован!")
            try:
                await self._bot.send_message(
                    chat_id=user_id,
                    text="❌ Ошибка: звонки не настроены. Проверьте конфигурацию бота."
                )
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения: {e}")
            return
        
        # Устанавливаем флаг активного звонка
        self.state.start_calling(user_id, alarm_id)
        
        # Отправляем сообщение о начале звонков
        try:
            await self._bot.send_message(
                chat_id=user_id,
                text=random.choice(WAKE_UP_MESSAGES)
            )
            logger.info(f"Сообщение о начале звонков отправлено user_id={user_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение user_id={user_id}: {e}")
        
        # Запускаем цикл звонков с обработкой ошибок
        logger.info(f"Запускаем цикл звонков для @{username}")
        task = asyncio.create_task(self._call_loop(user_id, alarm_id, username))
        task.add_done_callback(lambda t: self._handle_task_error(t, user_id, alarm_id))
        self.state.set_alarm_task(user_id, alarm_id, task)
    
    def _handle_task_error(self, task: asyncio.Task, user_id: int, alarm_id: int):
        """Обработчик ошибок для задач"""
        try:
            exc = task.exception()
            if exc:
                logger.error(f"Ошибка в задаче звонков user_id={user_id}, alarm_id={alarm_id}: {exc}")
        except asyncio.CancelledError:
            logger.info(f"Задача отменена: user_id={user_id}, alarm_id={alarm_id}")
        except Exception as e:
            logger.error(f"Ошибка обработки задачи: {e}")
    
    async def _call_loop(self, user_id: int, alarm_id: int, username: str):
        """Цикл звонков"""
        logger.info(f"_call_loop запущен: user_id={user_id}, alarm_id={alarm_id}, username=@{username}")
        
        caller = self.state.caller
        if not caller:
            logger.error("Caller is None в _call_loop!")
            if self._bot:
                try:
                    await self._bot.send_message(
                        chat_id=user_id,
                        text="❌ Ошибка: не удалось инициализировать звонки"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки сообщения об ошибке: {e}")
            return
        
        logger.info("Caller OK, генерируем пример...")
        
        # Генерируем первый пример
        example_text, correct_answer = self.generate_math_example()
        self.state.set_active_example(user_id, alarm_id, example_text, correct_answer)
        logger.info(f"Пример сгенерирован: {example_text} = {correct_answer}")
        
        # Отправляем пример (БЕЗ Markdown чтобы избежать ошибок)
        if self._bot:
            try:
                await self._bot.send_message(
                    chat_id=user_id,
                    text=f"🧮 Реши пример — остановишь звонки:\n\n{example_text} = ?\n\nОтправь ответ числом."
                )
                logger.info(f"Пример отправлен пользователю {user_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки примера: {e}")
        
        call_count = 0
        
        try:
            logger.info(f"Начинаем цикл звонков. has_alarm={self.state.has_alarm(user_id, alarm_id)}")
            
            while self.state.has_alarm(user_id, alarm_id):
                if not self.state.has_active_example(user_id, alarm_id):
                    logger.info(f"Пример решен: user_id={user_id}, alarm_id={alarm_id}")
                    break
                
                call_count += 1
                logger.info(f"📞 Звонок #{call_count}: user_id={user_id}, @{username}")
                
                try:
                    result = await caller.call(username=username, duration=CALL_DURATION)
                    if result.status.value == "✅ Успешно":
                        logger.info(f"✅ Звонок #{call_count} успешен для @{username}")
                    else:
                        logger.warning(f"⚠️ Звонок #{call_count} не удался: {result.message}")
                except Exception as e:
                    logger.error(f"❌ Ошибка звонка #{call_count}: {e}")
                
                if not self.state.has_alarm(user_id, alarm_id) or not self.state.has_active_example(user_id, alarm_id):
                    logger.info("Выходим из цикла: будильник отменён или пример решён")
                    break
                
                logger.info(f"Ждём {CALL_INTERVAL} секунд до следующего звонка...")
                await asyncio.sleep(CALL_INTERVAL)
                
                # Новый пример (с нарастающим отчаянием)
                if self.state.has_active_example(user_id, alarm_id):
                    example_text, correct_answer = self.generate_math_example()
                    self.state.set_active_example(user_id, alarm_id, example_text, correct_answer)
                    logger.info(f"Новый пример: {example_text} = {correct_answer}")
                    if self._bot:
                        try:
                            msg_template = random.choice(NEW_EXAMPLE_MESSAGES)
                            msg = msg_template.format(
                                example=example_text,
                                n=call_count
                            )
                            await self._bot.send_message(chat_id=user_id, text=msg)
                        except Exception as e:
                            logger.error(f"Ошибка отправки нового примера: {e}")
                
        except asyncio.CancelledError:
            logger.info(f"Звонки отменены: user_id={user_id}, alarm_id={alarm_id}")
        except Exception as e:
            logger.error(f"Ошибка в цикле звонков: {e}", exc_info=True)
            if self._bot:
                try:
                    await self._bot.send_message(chat_id=user_id, text=f"❌ Ошибка: {e}")
                except Exception:
                    pass
        finally:
            logger.info(f"_call_loop завершён: user_id={user_id}, alarm_id={alarm_id}")
            self.state.clear_active_example(user_id, alarm_id)
            self.state.stop_calling(user_id)  # Сбрасываем флаг звонка
    
    async def schedule_alarm(self, user_id: int, alarm_time: datetime) -> Optional[int]:
        """Планирует будильник. Возвращает alarm_id или None"""
        now = datetime.now()
        
        if alarm_time <= now:
            return None
        
        # Проверяем конфликт времени с другими пользователями
        conflict = await self.db.check_alarm_time_conflict(alarm_time, user_id)
        if conflict:
            return None
        
        # Создаем будильник в БД
        alarm = await self.db.create_alarm(user_id, alarm_time)
        alarm_id = alarm.id
        
        # Добавляем в state
        self.state.add_alarm(user_id, alarm_id, alarm_time)
        
        # Планируем через шедулер
        if self.scheduler.schedule_alarm(user_id, alarm_id, alarm_time):
            return alarm_id
        else:
            # Если не удалось запланировать - откатываем
            await self.db.deactivate_alarm_by_id(alarm_id)
            self.state.remove_alarm(user_id, alarm_id)
            return None
    
    async def restore_alarms_from_db(self):
        """Восстанавливает активные будильники из БД"""
        logger.info("Восстановление будильников из БД...")
        
        alarms = await self.db.get_all_active_alarms()
        restored_count = 0
        skipped_count = 0
        
        for alarm in alarms:
            now = datetime.now()
            
            if alarm.alarm_time <= now:
                await self.db.deactivate_alarm_by_id(alarm.id)
                skipped_count += 1
                continue
            
            # Добавляем в state и scheduler
            self.state.add_alarm(alarm.user_id, alarm.id, alarm.alarm_time)
            
            if self.scheduler.schedule_alarm(alarm.user_id, alarm.id, alarm.alarm_time):
                restored_count += 1
                logger.info(f"Восстановлен: user_id={alarm.user_id}, alarm_id={alarm.id}, time={alarm.alarm_time}")
                
                if self._bot:
                    try:
                        time_str = alarm.alarm_time.strftime("%H:%M")
                        await self._bot.send_message(
                            chat_id=alarm.user_id,
                            text=random.choice([
                                f"🔄 Я перезапустился, но всё помню. Будильник на {time_str} никуда не делся.",
                                f"🔄 Бот перезапущен. Будильник на {time_str} восстановлен. Деваться некуда.",
                                f"🔄 Вернулся. Будильник на {time_str} всё ещё в силе. Я не забываю.",
                            ]),
                            reply_markup=get_main_keyboard()
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось уведомить user_id={alarm.user_id}: {e}")
        
        logger.info(f"Восстановлено {restored_count} будильников, пропущено {skipped_count} просроченных")
    
    async def restore_reminders_from_db(self):
        """Восстанавливает активные напоминалки из БД"""
        logger.info("Восстановление напоминалок из БД...")
        
        reminders = await self.db.get_all_active_reminders()
        restored_count = 0
        skipped_count = 0
        
        for reminder in reminders:
            now = datetime.now()
            
            if reminder.remind_time <= now:
                await self.db.deactivate_reminder_by_id(reminder.id)
                skipped_count += 1
                continue
            
            if self.scheduler.schedule_reminder(reminder.user_id, reminder.id, reminder.remind_time):
                restored_count += 1
                logger.info(f"Напоминалка восстановлена: user_id={reminder.user_id}, reminder_id={reminder.id}")
        
        logger.info(f"Восстановлено {restored_count} напоминалок, пропущено {skipped_count} просроченных")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # ОБРАБОТЧИКИ КНОПОК МЕНЮ
    # ═══════════════════════════════════════════════════════════════════════════════
    
    async def handle_command_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start — приветственное сообщение"""
        if not await self.check_user_allowed(update):
            await update.message.reply_text(
                "⛔ У вас нет доступа к этому боту.",
                reply_markup=get_main_keyboard()
            )
            return
        
        user_id = update.effective_user.id
        user = update.effective_user
        
        # Записываем пользователя в БД
        await self.db.get_or_create_user(
            telegram_id=user_id,
            username=user.username,
            first_name=user.first_name
        )
        
        welcome_text = random.choice([
            (
                "👋 О, явился.\n\n"
                "Я — будильник-бот 🔔 Специализируюсь на том чтобы ты не проспал.\n\n"
                "🎯 Умею:\n"
                "• Звонить тебе в Telegram пока не встанешь\n"
                "• Заставлять решать примеры (да, как в 3 классе)\n"
                "• Создавать напоминалки на любую дату\n"
                "• Присылать факты по утрам (чтобы было не так грустно)\n\n"
                "📞 Каждые 2 минуты. Без остановок. Пока не решишь пример.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 Если кнопки не появились — напиши «Стартуем»"
            ),
            (
                "👋 Привет! Ты только что запустил свою персональную пытку.\n\n"
                "Я — будильник-бот 🔔\n\n"
                "🎯 Умею:\n"
                "• Звонить снова и снова пока ты не встанешь\n"
                "• Выключаться только после решения математики\n"
                "• Напоминалки на любой момент\n"
                "• Рандомные факты чтобы ты не чувствовал себя совсем одиноким\n\n"
                "📞 Звонки каждые 2 минуты. Кнопки «отложить» нет. Специально.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 Нажми «🚀 Стартуем» чтобы поставить будильник"
            ),
            (
                "👋 Здорово, соня.\n\n"
                "Я буду звонить тебе в Telegram пока ты не решишь пример 🧮\n\n"
                "🎯 Функции:\n"
                "• Будильники со звонками\n"
                "• Защита от сноуза через математику\n"
                "• Напоминалки\n"
                "• Утренние факты (иногда интересные, иногда нет)\n\n"
                "📞 Интервал: 2 минуты. Терпение у меня бесконечное.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 Кнопки снизу — используй их"
            ),
        ])
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_keyboard()
        )
    
    async def handle_start_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Стартуем' — создание будильника"""
        if not await self.check_user_allowed(update):
            await update.message.reply_text(
                "⛔ У вас нет доступа к этому боту.",
                reply_markup=get_main_keyboard()
            )
            return
        
        user_id = update.effective_user.id
        user = update.effective_user
        
        # Записываем пользователя в БД
        await self.db.get_or_create_user(
            telegram_id=user_id,
            username=user.username,
            first_name=user.first_name
        )
        
        # Проверяем лимит будильников
        current_count = await self.db.count_active_alarms_for_user(user_id)
        if current_count >= MAX_ALARMS_PER_USER:
            await update.message.reply_text(
                f"🚫 У тебя уже {current_count} из {MAX_ALARMS_PER_USER} будильников.\n\n"
                f"Удали один — потом поставишь новый.\n"
                f"_(Или живи так. Но это много звонков.)_",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return

        keyboard = [
            [
                InlineKeyboardButton("📅 На Сегодня", callback_data="today"),
                InlineKeyboardButton("📆 На Завтра", callback_data="tomorrow")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⏰ На какое время поставить будильник?",
            reply_markup=reply_markup
        )
    
    async def handle_status_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Статус'"""
        if not await self.check_user_allowed(update):
            await update.message.reply_text("⛔ У вас нет доступа к этому боту.", reply_markup=get_main_keyboard())
            return
        
        user_id = update.effective_user.id
        alarms = await self.db.get_active_alarms_for_user(user_id)
        
        status_text = "📊 *Статус бота:* ✅ Работает\n\n"
        
        if alarms:
            status_text += f"🔔 *Твои активные будильники:* {len(alarms)}\n"
            for alarm in alarms:
                time_str = alarm.alarm_time.strftime("%H:%M (%d.%m)")
                remaining = format_time_remaining(alarm.alarm_time)
                status_text += f"  • {time_str} — через {remaining}\n"
        else:
            status_text += "😴 Активных будильников нет"
        
        await update.message.reply_text(
            status_text,
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    
    async def handle_stop_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Стоп мне неприятно'"""
        if not await self.check_user_allowed(update):
            await update.message.reply_text("⛔ У вас нет доступа к этому боту.", reply_markup=get_main_keyboard())
            return
        
        user_id = update.effective_user.id
        alarms = await self.db.get_active_alarms_for_user(user_id)
        
        if not alarms:
            await update.message.reply_text(
                "ℹ️ У тебя нет активных будильников.",
                reply_markup=get_main_keyboard()
            )
            return
        
        if len(alarms) == 1:
            # Один будильник - сразу удаляем
            alarm = alarms[0]
            self.scheduler.cancel_alarm(user_id, alarm.id)
            self.state.cleanup_alarm(user_id, alarm.id)
            await self.db.deactivate_alarm_by_id(alarm.id)
            
            await update.message.reply_text(
                "✅ Будильник остановлен. Сладких снов! 😴",
                reply_markup=get_main_keyboard()
            )
        else:
            # Несколько будильников - показываем выбор
            keyboard = []
            for alarm in alarms:
                time_str = alarm.alarm_time.strftime("%H:%M (%d.%m)")
                keyboard.append([InlineKeyboardButton(f"❌ {time_str}", callback_data=f"stop_{alarm.id}")])
            keyboard.append([InlineKeyboardButton("🛑 Удалить ВСЕ", callback_data="stop_all")])
            
            await update.message.reply_text(
                "Какой будильник остановить?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def handle_info_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Инфо'"""
        info_text = (
            "ℹ️ *Будильник-бот*\n\n"
            "🔹 Ставишь будильник на нужное время\n"
            "🔹 Бот звонит в Telegram пока не встанешь\n"
            "🔹 Выключить можно только решив математический пример\n"
            "🔹 Кнопки «отложить» нет — это не баг, это фича\n"
            "🔹 Можно поставить несколько будильников\n"
            "🔹 Есть напоминалки на любую дату\n\n"
            f"📞 Звонит каждые *{int(CALL_INTERVAL/60)} мин* по *{int(CALL_DURATION)} сек*\n"
            f"⏰ Макс. будильников: *{MAX_ALARMS_PER_USER}*\n"
            f"📝 Макс. напоминалок: *{MAX_REMINDERS_PER_USER}*\n\n"
            "💡 _Бот не несёт ответственности за испорченное настроение с утра_"
        )
        
        await update.message.reply_text(
            info_text,
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    
    async def handle_my_alarms_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Мои Будильники'"""
        if not await self.check_user_allowed(update):
            await update.message.reply_text("⛔ У вас нет доступа к этому боту.", reply_markup=get_main_keyboard())
            return
        
        user_id = update.effective_user.id
        alarms = await self.db.get_active_alarms_for_user(user_id)
        
        if not alarms:
            await update.message.reply_text(
                random.choice([
                    "😴 Будильников нет. Живёшь на авось.\n\nНажми *🚀 Стартуем* чтобы исправить это.",
                    "😴 Пусто. Ни одного будильника. Ты либо очень дисциплинирован, либо уже проспал.\n\nНажми *🚀 Стартуем*.",
                    "😴 Будильников нет. Надеюсь у тебя есть другой план на утро.\n\nЕсли нет — *🚀 Стартуем*.",
                ]),
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return
        
        text = f"⏰ *Твои будильники ({len(alarms)}/{MAX_ALARMS_PER_USER}):*\n\n"
        
        keyboard = []
        for i, alarm in enumerate(alarms, 1):
            time_str = alarm.alarm_time.strftime("%H:%M")
            date_str = alarm.alarm_time.strftime("%d.%m.%Y")
            remaining = format_time_remaining(alarm.alarm_time)
            
            text += f"{i}. 🔔 *{time_str}* ({date_str})\n"
            text += f"   ⏱ Через: {remaining}\n\n"
            
            keyboard.append([InlineKeyboardButton(f"❌ Удалить {time_str}", callback_data=f"delete_{alarm.id}")])
        
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_all_alarms_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Все будильники'"""
        if not await self.check_user_allowed(update):
            await update.message.reply_text("⛔ У вас нет доступа к этому боту.", reply_markup=get_main_keyboard())
            return
        
        alarms_with_users = await self.db.get_all_active_alarms_with_users()
        
        if not alarms_with_users:
            await update.message.reply_text(
                "😴 Нет активных будильников ни у кого.",
                reply_markup=get_main_keyboard()
            )
            return
        
        text = f"👥 *Все активные будильники ({len(alarms_with_users)}):*\n\n"
        
        for alarm, username in alarms_with_users:
            time_str = alarm.alarm_time.strftime("%H:%M")
            date_str = alarm.alarm_time.strftime("%d.%m")
            remaining = format_time_remaining(alarm.alarm_time)
            user_display = f"@{username}" if username else f"ID:{alarm.user_id}"
            
            text += f"🔔 *{time_str}* ({date_str}) — {user_display}\n"
            text += f"   ⏱ Через: {remaining}\n\n"
        
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # НАПОМИНАЛКИ
    # ═══════════════════════════════════════════════════════════════════════════════
    
    async def handle_new_reminder_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Напоминалка' — создание напоминалки"""
        if not await self.check_user_allowed(update):
            await update.message.reply_text("⛔ У вас нет доступа к этому боту.", reply_markup=get_main_keyboard())
            return
        
        user_id = update.effective_user.id
        
        # Проверяем лимит напоминалок
        current_count = await self.db.count_active_reminders_for_user(user_id)
        if current_count >= MAX_REMINDERS_PER_USER:
            await update.message.reply_text(
                f"⚠️ У тебя уже {current_count} напоминалок (максимум {MAX_REMINDERS_PER_USER}).\n"
                f"Удали одну, чтобы создать новую.",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Устанавливаем режим создания напоминалки
        context.user_data['creating_reminder'] = True
        context.user_data['reminder_step'] = 'text'
        
        await update.message.reply_text(
            "📝 Создаём напоминалку!\n\n"
            "Шаг 1/2: О чём тебе напомнить?\n"
            "Напиши текст напоминалки:",
            reply_markup=get_main_keyboard()
        )
    
    async def handle_my_reminders_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Мои Напоминалки'"""
        if not await self.check_user_allowed(update):
            await update.message.reply_text("⛔ У вас нет доступа к этому боту.", reply_markup=get_main_keyboard())
            return
        
        user_id = update.effective_user.id
        reminders = await self.db.get_active_reminders_for_user(user_id)
        
        if not reminders:
            await update.message.reply_text(
                "🗒 У тебя нет активных напоминалок.\n\n"
                "Нажми «📝 Напоминалка», чтобы создать!",
                reply_markup=get_main_keyboard()
            )
            return
        
        text = f"🗒 Твои напоминалки ({len(reminders)}/{MAX_REMINDERS_PER_USER}):\n\n"
        
        keyboard = []
        for i, reminder in enumerate(reminders, 1):
            time_str = reminder.remind_time.strftime("%H:%M")
            date_str = reminder.remind_time.strftime("%d.%m.%Y")
            remaining = format_time_remaining(reminder.remind_time)
            
            # Обрезаем текст если слишком длинный
            reminder_text = reminder.text[:50] + "..." if len(reminder.text) > 50 else reminder.text
            
            text += f"{i}. 📌 {time_str} ({date_str})\n"
            text += f"   📝 {reminder_text}\n"
            text += f"   ⏱ Через: {remaining}\n\n"
            
            keyboard.append([InlineKeyboardButton(f"❌ Удалить #{i}", callback_data=f"delremind_{reminder.id}")])
        
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_reminder_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Обработка создания напоминалки (пошаговый процесс)"""
        if not context.user_data.get('creating_reminder'):
            return False
        
        user_id = update.effective_user.id
        text = update.message.text.strip()
        step = context.user_data.get('reminder_step', 'text')
        
        if step == 'text':
            # Сохраняем текст напоминалки
            context.user_data['reminder_text'] = text
            context.user_data['reminder_step'] = 'datetime'
            
            await update.message.reply_text(
                "✅ Текст сохранён!\n\n"
                "Шаг 2/2: Когда напомнить?\n\n"
                "Отправь дату и время в формате:\n"
                "• `25.12 18:00` — конкретная дата\n"
                "• `18:00` — сегодня в это время\n"
                "• `завтра 09:30` — завтра",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return True
        
        elif step == 'datetime':
            # Парсим дату и время
            remind_time = self.parse_reminder_datetime(text)
            
            if not remind_time:
                await update.message.reply_text(
                    "❌ Не понял формат. Попробуй так:\n"
                    "• `25.12 18:00`\n"
                    "• `18:00`\n"
                    "• `завтра 09:30`",
                    parse_mode="Markdown",
                    reply_markup=get_main_keyboard()
                )
                return True
            
            if remind_time <= datetime.now():
                await update.message.reply_text(
                    "❌ Это время уже прошло! Укажи время в будущем.",
                    reply_markup=get_main_keyboard()
                )
                return True
            
            reminder_text = context.user_data.get('reminder_text', '')
            
            # Создаём напоминалку в БД
            reminder = await self.db.create_reminder(user_id, reminder_text, remind_time)
            
            # Планируем через scheduler
            self.scheduler.schedule_reminder(user_id, reminder.id, remind_time)
            
            # Очищаем состояние
            context.user_data['creating_reminder'] = False
            context.user_data['reminder_step'] = None
            context.user_data['reminder_text'] = None
            
            time_str = remind_time.strftime("%H:%M")
            date_str = remind_time.strftime("%d.%m.%Y")
            remaining = format_time_remaining(remind_time)
            
            await update.message.reply_text(
                f"✅ Напоминалка создана!\n\n"
                f"📌 {time_str} ({date_str})\n"
                f"📝 {reminder_text}\n\n"
                f"⏱ До напоминания: {remaining}",
                reply_markup=get_main_keyboard()
            )
            return True
        
        return False
    
    @staticmethod
    def parse_reminder_datetime(text: str) -> Optional[datetime]:
        """Парсит дату и время для напоминалки"""
        text = text.strip().lower()
        now = datetime.now()
        
        # Паттерн: "завтра HH:MM"
        match = re.match(r'завтра\s+(\d{1,2})[:\s](\d{2})', text)
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # Паттерн: "DD.MM HH:MM"
        match = re.match(r'(\d{1,2})\.(\d{1,2})\s+(\d{1,2})[:\s](\d{2})', text)
        if match:
            day, month = int(match.group(1)), int(match.group(2))
            hour, minute = int(match.group(3)), int(match.group(4))
            if 1 <= day <= 31 and 1 <= month <= 12 and 0 <= hour <= 23 and 0 <= minute <= 59:
                year = now.year
                remind_time = datetime(year, month, day, hour, minute, 0)
                if remind_time < now:
                    remind_time = datetime(year + 1, month, day, hour, minute, 0)
                return remind_time
        
        # Паттерн: "HH:MM" (сегодня)
        match = re.match(r'^(\d{1,2})[:\s](\d{2})$', text)
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                remind_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if remind_time <= now:
                    remind_time += timedelta(days=1)
                return remind_time
        
        return None
    
    async def on_reminder_triggered(self, user_id: int, reminder_id: int):
        """Callback при срабатывании напоминалки"""
        logger.info(f"📝 Напоминалка сработала: user_id={user_id}, reminder_id={reminder_id}")
        
        if not self._bot:
            return
        
        reminder = await self.db.get_reminder_by_id(reminder_id)
        if not reminder:
            logger.error(f"Напоминалка {reminder_id} не найдена")
            return
        
        try:
            await self._bot.send_message(
                chat_id=user_id,
                text=f"🔔 Напоминаю!\n\n"
                     f"Ты просил напомнить тебе:\n\n"
                     f"📝 {reminder.text}",
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка отправки напоминалки: {e}")
        
        # Деактивируем напоминалку
        await self.db.deactivate_reminder_by_id(reminder_id)
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # ОБРАБОТЧИКИ CALLBACK
    # ═══════════════════════════════════════════════════════════════════════════════
    
    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик inline кнопок"""
        query = update.callback_query
        
        if not await self.check_user_allowed_from_query(query):
            await query.answer("⛔ У вас нет доступа к этому боту.", show_alert=True)
            return
        
        await query.answer()
        data = query.data
        user_id = query.from_user.id
        
        # Выбор дня
        if data in ["today", "tomorrow"]:
            context.user_data['alarm_choice'] = data
            await query.edit_message_text(
                "Отлично! Во сколько разбудить?\n\n"
                "Отправь время в формате:\n"
                "• `22:03`\n"
                "• `22 03`\n"
                "• `4:20`",
                parse_mode="Markdown"
            )
        
        # Удаление конкретного будильника
        elif data.startswith("delete_") or data.startswith("stop_"):
            if data == "stop_all":
                # Удалить все будильники пользователя
                alarms = await self.db.get_active_alarms_for_user(user_id)
                for alarm in alarms:
                    self.scheduler.cancel_alarm(user_id, alarm.id)
                    self.state.cleanup_alarm(user_id, alarm.id)
                    await self.db.deactivate_alarm_by_id(alarm.id)
                
                await query.edit_message_text(
                    f"✅ Удалено {len(alarms)} будильников. Сладких снов! 😴"
                )
            else:
                # Удалить конкретный будильник
                alarm_id = int(data.split("_")[1])
                self.scheduler.cancel_alarm(user_id, alarm_id)
                self.state.cleanup_alarm(user_id, alarm_id)
                await self.db.deactivate_alarm_by_id(alarm_id)
                
                await query.edit_message_text("✅ Будильник удален!")
        
        # Удаление напоминалки
        elif data.startswith("delremind_"):
            reminder_id = int(data.split("_")[1])
            self.scheduler.cancel_reminder(user_id, reminder_id)
            await self.db.deactivate_reminder_by_id(reminder_id)
            await query.edit_message_text("✅ Напоминалка удалена!")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # ОБРАБОТЧИКИ СООБЩЕНИЙ
    # ═══════════════════════════════════════════════════════════════════════════════
    
    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Обработчик ответов на математические примеры"""
        user_id = update.effective_user.id
        
        # Ищем будильник с активным примером
        alarm_id = self.state.find_alarm_with_example(user_id)
        if alarm_id is None:
            return False
        
        example = self.state.get_active_example(user_id, alarm_id)
        if not example:
            return False
        
        example_text, correct_answer = example
        answer_text = update.message.text.strip()
        
        try:
            user_answer = float(answer_text)
            if abs(user_answer - correct_answer) < 0.01:
                # Правильный ответ!
                logger.info(f"Пользователь {user_id} решил пример: {example_text} = {correct_answer}")
                
                # Очищаем состояние
                self.state.clear_active_example(user_id, alarm_id)
                self.state.cancel_alarm_task(user_id, alarm_id)
                self.state.remove_alarm(user_id, alarm_id)
                self.scheduler.cancel_alarm(user_id, alarm_id)
                await self.db.deactivate_alarm_by_id(alarm_id)
                
                # Получаем рандомный факт
                fact = await get_random_fact()
                
                win_msg = random.choice(CORRECT_ANSWER_MESSAGES)
                await update.message.reply_text(
                    f"{win_msg}\n\n"
                    f"☀️ *Доброе утро!*\n\n"
                    f"💡 *Кстати:*\n{fact}",
                    parse_mode="Markdown",
                    reply_markup=get_main_keyboard()
                )
                
                return True
            else:
                await update.message.reply_text(
                    random.choice(WRONG_ANSWER_MESSAGES),
                    reply_markup=get_main_keyboard()
                )
                return True
        except ValueError:
            return False
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Основной обработчик текстовых сообщений"""
        if not await self.check_user_allowed(update):
            await update.message.reply_text("⛔ У вас нет доступа к этому боту.", reply_markup=get_main_keyboard())
            return
        
        text = update.message.text.strip()
        
        # Обработка кнопок меню
        if text == BUTTON_START or text.lower() == "стартуем":
            await self.handle_start_button(update, context)
            return
        elif text == BUTTON_STATUS:
            await self.handle_status_button(update, context)
            return
        elif text == BUTTON_INFO:
            await self.handle_info_button(update, context)
            return
        elif text == BUTTON_MY_ALARMS:
            await self.handle_my_alarms_button(update, context)
            return
        elif text == BUTTON_ALL_ALARMS:
            await self.handle_all_alarms_button(update, context)
            return
        elif text == BUTTON_NEW_REMINDER:
            await self.handle_new_reminder_button(update, context)
            return
        elif text == BUTTON_MY_REMINDERS:
            await self.handle_my_reminders_button(update, context)
            return
        
        # Проверяем, не ответ ли это на пример
        if await self.handle_answer(update, context):
            return
        
        # Проверяем, не создаём ли напоминалку
        if await self.handle_reminder_creation(update, context):
            return
        
        # Пробуем распознать время
        user_id = update.effective_user.id
        time_result = self.parse_time(text)
        
        if not time_result:
            await update.message.reply_text(
                random.choice(RANDOM_GIBBERISH_RESPONSES) + "\n\n"
                "Если хочешь поставить будильник — отправь время:\n"
                "• `22:03`\n"
                "• `4:20`",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return
        
        hour, minute = time_result
        choice = context.user_data.get('alarm_choice', 'today')
        for_tomorrow = (choice == 'tomorrow')
        
        alarm_time = self.calculate_alarm_time(hour, minute, for_tomorrow)
        
        # Проверяем лимит
        current_count = await self.db.count_active_alarms_for_user(user_id)
        if current_count >= MAX_ALARMS_PER_USER:
            await update.message.reply_text(
                f"⚠️ У тебя уже {current_count} будильников (максимум {MAX_ALARMS_PER_USER}).\n"
                f"Удали один, чтобы создать новый.",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Проверяем конфликт с другими пользователями
        conflict = await self.db.check_alarm_time_conflict(alarm_time, user_id)
        if conflict:
            conflict_user_id, conflict_username = conflict
            time_str = alarm_time.strftime("%H:%M")
            await update.message.reply_text(
                f"⚠️ Бро, прости! У @{conflict_username} уже стоит похожий будильник на {time_str}.\n"
                f"Попробуй поставить на 10+ минут раньше или позже.",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Планируем будильник
        alarm_id = await self.schedule_alarm(user_id, alarm_time)
        
        if alarm_id:
            time_str = alarm_time.strftime("%H:%M")
            date_str = alarm_time.strftime("%d.%m.%Y")
            remaining = format_time_remaining(alarm_time)

            msg_template = random.choice(ALARM_SET_MESSAGES)
            msg = msg_template.format(
                time=time_str,
                date=date_str,
                interval=int(CALL_INTERVAL / 60),
                duration=int(CALL_DURATION),
                remaining=remaining,
            )
            await update.message.reply_text(
                msg,
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ Что-то пошло не так. Попробуй ещё раз, а если не поможет — перезапусти бота.",
                reply_markup=get_main_keyboard()
            )
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # ИНИЦИАЛИЗАЦИЯ И ЗАПУСК
    # ═══════════════════════════════════════════════════════════════════════════════
    
    async def init_caller(self) -> bool:
        """Инициализация TelegramCaller"""
        api_id, api_hash = load_config()
        
        if not api_id or not api_hash:
            api_id_str = os.getenv("TELEGRAM_API_ID", "")
            api_hash = os.getenv("TELEGRAM_API_HASH", "")
            if not api_id_str or not api_hash:
                logger.error("❌ TELEGRAM_API_ID и TELEGRAM_API_HASH должны быть установлены!")
                return False
            api_id = int(api_id_str)
            logger.info("API credentials из переменных окружения")
        else:
            logger.info("API credentials из конфигурационного файла")
        
        session_name = os.getenv("TELEGRAM_SESSION_NAME", "pyrogram_session")
        session_dir = os.getenv("TELEGRAM_SESSION_DIR", "")
        if session_dir:
            os.makedirs(session_dir, exist_ok=True)
            session_path = os.path.join(session_dir, session_name)
        else:
            session_path = session_name
        
        caller = TelegramCaller(api_id, api_hash, session_name=session_path)
        
        try:
            logger.info("Подключение к Telegram для звонков...")
            if await caller.connect():
                self.state.set_caller(caller)
                logger.info("✅ TelegramCaller инициализирован")
                return True
            else:
                logger.error("❌ Не удалось подключиться к Telegram")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка TelegramCaller: {e}")
            return False
    
    async def post_init(self, application: Application):
        """Выполняется после инициализации бота"""
        self._bot = application.bot
        
        await self.db.init_db()
        await self.db.init_default_allowed_users(DEFAULT_ALLOWED_USERNAMES)
        
        self.scheduler.init(self.on_alarm_triggered, self.on_reminder_triggered)
        self.scheduler.start()
        
        await self.init_caller()
        await self.restore_alarms_from_db()
        await self.restore_reminders_from_db()
        
        logger.info("✅ Бот полностью инициализирован")
    
    async def shutdown(self, application: Application):
        """Корректное завершение работы"""
        logger.info("Завершение работы бота...")
        self.scheduler.shutdown()
        await self.state.shutdown()
        await self.db.close()
        logger.info("Бот остановлен")
    
    def run(self):
        """Запуск бота"""
        self.application = (
            Application.builder()
            .token(self.bot_token)
            .post_init(self.post_init)
            .post_shutdown(self.shutdown)
            .build()
        )
        
        # Команды
        self.application.add_handler(CommandHandler("start", self.handle_command_start))
        self.application.add_handler(CommandHandler("stop", self.handle_stop_button))
        
        # Inline кнопки
        self.application.add_handler(CallbackQueryHandler(self.handle_button))
        
        # Текстовые сообщения (включая кнопки меню)
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        logger.info("Запуск бота...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Главная функция"""
    bot_token = os.getenv("BOT_TOKEN", "")

    if not bot_token:
        print("❌ Ошибка: не установлен BOT_TOKEN!")
        return
    
    database_url = os.getenv("DATABASE_URL", "")

    if not database_url:
        print("❌ Ошибка: не установлен DATABASE_URL!")
        return
    
    bot = AlarmBot(bot_token, database_url)
    bot.run()


if __name__ == "__main__":
    main()
