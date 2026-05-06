import os
import requests

API_KEY = os.getenv("WEATHER_API_KEY")
def get_weather(city): # type: ignore
    if not API_KEY:
        return "Weather unavailable (missing API key)."
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}&units=imperial"
    response = requests.get(url)
    if response.status_code != 200:
        return "Weather unavailable."
    data = response.json()
    temp = data["main"]["temp"]
    desc = data["weather"][0]["description"]
    return f"{city.title()} is {temp}°F with {desc}." # type: ignore
