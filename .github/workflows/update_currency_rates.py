# ====================================================================================
# update_currency_rates.py — Скрипт для оновлення курсів валют НБП (Narodowy Bank Polski)
# ====================================================================================
# Цей скрипт запускається GitHub Action щодня.
# Він завантажує курси валют з офіційного API Національного банку Польщі (NBP)
# та зберігає їх у файл currency_rates.csv в корені репозиторію.
# ====================================================================================
#
# ЯК ЦЕ ПРАЦЮЄ:
# -------------
# 1. Якщо файл currency_rates.csv ще не існує (або порожній):
#    - Скрипт завантажує ПОВНУ історію курсів з 2 січня 2002 року до сьогодні
#    - Це відбувається один раз, при першому запуску
#    - Завантаження займає 5-15 хвилин, тому що потрібно обробити 40+ валют
#
# 2. Якщо файл вже існує:
#    - Скрипт знаходить останню дату в наявному файлі
#    - Завантажує ТІЛЬКИ нові дні (від останньої дати до сьогодні)
#    - Це відбувається швидко, десь за 1-2 хвилини
#
# 3. Після завантаження:
#    - Всі прогалини (вихідні, свята) заповнюються останнім відомим курсом (ffill)
#    - Курси округлюються до 4 знаків після коми
#    - Файл зберігається в корені репозиторію з назвою "currency_rates.csv"
#
# ====================================================================================

import pandas as pd
import requests
from datetime import datetime, timedelta
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ========================== СПИСОК ВАЛЮТ ==========================
# Це перелік всіх валют, які публікує Національний банк Польщі (станом на 2025 рік)
# Валют всього 46, включаючи злотий (PLN), який додається автоматично
# Якщо валюти немає в цьому списку, її курс не буде завантажено
CURRENCIES = [
    "USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "NOK", "SEK",
    "HKD", "SGD", "CNY", "KRW", "MXN", "BRL", "INR", "ZAR", "TRY", "PLN",
    "CZK", "HUF", "DKK", "ISK", "HRK", "RON", "BGN", "RUB", "ILS", "IDR",
    "MYR", "PHP", "THB", "CLP", "COP", "PEN", "UAH", "GEL", "KZT", "AED",
    "SAR", "KWD", "QAR", "BHD", "OMR", "JOD"
]

# Дата початку: 2 січня 2002 року (перша доступна дата в API NBP)
# Раніше цієї дати архівних курсів не існує в електронному вигляді
START_DATE = "2002-01-02"

