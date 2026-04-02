"""
Database module - PostgreSQL модели и репозиторий
"""

import asyncio
from datetime import datetime
from typing import Optional, List, Tuple
from contextlib import asynccontextmanager

from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, Float
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select, delete, update

Base = declarative_base()


class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    is_allowed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Alarm(Base):
    """Модель будильника"""
    __tablename__ = "alarms"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    alarm_time = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AllowedUser(Base):
    """Модель разрешенных пользователей"""
    __tablename__ = "allowed_users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    added_at = Column(DateTime, default=datetime.utcnow)


class Reminder(Base):
    """Модель напоминалки"""
    __tablename__ = "reminders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    text = Column(String(1000), nullable=False)
    remind_time = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, 
            class_=AsyncSession, 
            expire_on_commit=False
        )
    
    async def init_db(self):
        """Инициализация базы данных (создание таблиц)"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def close(self):
        """Закрытие соединения"""
        await self.engine.dispose()
    
    @asynccontextmanager
    async def session(self):
        """Контекстный менеджер для сессии"""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # ПОЛЬЗОВАТЕЛИ
    # ═══════════════════════════════════════════════════════════════════════════════
    
    async def get_or_create_user(
        self, 
        telegram_id: int, 
        username: Optional[str] = None,
        first_name: Optional[str] = None
    ) -> User:
        """Получить или создать пользователя"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                # Обновляем информацию
                if username:
                    user.username = username
                if first_name:
                    user.first_name = first_name
                user.last_active_at = datetime.utcnow()
            else:
                # Создаем нового
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name
                )
                session.add(user)
            
            await session.commit()
            return user
    
    async def get_user(self, telegram_id: int) -> Optional[User]:
        """Получить пользователя по telegram_id"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # РАЗРЕШЕННЫЕ ПОЛЬЗОВАТЕЛИ
    # ═══════════════════════════════════════════════════════════════════════════════
    
    async def is_username_allowed(self, username: str) -> bool:
        """Проверить, разрешен ли пользователь по username"""
        if not username:
            return False
        
        async with self.session() as session:
            result = await session.execute(
                select(AllowedUser).where(
                    AllowedUser.username.ilike(username.lower())
                )
            )
            return result.scalar_one_or_none() is not None
    
    async def add_allowed_user(self, username: str) -> bool:
        """Добавить разрешенного пользователя"""
        username = username.lower().strip()
        if username.startswith("@"):
            username = username[1:]
        
        async with self.session() as session:
            # Проверяем, не существует ли уже
            result = await session.execute(
                select(AllowedUser).where(AllowedUser.username == username)
            )
            if result.scalar_one_or_none():
                return False
            
            allowed = AllowedUser(username=username)
            session.add(allowed)
            await session.commit()
            return True
    
    async def remove_allowed_user(self, username: str) -> bool:
        """Удалить разрешенного пользователя"""
        username = username.lower().strip()
        if username.startswith("@"):
            username = username[1:]
        
        async with self.session() as session:
            result = await session.execute(
                delete(AllowedUser).where(AllowedUser.username == username)
            )
            await session.commit()
            return result.rowcount > 0
    
    async def get_all_allowed_users(self) -> list[str]:
        """Получить всех разрешенных пользователей"""
        async with self.session() as session:
            result = await session.execute(select(AllowedUser))
            return [u.username for u in result.scalars().all()]
    
    async def init_default_allowed_users(self, usernames: list[str]):
        """Инициализировать дефолтных разрешенных пользователей"""
        for username in usernames:
            await self.add_allowed_user(username)
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # БУДИЛЬНИКИ (ПОДДЕРЖКА НЕСКОЛЬКИХ)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    async def create_alarm(self, user_id: int, alarm_time: datetime) -> Alarm:
        """Создать будильник и вернуть его с ID"""
        async with self.session() as session:
            alarm = Alarm(user_id=user_id, alarm_time=alarm_time, is_active=True)
            session.add(alarm)
            await session.flush()  # Получаем ID до коммита
            await session.commit()
            await session.refresh(alarm)
            return alarm
    
    async def get_alarm_by_id(self, alarm_id: int) -> Optional[Alarm]:
        """Получить будильник по ID"""
        async with self.session() as session:
            result = await session.execute(
                select(Alarm).where(Alarm.id == alarm_id)
            )
            return result.scalar_one_or_none()
    
    async def get_active_alarms_for_user(self, user_id: int) -> List[Alarm]:
        """Получить все активные будильники пользователя"""
        async with self.session() as session:
            result = await session.execute(
                select(Alarm).where(
                    Alarm.user_id == user_id,
                    Alarm.is_active == True
                ).order_by(Alarm.alarm_time)
            )
            return list(result.scalars().all())
    
    async def get_active_alarm(self, user_id: int) -> Optional[Alarm]:
        """Получить первый активный будильник пользователя (для обратной совместимости)"""
        alarms = await self.get_active_alarms_for_user(user_id)
        return alarms[0] if alarms else None
    
    async def deactivate_alarm_by_id(self, alarm_id: int) -> bool:
        """Деактивировать конкретный будильник по ID"""
        async with self.session() as session:
            result = await session.execute(
                select(Alarm).where(
                    Alarm.id == alarm_id,
                    Alarm.is_active == True
                )
            )
            alarm = result.scalar_one_or_none()
            if alarm:
                alarm.is_active = False
                await session.commit()
                return True
            return False
    
    async def deactivate_alarm(self, user_id: int) -> bool:
        """Деактивировать все будильники пользователя"""
        async with self.session() as session:
            result = await session.execute(
                select(Alarm).where(
                    Alarm.user_id == user_id,
                    Alarm.is_active == True
                )
            )
            alarms = result.scalars().all()
            if alarms:
                for alarm in alarms:
                    alarm.is_active = False
                await session.commit()
                return True
            return False
    
    async def get_all_active_alarms(self) -> List[Alarm]:
        """Получить все активные будильники"""
        async with self.session() as session:
            result = await session.execute(
                select(Alarm).where(Alarm.is_active == True).order_by(Alarm.alarm_time)
            )
            return list(result.scalars().all())
    
    async def get_all_active_alarms_with_users(self) -> List[Tuple[Alarm, Optional[str]]]:
        """Получить все активные будильники с username пользователей"""
        async with self.session() as session:
            result = await session.execute(
                select(Alarm).where(Alarm.is_active == True).order_by(Alarm.alarm_time)
            )
            alarms = list(result.scalars().all())
            
            alarms_with_users = []
            for alarm in alarms:
                user_result = await session.execute(
                    select(User).where(User.telegram_id == alarm.user_id)
                )
                user = user_result.scalar_one_or_none()
                username = user.username if user else None
                alarms_with_users.append((alarm, username))
            
            return alarms_with_users
    
    async def check_alarm_time_conflict(self, alarm_time: datetime, exclude_user_id: int) -> Optional[Tuple[int, str]]:
        """
        Проверить конфликт времени с другими пользователями.
        Возвращает (user_id, username) если конфликт есть, иначе None.
        Конфликт = разница менее 10 минут.
        """
        async with self.session() as session:
            result = await session.execute(
                select(Alarm).where(Alarm.is_active == True)
            )
            alarms = result.scalars().all()
            
            for alarm in alarms:
                if alarm.user_id == exclude_user_id:
                    continue
                
                time_diff = abs((alarm_time - alarm.alarm_time).total_seconds())
                if time_diff < 600:  # 10 минут
                    # Получаем username
                    user_result = await session.execute(
                        select(User).where(User.telegram_id == alarm.user_id)
                    )
                    user = user_result.scalar_one_or_none()
                    username = user.username if user else "неизвестный пользователь"
                    return (alarm.user_id, username)
            
            return None
    
    async def count_active_alarms_for_user(self, user_id: int) -> int:
        """Подсчитать количество активных будильников пользователя"""
        async with self.session() as session:
            result = await session.execute(
                select(Alarm).where(
                    Alarm.user_id == user_id,
                    Alarm.is_active == True
                )
            )
            return len(list(result.scalars().all()))
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # НАПОМИНАЛКИ
    # ═══════════════════════════════════════════════════════════════════════════════
    
    async def create_reminder(self, user_id: int, text: str, remind_time: datetime) -> Reminder:
        """Создать напоминалку"""
        async with self.session() as session:
            reminder = Reminder(user_id=user_id, text=text, remind_time=remind_time, is_active=True)
            session.add(reminder)
            await session.flush()
            await session.commit()
            await session.refresh(reminder)
            return reminder
    
    async def get_reminder_by_id(self, reminder_id: int) -> Optional[Reminder]:
        """Получить напоминалку по ID"""
        async with self.session() as session:
            result = await session.execute(
                select(Reminder).where(Reminder.id == reminder_id)
            )
            return result.scalar_one_or_none()
    
    async def get_active_reminders_for_user(self, user_id: int) -> List[Reminder]:
        """Получить все активные напоминалки пользователя"""
        async with self.session() as session:
            result = await session.execute(
                select(Reminder).where(
                    Reminder.user_id == user_id,
                    Reminder.is_active == True
                ).order_by(Reminder.remind_time)
            )
            return list(result.scalars().all())
    
    async def deactivate_reminder_by_id(self, reminder_id: int) -> bool:
        """Деактивировать напоминалку"""
        async with self.session() as session:
            result = await session.execute(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.is_active == True
                )
            )
            reminder = result.scalar_one_or_none()
            if reminder:
                reminder.is_active = False
                await session.commit()
                return True
            return False
    
    async def get_all_active_reminders(self) -> List[Reminder]:
        """Получить все активные напоминалки"""
        async with self.session() as session:
            result = await session.execute(
                select(Reminder).where(Reminder.is_active == True).order_by(Reminder.remind_time)
            )
            return list(result.scalars().all())
    
    async def count_active_reminders_for_user(self, user_id: int) -> int:
        """Подсчитать количество активных напоминалок пользователя"""
        async with self.session() as session:
            result = await session.execute(
                select(Reminder).where(
                    Reminder.user_id == user_id,
                    Reminder.is_active == True
                )
            )
            return len(list(result.scalars().all()))
