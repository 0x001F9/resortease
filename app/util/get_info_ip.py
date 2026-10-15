import requests

def get_address_ip(ip_address: str) -> str | None:
    url = f"http://ip-api.com/json/{ip_address}?fields=status,message,country,regionName,city,lat,lon,query"

    try:
        response = requests.get(url)

        if response.status_code != 200 or response.json().get("status") != "success":
            return None

        response = response.json()

        country = response.get("country")
        region = response.get("regionName")
        city = response.get("city")
        latitude = response.get("lat")
        longitude = response.get("lon")

        return f"{city}, {region}, {country} (Lat: {latitude}, Lon: {longitude})"
    except requests.RequestException:
        return None