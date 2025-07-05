from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import struct
import time
from base64 import urlsafe_b64encode, urlsafe_b64decode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Set
from threading import Lock

from pytmbot.exceptions import CallbackValidationError

# Telegram Bot API ограничения
MAX_CALLBACK_DATA_LENGTH = 64

# Настройки безопасности
CALLBACK_TTL = timedelta(minutes=5)
MAX_PARAMS_COUNT = 5
MAX_PARAM_KEY_LENGTH = 10
MAX_PARAM_VALUE_LENGTH = 20
MAX_ACTION_LENGTH = 15

# Для защиты от replay-атак - в production лучше использовать Redis/DB
_used_nonces: Set[str] = set()
_nonce_lock = Lock()


@dataclass(frozen=True)
class CallbackData:
    """Secure callback data for inline buttons"""
    action: str
    params: Dict[str, str]
    nonce: str
    user_id: Optional[int] = None
    created_at: Optional[datetime] = None

    @property
    def is_expired(self) -> bool:
        """Checks if the data has expired"""
        if not self.created_at:
            return False
        return datetime.now(timezone.utc) > self.created_at + CALLBACK_TTL


class SecureCallback:
    """Callback data generation and validation with security features"""

    def __init__(self, secret_key: Optional[bytes] = None):
        """
        Initialize SecureCallback

        :param secret_key: Secret key for HMAC. If None, generates new one.
                          In production, should be loaded from secure storage.
        """
        if secret_key is None:
            # В production загружайте из переменных окружения или secure vault
            self.secret_key = secrets.token_bytes(32)
        else:
            if len(secret_key) < 32:
                raise ValueError("Secret key must be at least 32 bytes")
            self.secret_key = secret_key

    def generate(
            self,
            action: str,
            params: Optional[Dict[str, str]] = None,
            user_id: Optional[int] = None
    ) -> str:
        """
        Generates secure callback data

        :param action: Action name (e.g., "get_full")
        :param params: Action parameters
        :param user_id: User ID for binding
        :return: Secure string for callback_data
        :raises CallbackValidationError: If validation fails
        """
        if params is None:
            params = {}

        # Валидация входных данных
        self._validate_input(action, params, user_id)

        # Генерация nonce для защиты от replay-атак
        nonce = secrets.token_hex(4)  # 8 символов

        # Создание объекта данных
        data = CallbackData(
            action=action,
            params=params,
            nonce=nonce,
            user_id=user_id,
            created_at=datetime.now(timezone.utc)
        )

        # Сериализация в компактный формат
        serialized = self._serialize_compact(data)

        # Добавление HMAC подписи
        signature = self._sign(serialized)
        secured = f"{serialized}.{signature}"

        # Проверка ограничений Telegram
        if len(secured) > MAX_CALLBACK_DATA_LENGTH:
            raise CallbackValidationError(
                f"Callback data too long: {len(secured)} > {MAX_CALLBACK_DATA_LENGTH}"
            )

        return secured

    def validate(self, callback_data: str, expected_user_id: Optional[int] = None) -> CallbackData:
        """
        Validates and parses callback data

        :param callback_data: Data from callback request
        :param expected_user_id: Expected user ID for additional validation
        :return: Parsed data
        :raises CallbackValidationError: If data is invalid
        """
        try:
            if not callback_data or '.' not in callback_data:
                raise CallbackValidationError("Invalid format")

            # Разделение данных и подписи
            serialized, signature = callback_data.rsplit('.', 1)

            # Верификация подписи
            if not self._verify(serialized, signature):
                raise CallbackValidationError("Invalid signature")

            # Десериализация
            data = self._deserialize_compact(serialized)

            # Проверка времени жизни
            if data.is_expired:
                raise CallbackValidationError("Callback data expired")

            # Проверка nonce (защита от replay-атак)
            if not self._check_and_mark_nonce(data.nonce):
                raise CallbackValidationError("Nonce already used or invalid")

            # Проверка привязки к пользователю
            if expected_user_id is not None and data.user_id != expected_user_id:
                raise CallbackValidationError("User ID mismatch")

            return data

        except (ValueError, AttributeError, struct.error) as e:
            raise CallbackValidationError(f"Decoding error: {e}")

    def _validate_input(self, action: str, params: Dict[str, str], user_id: Optional[int]) -> None:
        """Validates input parameters"""
        # Валидация action
        if not action or len(action) > MAX_ACTION_LENGTH:
            raise CallbackValidationError(f"Invalid action length: {len(action)}")

        if not re.match(r'^[a-z_][a-z0-9_]*$', action):  # Более строгая валидация
            raise CallbackValidationError("Invalid action format")

        # Валидация параметров
        if len(params) > MAX_PARAMS_COUNT:
            raise CallbackValidationError(f"Too many parameters: {len(params)}")

        for key, value in params.items():
            if not key or len(key) > MAX_PARAM_KEY_LENGTH:
                raise CallbackValidationError(f"Invalid param key length: {len(key)}")

            if not value or len(value) > MAX_PARAM_VALUE_LENGTH:
                raise CallbackValidationError(f"Invalid param value length: {len(value)}")

            if not re.match(r'^[a-z0-9_-]+$', key):
                raise CallbackValidationError(f"Invalid param key format: {key}")

            if not re.match(r'^[a-zA-Z0-9_-]+$', value):
                raise CallbackValidationError(f"Invalid param value format: {value}")

        # Валидация user_id
        if user_id is not None and (user_id <= 0 or user_id > 2 ** 31):
            raise CallbackValidationError(f"Invalid user_id: {user_id}")

    def _serialize_compact(self, data: CallbackData) -> str:
        """Сериализует данные в компактный бинарный формат для экономии места"""
        # Используем бинарную упаковку для экономии места
        buffer = bytearray()

        # Action (до 15 символов)
        action_bytes = data.action.encode('utf-8')
        buffer.append(len(action_bytes))
        buffer.extend(action_bytes)

        # Timestamp (4 байта)
        if data.created_at:
            timestamp = int(data.created_at.timestamp())
            buffer.extend(struct.pack('>I', timestamp))
        else:
            buffer.extend(b'\x00\x00\x00\x00')

        # User ID (4 байта, опционально)
        if data.user_id:
            buffer.extend(struct.pack('>I', data.user_id))
        else:
            buffer.extend(b'\x00\x00\x00\x00')

        # Nonce (4 байта hex = 8 символов -> 4 байта бинарно)
        nonce_bytes = bytes.fromhex(data.nonce)
        buffer.extend(nonce_bytes)

        # Параметры (компактно)
        buffer.append(len(data.params))
        for key, value in data.params.items():
            key_bytes = key.encode('utf-8')
            value_bytes = value.encode('utf-8')
            buffer.append(len(key_bytes))
            buffer.extend(key_bytes)
            buffer.append(len(value_bytes))
            buffer.extend(value_bytes)

        # Base64 кодирование для безопасной передачи
        return urlsafe_b64encode(buffer).decode('ascii').rstrip('=')

    def _deserialize_compact(self, serialized: str) -> CallbackData:
        """Десериализует данные из компактного формата"""
        # Восстановление padding для base64
        padding = 4 - (len(serialized) % 4)
        if padding != 4:
            serialized += '=' * padding

        try:
            buffer = urlsafe_b64decode(serialized.encode('ascii'))
        except Exception as e:
            raise ValueError(f"Base64 decode error: {e}")

        if len(buffer) < 14:  # Минимальный размер
            raise ValueError("Buffer too short")

        pos = 0

        # Action
        action_len = buffer[pos]
        pos += 1
        if pos + action_len > len(buffer):
            raise ValueError("Invalid action length")
        action = buffer[pos:pos + action_len].decode('utf-8')
        pos += action_len

        # Timestamp
        if pos + 4 > len(buffer):
            raise ValueError("Invalid timestamp position")
        timestamp_int = struct.unpack('>I', buffer[pos:pos + 4])[0]
        pos += 4
        created_at = None
        if timestamp_int != 0:
            # Валидация временной метки
            if not (1000000000 < timestamp_int < 2 ** 31):  # Разумные границы
                raise ValueError("Timestamp out of range")
            created_at = datetime.fromtimestamp(timestamp_int, tz=timezone.utc)

        # User ID
        if pos + 4 > len(buffer):
            raise ValueError("Invalid user_id position")
        user_id_int = struct.unpack('>I', buffer[pos:pos + 4])[0]
        pos += 4
        user_id = user_id_int if user_id_int != 0 else None

        # Nonce
        if pos + 4 > len(buffer):
            raise ValueError("Invalid nonce position")
        nonce = buffer[pos:pos + 4].hex()
        pos += 4

        # Параметры
        if pos >= len(buffer):
            raise ValueError("Invalid params position")
        params_count = buffer[pos]
        pos += 1

        params = {}
        for _ in range(params_count):
            if pos >= len(buffer):
                raise ValueError("Invalid param key length position")
            key_len = buffer[pos]
            pos += 1

            if pos + key_len > len(buffer):
                raise ValueError("Invalid param key position")
            key = buffer[pos:pos + key_len].decode('utf-8')
            pos += key_len

            if pos >= len(buffer):
                raise ValueError("Invalid param value length position")
            value_len = buffer[pos]
            pos += 1

            if pos + value_len > len(buffer):
                raise ValueError("Invalid param value position")
            value = buffer[pos:pos + value_len].decode('utf-8')
            pos += value_len

            params[key] = value

        return CallbackData(
            action=action,
            params=params,
            nonce=nonce,
            user_id=user_id,
            created_at=created_at
        )

    def _sign(self, data: str) -> str:
        """Генерирует HMAC подпись"""
        h = hmac.new(self.secret_key, data.encode('utf-8'), hashlib.sha256)
        # Используем первые 12 байт (16 символов base64) для экономии места
        # Это всё ещё даёт 96 бит энтропии, что достаточно для данного применения
        return urlsafe_b64encode(h.digest()[:12]).decode('ascii').rstrip('=')

    def _verify(self, data: str, signature: str) -> bool:
        """Верифицирует HMAC подпись"""
        try:
            expected_sign = self._sign(data)
            return hmac.compare_digest(expected_sign, signature)
        except Exception:
            return False

    def _check_and_mark_nonce(self, nonce: str) -> bool:
        """
        Проверяет и помечает nonce как использованный
        В production следует использовать Redis или базу данных
        """
        with _nonce_lock:
            if nonce in _used_nonces:
                return False

            # Очистка старых nonces (простая реализация)
            current_time = time.time()
            if len(_used_nonces) > 10000:  # Максимум 10k nonces в памяти
                _used_nonces.clear()

            _used_nonces.add(nonce)
            return True

    def cleanup_expired_nonces(self) -> None:
        """
        Очистка устаревших nonces
        Следует вызывать периодически (например, через cron)
        """
        with _nonce_lock:
            _used_nonces.clear()


# Пример использования с singleton для приложения
class CallbackManager:
    """Singleton для управления callback данными в приложении"""
    _instance = None
    _callback_handler = None

    def __new__(cls, secret_key: Optional[bytes] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._callback_handler = SecureCallback(secret_key)
        return cls._instance

    def generate(self, action: str, params: Optional[Dict[str, str]] = None, user_id: Optional[int] = None) -> str:
        return self._callback_handler.generate(action, params, user_id)

    def validate(self, callback_data: str, expected_user_id: Optional[int] = None) -> CallbackData:
        return self._callback_handler.validate(callback_data, expected_user_id)