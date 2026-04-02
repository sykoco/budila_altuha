"""
State Manager - Менеджер состояния приложения
Поддержка нескольких будильников для одного пользователя
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass, field

from call import TelegramCaller


@dataclass
class AlarmState:
    """Состояние конкретного будильника"""
    alarm_id: int
    alarm_time: datetime
    task: Optional[asyncio.Task] = None
    active_example: Optional[Tuple[str, float]] = None  # (example_text, correct_answer)


@dataclass
class UserState:
    """Состояние пользователя"""
    username: Optional[str] = None
    # Будильники: alarm_id -> AlarmState
    alarms: Dict[int, AlarmState] = field(default_factory=dict)
    # Флаг активного звонка (чтобы не звонить одновременно)
    is_calling: bool = False
    # ID будильника который сейчас звонит
    active_calling_alarm_id: Optional[int] = None


class StateManager:
    """
    Единый менеджер состояния приложения.
    Поддерживает несколько будильников для одного пользователя.
    """
    
    def __init__(self):
        # Состояния пользователей: user_id -> UserState
        self._user_states: Dict[int, UserState] = {}
        
        # TelegramCaller instance
        self._caller: Optional[TelegramCaller] = None
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # CALLER
    # ═══════════════════════════════════════════════════════════════════════════════
    
    @property
    def caller(self) -> Optional[TelegramCaller]:
        """Получить TelegramCaller"""
        return self._caller
    
    def set_caller(self, caller: TelegramCaller):
        """Установить TelegramCaller"""
        self._caller = caller
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # USER STATE
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def get_user_state(self, user_id: int) -> UserState:
        """Получить состояние пользователя (создает если нет)"""
        if user_id not in self._user_states:
            self._user_states[user_id] = UserState()
        return self._user_states[user_id]
    
    def set_username(self, user_id: int, username: str):
        """Установить username пользователя"""
        state = self.get_user_state(user_id)
        state.username = username
    
    def get_username(self, user_id: int) -> Optional[str]:
        """Получить username пользователя"""
        state = self._user_states.get(user_id)
        return state.username if state else None
    
    def clear_user_state(self, user_id: int):
        """Очистить состояние пользователя"""
        if user_id in self._user_states:
            del self._user_states[user_id]
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # АКТИВНЫЙ ЗВОНОК (блокировка одновременных звонков)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def is_user_calling(self, user_id: int) -> bool:
        """Проверить, звонит ли сейчас будильник пользователю"""
        state = self._user_states.get(user_id)
        return state.is_calling if state else False
    
    def start_calling(self, user_id: int, alarm_id: int):
        """Начать звонок (установить флаг)"""
        state = self.get_user_state(user_id)
        state.is_calling = True
        state.active_calling_alarm_id = alarm_id
    
    def stop_calling(self, user_id: int):
        """Остановить звонок (сбросить флаг)"""
        state = self._user_states.get(user_id)
        if state:
            state.is_calling = False
            state.active_calling_alarm_id = None
    
    def get_active_calling_alarm_id(self, user_id: int) -> Optional[int]:
        """Получить ID будильника который сейчас звонит"""
        state = self._user_states.get(user_id)
        return state.active_calling_alarm_id if state else None
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # ALARM STATE (несколько будильников)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def add_alarm(self, user_id: int, alarm_id: int, alarm_time: datetime):
        """Добавить будильник"""
        state = self.get_user_state(user_id)
        state.alarms[alarm_id] = AlarmState(alarm_id=alarm_id, alarm_time=alarm_time)
    
    def get_alarm(self, user_id: int, alarm_id: int) -> Optional[AlarmState]:
        """Получить состояние будильника"""
        state = self._user_states.get(user_id)
        if state:
            return state.alarms.get(alarm_id)
        return None
    
    def get_all_alarms(self, user_id: int) -> List[AlarmState]:
        """Получить все будильники пользователя"""
        state = self._user_states.get(user_id)
        if state:
            return list(state.alarms.values())
        return []
    
    def remove_alarm(self, user_id: int, alarm_id: int):
        """Удалить будильник из состояния"""
        state = self._user_states.get(user_id)
        if state and alarm_id in state.alarms:
            alarm_state = state.alarms[alarm_id]
            if alarm_state.task:
                alarm_state.task.cancel()
            del state.alarms[alarm_id]
    
    def has_alarm(self, user_id: int, alarm_id: int) -> bool:
        """Проверить, есть ли будильник"""
        state = self._user_states.get(user_id)
        return state is not None and alarm_id in state.alarms
    
    def has_any_alarm(self, user_id: int) -> bool:
        """Проверить, есть ли хотя бы один будильник"""
        state = self._user_states.get(user_id)
        return state is not None and len(state.alarms) > 0
    
    def get_alarms_count(self, user_id: int) -> int:
        """Получить количество будильников"""
        state = self._user_states.get(user_id)
        return len(state.alarms) if state else 0
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # ALARM TASKS
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def set_alarm_task(self, user_id: int, alarm_id: int, task: asyncio.Task):
        """Установить задачу для будильника"""
        alarm_state = self.get_alarm(user_id, alarm_id)
        if alarm_state:
            alarm_state.task = task
    
    def get_alarm_task(self, user_id: int, alarm_id: int) -> Optional[asyncio.Task]:
        """Получить задачу будильника"""
        alarm_state = self.get_alarm(user_id, alarm_id)
        return alarm_state.task if alarm_state else None
    
    def has_alarm_task(self, user_id: int, alarm_id: int) -> bool:
        """Проверить, есть ли активная задача"""
        alarm_state = self.get_alarm(user_id, alarm_id)
        return alarm_state is not None and alarm_state.task is not None
    
    def cancel_alarm_task(self, user_id: int, alarm_id: int) -> bool:
        """Отменить задачу будильника"""
        alarm_state = self.get_alarm(user_id, alarm_id)
        if alarm_state and alarm_state.task:
            alarm_state.task.cancel()
            alarm_state.task = None
            return True
        return False
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # MATH EXAMPLES
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def set_active_example(self, user_id: int, alarm_id: int, example_text: str, correct_answer: float):
        """Установить активный математический пример для будильника"""
        alarm_state = self.get_alarm(user_id, alarm_id)
        if alarm_state:
            alarm_state.active_example = (example_text, correct_answer)
    
    def get_active_example(self, user_id: int, alarm_id: int) -> Optional[Tuple[str, float]]:
        """Получить активный пример для будильника"""
        alarm_state = self.get_alarm(user_id, alarm_id)
        return alarm_state.active_example if alarm_state else None
    
    def has_active_example(self, user_id: int, alarm_id: int) -> bool:
        """Проверить, есть ли активный пример"""
        example = self.get_active_example(user_id, alarm_id)
        return example is not None
    
    def clear_active_example(self, user_id: int, alarm_id: int):
        """Очистить активный пример"""
        alarm_state = self.get_alarm(user_id, alarm_id)
        if alarm_state:
            alarm_state.active_example = None
    
    def find_alarm_with_example(self, user_id: int) -> Optional[int]:
        """Найти alarm_id с активным примером для пользователя"""
        state = self._user_states.get(user_id)
        if state:
            for alarm_id, alarm_state in state.alarms.items():
                if alarm_state.active_example is not None:
                    return alarm_id
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # CONFLICT CHECK
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def check_time_conflict(self, new_alarm_time: datetime, exclude_user_id: int) -> Optional[Tuple[int, str]]:
        """
        Проверяет, есть ли конфликт времени с будильниками ДРУГИХ пользователей.
        Возвращает (user_id, username) конфликтующего или None.
        Конфликт = разница менее 10 минут.
        """
        for user_id, state in self._user_states.items():
            if user_id == exclude_user_id:
                continue
            
            for alarm_state in state.alarms.values():
                if alarm_state.alarm_time is None:
                    continue
                
                time_diff = abs((new_alarm_time - alarm_state.alarm_time).total_seconds())
                if time_diff < 600:  # 10 минут = 600 секунд
                    return (user_id, state.username or "неизвестный пользователь")
        
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def cleanup_alarm(self, user_id: int, alarm_id: int):
        """Очистка конкретного будильника"""
        self.cancel_alarm_task(user_id, alarm_id)
        self.remove_alarm(user_id, alarm_id)
    
    def full_cleanup(self, user_id: int):
        """Полная очистка всех будильников пользователя"""
        state = self._user_states.get(user_id)
        if state:
            for alarm_id in list(state.alarms.keys()):
                self.cancel_alarm_task(user_id, alarm_id)
            state.alarms.clear()
    
    async def shutdown(self):
        """Корректное завершение работы"""
        # Отменяем все задачи всех пользователей
        for user_id, state in self._user_states.items():
            for alarm_state in state.alarms.values():
                if alarm_state.task:
                    alarm_state.task.cancel()
        
        # Отключаем caller
        if self._caller:
            await self._caller.disconnect()
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # LEGACY SUPPORT (для обратной совместимости)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def set_alarm_time(self, user_id: int, alarm_time: datetime):
        """Legacy: установить время (использует alarm_id=0)"""
        self.add_alarm(user_id, 0, alarm_time)
    
    def get_alarm_time(self, user_id: int) -> Optional[datetime]:
        """Legacy: получить время первого будильника"""
        state = self._user_states.get(user_id)
        if state and state.alarms:
            first_alarm = next(iter(state.alarms.values()))
            return first_alarm.alarm_time
        return None
    
    def clear_alarm_time(self, user_id: int):
        """Legacy: очистить все времена будильников"""
        state = self._user_states.get(user_id)
        if state:
            for alarm_state in state.alarms.values():
                alarm_state.alarm_time = None
    
    def get_all_alarm_times(self) -> Dict[int, datetime]:
        """Legacy: получить первые времена будильников всех пользователей"""
        result = {}
        for user_id, state in self._user_states.items():
            if state.alarms:
                first_alarm = next(iter(state.alarms.values()))
                if first_alarm.alarm_time:
                    result[user_id] = first_alarm.alarm_time
        return result