# ========================== ФУНКЦІЯ ЗАПИТУ З ПОВТОРАМИ ==========================
def get_with_retry(url, retries=3, backoff_factor=1, timeout=30):
    """
    Виконує HTTP-запит з автоматичними повторними спробами у разі помилки.
    Це потрібно, тому що API НБП іноді може тимчасово не відповідати.
    
    Параметри:
    - url: адреса для запиту
    - retries: кількість повторних спроб (за замовчуванням 3)
    - backoff_factor: затримка між спробами (що більше, то довше чекаємо)
    - timeout: максимальний час очікування відповіді в секундах
    
    Повертає об'єкт відповіді або None у разі помилки.
    """
    session = requests.Session()
    retry = Retry(total=retries,
                  read=retries,
                  connect=retries,
                  backoff_factor=backoff_factor,
                  status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException:
        return None

# ========================== ЗАВАНТАЖЕННЯ КУРСІВ ДЛЯ ОДНІЄЇ ВАЛЮТИ ==========================
def fetch_currency_rates(currency, start_date, end_date):
    """
    Завантажує курси для однієї конкретної валюти за вказаний проміжок часу.
    
    Параметри:
    - currency: код валюти, наприклад "USD" або "EUR"
    - start_date: дата початку у форматі "РРРР-ММ-ДД"
    - end_date: дата кінця у форматі "РРРР-ММ-ДД"
    
    Повертає словник, де ключ - дата, значення - курс.
    Наприклад: {"2024-01-01": 4.0, "2024-01-02": 4.01, ...}
    
    Якщо запит не вдався, повертає порожній словник.
    """
    url = f"https://api.nbp.pl/api/exchangerates/rates/a/{currency}/{start_date}/{end_date}/?format=json"
    response = get_with_retry(url)
    
    if response and response.status_code == 200:
        try:
            data = response.json()
            rates = {}
            for item in data['rates']:
                rates[item['effectiveDate']] = item['mid']
            return rates
        except Exception:
            return {}
    return {}

# ========================== ГОЛОВНА ФУНКЦІЯ ==========================
def update_currency_rates():
    """
    Головна функція, яка оновлює файл currency_rates.csv.
    
    ЩО ВОНА РОБИТЬ:
    --------------
    1. Перевіряє, чи існує вже файл з курсами
    2. Якщо файлу НЕМАЄ: завантажує повну історію з 2002 року до сьогодні
    3. Якщо файл ІСНУЄ: додає тільки нові дні, яких ще немає
    4. Заповнює прогалини (вихідні, свята) попередніми курсами
    5. Заокруглює всі курси до 4 знаків після коми
    6. Зберігає оновлений файл у корені репозиторію
    
    ДЛЯ ЧОГО ЦЕ ПОТРІБНО:
    ---------------------
    Головний додаток (калькулятор FIFO) читає курси з цього файлу,
    замість того щоб кожен раз ходити до API НБП. Це набагато швидше.
    """
    
    # Шлях до файлу (зберігається в корені репозиторію, не в папці data)
    file_path = "currency_rates.csv"
    
    # Сьогоднішня дата (потрібна, щоб знати, докуди завантажувати)
    today = datetime.now().date()
    
    # Перевіряємо, чи вже існує файл і чи він не порожній
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        # ========== ВИПАДОК 1: ФАЙЛ ІСНУЄ ==========
        # Читаємо існуючий файл
        existing_df = pd.read_csv(file_path)
        existing_df['Date'] = pd.to_datetime(existing_df['Date']).dt.date
        
        # Знаходимо останню дату, яка вже є у файлі
        last_date = existing_df['Date'].max()
        start_date = last_date + timedelta(days=1)
        
        print(f"Файл існує. Остання дата: {last_date}")
        print(f"Завантаження нових даних з {start_date} до {today}")
        
        # Якщо нових дат немає (сьогоднішня дата вже є у файлі) — завершуємо роботу
        if start_date > today:
            print("Нових даних для завантаження немає.")
            return
        
        # Створюємо порожню таблицю для нових дат
        date_range = pd.date_range(start=start_date, end=today)
        new_df = pd.DataFrame({'Date': date_range.strftime('%Y-%m-%d')})
        # Конвертуємо дати в правильний формат (щоб потім можна було порівнювати)
        new_df['Date'] = pd.to_datetime(new_df['Date']).dt.date
        
        # Для кожної валюти завантажуємо курси за нові дні
        for currency in CURRENCIES:
            if currency == "PLN":
                # Для злотого курс завжди 1.0
                new_df[currency] = 1.0
                continue
            
            print(f"Завантаження курсів для {currency} з {start_date} до {today}...")
            rates = fetch_currency_rates(currency, start_date.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
            
            # Додаємо курси до таблиці
            new_df[currency] = new_df['Date'].astype(str).map(rates)
        
        # Об'єднуємо стару таблицю з новою
        result_df = pd.concat([existing_df, new_df], ignore_index=True)
        
    else:
        # ========== ВИПАДОК 2: ФАЙЛ НЕ ІСНУЄ (або порожній) ==========
        # Створюємо новий файл з ПОВНОЮ історією з 2002 року
        print(f"Файл не існує. Створення нового файлу з історією з {START_DATE} до {today}")
        
        start = datetime.strptime(START_DATE, "%Y-%m-%d").date()
        date_range = pd.date_range(start=start, end=today)
        result_df = pd.DataFrame({'Date': date_range.strftime('%Y-%m-%d')})
        result_df['Date'] = pd.to_datetime(result_df['Date']).dt.date
        
        # Для кожної валюти завантажуємо курси річними порціями
        # (це повільніше, але потрібно тільки один раз)
        for currency in CURRENCIES:
            if currency == "PLN":
                result_df[currency] = 1.0
                continue
            
            print(f"Завантаження курсів для {currency}...")
            all_rates = {}
            
            # Розбиваємо на річні інтервали, щоб не перевантажувати API
            current_start = start
            while current_start <= today:
                current_end = min(current_start + timedelta(days=365), today)
                rates = fetch_currency_rates(currency, current_start.strftime('%Y-%m-%d'), current_end.strftime('%Y-%m-%d'))
                all_rates.update(rates)
                current_start = current_end + timedelta(days=1)
                print(f"  Завантажено до {current_end}")
            
            result_df[currency] = result_df['Date'].astype(str).map(all_rates)
    
    # ========== POST-OBRA ROBKA: ОЧИЩЕННЯ ДАНИХ ==========
    
    # Заповнюємо прогалини (вихідні, свята) останнім відомим курсом
    # Наприклад: якщо курс USD на суботу не опубліковано, беремо курс з п'ятниці
    for currency in CURRENCIES:
        if currency == "PLN":
            continue
        result_df[currency] = result_df[currency].ffill()
    
    # Заокруглюємо всі курси до 4 знаків після коми
    # Це потрібно, щоб уникнути дуже довгих дробових чисел
    for currency in CURRENCIES:
        if currency == "PLN":
            continue
        result_df[currency] = result_df[currency].round(4)
    
    # Зберігаємо готовий файл у корені репозиторію
    result_df.to_csv(file_path, index=False)
    print(f"Файл збережено: {file_path}")
    print(f"Діапазон дат: з {result_df['Date'].min()} по {result_df['Date'].max()}")
    print(f"Кількість рядків: {len(result_df)}")

# ========================== ЗАПУСК СКРИПТА ==========================
# Цей код виконується тільки якщо файл запущено безпосередньо, а не імпортовано
if __name__ == "__main__":
    update_currency_rates()
