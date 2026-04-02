"""
Scheduler - Планировщик будильников и напоминалок с APScheduler
Поддержка нескольких будильников и напоминалок для одного пользователя
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Awaitable, Dict, Any, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)


class AlarmScheduler:
    """
    Планировщик будильников и напоминалок на базе APScheduler.
    Поддерживает несколько будильников и напоминалок для одного пользователя.
    Формат job_id для будильников: "alarm_{user_id}_{alarm_id}"
    Формат job_id для напоминалок: "remind_{user_id}_{reminder_id}"
    """
    
    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None
        # Callback для будильников (user_id, alarm_id)
        self._alarm_callback: Optional[Callable[[int, int], Awaitable[None]]] = None
        # Callback для напоминалок (user_id, reminder_id)
        self._reminder_callback: Optional[Callable[[int, int], Awaitable[None]]] = None
    
    def init(self, alarm_callback: Callable[[int, int], Awaitable[None]], reminder_callback: Optional[Callable[[int, int], Awaitable[None]]] = None):
        """
        Инициализация шедулера.
        
        Args:
            alarm_callback: Асинхронная функция, вызываемая при срабатывании будильника.
                           Принимает (user_id, alarm_id).
            reminder_callback: Асинхронная функция, вызываемая при срабатывании напоминалки.
                              Принимает (user_id, reminder_id).
        """
        self._alarm_callback = alarm_callback
        self._reminder_callback = reminder_callback
        
        jobstores = {
            'default': MemoryJobStore()
        }
        
        self._scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            timezone='Europe/Moscow'
        )
        
        logger.info("AlarmScheduler инициализирован")
    
    def start(self):
        """Запуск шедулера"""
        if self._scheduler and not self._scheduler.running:
            self._scheduler.start()
            logger.info("AlarmScheduler запущен")
    
    def shutdown(self):
        """Остановка шедулера"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("AlarmScheduler остановлен")
    
    def schedule_alarm(self, user_id: int, alarm_id: int, alarm_time: datetime) -> bool:
        """
        Запланировать будильник.
        
        Args:
            user_id: ID пользователя
            alarm_id: ID будильника в БД
            alarm_time: Время срабатывания
            
        Returns:
            True если успешно запланировано
        """
        if not self._scheduler or not self._alarm_callback:
            logger.error("Scheduler не инициализирован")
            return False
        
        job_id = self._get_job_id(user_id, alarm_id)
        
        # Проверяем, что время в будущем
        if alarm_time <= datetime.now():
            logger.warning(f"Попытка запланировать будильник в прошлом: user_id={user_id}, alarm_id={alarm_id}")
            return False
        
        try:
            self._scheduler.add_job(
                func=self._trigger_alarm,
                trigger=DateTrigger(run_date=alarm_time),
                args=[user_id, alarm_id],
                id=job_id,
                name=f"alarm_user_{user_id}_id_{alarm_id}",
                replace_existing=True
            )
            
            logger.info(f"Будильник запланирован: user_id={user_id}, alarm_id={alarm_id}, time={alarm_time}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при планировании будильника: user_id={user_id}, alarm_id={alarm_id}: {e}")
            return False
    
    def cancel_alarm(self, user_id: int, alarm_id: int) -> bool:
        """
        Отменить конкретный будильник.
        
        Args:
            user_id: ID пользователя
            alarm_id: ID будильника
            
        Returns:
            True если будильник был отменен
        """
        if not self._scheduler:
            return False
        
        job_id = self._get_job_id(user_id, alarm_id)
        
        try:
            job = self._scheduler.get_job(job_id)
            if job:
                self._scheduler.remove_job(job_id)
                logger.info(f"Будильник отменен: user_id={user_id}, alarm_id={alarm_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка при отмене будильника: user_id={user_id}, alarm_id={alarm_id}: {e}")
            return False
    
    def cancel_all_user_alarms(self, user_id: int) -> int:
        """
        Отменить все будильники пользователя.
        
        Returns:
            Количество отмененных будильников
        """
        if not self._scheduler:
            return 0
        
        cancelled = 0
        prefix = f"alarm_{user_id}_"
        
        try:
            for job in self._scheduler.get_jobs():
                if job.id and job.id.startswith(prefix):
                    self._scheduler.remove_job(job.id)
                    cancelled += 1
            
            if cancelled > 0:
                logger.info(f"Отменено {cancelled} будильников для user_id={user_id}")
            return cancelled
        except Exception as e:
            logger.error(f"Ошибка при отмене всех будильников для user_id={user_id}: {e}")
            return cancelled
    
    def has_alarm(self, user_id: int, alarm_id: int) -> bool:
        """Проверить, есть ли конкретный будильник"""
        if not self._scheduler:
            return False
        
        job_id = self._get_job_id(user_id, alarm_id)
        return self._scheduler.get_job(job_id) is not None
    
    def has_any_alarm(self, user_id: int) -> bool:
        """Проверить, есть ли хотя бы один будильник у пользователя"""
        if not self._scheduler:
            return False
        
        prefix = f"alarm_{user_id}_"
        for job in self._scheduler.get_jobs():
            if job.id and job.id.startswith(prefix):
                return True
        return False
    
    def get_user_alarms_count(self, user_id: int) -> int:
        """Получить количество будильников пользователя"""
        if not self._scheduler:
            return 0
        
        count = 0
        prefix = f"alarm_{user_id}_"
        for job in self._scheduler.get_jobs():
            if job.id and job.id.startswith(prefix):
                count += 1
        return count
    
    def get_alarm_time(self, user_id: int, alarm_id: int) -> Optional[datetime]:
        """Получить время конкретного будильника"""
        if not self._scheduler:
            return None
        
        job_id = self._get_job_id(user_id, alarm_id)
        job = self._scheduler.get_job(job_id)
        
        if job and job.next_run_time:
            return job.next_run_time.replace(tzinfo=None)
        return None
    
    def get_all_scheduled_alarms(self) -> Dict[Tuple[int, int], datetime]:
        """
        Получить все запланированные будильники.
        
        Returns:
            Dict[(user_id, alarm_id)] -> datetime
        """
        if not self._scheduler:
            return {}
        
        result = {}
        for job in self._scheduler.get_jobs():
            if job.id and job.id.startswith("alarm_"):
                try:
                    # job.id имеет формат "alarm_{user_id}_{alarm_id}"
                    parts = job.id.split("_")
                    if len(parts) >= 3:
                        user_id = int(parts[1])
                        alarm_id = int(parts[2])
                        if job.next_run_time:
                            result[(user_id, alarm_id)] = job.next_run_time.replace(tzinfo=None)
                except (ValueError, AttributeError, IndexError):
                    continue
        
        return result
    
    async def _trigger_alarm(self, user_id: int, alarm_id: int):
        """Внутренний метод - триггер будильника"""
        logger.info(f"Будильник сработал: user_id={user_id}, alarm_id={alarm_id}")
        
        if self._alarm_callback:
            try:
                await self._alarm_callback(user_id, alarm_id)
            except Exception as e:
                logger.error(f"Ошибка в callback будильника: user_id={user_id}, alarm_id={alarm_id}: {e}")
    
    @staticmethod
    def _get_job_id(user_id: int, alarm_id: int) -> str:
        """Генерация ID задачи для будильника"""
        return f"alarm_{user_id}_{alarm_id}"
    
    @staticmethod
    def _get_reminder_job_id(user_id: int, reminder_id: int) -> str:
        """Генерация ID задачи для напоминалки"""
        return f"remind_{user_id}_{reminder_id}"
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # НАПОМИНАЛКИ
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def schedule_reminder(self, user_id: int, reminder_id: int, remind_time: datetime) -> bool:
        """
        Запланировать напоминалку.
        
        Args:
            user_id: ID пользователя
            reminder_id: ID напоминалки в БД
            remind_time: Время срабатывания
            
        Returns:
            True если успешно запланировано
        """
        if not self._scheduler or not self._reminder_callback:
            logger.error("Scheduler или reminder_callback не инициализирован")
            return False
        
        job_id = self._get_reminder_job_id(user_id, reminder_id)
        
        # Проверяем, что время в будущем
        if remind_time <= datetime.now():
            logger.warning(f"Попытка запланировать напоминалку в прошлом: user_id={user_id}, reminder_id={reminder_id}")
            return False
        
        try:
            self._scheduler.add_job(
                func=self._trigger_reminder,
                trigger=DateTrigger(run_date=remind_time),
                args=[user_id, reminder_id],
                id=job_id,
                name=f"remind_user_{user_id}_id_{reminder_id}",
                replace_existing=True
            )
            
            logger.info(f"Напоминалка запланирована: user_id={user_id}, reminder_id={reminder_id}, time={remind_time}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при планировании напоминалки: user_id={user_id}, reminder_id={reminder_id}: {e}")
            return False
    
    def cancel_reminder(self, user_id: int, reminder_id: int) -> bool:
        """
        Отменить напоминалку.
        
        Args:
            user_id: ID пользователя
            reminder_id: ID напоминалки
            
        Returns:
            True если напоминалка была отменена
        """
        if not self._scheduler:
            return False
        
        job_id = self._get_reminder_job_id(user_id, reminder_id)
        
        try:
            job = self._scheduler.get_job(job_id)
            if job:
                self._scheduler.remove_job(job_id)
                logger.info(f"Напоминалка отменена: user_id={user_id}, reminder_id={reminder_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка при отмене напоминалки: user_id={user_id}, reminder_id={reminder_id}: {e}")
            return False
    
    async def _trigger_reminder(self, user_id: int, reminder_id: int):
        """Внутренний метод - триггер напоминалки"""
        logger.info(f"Напоминалка сработала: user_id={user_id}, reminder_id={reminder_id}")
        
        if self._reminder_callback:
            try:
                await self._reminder_callback(user_id, reminder_id)
            except Exception as e:
                logger.error(f"Ошибка в callback напоминалки: user_id={user_id}, reminder_id={reminder_id}: {e}")
