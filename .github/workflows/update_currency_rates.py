# ====================================================================================
# update_currency_rates.py — Скрипт для оновлення курсів валют NBP
# ====================================================================================
# Цей скрипт запускається GitHub Action щодня.
# Він завантажує курси валют з API NBP та зберігає їх у файл currency_rates.csv
# ====================================================================================

import pandas as pd
import requests
from datetime import datetime, timedelta
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ========================== СПИСОК ВАЛЮТ ==========================
# Всі валюти, які публікує NBP (станом на 2025 рік)
CURRENCIES = [
    "USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "NOK", "SEK",
    "HKD", "SGD", "CNY", "KRW", "MXN", "BRL", "INR", "ZAR", "TRY", "PLN",
    "CZK", "HUF", "DKK", "ISK", "HRK", "RON", "BGN", "RUB", "ILS", "IDR",
    "MYR", "PHP", "THB", "CLP", "COP", "PEN", "UAH", "GEL", "KZT", "AED",
    "SAR", "KWD", "QAR", "BHD", "OMR", "JOD"
]

# Дата початку: 2 січня 2002 року (перша доступна дата в API NBP)
START_DATE = "2002-01-02"

# ========================== ФУНКЦІЯ ЗАПИТУ З ПОВТОРАМИ ==========================
def get_with_retry(url, retries=3, backoff_factor=1, timeout=30):
    """Wykonuje żądanie GET z automatycznymi ponownymi próbami."""
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
    Pobiera kursy dla jednej waluty z API NBP w podanym zakresie dat.
    Zwraca słownik {data: kurs} lub pusty słownik w przypadku błędu.
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

# ========================== GŁÓWNA FUNKCJA ==========================
def update_currency_rates():
    """
    Główna funkcja aktualizująca plik currency_rates.csv.
    - Jeśli plik nie istnieje → tworzy go z pełną historią od 2002 roku
    - Jeśli plik istnieje → dodaje tylko brakujące dni (od ostatniej daty do dzisiaj)
    """
    
    # Ścieżka do pliku (w korzeniu repozytorium)
    file_path = "currency_rates.csv"
    
    # Dzisiejsza data
    today = datetime.now().date()
    
    # Sprawdzenie czy plik istnieje
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        # Wczytaj istniejący plik
        existing_df = pd.read_csv(file_path)
        existing_df['Date'] = pd.to_datetime(existing_df['Date']).dt.date
        
        # Znajdź ostatnią datę w pliku
        last_date = existing_df['Date'].max()
        start_date = last_date + timedelta(days=1)
        
        print(f"Plik istnieje. Ostatnia data: {last_date}")
        print(f"Pobieranie brakujących danych od {start_date} do {today}")
        
        # Jeśli nie ma brakujących dni → zakończ
        if start_date > today:
            print("Brak nowych danych do pobrania.")
            return
        
        # Przygotuj DataFrame dla nowych danych
        date_range = pd.date_range(start=start_date, end=today)
        new_df = pd.DataFrame({'Date': date_range.strftime('%Y-%m-%d')})
        # Конвертуємо Date в той самий тип, що й existing_df
        new_df['Date'] = pd.to_datetime(new_df['Date']).dt.date
        
        # Dla każdej waluty pobierz brakujące kursy
        for currency in CURRENCIES:
            if currency == "PLN":
                new_df[currency] = 1.0
                continue
            
            print(f"Pobieranie kursów dla {currency} od {start_date} do {today}...")
            rates = fetch_currency_rates(currency, start_date.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
            
            # Wypełnij kolumnę
            new_df[currency] = new_df['Date'].astype(str).map(rates)
        
        # Połącz istniejący DataFrame z nowym
        result_df = pd.concat([existing_df, new_df], ignore_index=True)
        
    else:
        # Plik nie istnieje - utwórz od nowa z pełną historią
        print(f"Plik nie istnieje. Tworzenie nowego pliku z historią od {START_DATE} do {today}")
        
        start = datetime.strptime(START_DATE, "%Y-%m-%d").date()
        date_range = pd.date_range(start=start, end=today)
        result_df = pd.DataFrame({'Date': date_range.strftime('%Y-%m-%d')})
        result_df['Date'] = pd.to_datetime(result_df['Date']).dt.date
        
        # Dla każdej waluty pobierz kursy w rocznych porcjach
        for currency in CURRENCIES:
            if currency == "PLN":
                result_df[currency] = 1.0
                continue
            
            print(f"Pobieranie kursów dla {currency}...")
            all_rates = {}
            
            # Pobieranie w rocznych porcjach (od 2002 do dzisiaj)
            current_start = start
            while current_start <= today:
                current_end = min(current_start + timedelta(days=365), today)
                rates = fetch_currency_rates(currency, current_start.strftime('%Y-%m-%d'), current_end.strftime('%Y-%m-%d'))
                all_rates.update(rates)
                current_start = current_end + timedelta(days=1)
                print(f"  Pobrano do {current_end}")
            
            result_df[currency] = result_df['Date'].astype(str).map(all_rates)
    
    # Wypełnij brakujące wartości (weekendy, święta) poprzednim kursem
    for currency in CURRENCIES:
        if currency == "PLN":
            continue
        result_df[currency] = result_df[currency].ffill()
    
    # Zaokrąglij kursy do 4 miejsc po przecinku
    for currency in CURRENCIES:
        if currency == "PLN":
            continue
        result_df[currency] = result_df[currency].round(4)
    
    # Zapisz do pliku CSV (w korzeniu repozytorium)
    result_df.to_csv(file_path, index=False)
    print(f"Plik zapisany: {file_path}")
    print(f"Zakres dat: od {result_df['Date'].min()} do {result_df['Date'].max()}")
    print(f"Liczba wierszy: {len(result_df)}")

# ========================== URUCHOMIENIE ==========================
if __name__ == "__main__":
    update_currency_rates()
